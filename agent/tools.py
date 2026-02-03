"""
规格 4.4 Agent 工具：调用检索（含主题/年份分布）、分析服务，组装 RAG 上下文（含结构化摘要，严格只引用集合内文献）。
"""
from typing import Any

from lit_review_app.retrieval.search import search_with_distributions
from lit_review_app.retrieval.db import fetch_papers_with_structured, fetch_features
from lit_review_app.analysis.service import CollectionAnalyzer
from lit_review_app.agent.session import SessionState


def search_papers(
    topic: str = "",
    start_year: int | None = None,
    end_year: int | None = None,
    source: str | None = None,
    limit: int = 100,
) -> tuple[list[dict], SessionState]:
    """检索文献（多路融合 + 主题/年份分布），合并 features 到 papers，填充 SessionState。"""
    out = search_with_distributions(
        q=topic,
        start_year=start_year,
        end_year=end_year,
        source=source,
        limit=limit,
        use_query_understanding=True,
    )
    results = out.get("results", [])
    total = out.get("total", 0)
    topic_dist = out.get("topic_distribution", [])
    year_dist = out.get("year_distribution", [])
    pids = [r["paper_id"] for r in results]
    features = fetch_features(pids)
    for r in results:
        f = features.get(r["paper_id"], {})
        r["topic_id"] = f.get("topic_id", "")
        r["attitude_label"] = f.get("attitude_label", "")
        r["methods_label"] = f.get("methods_label", "")
        # 预填 features，避免仪表盘分析时再拉 HF 模型（态度/方法），减少卡死
        r["features"] = {
            "attitude": r.get("attitude_label") or "谨慎中性",
            "methods_label": r.get("methods_label") or "",
        }
        if not r.get("keywords"):
            r["keywords"] = []
    state = SessionState(
        topic=topic,
        start_year=start_year,
        end_year=end_year,
        paper_ids=pids,
        papers=results,
        topic_distribution=topic_dist,
        year_distribution=year_dist,
    )
    return results, state


def get_analysis_for_state(state: SessionState) -> SessionState:
    """规格 4.2.2：对当前文献集合做主题聚类、研究路径、共现、热点演化、态度演化。"""
    if not state.papers:
        return state
    analyzer = CollectionAnalyzer()
    state.stats = analyzer.get_dashboard_stats(state.papers)
    cluster_res = analyzer.perform_clustering(state.papers, n_clusters=min(5, len(state.papers)))
    state.clusters = cluster_res.get("clusters", [])
    return state


def build_rag_context(state: SessionState, max_chars: int = 8000, include_structured: bool = True) -> str:
    """
    规格 4.4.3 RAG：将结构化摘要、主题小结、统计表拼成上下文，严格要求模型只引用文献集合中的论文，用 [序号] 标注。
    """
    parts = [state.to_context_summary(max_papers=15)]
    if state.clusters:
        parts.append("主题聚类：")
        for c in state.clusters[:5]:
            parts.append(f"  - {c.get('topic_name', '')}（{c.get('count', 0)} 篇）")
    if include_structured and state.paper_ids:
        try:
            structured_list = fetch_papers_with_structured(state.paper_ids[:25])
            parts.append("文献结构化摘要（仅可引用以下文献，引用时用 [1][2] 等序号）：")
            for i, p in enumerate(structured_list):
                title = (p.get("title") or "")[:60]
                bg = (p.get("background") or "")[:150]
                rq = (p.get("research_question") or "")[:150]
                methods = (p.get("methods") or "")[:150]
                concl = (p.get("conclusions") or "")[:150]
                parts.append(f"  [{i+1}] {title}")
                if bg:
                    parts.append(f"      背景：{bg}")
                if rq:
                    parts.append(f"      研究问题：{rq}")
                if methods:
                    parts.append(f"      方法：{methods}")
                if concl:
                    parts.append(f"      结论：{concl}")
        except Exception:
            pass
    text = "\n".join(parts)
    return text[:max_chars] if len(text) > max_chars else text
