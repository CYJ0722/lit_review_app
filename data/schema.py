"""
数据库 schema：papers / paper_structured / paper_features。
在原有设计上增加 papers.source 列，用于存储「文献来源」文件夹标签。
"""
import sqlite3
from pathlib import Path


def ensure_schema(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.executescript("""
    PRAGMA foreign_keys = ON;
    CREATE TABLE IF NOT EXISTS papers (
        paper_id TEXT PRIMARY KEY,
        title TEXT,
        authors TEXT,
        year TEXT,
        journal TEXT,
        abstract TEXT,
        keywords TEXT,
        field TEXT,
        source TEXT,
        pdf_path TEXT,
        source_path TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_papers_year ON papers(year);
    CREATE INDEX IF NOT EXISTS idx_papers_journal ON papers(journal);
    CREATE INDEX IF NOT EXISTS idx_papers_source ON papers(source);

    CREATE TABLE IF NOT EXISTS paper_structured (
        paper_id TEXT PRIMARY KEY,
        background TEXT,
        research_question TEXT,
        methods TEXT,
        conclusions TEXT,
        contributions TEXT,
        limitations TEXT,
        FOREIGN KEY(paper_id) REFERENCES papers(paper_id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS paper_features (
        paper_id TEXT PRIMARY KEY,
        embedding_id TEXT,
        topic_id TEXT,
        attitude_label TEXT,
        methods_label TEXT,
        extra_tags TEXT,
        FOREIGN KEY(paper_id) REFERENCES papers(paper_id) ON DELETE CASCADE
    );
    """)
    # 若旧表无 source 列则添加
    try:
        cur.execute("SELECT source FROM papers LIMIT 1")
    except sqlite3.OperationalError:
        cur.execute("ALTER TABLE papers ADD COLUMN source TEXT")
    conn.commit()
