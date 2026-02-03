"""
统一 FastAPI 应用：检索、分析仪表盘、分析助理问答、综述生成。
与前端 web_config 的 realApi 契约对齐：searchPapers, getDashboardStats, askAnalysisAssistant。
"""
import logging
import re
import time
from pathlib import Path

logger = logging.getLogger(__name__)

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional

from lit_review_app.retrieval.search import search_with_distributions
from lit_review_app.retrieval.db import fetch_features, fetch_papers_with_structured, get_connection
from lit_review_app.analysis.service import CollectionAnalyzer
from lit_review_app.agent.tools import search_papers, get_analysis_for_state
from lit_review_app.agent.review_generator import (
    answer_question_with_rag,
    generate_review_fast,
    refine_review_with_chat,
    draft_to_latex_via_llm,
)


def _parse_abstract_meta(raw: str) -> tuple[str, dict]:
    """
    从原始摘要中拆出正文与元数据块，返回 (正文, { keywords, clc, docCode, articleId })。
    便于前端分框展示，不混在一起。
    """
    if not raw or not isinstance(raw, str):
        return "", {}
    s = raw.strip()
    # 去掉开头的 [摘要]、摘要]、] 等常见前缀（含全角、空白）
    s = re.sub(r"^[\s\ufeff]*(\[?\s*摘要\s*\]?|[\［\[]?\s*摘要\s*[\］\]]?)\s*", "", s, flags=re.I)
    while s and s[0] in " \t\n\r[]［］［\ufeff":
        s = s[1:]
    meta = {}
    # 提取 [关键词] 或 ［关键词］ ...（到下一个 [ 或结尾），允许标签内少量空格
    m = re.search(r"\[[\s]*关键词[\s]*\]([^\[]*)", s, re.I)
    if m:
        meta["keywords"] = m.group(1).strip()
        s = s[: m.start()] + s[m.end() :]
    m = re.search(r"\[[\s]*中图分类号[\s]*\]([^\[]*)", s, re.I)
    if m:
        meta["clc"] = m.group(1).strip()
        s = s[: m.start()] + s[m.end() :]
    m = re.search(r"\[[\s]*文献标识码[\s]*\]([^\[]*)", s, re.I)
    if m:
        meta["docCode"] = m.group(1).strip()
        s = s[: m.start()] + s[m.end() :]
    m = re.search(r"\[[\s]*文章编号[\s]*\]([^\[]*)", s, re.I)
    if m:
        meta["articleId"] = m.group(1).strip()
        s = s[: m.start()] + s[m.end() :]
    m = re.search(r"\[DOI\]([^\[]*)", s, re.I)
    if m:
        s = s[: m.start()] + s[m.end() :]
    body = re.sub(r"\s+", " ", s).strip()
    # 再次去掉可能残留的前导 ]、］ 等（如原文本为 "] 作为..." 且前一步未完全去掉时）
    while body and body[0] in "]］":
        body = body[1:].strip()
    return body, meta


def _clean_abstract_for_display(raw: str) -> str:
    """去掉摘要前的 ]、以及文内元数据块，只保留正文（兼容旧逻辑）。"""
    body, _ = _parse_abstract_meta(raw)
    return body


