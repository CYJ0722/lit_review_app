"""
规格 4.3 检索服务层：查询理解 + 多路检索融合（BM25 + 向量 + 期刊权重 + 用户偏好）+ 主题/年份分布输出。
"""
from collections import Counter
from typing import Any

from lit_review_app.retrieval.db import search_sqlite, fetch_papers_by_ids, fetch_features
from lit_review_app.retrieval.es_client import index_exists, bm25_search
from lit_review_app.retrieval.vector_store import index_ready, vector_search
from lit_review_app.retrieval.query_understanding import parse_query, ParsedQuery


# 规格 4.3：Score = w1*BM25 + w2*向量 + w3*期刊 + w4*用户偏好 + 标题匹配加分
DEFAULT_W1 = 0.45
DEFAULT_W2 = 0.25
DEFAULT_W3 = 0.1
DEFAULT_W4 = 0.1
# 标题中直接出现检索词时加分，避免“仅摘要相关”的文献压过“标题含检索词”的文献
DEFAULT_TITLE_BONUS = 0.2


def _title_match_bonus(title: str, topic_terms: list[str] | None, raw_query: str) -> float:
    """标题中含检索词则返回 1.0，否则 0；用于排序时优先标题匹配。"""
    if not title or not (topic_terms or raw_query or "").strip():
        return 0.0
    title_lower = (title or "").strip().lower()
    if topic_terms:
        for t in topic_terms:
            if t and t.strip().lower() in title_lower:
                return 1.0
    q = (raw_query or "").strip()
    if q and q.lower() in title_lower:
        return 1.0
    return 0.0


def _journal_weight(journal: str) -> float:
    """期刊权重 0–1，可扩展为配置表。"""
    if not journal:
        return 0.0
    j = (journal or "").strip().lower()
    high = {"经济研究", "管理世界", "journal of finance", "journal of political economy", "american economic review"}
    if any(h in j for h in high):
        return 0.9
    if "学报" in j or "journal" in j or "review" in j:
        return 0.5
    return 0.2


def _user_pref_score(text: str, pref_terms: list[str]) -> float:
    if not pref_terms or not text:
        return 0.0
    t = text.lower()
    hits = sum(1 for p in pref_terms if p.lower() in t)
    return min(1.0, hits / max(1, len(pref_terms)) * 0.5 + 0.5)


def hybrid_search(
    q: str = "",
    start_year: int | None = None,
    end_year: int | None = None,
    source: str | None = None,
    limit: int = 100,
    offset: int = 0,
    w1: float = DEFAULT_W1,
    w2: float = DEFAULT_W2,
    w3: float = DEFAULT_W3,
    w4: float = DEFAULT_W4,
    title_bonus: float = DEFAULT_TITLE_BONUS,
    user_pref_terms: list[str] | None = None,
    topic_terms: list[str] | None = None,
) -> tuple[list[dict], int]:
    """
    多路检索融合；返回 (results, total)，results 含 score 及元数据。
    """
    use_es = index_exists()
    use_vec = index_ready()
    pref = user_pref_terms or []

    if use_es or use_vec:
        id_scores = {}
        max_bm25 = 1.0
        max_vec = 1.0
        if use_es:
            bm25_hits = bm25_search(q, start_year, end_year, source, size=limit * 2)
            for pid, score in bm25_hits:
                id_scores[pid] = id_scores.get(pid, {})
                id_scores[pid]["bm25"] = score
            if bm25_hits:
                max_bm25 = max(s for _, s in bm25_hits) or 1.0
        if use_vec and q and q.strip():
            vec_hits = vector_search(q, top_k=limit * 2)
            for pid, score in vec_hits:
                id_scores[pid] = id_scores.get(pid, {})
                id_scores[pid]["vec"] = score
            if vec_hits:
                max_vec = max(s for _, s in vec_hits) or 1.0
        if id_scores:
            pids_all = list(id_scores.keys())
            meta = fetch_papers_by_ids(pids_all)
            combined = []
            for pid, scores in id_scores.items():
                md = meta.get(pid, {})
                if start_year is not None:
                    try:
                        y = int(md.get("year") or 0)
                        if y < start_year:
                            continue
                    except (TypeError, ValueError):
                        continue
                if end_year is not None:
                    try:
                        y = int(md.get("year") or 0)
                        if y > end_year:
                            continue
                    except (TypeError, ValueError):
                        continue
                if source and (md.get("source") or "") != source:
                    continue
                bm = (scores.get("bm25") or 0) / max_bm25
                vc = (scores.get("vec") or 0) / max_vec
                jw = _journal_weight(md.get("journal", ""))
                up = _user_pref_score((md.get("title", "") or "") + " " + (md.get("abstract", "") or ""), pref)
                tb = _title_match_bonus(md.get("title", ""), topic_terms, q)
                score = w1 * bm + w2 * vc + w3 * jw + w4 * up + title_bonus * tb
                combined.append((pid, score))
            combined.sort(key=lambda x: x[1], reverse=True)
            pids = [x[0] for x in combined[offset : offset + limit]]
            results = []
            for pid in pids:
                if pid not in meta:
                    continue
                r = dict(meta[pid])
                r["score"] = next((s for i, s in combined if i == pid), 0.0)
                results.append(r)
            return results, len(combined)
    return search_sqlite(q, start_year, end_year, source, limit, offset)


def search_with_distributions(
    q: str = "",
    start_year: int | None = None,
    end_year: int | None = None,
    source: str | None = None,
    limit: int = 100,
    offset: int = 0,
    use_query_understanding: bool = True,
    db_path: str | None = None,
) -> dict[str, Any]:
    """
    规格 4.3 输出：候选文献列表 + 主题分布 + 年份分布。
    若 use_query_understanding=True，从 q 中解析时间等并覆盖 start_year/end_year。
    """
    if use_query_understanding and q and q.strip():
        pq = parse_query(q)
        if pq.start_year is not None:
            start_year = start_year if start_year is not None else pq.start_year
        if pq.end_year is not None:
            end_year = end_year if end_year is not None else pq.end_year
        topic_str = " ".join(pq.topic_terms) if pq.topic_terms else q
        topic_terms = list(pq.topic_terms) if pq.topic_terms else [q.strip()]
    else:
        topic_str = q or ""
        topic_terms = [q.strip()] if (q or "").strip() else None
    results, total = hybrid_search(
        topic_str, start_year, end_year, source,
        limit=limit, offset=offset, topic_terms=topic_terms,
    )
    if not results:
        return {"results": [], "total": 0, "topic_distribution": [], "year_distribution": []}
    pids = [r["paper_id"] for r in results]
    features = fetch_features(pids, db_path=db_path)
    topic_cnt = Counter()
    year_cnt = Counter()
    for r in results:
        y = r.get("year")
        if y is not None:
            try:
                year_cnt[int(y)] += 1
            except (TypeError, ValueError):
                pass
        f = features.get(r["paper_id"], {})
        tid = f.get("topic_id") or ""
        if tid:
            topic_cnt[tid] += 1
    topic_distribution = [{"topic_id": k, "count": v} for k, v in topic_cnt.most_common(20)]
    year_distribution = [{"year": k, "count": v} for k, v in sorted(year_cnt.items())]
    return {
        "results": results,
        "total": total,
        "topic_distribution": topic_distribution,
        "year_distribution": year_distribution,
    }
