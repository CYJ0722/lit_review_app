"""
Elasticsearch 索引与 BM25 检索。用于关键词匹配，不做简单 TF-IDF 降级。
"""
import json
from typing import Any

from lit_review_app.config.settings import ES_HOST, ES_INDEX


def _get_client():
    try:
        from elasticsearch import Elasticsearch
        return Elasticsearch(ES_HOST)
    except Exception:
        return None


def index_exists() -> bool:
    es = _get_client()
    if not es:
        return False
    try:
        r = es.indices.exists(index=ES_INDEX)
        return r if isinstance(r, bool) else getattr(r, "body", False)
    except Exception:
        return False


def create_index_if_not_exists() -> bool:
    es = _get_client()
    if not es:
        return False
    if index_exists():
        return True
    mapping = {
        "settings": {"number_of_shards": 1, "number_of_replicas": 0},
        "mappings": {
            "properties": {
                "paper_id": {"type": "keyword"},
                "title": {"type": "text", "fields": {"raw": {"type": "keyword"}}},
                "authors": {"type": "text", "index": False},
                "year": {"type": "keyword"},
                "journal": {"type": "text"},
                "abstract": {"type": "text"},
                "keywords": {"type": "text"},
                "field": {"type": "keyword"},
                "source": {"type": "keyword"},
                "pdf_path": {"type": "keyword", "index": False},
            }
        },
    }
    try:
        es.indices.create(index=ES_INDEX, body=mapping)
        return True
    except Exception as e:
        if "resource_already_exists" not in str(e).lower():
            try:
                es.indices.create(index=ES_INDEX, body={"mappings": mapping["mappings"]})
            except Exception:
                pass
        return index_exists()


def index_paper(doc: dict) -> bool:
    es = _get_client()
    if not es:
        return False
    create_index_if_not_exists()
    body = {
        "paper_id": doc.get("paper_id"),
        "title": doc.get("title") or "",
        "authors": json.dumps(doc.get("authors") or [], ensure_ascii=False),
        "year": str(doc.get("year") or ""),
        "journal": doc.get("journal") or "",
        "abstract": doc.get("abstract") or "",
        "keywords": doc.get("keywords") or "",
        "field": doc.get("field") or "",
        "source": doc.get("source") or "",
        "pdf_path": doc.get("pdf_path") or "",
    }
    if isinstance(body["keywords"], list):
        body["keywords"] = " ".join(body["keywords"]) if body["keywords"] else ""
    try:
        es.index(index=ES_INDEX, id=doc.get("paper_id"), body=body)
        return True
    except TypeError:
        try:
            es.index(index=ES_INDEX, id=doc.get("paper_id"), document=body)
            return True
        except Exception:
            return False
    except Exception:
        return False


def bm25_search(
    q: str,
    start_year: int | None = None,
    end_year: int | None = None,
    source: str | None = None,
    size: int = 100,
) -> list[tuple[str, float]]:
    """
    BM25 检索，返回 [(paper_id, score), ...]。
    """
    es = _get_client()
    if not es or not index_exists():
        return []
    must = []
    if q and q.strip():
        must.append({
            "multi_match": {
                "query": q.strip(),
                "fields": ["title^3", "abstract^2", "keywords^2", "journal"],
                "type": "best_fields",
            }
        })
    filter_clauses = []
    if start_year is not None:
        filter_clauses.append({"range": {"year": {"gte": str(start_year)}}})
    if end_year is not None:
        filter_clauses.append({"range": {"year": {"lte": str(end_year)}}})
    if source:
        filter_clauses.append({"term": {"source": source}})
    query = {"bool": {"must": must if must else [{"match_all": {}}], "filter": filter_clauses}}
    try:
        res = es.search(index=ES_INDEX, query=query, size=size)
        out = []
        for h in res.get("hits", {}).get("hits", []):
            pid = h.get("_id") or (h.get("_source") or {}).get("paper_id")
            score = float(h.get("_score") or 0)
            if pid:
                out.append((pid, score))
        return out
    except Exception:
        return []
