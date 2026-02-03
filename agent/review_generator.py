"""
综述生成：两种模式（快速综述 / 基于当前分析的定制综述），使用 RAG + 大模型。
"""
import logging
from typing import Any

from lit_review_app.agent.session import SessionState

logger = logging.getLogger(__name__)
from lit_review_app.agent.tools import search_papers, get_analysis_for_state, build_rag_context


def _call_llm(
    system: str,
    user: str,
    max_tokens: int = 2000,
    timeout: float = 90.0,
) -> str:
    """调用大模型：智谱 GLM-4-Flash（OpenAI 兼容 API）。未配置时返回占位。"""
    import os
    from lit_review_app.config.settings import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL
    api_key = os.environ.get("OPENAI_API_KEY") or OPENAI_API_KEY
    base_url = os.environ.get("OPENAI_BASE_URL") or OPENAI_BASE_URL
    model = os.environ.get("OPENAI_MODEL") or OPENAI_MODEL
    if not api_key:
        return (
            "【未配置 OPENAI_API_KEY】请设置环境变量（智谱 API Key）后重试。"
            " 综述草稿将基于当前文献摘要生成，此处返回占位说明。"
        )
    try:
        from openai import OpenAI
        client = OpenAI(
            api_key=api_key,
            base_url=base_url.rstrip("/") if base_url else None,
            timeout=timeout,
        )
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
        )
        if resp.choices:
            return resp.choices[0].message.content or ""
    except Exception as e:
        return f"【调用大模型失败】{e}"
    return ""


def generate_review_fast(
    topic: str,
    start_year: int | None = None,
    end_year: int | None = None,
) -> tuple[str, SessionState]:
    """
    规格 4.4.3 模式 A：检索 → 分析 → 推荐文献集合（默认全选）→ 生成大纲 → 分章节草稿。
    单次调用生成结构化草稿：背景、主要研究路径、热点与趋势、不足与展望；严格只引用上下文中列出的文献，用 [1][2] 序号。
    """
    results, state = search_papers(topic=topic, start_year=start_year, end_year=end_year, limit=80)
    state = get_analysis_for_state(state)
    context = build_rag_context(state, max_chars=8000, include_structured=True)
    system = (
        "你是一位学术写作助手。请根据提供的文献集合与结构化摘要、统计信息，撰写一篇结构化的文献综述草稿。"
        "必须包含以下章节：一、背景与问题；二、主要研究路径；三、热点与趋势；四、不足与展望。"
        "严格约束：只能引用上下文中已列出的文献，且引用时必须使用 [1][2][3] 等序号对应文献列表中的 [1][2][3]，不得编造文献。"
    )
    user = f"主题：{topic}\n时间范围：{start_year or '?'}–{end_year or '?'}\n\n文献与统计信息：\n{context}\n\n请生成综述草稿（含上述四部分）。"
    logger.info("generate_review_fast calling LLM topic=%r contextLen=%d", topic, len(context or ""))
    draft = _call_llm(system, user, max_tokens=4000, timeout=120.0)
    logger.info("generate_review_fast LLM returned draftLen=%d", len(draft or ""))
    return draft, state


def generate_review_from_session(
    state: SessionState,
    user_focus: str = "",
) -> tuple[str, SessionState]:
    """
    规格 4.4.3 模式 B：基于当前分析的定制综述。以当前 SessionState + 用户关注角度为约束，定制大纲与章节。
    严格只引用文献集合中的论文，用 [1][2] 序号。
    """
    state = get_analysis_for_state(state) if not state.stats else state
    context = build_rag_context(state, max_chars=8000, include_structured=True)
    focus_note = ""
    if user_focus:
        focus_note = f"\n用户特别关注的角度（请在综述中重点体现）：{user_focus}"
    if state.user_focus_angles:
        focus_note += "\n用户此前关注的角度：" + "；".join(state.user_focus_angles)
    system = (
        "你是一位学术写作助手。请根据当前文献集合与结构化摘要、统计信息撰写综述草稿。"
        "若提供了用户关注角度，请在综述中单列小节或重点段落体现这些角度。"
        "严格约束：只能引用上下文中已列出的文献，引用时使用 [1][2][3] 等序号，不得编造文献。"
    )
    user = f"文献与统计信息：\n{context}{focus_note}\n\n请生成定制综述草稿。"
    draft = _call_llm(system, user)
    return draft, state


