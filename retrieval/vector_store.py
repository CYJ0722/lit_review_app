"""
向量检索：sentence-transformers 编码 + FAISS 索引，用于语义匹配（RAG 不降级为 TF-IDF）。
FAISS 的 C++ 端在 Windows 上对含中文等非 ASCII 路径可能报错，故通过临时文件写入再移动。
"""
import json
import os
import pickle
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any

from lit_review_app.config.settings import LIT_DB_PATH, LIT_EMBEDDINGS_DIR, EMBED_MODEL, get_device

_EMBED_LOAD_TIMEOUT = int(os.environ.get("LIT_EMBED_LOAD_TIMEOUT", "45"))
_embed_model_instance = None
_embed_model_failed = False


def _embed_model():
    """懒加载 SentenceTransformer；带超时，失败则返回 None，检索仍可用 SQLite/ES。"""
    global _embed_model_instance, _embed_model_failed
    if _embed_model_instance is not None:
        return _embed_model_instance
    if _embed_model_failed:
        return None
    result = [None]
    err_holder = [None]

    def load():
        try:
            from sentence_transformers import SentenceTransformer
            result[0] = SentenceTransformer(EMBED_MODEL, device=get_device())
        except Exception as e:
            err_holder[0] = e

    th = threading.Thread(target=load, daemon=True)
    th.start()
    th.join(timeout=_EMBED_LOAD_TIMEOUT)
    if th.is_alive():
        _embed_model_failed = True
        return None
    if err_holder[0] is not None:
        _embed_model_failed = True
        return None
    _embed_model_instance = result[0]
    return _embed_model_instance


def _faiss_write_via_temp(index, dest_path: str) -> None:
    """先写入系统临时目录（通常为纯英文路径），再移动到目标，避免 FAISS 在 Windows 下对中文路径报错。"""
    dest_path = str(Path(dest_path).resolve())
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(suffix=".faiss_index", prefix="faiss_")
        os.close(fd)
        import faiss
        faiss.write_index(index, tmp)
        Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
        shutil.move(tmp, dest_path)
        tmp = None
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass


def _faiss_index_path() -> Path:
    return Path(LIT_EMBEDDINGS_DIR) / "faiss_index"


def _id_list_path() -> Path:
    return Path(LIT_EMBEDDINGS_DIR) / "paper_ids.pkl"


def build_index(db_path: str | None = None, limit: int | None = None) -> int:
    """
    从 SQLite papers 表读取 title+abstract，编码后构建 FAISS 索引并保存。
    返回索引的文献数量。
    """
    import sqlite3
    model = _embed_model()
    if not model:
        raise RuntimeError("sentence_transformers 未安装或模型加载失败")
    db_path = db_path or LIT_DB_PATH
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    q = "SELECT paper_id, title, abstract FROM papers"
    if limit:
        q += f" LIMIT {int(limit)}"
    cur.execute(q)
    rows = cur.fetchall()
    conn.close()

    ids = []
    texts = []
    for r in rows:
        pid, title, abstract = r[0], r[1] or "", r[2] or ""
        text = f"{title}\n{abstract}"[:4000]
        if not text.strip():
            continue
        ids.append(pid)
        texts.append(text)

    if not ids:
        return 0

    import numpy as np
    vecs = model.encode(texts, show_progress_bar=True)
    if not hasattr(vecs, 'shape'):
        vecs = np.array(vecs, dtype=np.float32)
    else:
        vecs = np.asarray(vecs, dtype=np.float32)
    Path(LIT_EMBEDDINGS_DIR).mkdir(parents=True, exist_ok=True)

    try:
        import faiss
        dim = vecs.shape[1]
        index = faiss.IndexFlatIP(dim)
        faiss.normalize_L2(vecs)
        index.add(vecs)
        _faiss_write_via_temp(index, str(_faiss_index_path()))
        Path(LIT_EMBEDDINGS_DIR).mkdir(parents=True, exist_ok=True)
        with open(_id_list_path(), "wb") as f:
            pickle.dump(ids, f)
    except Exception as e:
        raise RuntimeError(f"FAISS 构建失败: {e}")

    return len(ids)


def vector_search(
    query: str,
    top_k: int = 100,
    start_year: int | None = None,
    end_year: int | None = None,
    source: str | None = None,
    db_path: str | None = None,
) -> list[tuple[str, float]]:
    """
    语义检索，返回 [(paper_id, score), ...]。需先 build_index。
    若需按 year/source 过滤，在结果后与 DB 过滤合并（本层只做向量检索）。
    """
    model = _embed_model()
    if not model:
        return []
    if not _faiss_index_path().exists() or not _id_list_path().exists():
        return []
    try:
        import faiss
        index = faiss.read_index(str(_faiss_index_path()))
        with open(_id_list_path(), "rb") as f:
            ids = pickle.load(f)
    except Exception:
        return []

    import numpy as np
    q_vec = model.encode([query[:2000]])
    q_vec = np.asarray(q_vec, dtype=np.float32)
    faiss.normalize_L2(q_vec)
    scores, indices = index.search(q_vec, min(top_k, len(ids)))
    out = []
    for i, idx in enumerate(indices[0]):
        if idx < 0 or idx >= len(ids):
            continue
        out.append((ids[idx], float(scores[0][i])))
    return out


def index_ready() -> bool:
    return _faiss_index_path().exists() and _id_list_path().exists()


def build_index_from_embedding_files(db_path: str | None = None) -> int:
    """
    规格 4.1：从 paper_features.embedding_id 指向的 .npy 文件构建 FAISS 索引。
    用于离线已逐篇写入 embedding 后的统一向量库。
    """
    import sqlite3
    import numpy as np
    db_path = db_path or LIT_DB_PATH
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT paper_id, embedding_id FROM paper_features WHERE embedding_id IS NOT NULL AND embedding_id != ''")
    rows = cur.fetchall()
    conn.close()
    if not rows:
        return 0
    ids = []
    vecs_list = []
    for pid, emb_path in rows:
        try:
            v = np.load(emb_path, allow_pickle=True)
            if hasattr(v, "shape") and len(v.shape) >= 1:
                vecs_list.append(np.asarray(v, dtype=np.float32).flatten())
                ids.append(pid)
        except Exception:
            continue
    if not ids:
        return 0
    vecs = np.stack(vecs_list)
    if vecs.ndim == 1:
        vecs = vecs.reshape(1, -1)
    Path(LIT_EMBEDDINGS_DIR).mkdir(parents=True, exist_ok=True)
    try:
        import faiss
        dim = vecs.shape[1]
        index = faiss.IndexFlatIP(dim)
        faiss.normalize_L2(vecs)
        index.add(vecs)
        _faiss_write_via_temp(index, str(_faiss_index_path()))
        with open(_id_list_path(), "wb") as f:
            pickle.dump(ids, f)
    except Exception as e:
        raise RuntimeError(f"FAISS 构建失败: {e}")
    return len(ids)
