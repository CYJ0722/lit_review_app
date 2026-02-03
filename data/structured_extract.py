"""
结构化摘要抽取（规格 4.1 paper_structured）：
背景、研究问题、方法、结论、创新、不足。
优先使用智谱 GLM 从摘要/正文抽取；无 API 时使用启发式规则从摘要与章节识别。
针对智谱 429 限速：请求间隔 + 429 时指数退避重试。
"""
import os
import re
import time
from typing import Any

from lit_review_app.config.settings import (
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    OPENAI_MODEL,
)

# 连续请求间隔（秒），降低触发限速概率；可通过环境变量 GLM_REQUEST_DELAY 覆盖
GLM_REQUEST_DELAY = float(os.environ.get("GLM_REQUEST_DELAY", "3.0"))
# 429 重试次数与初始等待（秒）
GLM_RATE_LIMIT_RETRIES = int(os.environ.get("GLM_RATE_LIMIT_RETRIES", "3"))
GLM_RATE_LIMIT_INITIAL_WAIT = float(os.environ.get("GLM_RATE_LIMIT_INITIAL_WAIT", "2.0"))


def _is_rate_limit_error(e: Exception) -> bool:
    """是否为限速/请求过多类错误（429 或智谱 1305）。"""
    s = str(e).lower()
    return "429" in s or "1305" in s or "请求过多" in s or "rate" in s or "limit" in s


def _call_llm_extract(text: str) -> dict[str, str]:
    """使用智谱 GLM 从文本中抽取结构化字段；遇 429 时指数退避重试，请求前可加间隔。"""
    api_key = os.environ.get("OPENAI_API_KEY") or OPENAI_API_KEY
    base_url = os.environ.get("OPENAI_BASE_URL") or OPENAI_BASE_URL
    model = os.environ.get("OPENAI_MODEL") or OPENAI_MODEL
    if not api_key or not text.strip():
        return {}
    delay = max(0, GLM_REQUEST_DELAY)
    if delay > 0:
        time.sleep(delay)
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=base_url.rstrip("/") if base_url else None)
        prompt = """从下面学术文献的摘要或正文片段中，抽取以下六项内容，每项用一句话概括；若无法识别则输出“无”。
输出格式（每行一项，不要编号外的其他符号）：
背景：
研究问题：
方法与数据：
主要结论：
创新点：
不足与局限：

文本：
"""
        last_err = None
        for attempt in range(GLM_RATE_LIMIT_RETRIES + 1):
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt + text[:4000]}],
                    max_tokens=800,
                )
                if not resp.choices:
                    return {}
                content = resp.choices[0].message.content or ""
                return _parse_llm_response(content)
            except Exception as e:
                last_err = e
                if attempt < GLM_RATE_LIMIT_RETRIES and _is_rate_limit_error(e):
                    wait = GLM_RATE_LIMIT_INITIAL_WAIT * (2 ** attempt)
                    time.sleep(wait)
                    continue
                raise
        if last_err:
            raise last_err
        return {}
    except Exception as e:
        import warnings
        warnings.warn(f"GLM 结构化摘要调用失败，将回退到启发式: {e}", UserWarning, stacklevel=2)
        return {}


def _parse_llm_response(content: str) -> dict[str, str]:
    """解析 LLM 返回的「背景：…」格式为 dict。"""
    out = {}
    keys = ["background", "research_question", "methods", "conclusions", "contributions", "limitations"]
    labels = ["背景", "研究问题", "方法与数据", "主要结论", "创新点", "不足与局限"]
    for key, label in zip(keys, labels):
        m = re.search(rf"{re.escape(label)}\s*[：:]\s*(.+?)(?=\n[A-Z\u4e00-\u9fff]|$)", content, re.DOTALL)
        if m:
            val = m.group(1).strip().strip("。").replace("\n", " ")
            if val and val != "无":
                out[key] = val[:2000]
    return out


def _heuristic_from_abstract(abstract: str, full_text_snippet: str = "") -> dict[str, str]:
    """无 LLM 时：从摘要与正文片段用启发式规则抽取。"""
    text = (abstract or "") + "\n" + (full_text_snippet or "")[:3000]
    if not text.strip():
        return {}
    out = {}
    # 背景：常含“随着”“近年来”“在……背景下”
    m = re.search(r"(随着|近年来|在[^。]{5,50}背景下?)[^。]{10,200}[。.]", text)
    if m:
        out["background"] = m.group(0).strip()[:500]
    # 研究问题：含“本文”“本研究”“探讨”“分析”
    m = re.search(r"(本文|本研究|本论文)[^。]{5,150}(探讨|研究|分析)[^。]{0,100}[。.]", text)
    if m:
        out["research_question"] = m.group(0).strip()[:500]
    # 方法：含“方法”“数据”“实证”“案例”
    for pat in [r"(采用|运用|通过)[^。]{10,120}(方法|模型|数据)[^。]{0,80}[。.]", r"(实证|案例|比较)[^。]{5,100}[。.]"]:
        m = re.search(pat, text)
        if m:
            out["methods"] = m.group(0).strip()[:500]
            break
    # 结论：含“表明”“发现”“结果”
    m = re.search(r"(结果表明?|研究发现?|综上)[^。]{10,200}[。.]", text)
    if m:
        out["conclusions"] = m.group(0).strip()[:500]
    # 创新/不足：含“创新”“不足”“局限”
    m = re.search(r"(创新|贡献)[点在于]?[^。]{5,120}[。.]", text)
    if m:
        out["contributions"] = m.group(0).strip()[:500]
    m = re.search(r"(不足|局限)[^。]{5,120}[。.]", text)
    if m:
        out["limitations"] = m.group(0).strip()[:500]
    return out


def extract_structured(abstract: str, full_text_snippet: str = "", use_llm: bool = True) -> dict[str, str]:
    """
    返回 paper_structured 所需字段（背景、研究问题、方法、结论、创新、不足）。
    use_llm=True 且配置了 API Key 时调用智谱；否则使用启发式。
    """
    text = (abstract or "").strip() + "\n" + (full_text_snippet or "").strip()
    if use_llm and (os.environ.get("OPENAI_API_KEY") or OPENAI_API_KEY):
        llm_out = _call_llm_extract(text)
        if llm_out:
            return {
                "background": llm_out.get("background", ""),
                "research_question": llm_out.get("research_question", ""),
                "methods": llm_out.get("methods", ""),
                "conclusions": llm_out.get("conclusions", ""),
                "contributions": llm_out.get("contributions", ""),
                "limitations": llm_out.get("limitations", ""),
            }
    heuristic = _heuristic_from_abstract(abstract, full_text_snippet)
    return {
        "background": heuristic.get("background", ""),
        "research_question": heuristic.get("research_question", ""),
        "methods": heuristic.get("methods", ""),
        "conclusions": heuristic.get("conclusions", ""),
        "contributions": heuristic.get("contributions", ""),
        "limitations": heuristic.get("limitations", ""),
    }
