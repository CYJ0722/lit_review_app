"""
规格 4.3 查询理解：将用户自然语言解析为结构化查询（主题词列表、时间区间、过滤条件）。
"""
import re
from dataclasses import dataclass
from typing import Any


@dataclass
class ParsedQuery:
    topic_terms: list[str]
    start_year: int | None
    end_year: int | None
    language: str | None
    journal_level: str | None
    raw_query: str


def parse_query(raw: str) -> ParsedQuery:
    """
    从自然语言中抽取：主题词（剩余有效词）、时间区间（年份正则）、语言/期刊等过滤（可选）。
    """
    raw = (raw or "").strip()
    topic_terms = []
    start_year = None
    end_year = None
    language = None
    journal_level = None

    # 年份：2018-2024、2018至2024、2018年到2024、after 2020、before 2019
    year_patterns = [
        (r"(?:19|20)\d{2}\s*[-–至到]\s*(?:19|20)\d{2}", "range"),
        (r"(?:19|20)\d{2}\s*年\s*(?:至今|以后)", "start"),
        (r"(?:after|since|从)\s*(?:19|20)\d{2}", "start"),
        (r"(?:before|之前)\s*(?:19|20)\d{2}", "end"),
        (r"(?:19|20)\d{2}\s*年?(?:以前|之前)", "end"),
    ]
    remaining = raw
    for pat, kind in year_patterns:
        m = re.search(pat, remaining, re.I)
        if m:
            nums = re.findall(r"19\d{2}|20\d{2}", m.group(0))
            nums = [int(x) for x in nums]
            if kind == "range" and len(nums) >= 2:
                start_year, end_year = min(nums), max(nums)
            elif kind == "start" and nums:
                start_year = max(nums)
            elif kind == "end" and nums:
                end_year = min(nums)
            remaining = remaining[: m.start()] + " " + remaining[m.end() :]

    # 语言：中文/英文
    if re.search(r"\b(中文|汉语|china|chinese)\b", remaining, re.I):
        language = "zh"
        remaining = re.sub(r"\b(中文|汉语|china|chinese)\b", " ", remaining, flags=re.I)
    elif re.search(r"\b(英文|英语|english)\b", remaining, re.I):
        language = "en"
        remaining = re.sub(r"\b(英文|英语|english)\b", " ", remaining, flags=re.I)

    # 主题词：剩余部分去停用词、拆分为词列表（中文按字/词，英文按单词）
    stop = {"的", "与", "和", "及", "等", "之", "在", "是", "有", "为", "对", "从", "到", "关于", "研究", "分析", "the", "and", "for", "with", "from", "about"}
    tokens = re.findall(r"[a-zA-Z]{2,}|[\u4e00-\u9fff]+", remaining)
    topic_terms = [t for t in tokens if t and t not in stop]
    if not topic_terms and raw.strip():
        topic_terms = [raw.strip()[:50]]

    return ParsedQuery(
        topic_terms=topic_terms,
        start_year=start_year,
        end_year=end_year,
        language=language,
        journal_level=journal_level,
        raw_query=raw,
    )
