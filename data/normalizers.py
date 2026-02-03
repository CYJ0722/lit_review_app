"""简单规范化：作者、年份、期刊、关键词。"""
import re
from typing import Any


def normalize_year(y: Any) -> str | None:
    if y is None:
        return None
    s = str(y).strip()
    m = re.search(r"(19\d{2}|20\d{2})", s)
    return m.group(1) if m else None


def normalize_author(name: str) -> str:
    if not name or not isinstance(name, str):
        return ""
    s = name.strip()
    s = re.sub(r"\(.*?\)", "", s)
    s = re.sub(r"\[.*?\]", "", s)
    s = re.sub(r"\<.*?\>", "", s)
    s = re.sub(r"[，,;。]+$", "", s)
    s = re.sub(r"\s+", " ", s)
    if "," in s and not re.search(r"\b(and|和)\b", s, re.I):
        parts = [p.strip() for p in s.split(",") if p.strip()]
        if len(parts) >= 2:
            s = " ".join(parts[1:] + [parts[0]])
    return s.strip()


def normalize_journal(name: str) -> str:
    if not name:
        return ""
    s = name.strip()
    s = re.sub(r"\s+", " ", s)
    s = s.strip(" ,;:。")
    # 期刊字段常混入正文：截断于正文起始标记或长度上限
    if len(s) > 80:
        for sep in ["稳健性检验", "（一）", "一、", "二、", "参考文献", "引言", "目录", "数字政府治理（"]:
            idx = s.find(sep)
            if idx > 10:
                s = s[:idx].strip()
                break
        if len(s) > 80:
            s = s[:80].strip()
    # 若明显是「中国行政管理」+ 期号/英文名 + 大段正文，只保留期刊名
    if "中国行政管理" in s and len(s) > 35:
        if re.search(r"中国行政管理.{10,}(稳健性|引言|参考文献|（[一二三四五六七八九十]）)", s):
            return "中国行政管理"
    return s


def normalize_keywords(kw: Any) -> list:
    if not kw:
        return []
    if isinstance(kw, str):
        parts = re.split(r"[,;；\n]", kw)
    else:
        parts = list(kw)
    return [p.strip() for p in parts if p and p.strip()]
