"""
检索层数据访问：从 SQLite 按关键词、年份、来源等查询 papers，返回统一结构。
不依赖 OpenSearch/Milvus，仅 SQLite 即可运行；后续可挂接 ES/向量。
"""
import json
import sqlite3
from pathlib import Path
from typing import Any

from lit_review_app.config.settings import LIT_DB_PATH


def get_connection(db_path: str | None = None):
    db_path = db_path or LIT_DB_PATH
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(db_path)


def search_sqlite(
    q: str = "",
    start_year: int | None = None,
    end_year: int | None = None,
    source: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db_path: str | None = None,
) -> tuple[list[dict], int]:
    """
    关键词 + 年份 + 来源过滤，返回 (results, total)。
    results 中每项为 paper 元数据（含 paper_id, title, authors, year, journal, abstract, keywords, source, pdf_path）。
    """
    conn = get_connection(db_path)
    cur = conn.cursor()

    where = []
    params = []
    if q and q.strip():
        t = f"%{q.strip()}%"
        where.append("(title LIKE ? OR abstract LIKE ? OR keywords LIKE ? OR journal LIKE ?)")
        params.extend([t, t, t, t])
    if start_year is not None:
        where.append("(CAST(year AS INTEGER) >= ?)")
        params.append(start_year)
    if end_year is not None:
        where.append("(CAST(year AS INTEGER) <= ?)")
        params.append(end_year)
    if source:
        where.append("(source = ?)")
        params.append(source)

    where_sql = " AND ".join(where) if where else "1=1"
    count_sql = f"SELECT COUNT(*) FROM papers WHERE {where_sql}"
    cur.execute(count_sql, params)
    total = cur.fetchone()[0]

    sel = """
    SELECT paper_id, title, authors, year, journal, abstract, keywords, field, source, pdf_path
    FROM papers WHERE """ + where_sql + """ ORDER BY year DESC, paper_id LIMIT ? OFFSET ?
    """
    cur.execute(sel, params + [limit, offset])
    rows = cur.fetchall()
    conn.close()

    results = []
    for r in rows:
        results.append({
            "paper_id": r[0],
            "title": r[1] or "",
            "authors": json.loads(r[2]) if r[2] else [],
            "year": int(r[3]) if r[3] and str(r[3]).isdigit() else r[3],
            "journal": r[4] or "",
            "abstract": r[5] or "",
            "keywords": (r[6].split(",") if isinstance(r[6], str) else []) if r[6] else [],
            "field": r[7] or "",
            "source": r[8] or "",
            "pdf_path": r[9] or "",
        })
    return results, total


def fetch_papers_by_ids(paper_ids: list[str], db_path: str | None = None) -> dict[str, dict]:
    """根据 paper_id 列表批量取元数据。"""
    if not paper_ids:
        return {}
    conn = get_connection(db_path)
    cur = conn.cursor()
    placeholders = ",".join("?" * len(paper_ids))
    cur.execute(
        f"""
        SELECT paper_id, title, authors, year, journal, abstract, keywords, field, source, pdf_path
        FROM papers WHERE paper_id IN ({placeholders})
        """,
        paper_ids,
    )
    out = {}
    for r in cur.fetchall():
        out[r[0]] = {
            "paper_id": r[0],
            "title": r[1] or "",
            "authors": json.loads(r[2]) if r[2] else [],
            "year": int(r[3]) if r[3] and str(r[3]).isdigit() else r[3],
            "journal": r[4] or "",
            "abstract": r[5] or "",
            "keywords": (r[6].split(",") if isinstance(r[6], str) else []) if r[6] else [],
            "field": r[7] or "",
            "source": r[8] or "",
            "pdf_path": r[9] or "",
        }
    conn.close()
    return out


def fetch_papers_with_structured(paper_ids: list[str], db_path: str | None = None) -> list[dict]:
    """
    规格 4.3 输出：候选列表含基本元信息与结构化摘要。
    返回 list[dict]，每项含 papers 字段 + paper_structured 字段（background, research_question, methods, conclusions, contributions, limitations）。
    """
    if not paper_ids:
        return []
    conn = get_connection(db_path)
    cur = conn.cursor()
    placeholders = ",".join("?" * len(paper_ids))
    cur.execute(
        f"""
        SELECT p.paper_id, p.title, p.authors, p.year, p.journal, p.abstract, p.keywords, p.field, p.source, p.pdf_path,
               s.background, s.research_question, s.methods, s.conclusions, s.contributions, s.limitations
        FROM papers p
        LEFT JOIN paper_structured s ON p.paper_id = s.paper_id
        WHERE p.paper_id IN ({placeholders})
        """,
        paper_ids,
    )
    out = []
    for r in cur.fetchall():
        out.append({
            "paper_id": r[0],
            "title": r[1] or "",
            "authors": json.loads(r[2]) if r[2] else [],
            "year": int(r[3]) if r[3] and str(r[3]).isdigit() else r[3],
            "journal": r[4] or "",
            "abstract": r[5] or "",
            "keywords": (r[6].split(",") if isinstance(r[6], str) else []) if r[6] else [],
            "field": r[7] or "",
            "source": r[8] or "",
            "pdf_path": r[9] or "",
            "background": r[10] or "",
            "research_question": r[11] or "",
            "methods": r[12] or "",
            "conclusions": r[13] or "",
            "contributions": r[14] or "",
            "limitations": r[15] or "",
        })
    conn.close()
    return out


def fetch_features(paper_ids: list[str], db_path: str | None = None) -> dict[str, dict]:
    """取 paper_features：topic_id, attitude_label, methods_label。"""
    if not paper_ids:
        return {}
    conn = get_connection(db_path)
    cur = conn.cursor()
    placeholders = ",".join("?" * len(paper_ids))
    cur.execute(
        f"""
        SELECT paper_id, topic_id, attitude_label, methods_label
        FROM paper_features WHERE paper_id IN ({placeholders})
        """,
        paper_ids,
    )
    out = {r[0]: {"topic_id": r[1] or "", "attitude_label": r[2] or "", "methods_label": r[3] or ""} for r in cur.fetchall()}
    conn.close()
    return out
