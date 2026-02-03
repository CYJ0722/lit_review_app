"""
分析与特征服务：单篇文献（关键词、态度、向量）与文献集合分析（聚类、共现、热点演化、态度演化）。
与 DB 对接：可接收 paper_id 列表，从 DB 拉取元数据后分析；或直接接收 paper 列表。
模型加载带超时，避免 Hugging Face 连接失败时仪表盘一直卡住。
"""
import json
import os
import threading
from collections import Counter, defaultdict
from typing import Any

from lit_review_app.retrieval.db import fetch_papers_by_ids, get_connection
from lit_review_app.config.settings import LIT_DB_PATH, EMBED_MODEL, get_device

_ANALYSIS_MODEL_LOAD_TIMEOUT = int(os.environ.get("LIT_ANALYSIS_MODEL_TIMEOUT", "45"))


def _try_import_ml():
    try:
        import numpy as np
        from sklearn.cluster import KMeans
        return np, KMeans
    except ImportError:
        return None, None


def _try_import_keybert():
    try:
        from keybert import KeyBERT
        return KeyBERT
    except ImportError:
        return None


def _try_import_sentence_transformers():
    try:
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer
    except ImportError:
        return None


def _try_import_zero_shot():
    try:
        from transformers import pipeline
        return pipeline
    except ImportError:
        return None


class SinglePaperProcessor:
    """单篇文献：关键词、态度/方法分类、向量（可选）。"""

    def __init__(self, device: str = "cpu"):
        self._kw_model = None
        self._embed_model = None
        self._classifier = None
        self._device = device

    def _ensure_kw(self):
        if self._kw_model is None:
            kb = _try_import_keybert()
            if kb:
                self._kw_model = kb()
            else:
                self._kw_model = False  # 无 KeyBERT 时用简单抽取
        return self._kw_model

    def _ensure_embed(self):
        if self._embed_model is None:
            result = [None]
            def load():
                st = _try_import_sentence_transformers()
                if st and EMBED_MODEL:
                    try:
                        result[0] = st(EMBED_MODEL, device=self._device)
                    except Exception:
                        result[0] = False
                else:
                    result[0] = False
            th = threading.Thread(target=load, daemon=True)
            th.start()
            th.join(timeout=_ANALYSIS_MODEL_LOAD_TIMEOUT)
            self._embed_model = result[0] if not th.is_alive() and result[0] is not None else False
        return self._embed_model

    def _ensure_classifier(self):
        if self._classifier is None:
            result = [None]
            def load():
                pipe = _try_import_zero_shot()
                if pipe:
                    try:
                        result[0] = pipe(
                            "zero-shot-classification",
                            model="facebook/bart-large-mnli",
                            device=0 if self._device == "cuda" else -1,
                        )
                    except Exception:
                        result[0] = False
                else:
                    result[0] = False
            th = threading.Thread(target=load, daemon=True)
            th.start()
            th.join(timeout=_ANALYSIS_MODEL_LOAD_TIMEOUT)
            self._classifier = result[0] if not th.is_alive() and result[0] is not None else False
        return self._classifier

    def extract_keywords(self, text: str, top_n: int = 5) -> list[str]:
        if not text or not text.strip():
            return []
        model = self._ensure_kw()
        if model:
            kw = model.extract_keywords(
                text, keyphrase_ngram_range=(1, 2), stop_words="english", top_n=top_n
            )
            return [k[0] for k in kw]
        # 简单回退：按词频取前几
        import re
        words = re.findall(r"\b[a-zA-Z\u4e00-\u9fff]{2,}\b", text)
        cnt = Counter(words)
        return [w for w, _ in cnt.most_common(top_n)]

    def get_embedding(self, text: str) -> list[float] | None:
        if not text or not text.strip():
            return None
        model = self._ensure_embed()
        if not model:
            return None
        emb = model.encode(text[:2000])
        return emb.tolist()

    def classify_attitude(self, text: str) -> str:
        if not text or not text.strip():
            return "neutral"
        pipe = self._ensure_classifier()
        if not pipe:
            return "neutral"
        labels = ["optimistic", "neutral", "critical", "concerned"]
        res = pipe(text[:500], candidate_labels=labels)
        return res["labels"][0] if res else "neutral"

    def process_paper(self, paper_id: str, title: str, abstract: str) -> dict[str, Any]:
        full = f"{title or ''}. {abstract or ''}".strip()
        kw = self.extract_keywords(full, top_n=5)
        vec = self.get_embedding(full)
        attitude = self.classify_attitude(abstract or title or "")
        return {
            "paper_id": paper_id,
            "keywords": kw,
            "vector": vec,
            "attitude": attitude,
            "features": {"attitude": attitude},
        }