def answer_question_with_rag(
    question: str,
    topic: str = "",
    start_year: int | None = None,
    end_year: int | None = None,
) -> tuple[str, list[str]]:
    """
    规格 4.4.2 Q&A：从 SessionState 确定文献集合（或重新检索），调分析服务获取统计，RAG 上下文 + 大模型回答，严格只引用所给文献 [1][2]。
    """
    results, state = search_papers(topic=topic, start_year=start_year, end_year=end_year, limit=50)
    state.papers = results
    state.last_question = question
    state = get_analysis_for_state(state)
    context = build_rag_context(state, max_chars=6000, include_structured=True)
    system = (
        "你是一位文献分析助理。根据提供的文献集合与结构化摘要、统计信息回答用户问题。"
        "严格约束：回答中若提到具体研究，必须用文献序号 [1][2][3] 等形式标注，且只能引用上下文中已列出的文献，不得编造。"
    )
    user = f"当前主题与时间范围：{topic or '不限'}，{start_year or '?'}–{end_year or '?'}\n\n文献与统计：\n{context}\n\n用户问题：{question}"
    answer = _call_llm(system, user, max_tokens=2500, timeout=120.0)
    ref_ids = [p["paper_id"] for p in state.papers[:10]]
    return answer, ref_ids


def refine_review_with_chat(
    draft: str,
    question: str,
    topic: str = "",
    paper_ids: list[str] | None = None,
) -> str:
    """
    根据用户问题完善综述草稿。可传入当前草稿、用户问题、主题与引用文献 id 列表；
    若提供 paper_ids 则拉取文献摘要作为上下文，否则仅基于草稿与问题修改。
    返回完善后的完整综述正文。
    """
    from lit_review_app.agent.tools import build_rag_context
    from lit_review_app.retrieval.db import get_connection
    import json

    context_extra = ""
    if paper_ids:
        conn = get_connection()
        cur = conn.cursor()
        placeholders = ",".join("?" * len(paper_ids))
        cur.execute(
            f"SELECT paper_id, title, abstract, year FROM papers WHERE paper_id IN ({placeholders})",
            paper_ids[:50],
        )
        rows = cur.fetchall()
        conn.close()
        parts = []
        for i, r in enumerate(rows, 1):
            pid, title, abstract, year = r[0], r[1] or "", r[2] or "", r[3]
            ab = (abstract or "")[:300].replace("\n", " ")
            parts.append(f"[{i}] {title} ({year})\n{ab}")
        if parts:
            context_extra = "\n\n引用文献摘要（供参考）：\n" + "\n\n".join(parts)

    system = (
        "你是一位学术写作助手。用户会提供一篇文献综述草稿和一个修改意见/问题。"
        "请根据用户的问题或意见，对草稿进行实质性修改与完善：可增删段落、重写小节、补充论据或案例，使修改后的正文明显体现用户意图。"
        "不要只做微调或简单复述；直接输出修改后的完整综述正文。"
        "要求：保持章节结构（如 一、二、三、四），保持 [1][2][3] 等文献引用格式，不要编造文献。"
    )
    user = f"综述草稿：\n{draft}\n\n用户问题/修改意见：{question}\n{context_extra}\n\n请根据上述意见对草稿做实质性修改，并直接输出修改后的完整综述正文（不要加解释）。"
    out = _call_llm(system, user, max_tokens=4000, timeout=120.0)
    return out.strip() or draft


def draft_to_latex_via_llm(draft: str) -> str:
    """
    通过大模型将综述草稿转为英文 LaTeX 源码，便于用标准 pdflatex 编译（无需 ctex）。
    要求：先翻译为英文，再输出 .tex，使用 \\section/\\subsection、\\textbf，禁止 * 与 \\ 在 \\textbf 内。
    失败或未配置时返回空字符串，调用方应回退到规则转换。
    """
    system = (
        "You are a LaTeX document assistant. The user will provide a Chinese literature review draft. "
        "You must: (1) Translate the entire content into English; (2) Output a complete, compilable .tex source. "
        "Rules: "
        "Use \\documentclass[12pt]{article}, \\usepackage[utf8]{inputenc}, \\usepackage[T1]{fontenc}. "
        "Do NOT use ctex or any Chinese package - the output must be English only so it compiles with pdflatex. "
        "Use \\section{} for main headings (e.g. 'I. Background and Issues'), \\subsection{} for subheadings. "
        "Use \\textbf{} for bold phrases; do not put \\\\ or \\newline inside \\textbf{}. "
        "Do not use Markdown symbols (*, **, #). Separate paragraphs with blank lines. "
        "Escape special characters (& % _ { }) in body text. "
        "Output only the .tex file content, no explanation."
    )
    user = f"Translate the following Chinese literature review into English and output as LaTeX:\n\n{draft}"
    out = _call_llm(system, user, max_tokens=4000, timeout=60.0)
    if not out or "documentclass" not in out.lower():
        return ""
    out = out.strip()
    import re
    for cmd in ("textbf", "section", "subsection", "documentclass", "usepackage", "begin", "end", "title", "author", "date", "parskip", "setlength", "parindent", "inputenc", "fontenc"):
        out = out.replace("\\\\" + cmd, "\\" + cmd)
    def fix_textbf(m):
        inner = m.group(1)
        inner = inner.replace("\\\\", " ").replace("\\newline", " ")
        inner = re.sub(r"\s+", " ", inner).strip()
        return "\\textbf{" + inner + "}"
    out = re.sub(r"\\textbf\{([^{}]*)\}", fix_textbf, out)
    return out