app = FastAPI(title="文献分析与综述助手 API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _paper_to_frontend(p: dict, include_structured: bool = False) -> dict:
    """将内部 paper 转为前端 Paper 格式；摘要与元数据分拆，便于详情分框展示。"""
    raw_abstract = p.get("abstract", "") or ""
    abstract_body, abstract_meta = _parse_abstract_meta(raw_abstract)
    out = {
        "id": p.get("paper_id", ""),
        "title": p.get("title", ""),
        "authors": p.get("authors", []),
        "year": int(p["year"]) if p.get("year") is not None and str(p.get("year")).isdigit() else p.get("year"),
        "journal": p.get("journal", ""),
        "keywords": p.get("keywords", []),
        "abstract": abstract_body,
        "topicId": p.get("topic_id", "") or "",
        "abstractMeta": abstract_meta if any(abstract_meta.values()) else None,
    }
    if include_structured and any(p.get(k) for k in ("background", "research_question", "methods", "conclusions", "contributions", "limitations")):
        out["structured"] = {
            "background": p.get("background", ""),
            "research_question": p.get("research_question", ""),
            "methods": p.get("methods", ""),
            "conclusions": p.get("conclusions", ""),
            "contributions": p.get("contributions", ""),
            "limitations": p.get("limitations", ""),
        }
    return out


# ---------- 与前端 realApi 对齐的接口 ----------

@app.get("/api/search")
def api_search(
    topic: Optional[str] = Query(None),
    startYear: Optional[int] = Query(None),
    endYear: Optional[int] = Query(None),
    language: Optional[str] = Query(None),
    includeStructured: Optional[bool] = Query(True, description="是否在结果中带结构化摘要"),
):
    """
    规格 4.3 输出：候选列表（含 topicId、可选结构化摘要）+ 主题分布 + 年份分布。
    """
    out = search_with_distributions(
        q=topic or "",
        start_year=startYear,
        end_year=endYear,
        limit=200,
        use_query_understanding=True,
    )
    results = out.get("results", [])
    if not results:
        return {
            "results": [],
            "total": 0,
            "topicDistribution": out.get("topic_distribution", []),
            "yearDistribution": out.get("year_distribution", []),
        }
    pids = [r["paper_id"] for r in results]
    features = fetch_features(pids)
    for r in results:
        r["topic_id"] = (features.get(r["paper_id"], {}) or {}).get("topic_id", "") or ""
    if includeStructured:
        structured_list = fetch_papers_with_structured(pids)
        by_id = {s["paper_id"]: s for s in structured_list}
        for r in results:
            s = by_id.get(r["paper_id"], {})
            for k in ("background", "research_question", "methods", "conclusions", "contributions", "limitations"):
                r[k] = s.get(k, "") or ""
    return {
        "results": [_paper_to_frontend(p, include_structured=includeStructured) for p in results],
        "total": out.get("total", 0),
        "topicDistribution": out.get("topic_distribution", []),
        "yearDistribution": out.get("year_distribution", []),
    }


@app.get("/api/dashboard/stats")
def api_dashboard_stats(
    topic: Optional[str] = Query(None),
    startYear: Optional[int] = Query(None),
    endYear: Optional[int] = Query(None),
):
    """
    规格 4.2.2 仪表盘：年度发文、关键词 Top10、态度占比、研究路径分布、主题聚类、共现网络、热点演化、态度演化。
    """
    results, state = search_papers(
        topic=topic or "",
        start_year=startYear,
        end_year=endYear,
        limit=500,
    )
    state = get_analysis_for_state(state)
    stats = state.stats or {}
    analyzer = CollectionAnalyzer()
    cooccurrence = analyzer.build_cooccurrence_network(state.papers, min_weight=1) if state.papers else {"nodes": [], "links": []}
    trend_series = analyzer.analyze_trends(state.papers) if state.papers else {"years": [], "series": []}
    attitude_evolution = analyzer.analyze_attitude_evolution(state.papers) if state.papers else {"years": [], "series": []}
    return {
        "yearlyCounts": stats.get("yearlyCounts", []),
        "topKeywords": stats.get("topKeywords", []),
        "attitudeDistribution": stats.get("attitudeDistribution", []),
        "researchPathDistribution": stats.get("researchPathDistribution", []),
        "clusters": state.clusters,
        "topicDistribution": state.topic_distribution,
        "cooccurrence": cooccurrence,
        "trendSeries": trend_series,
        "attitudeEvolution": attitude_evolution,
    }


class AskBody(BaseModel):
    question: str
    topic: Optional[str] = None
    startYear: Optional[int] = None
    endYear: Optional[int] = None


@app.post("/api/chat")
def api_chat(body: AskBody):
    """
    对应前端 askAnalysisAssistant({ question, topic?, startYear?, endYear? })
    -> { answer: string, referencedPaperIds: string[] }
    超时或异常时返回友好提示，避免前端一直等待无返回。
    """
    try:
        answer, ref_ids = answer_question_with_rag(
            question=body.question,
            topic=body.topic or "",
            start_year=body.startYear,
            end_year=body.endYear,
        )
        return {"answer": answer or "暂无回复。", "referencedPaperIds": ref_ids or []}
    except Exception as e:
        logger.exception("api/chat failed: %s", e)
        msg = str(e).strip() or "服务暂时不可用"
        if "timeout" in msg.lower() or "timed out" in msg.lower():
            msg = "请求超时，请稍后重试。"
        return {"answer": f"【回复失败】{msg}", "referencedPaperIds": []}


# ---------- 综述生成（可选，供前端“生成综述”按钮调用） ----------

class ReviewFastBody(BaseModel):
    topic: str
    startYear: Optional[int] = None
    endYear: Optional[int] = None


@app.post("/api/review/fast")
def api_review_fast(body: ReviewFastBody):
    """规格 4.4.3 模式 A：快速综述。"""
    t0 = time.perf_counter()
    logger.info("review/fast start topic=%r startYear=%s endYear=%s", body.topic, body.startYear, body.endYear)
    try:
        draft, state = generate_review_fast(
            topic=body.topic,
            start_year=body.startYear,
            end_year=body.endYear,
        )
        elapsed = time.perf_counter() - t0
        logger.info("review/fast done topic=%r draftLen=%d paperIds=%d elapsed=%.2fs", body.topic, len(draft or ""), len(state.paper_ids or []), elapsed)
        return {"draft": draft, "paperIds": state.paper_ids}
    except Exception as e:
        logger.exception("review/fast failed topic=%r: %s", body.topic, e)
        raise


class RefineReviewBody(BaseModel):
    draft: str
    question: str
    topic: Optional[str] = None
    paperIds: Optional[list[str]] = None


@app.post("/api/review/refine")
def api_review_refine(body: RefineReviewBody):
    """根据用户问题完善综述草稿，返回完善后的完整正文。"""
    try:
        refined = refine_review_with_chat(
            draft=body.draft,
            question=body.question,
            topic=body.topic or "",
            paper_ids=body.paperIds,
        )
        return {"draft": refined}
    except Exception as e:
        logger.exception("review/refine failed: %s", e)
        raise


class ExportBody(BaseModel):
    draft: str
    format: str = "txt"  # txt | latex（latex 时后端始终优先用 AI 生成）


@app.post("/api/review/export")
def api_review_export(body: ExportBody):
    """规格 2.1：导出综述草稿为文本或 LaTeX。LaTeX 时优先用 AI 生成标准格式，失败则规则转换。"""
    if body.format == "latex":
        content = draft_to_latex_via_llm(body.draft)
        if content:
            logger.info("review/export latex: used AI-generated LaTeX, len=%d", len(content))
        else:
            content = _draft_to_latex(body.draft)
            logger.info("review/export latex: fallback to rule-based LaTeX, len=%d", len(content))
        return {"content": content, "filename": "review.tex", "mime": "application/x-tex"}
    return {"content": body.draft, "filename": "review.txt", "mime": "text/plain"}


def _latex_escape(s: str) -> str:
    for a, b in [("\\", "\\\\"), ("&", "\\&"), ("%", "\\%"), ("_", "\\_"), ("{", "\\{"), ("}", "\\}")]:
        s = s.replace(a, b)
    return s


def _draft_to_latex(draft: str) -> str:
    """将纯文本综述转为严格 LaTeX：** 转为 \\textbf{}，按章节拆分为 \\section，正文转义。"""
    import re
    s = draft.strip()
    # 先把 **xxx** 或 ** xxx ** 转为 \textbf{xxx}，避免“披着 latex 外衣的 markdown”
    def repl(m):
        inner = m.group(1).strip()
        return "\\textbf{" + _latex_escape(inner) + "}"
    s = re.sub(r"\*\*\s*([^*]*?)\s*\*\*", repl, s)
    # 单 * 斜体转为 \emph{}
    def emph_repl(m):
        inner = m.group(1).strip()
        return "\\emph{" + _latex_escape(inner) + "}"
    s = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", emph_repl, s)
    # 按「一、」「二、」等章节标题拆分
    parts = re.split(r"(?=^[一二三四五六七八九十]+[、．.]\s*[^\n]*)", s, flags=re.MULTILINE)
    lines = [
        "\\documentclass[12pt]{article}",
        "\\usepackage[UTF8]{ctex}",
        "\\usepackage{parskip}",
        "\\setlength{\\parindent}{0pt}",
        "\\begin{document}",
        "",
    ]
    for block in parts:
        block = block.strip()
        if not block:
            continue
        first_line, _, rest = block.partition("\n")
        if re.match(r"^[一二三四五六七八九十]+[、．.]\s*.+", first_line):
            title_esc = _latex_escape(first_line)
            lines.append("\\section{" + title_esc + "}")
            lines.append("")
            body = rest.strip()
        else:
            body = block
        if body:
            body_esc = _latex_escape(body)
            lines.append(body_esc.replace("\n", "\n\n"))
            lines.append("")
    lines.append("\\end{document}")
    return "\n".join(lines)


# ---------- 引用列表：按 paper_ids 批量取文献简要信息 ----------

@app.get("/api/papers")
def api_papers_by_ids(ids: Optional[str] = Query(None, description="paper_id 列表，逗号分隔")):
    """根据 paper_id 列表返回文献简要信息（id, title, authors, year, journal），用于综述引用列表展示。"""
    if not ids or not ids.strip():
        return {"papers": []}
    import json
    pids = [x.strip() for x in ids.split(",") if x.strip()]
    if not pids:
        return {"papers": []}
    conn = get_connection()
    cur = conn.cursor()
    placeholders = ",".join("?" * len(pids))
    cur.execute(
        f"SELECT paper_id, title, authors, year, journal FROM papers WHERE paper_id IN ({placeholders})",
        pids,
    )
    rows = cur.fetchall()
    conn.close()
    order = {pid: i for i, pid in enumerate(pids)}
    out = [
        {
            "id": r[0],
            "title": r[1] or "",
            "authors": json.loads(r[2]) if r[2] else [],
            "year": int(r[3]) if r[3] and str(r[3]).isdigit() else r[3],
            "journal": r[4] or "",
        }
        for r in rows
    ]
    out.sort(key=lambda x: order.get(x["id"], 999))
    return {"papers": out}


# ---------- 健康检查 ----------

@app.get("/health")
def health():
    return {"status": "ok"}


# ---------- 静态前端（构建后可通过 http://localhost:8000 打开完整页面） ----------

_FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"

if _FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=_FRONTEND_DIST / "assets"), name="assets")

    @app.get("/")
    def _serve_index():
        return FileResponse(_FRONTEND_DIST / "index.html")

    @app.get("/search")
    def _serve_search():
        return FileResponse(_FRONTEND_DIST / "index.html")

    @app.get("/dashboard")
    def _serve_dashboard():
        return FileResponse(_FRONTEND_DIST / "index.html")

    @app.get("/review")
    def _serve_review():
        return FileResponse(_FRONTEND_DIST / "index.html")