class CollectionAnalyzer:
    """文献集合分析：聚类、共现网络、热点演化、态度演化。"""

    def __init__(self, single_processor: SinglePaperProcessor | None = None):
        self.processor = single_processor or SinglePaperProcessor(device=get_device())

    def _enrich_papers(self, papers: list[dict]) -> list[dict]:
        """为缺少 keywords/vector/features 的 paper 补全。"""
        out = []
        for p in papers:
            pid = p.get("paper_id") or p.get("id")
            title = p.get("title") or ""
            abstract = p.get("abstract") or ""
            if not pid:
                continue
            if "keywords" not in p or not p["keywords"]:
                full = f"{title}. {abstract}"
                p = dict(p)
                p["keywords"] = self.processor.extract_keywords(full, top_n=5)
            if "vector" not in p or p["vector"] is None:
                full = f"{title}. {abstract}"
                p = dict(p)
                p["vector"] = self.processor.get_embedding(full)
            if "features" not in p or not p["features"]:
                p = dict(p)
                att = p.get("attitude_label") or self.processor.classify_attitude(abstract or title)
                p["features"] = {"attitude": att, "methods_label": p.get("methods_label", "")}
            else:
                p = dict(p)
                p["features"]["attitude"] = p.get("attitude_label") or (p["features"].get("attitude") or "谨慎中性")
                p["features"]["methods_label"] = p.get("methods_label") or p["features"].get("methods_label", "")
            p["id"] = pid
            out.append(p)
        return out

    def perform_clustering(
        self, papers: list[dict], n_clusters: int = 5
    ) -> dict[str, Any]:
        papers = self._enrich_papers(papers)
        if not papers:
            return {"clusters": []}
        np, KMeans = _try_import_ml()
        if not np or not KMeans:
            return {"clusters": []}
        vectors = []
        valid = []
        for p in papers:
            v = p.get("vector")
            if v is not None and len(v) > 0:
                vectors.append(v)
                valid.append(p)
        if not vectors:
            return {"clusters": []}
        X = np.array(vectors)
        n = min(n_clusters, len(vectors))
        kmeans = KMeans(n_clusters=n, random_state=42, n_init=10)
        labels = kmeans.fit_predict(X)
        clusters = defaultdict(list)
        for i, label in enumerate(labels):
            clusters[int(label)].append(valid[i])
        cluster_summaries = []
        for label, items in sorted(clusters.items()):
            all_kw = [k for it in items for k in it.get("keywords", [])]
            top_k = Counter(all_kw).most_common(3)
            # 主题名：取前 2 个关键词、每词最多 8 字，避免图表上“无厘头”长串
            parts = []
            for k, _ in top_k[:2]:
                parts.append(k[:8] + ("…" if len(k) > 8 else ""))
            topic_name = " / ".join(parts) if parts else f"主题{label}"
            cluster_summaries.append({
                "cluster_id": label,
                "topic_name": topic_name,
                "count": len(items),
                "paper_ids": [it.get("paper_id") or it.get("id") for it in items],
            })
        return {"clusters": cluster_summaries}

    def build_cooccurrence_network(
        self, papers: list[dict], min_weight: int = 1
    ) -> dict[str, Any]:
        papers = self._enrich_papers(papers)
        pair_counts = Counter()
        word_counts = Counter()
        for p in papers:
            kws = p.get("keywords") or []
            word_counts.update(kws)
            for i in range(len(kws)):
                for j in range(i + 1, len(kws)):
                    pair = tuple(sorted([kws[i], kws[j]]))
                    pair_counts[pair] += 1
        valid_nodes = set()
        for (u, v), w in pair_counts.items():
            if w >= min_weight:
                valid_nodes.add(u)
                valid_nodes.add(v)
        import math
        # 节点展示名截断，避免长短语/句子导致共现图难以理解
        max_name_len = 12
        nodes = [
            {
                "id": n,
                "name": (n[:max_name_len] + ("…" if len(n) > max_name_len else "")),
                "value": word_counts[n],
                "symbolSize": math.log(word_counts[n] + 1) * 5,
            }
            for n in valid_nodes
        ]
        links = []
        for (u, v), w in pair_counts.items():
            if w >= min_weight:
                links.append({"source": u, "target": v, "value": w})
        return {"nodes": nodes, "links": links}

    def analyze_trends(self, papers: list[dict]) -> dict[str, Any]:
        papers = self._enrich_papers(papers)
        if not papers:
            return {"years": [], "series": []}
        year_kw = defaultdict(lambda: Counter())
        years_set = set()
        for p in papers:
            y = p.get("year")
            if y is not None:
                try:
                    y = int(y)
                    years_set.add(y)
                except (TypeError, ValueError):
                    pass
            for kw in p.get("keywords") or []:
                if y is not None:
                    year_kw[y][kw] += 1
        years = sorted(years_set)
        all_kw = Counter()
        for c in year_kw.values():
            all_kw.update(c)
        top_keywords = [k for k, _ in all_kw.most_common(10)]
        series = []
        for kw in top_keywords:
            data = [year_kw[y].get(kw, 0) for y in years]
            series.append({"name": kw, "data": data})
        return {"years": years, "series": series}

    def analyze_attitude_evolution(self, papers: list[dict]) -> dict[str, Any]:
        papers = self._enrich_papers(papers)
        if not papers:
            return {"years": [], "series": []}
        year_att = defaultdict(Counter)
        years_set = set()
        for p in papers:
            y = p.get("year")
            att = (p.get("features") or {}).get("attitude", "谨慎中性")
            if y is not None:
                try:
                    y = int(y)
                    years_set.add(y)
                except (TypeError, ValueError):
                    pass
            if y is not None:
                year_att[y][att] += 1
        years = sorted(years_set)
        all_att = set()
        for c in year_att.values():
            all_att.update(c.keys())
        categories = sorted(all_att)
        series = []
        for cat in categories:
            data = [year_att[y].get(cat, 0) for y in years]
            series.append({"name": cat, "data": data, "type": "bar", "stack": "total"})
        return {"years": years, "series": series}

    def get_dashboard_stats(
        self, papers: list[dict]
    ) -> dict[str, Any]:
        """规格 4.2.2：返回仪表盘所需 yearlyCounts, topKeywords, attitudeDistribution, researchPathDistribution（研究方法分布）。"""
        papers = self._enrich_papers(papers)
        yearly = Counter()
        kw_counter = Counter()
        att_counter = Counter()
        methods_counter = Counter()
        for p in papers:
            y = p.get("year")
            if y is not None:
                try:
                    yearly[int(y)] += 1
                except (TypeError, ValueError):
                    pass
            for kw in p.get("keywords") or []:
                kw_counter[kw] += 1
            att = (p.get("features") or {}).get("attitude", "谨慎中性")
            att_counter[att] += 1
            meth = (p.get("features") or {}).get("methods_label") or p.get("methods_label") or "其他"
            if meth:
                methods_counter[meth] += 1
        years = sorted(yearly.keys())
        yearlyCounts = [{"year": y, "count": yearly[y]} for y in years]
        topKeywords = [{"name": k, "value": v} for k, v in kw_counter.most_common(10)]
        attitudeDistribution = [{"name": k, "value": v} for k, v in att_counter.items()]
        researchPathDistribution = [{"name": k, "value": v} for k, v in methods_counter.most_common(10)]
        return {
            "yearlyCounts": yearlyCounts,
            "topKeywords": topKeywords,
            "attitudeDistribution": attitudeDistribution,
            "researchPathDistribution": researchPathDistribution,
        }
