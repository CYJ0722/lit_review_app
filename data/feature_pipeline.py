"""
单篇文献特征流水线（规格 4.1 paper_features + 4.2.1 单篇分析）：
关键词（KeyBERT）、态度（乐观/谨慎中性/批判性）、方法标签、向量编码。
供离线导入与在线分析复用。模型按需加载、单例复用，避免每篇重复 Load。
"""
from pathlib import Path
from typing import Any

from lit_review_app.config.settings import LIT_EMBEDDINGS_DIR, EMBED_MODEL, get_device


# 规格 4.2.1：态度 乐观评估/谨慎中性/批判性
ATTITUDE_LABELS = ["乐观评估", "谨慎中性", "批判性"]

# 规格 4.2.2：研究路径 规范分析/实证/案例研究等
METHODS_LABELS = ["规范分析", "实证研究", "案例研究", "比较研究", "理论分析", "其他"]

# 单例缓存，避免每篇文献重复加载模型
_keybert_model = None
_embed_model = None
_zeroshot_pipe = None


def _get_keybert():
    global _keybert_model
    if _keybert_model is None:
        from keybert import KeyBERT
        # 复用 EMBED_MODEL，避免再加载一套 sentence-transformers（all-MiniLM-L6-v2）
        _keybert_model = KeyBERT(model=_get_embed_model())
    return _keybert_model


def _get_embed_model():
    global _embed_model
    if _embed_model is None:
        from sentence_transformers import SentenceTransformer
        device = get_device()
        _embed_model = SentenceTransformer(EMBED_MODEL, device=device)
    return _embed_model


def _get_zeroshot_pipe():
    global _zeroshot_pipe
    if _zeroshot_pipe is None:
        from transformers import pipeline
        device_id = 0 if get_device() == "cuda" else -1
        _zeroshot_pipe = pipeline("zero-shot-classification", model="facebook/bart-large-mnli", device=device_id)
    return _zeroshot_pipe


def _keybert_extract(text: str, top_n: int = 8) -> list[str]:
    try:
        model = _get_keybert()
        kw = model.extract_keywords(
            text,
            keyphrase_ngram_range=(1, 2),
            stop_words="english",
            top_n=top_n,
            use_mmr=True,
            diversity=0.5,
        )
        return [k[0] for k in kw if k[0].strip()]
    except Exception:
        return _fallback_keywords(text, top_n)


def _fallback_keywords(text: str, top_n: int) -> list[str]:
    import re
    from collections import Counter
    words = re.findall(r"[a-zA-Z]{2,}|[\u4e00-\u9fff]{2,}", text)
    stop = {"the", "and", "for", "with", "this", "that", "from", "have", "are", "was", "were", "been", "being", "will", "would", "can", "could", "may", "might", "本文", "研究", "分析", "方法", "结果", "结论"}
    cnt = Counter(w for w in words if w.lower() not in stop)
    return [w for w, _ in cnt.most_common(top_n)]


def _classify_attitude(abstract: str) -> str:
    """态度分类：乐观评估/谨慎中性/批判性。复用单例 pipeline。"""
    if not abstract or not abstract.strip():
        return "谨慎中性"
    try:
        pipe = _get_zeroshot_pipe()
        labels_en = ["optimistic", "neutral", "critical"]
        res = pipe(abstract[:512], candidate_labels=labels_en, multi_label=False)
        if res and res.get("labels"):
            en_to_cn = {"optimistic": "乐观评估", "neutral": "谨慎中性", "critical": "批判性"}
            return en_to_cn.get(res["labels"][0], "谨慎中性")
        return "谨慎中性"
    except Exception:
        return "谨慎中性"


def _classify_methods(abstract: str) -> str:
    """方法标签：规范分析/实证/案例/比较/理论/其他。复用单例 pipeline。"""
    if not abstract or not abstract.strip():
        return "其他"
    try:
        pipe = _get_zeroshot_pipe()
        labels_en = ["normative analysis", "empirical study", "case study", "comparative study", "theoretical analysis", "other"]
        res = pipe(abstract[:512], candidate_labels=labels_en, multi_label=False)
        if res and res.get("labels"):
            en_to_cn = dict(zip(labels_en, METHODS_LABELS))
            return en_to_cn.get(res["labels"][0], "其他")
        return "其他"
    except Exception:
        return "其他"


def _embed_and_save(paper_id: str, title: str, abstract: str, embeddings_dir: str | Path) -> str | None:
    """编码标题+摘要并保存为 .npy，返回存储路径（供 paper_features.embedding_id）。复用单例 SentenceTransformer。"""
    try:
        import numpy as np
        model = _get_embed_model()
        text = f"{title or ''}\n{abstract or ''}"[:4000]
        if not text.strip():
            return None
        vec = model.encode(text, convert_to_numpy=True)
        vec = np.asarray(vec, dtype=np.float32)
        path = Path(embeddings_dir)
        path.mkdir(parents=True, exist_ok=True)
        out_file = path / f"{paper_id}.npy"
        np.save(out_file, vec)
        return str(out_file.resolve())
    except Exception:
        return None


def run_single_paper(
    paper_id: str,
    title: str,
    abstract: str,
    full_text_snippet: str = "",
    embeddings_dir: str | Path | None = None,
    use_llm_structured: bool = True,
) -> dict[str, Any]:
    """
    对单篇文献运行完整特征流水线。
    返回：
      structured: dict 用于 paper_structured（背景、研究问题、方法、结论、创新、不足）
      keywords: list 用于 papers.keywords
      attitude_label: str
      methods_label: str
      embedding_id: str | None 存储路径
    """
    from lit_review_app.data.structured_extract import extract_structured

    structured = extract_structured(abstract, full_text_snippet, use_llm=use_llm_structured)
    combined = f"{title or ''}\n{abstract or ''}"
    keywords = _keybert_extract(combined, top_n=8)
    attitude_label = _classify_attitude(abstract or title or "")
    methods_label = _classify_methods(abstract or title or "")
    emb_dir = embeddings_dir or LIT_EMBEDDINGS_DIR
    embedding_id = _embed_and_save(paper_id, title, abstract, emb_dir)

    return {
        "structured": structured,
        "keywords": keywords,
        "attitude_label": attitude_label,
        "methods_label": methods_label,
        "embedding_id": embedding_id,
    }
