"""
规格 4.1 数据与索引层：发现 PDF → 解析 → 结构化摘要 → 关键词/态度/方法/向量 → 主题聚类 → 入库 → ES → FAISS。
禁止 mock/placeholder；结构化摘要用智谱或启发式，关键词用 KeyBERT，态度/方法用分类器，向量存 .npy 并建 FAISS。
"""
import json
import sqlite3
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from lit_review_app.config.settings import LIT_DB_PATH, LIT_OUT_DIR, PROJECT_ROOT
from lit_review_app.data.discovery import find_pdfs
from lit_review_app.data.extract import process_pdf
from lit_review_app.data.schema import ensure_schema
from lit_review_app.data.feature_pipeline import run_single_paper
from lit_review_app.config.settings import LIT_EMBEDDINGS_DIR


def sha1_of_record(rec: dict) -> str:
    if rec.get("_sha1"):
        return rec["_sha1"]
    import hashlib
    base = (rec.get("title") or "") + "||" + json.dumps(rec.get("authors", []), ensure_ascii=False)
    return hashlib.sha1(base.encode("utf-8")).hexdigest()


def run_import(
    outdir: Path | None = None,
    db_path: str | None = None,
    limit: int | None = None,
    skip_db: bool = False,
    index_es: bool = True,
    index_vector: bool = True,
    skip_features: bool = False,
    n_topics: int = 30,
) -> int:
    outdir = outdir or Path(LIT_OUT_DIR)
    outdir.mkdir(parents=True, exist_ok=True)
    raw_dir = outdir / "raw_texts"
    raw_dir.mkdir(exist_ok=True)

    pdfs = find_pdfs()
    if not pdfs:
        print("未找到 PDF。请设置 LIT_SOURCE_ROOTS 或将文献放入 第二批文献收集、2023-2025 等目录。")
        return 0
    if limit:
        pdfs = pdfs[: int(limit)]

    parsed_path = outdir / "parsed.jsonl"
    seen = set()
    count = 0
    with parsed_path.open("w", encoding="utf-8") as fout:
        for pdf_path, source_label in pdfs:
            print("Processing", pdf_path.name, "| source:", source_label)
            res = process_pdf(pdf_path, source_label)
            if res.get("_error"):
                print("  Error:", res["_error"])
                continue
            h = res.get("_sha1")
            if h in seen:
                print("  Skip duplicate")
                continue
            seen.add(h)
            snippet = res.get("_raw_text_snippet") or res.get("abstract") or ""
            try:
                (raw_dir / (h + ".txt")).write_text(snippet[:5000], encoding="utf-8")
            except Exception:
                pass
            res.pop("_raw_text_snippet", None)
            fout.write(json.dumps(res, ensure_ascii=False) + "\n")
            count += 1

    print("Parsed", count, "PDF(s). Output:", parsed_path)

    if skip_db:
        return count

    db_path = db_path or LIT_DB_PATH
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    ensure_schema(conn)
    cur = conn.cursor()
    inserted = 0
    with parsed_path.open("r", encoding="utf-8") as fin:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            paper_id = sha1_of_record(rec)
            title = rec.get("title")
            authors = json.dumps(rec.get("authors") or [], ensure_ascii=False)
            year = rec.get("year")
            journal = rec.get("journal")
            abstract = rec.get("abstract")
            keywords = rec.get("keywords")
            if isinstance(keywords, list):
                keywords = ",".join(keywords) if keywords else None
            field = rec.get("field")
            source = rec.get("source")
            pdf_path = rec.get("_path")
            cur.execute(
                """
                INSERT OR REPLACE INTO papers
                (paper_id, title, authors, year, journal, abstract, keywords, field, source, pdf_path, source_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (paper_id, title, authors, year, journal, abstract, keywords, field, source, pdf_path, pdf_path),
            )
            cur.execute("INSERT OR IGNORE INTO paper_structured(paper_id) VALUES(?)", (paper_id,))
            cur.execute("INSERT OR IGNORE INTO paper_features(paper_id) VALUES(?)", (paper_id,))
            inserted += 1
    conn.commit()
    conn.close()
    print("DB:", db_path, "| Inserted/Updated", inserted, "rows.")

    if not skip_db and not skip_features:
        _run_feature_pipeline(db_path, outdir, raw_dir, n_topics=n_topics)
        if index_es:
            _index_to_es(db_path)
        if index_vector:
            _build_vector_index_from_files(db_path)

    return count


def _run_feature_pipeline(db_path: str, outdir: Path, raw_dir: Path, n_topics: int = 30) -> None:
    """规格 4.1/4.2.1：逐篇结构化摘要、关键词、态度、方法、向量；再全局主题聚类写入 topic_id。"""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT paper_id, title, abstract FROM papers")
    rows = cur.fetchall()
    conn.close()
    if not rows:
        return
    for i, (paper_id, title, abstract) in enumerate(rows):
        if (i + 1) % 50 == 0:
            print("  Feature pipeline:", i + 1, "/", len(rows))
        raw_file = raw_dir / (paper_id + ".txt")
        full_snippet = raw_file.read_text(encoding="utf-8", errors="ignore") if raw_file.exists() else ""
        try:
            out = run_single_paper(
                paper_id=paper_id,
                title=title or "",
                abstract=abstract or "",
                full_text_snippet=full_snippet,
                embeddings_dir=LIT_EMBEDDINGS_DIR,
                use_llm_structured=True,
            )
        except Exception as e:
            print("  Error", paper_id, e)
            continue
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        s = out["structured"]
        cur.execute(
            """
            UPDATE paper_structured SET background=?, research_question=?, methods=?, conclusions=?, contributions=?, limitations=?
            WHERE paper_id=?
            """,
            (s.get("background", ""), s.get("research_question", ""), s.get("methods", ""), s.get("conclusions", ""), s.get("contributions", ""), s.get("limitations", ""), paper_id),
        )
        kw_str = ",".join(out["keywords"][:15]) if out.get("keywords") else ""
        cur.execute("UPDATE papers SET keywords=? WHERE paper_id=?", (kw_str, paper_id))
        cur.execute(
            "UPDATE paper_features SET attitude_label=?, methods_label=?, embedding_id=? WHERE paper_id=?",
            (out.get("attitude_label", ""), out.get("methods_label", ""), out.get("embedding_id") or "", paper_id),
        )
        conn.commit()
        conn.close()
    print("  Feature pipeline done. Assigning topic_id...")
    _assign_topic_ids(db_path, n_topics=n_topics)
    _print_sample_structured(db_path)


def _print_sample_structured(db_path: str) -> None:
    """打印一条 paper_structured 样本，便于检查 API 抽取是否生效。"""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "SELECT p.paper_id, p.title, s.background, s.research_question, s.methods, s.conclusions FROM papers p "
        "LEFT JOIN paper_structured s ON p.paper_id = s.paper_id LIMIT 1"
    )
    row = cur.fetchone()
    conn.close()
    if row:
        pid, title, bg, rq, m, c = row
        has_glm = bool((bg or "").strip() and (rq or "").strip())
        print("  [样本] paper_id:", pid[:12] + "...", "| 标题:", (title or "")[:40] + "..." if (title or "") and len(title or "") > 40 else (title or ""))
        print("  [样本] 结构化摘要(背景/问题/方法/结论) 已填:", has_glm, "| 背景长度:", len(bg or ""), "| 结论长度:", len(c or ""))


def _assign_topic_ids(db_path: str, n_topics: int = 30) -> None:
    """规格 4.2.2：利用预计算向量做 k-means 聚类，写入 paper_features.topic_id。"""
    import numpy as np
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT paper_id, embedding_id FROM paper_features WHERE embedding_id IS NOT NULL AND embedding_id != ''")
    rows = cur.fetchall()
    conn.close()
    if not rows:
        return
    ids = []
    vecs = []
    for pid, emb_path in rows:
        try:
            v = np.load(emb_path, allow_pickle=True)
            v = np.asarray(v, dtype=np.float32).flatten()
            vecs.append(v)
            ids.append(pid)
        except Exception:
            continue
    if not vecs:
        return
    X = np.stack(vecs)
    n_clusters = min(n_topics, len(ids))
    if n_clusters < 2:
        return
    try:
        import warnings
        from sklearn.cluster import KMeans
        from sklearn.exceptions import ConvergenceWarning
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ConvergenceWarning)  # 忽略「distinct clusters 少于 n_clusters」
            kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
            labels = kmeans.fit_predict(X)
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        for pid, label in zip(ids, labels):
            cur.execute("UPDATE paper_features SET topic_id=? WHERE paper_id=?", (f"topic_{label}", pid))
        conn.commit()
        conn.close()
        print("  topic_id assigned, n_clusters=", n_clusters)
    except Exception as e:
        print("  topic_id assign failed:", e)


def _index_to_es(db_path: str) -> None:
    try:
        from lit_review_app.retrieval.es_client import create_index_if_not_exists, index_paper
        from lit_review_app.retrieval.db import get_connection, fetch_papers_by_ids
        conn = get_connection(db_path)
        cur = conn.cursor()
        cur.execute("SELECT paper_id FROM papers")
        ids = [r[0] for r in cur.fetchall()]
        conn.close()
        if not ids:
            return
        create_index_if_not_exists()
        meta = fetch_papers_by_ids(ids, db_path=db_path)
        for pid, doc in meta.items():
            index_paper(doc)
        print("ES: 已索引", len(meta), "篇文献。")
    except Exception as e:
        print("ES 索引失败:", e)


def _build_vector_index_from_files(db_path: str) -> None:
    try:
        from lit_review_app.retrieval.vector_store import build_index_from_embedding_files
        n = build_index_from_embedding_files(db_path=db_path)
        print("向量索引: 已构建", n, "篇。")
    except Exception as e:
        print("向量索引构建失败:", e)


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--outdir", default=LIT_OUT_DIR)
    p.add_argument("--db", default=LIT_DB_PATH)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--skip-db", action="store_true")
    p.add_argument("--skip-features", action="store_true", help="跳过单篇特征与主题聚类")
    p.add_argument("--no-es", action="store_true")
    p.add_argument("--no-vector", action="store_true")
    p.add_argument("--n-topics", type=int, default=30)
    args = p.parse_args()
    run_import(
        outdir=Path(args.outdir),
        db_path=args.db,
        limit=args.limit,
        skip_db=args.skip_db,
        index_es=not args.no_es,
        index_vector=not args.no_vector,
        skip_features=args.skip_features,
        n_topics=args.n_topics,
    )


if __name__ == "__main__":
    main()
