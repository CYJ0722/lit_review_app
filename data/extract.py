"""
PDF 解析与元数据抽取：使用 pdfminer.six 提取文本，启发式解析标题/作者/摘要/年份。
- 改进作者行：排除「内容提要」、过长段落、明显非人名的行。
- 摘要：优先「摘要」/「Abstract」后段落；年份限制在合理范围。
- 存储路径使用相对于 PROJECT_ROOT 的相对路径（便于迁移），并记录 source 来源标签。
"""
import hashlib
import re
from pathlib import Path
from typing import Any

from pdfminer.high_level import extract_text

from lit_review_app.config.settings import PROJECT_ROOT
from lit_review_app.data.normalizers import (
    normalize_author,
    normalize_journal,
    normalize_keywords,
    normalize_year,
)


def _normalize_text(s: str) -> str:
    fw = "０１２３４５６７８９"
    hw = "0123456789"
    trans = {ord(f): ord(d) for f, d in zip(fw, hw)}
    trans[ord("\u3000")] = ord(" ")
    s = s.translate(trans)
    s = re.sub(r"[ \t\u00A0]+", " ", s)
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    return s


# 不应作为作者名的片段（整行或明显噪音）
AUTHOR_NOISE = {
    "内容提要",
    "摘要",
    "abstract",
    "关键词",
    "keywords",
    "引言",
    "introduction",
    "目录",
    "一、",
    "二、",
    "（",
    "(",
    "中国行政管理",
    "PUBLIC ADMINISTRATION",
    "数字政府治理",
    "公共安全",
    "他山之石",
    "本刊专稿",
    "探索与争鸣",
    "作者：",
    "基金项目",
    "DOI：",
    "要］",
}


def _is_likely_author_line(line: str) -> bool:
    line = line.strip()
    if not line or len(line) > 80:
        return False
    for noise in AUTHOR_NOISE:
        if noise in line:
            return False
    # 学院、大学等多为单位
    if re.search(r"(学院|大学|研究院|公司|联系方式|地址|通讯作者|email|@)", line, re.I):
        return False
    return True


def _extract_authors_from_lines(lines: list, title_end_idx: int) -> list:
    authors = []
    for j in range(title_end_idx + 1, min(title_end_idx + 8, len(lines))):
        line = lines[j]
        if re.search(r"\b(Abstract|摘要|Introduction|Keywords?)\b", line, re.I):
            break
        if not _is_likely_author_line(line):
            continue
        # 中文：短段、可能含逗号/顿号/空格分隔的多个姓名
        if re.search(r"[\u4e00-\u9fff]", line):
            parts = re.split(r"[,;；\s、]{1,}", line)
            for p in parts:
                p = p.strip(" ,;。")
                if 1 <= len(p) <= 20 and p not in authors:
                    authors.append(p)
        elif "," in line or " and " in line.lower() or "和" in line:
            parts = re.split(r"[,;；]|\s+and\s+|和", line)
            for p in parts:
                p = normalize_author(p)
                if p and p not in authors:
                    authors.append(p)
        elif re.search(r"[A-Z][a-z]+\s+[A-Z][a-z]+", line):
            if line not in authors:
                authors.append(line)
    # 去重保序
    seen = set()
    out = []
    for a in authors:
        a = normalize_author(a)
        if a and a not in seen:
            seen.add(a)
            out.append(a)
    return out


def extract_metadata_from_text(text: str) -> dict:
    text = _normalize_text(text)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    meta = {"title": "", "authors": [], "year": None, "journal": "", "abstract": "", "keywords": ""}

    if not lines:
        return meta

    # 标题：前几行合并直到足够长，跳过纯百分号行
    title_idx = 0
    acc = []
    for i in range(min(6, len(lines))):
        if lines[i].strip().endswith("%"):
            continue
        acc.append(lines[i])
        cand = " ".join(acc)
        if len(cand) >= 15:
            meta["title"] = re.sub(r"\s+", " ", cand).strip()
            title_idx = i
            break
    else:
        meta["title"] = re.sub(r"\s+", " ", lines[0]).strip()
        title_idx = 0

    meta["authors"] = _extract_authors_from_lines(lines, title_idx)

    # 年份：整文中找合理年份
    m = re.search(r"\b(19\d{2}|20[0-3]\d)\b", text)
    if m:
        meta["year"] = m.group(1)

    # 摘要
    low = text.lower()
    m_abs = re.search(r"(摘\s*要|要\s*摘|abstract)", low, re.I)
    if m_abs:
        idx = m_abs.end()
        rest = text[idx : idx + 5000]
        stop = re.search(r"\n\s*(关键词|keywords|中图|引言|1\.|目录)", rest, re.I)
        abstract = rest[: stop.start()].strip() if stop else rest.strip()[:2000]
        meta["abstract"] = re.sub(r"\s+", " ", abstract)

    # 期刊/来源：前几行中含 journal / 期刊 等；normalize_journal 会截断混入的正文
    for l in lines[:12]:
        if re.search(r"journal|proceedings|conference|期刊|会议", l, re.I):
            meta["journal"] = normalize_journal(l)
            break
    if not meta["journal"] and re.search(r"中国行政管理", text[:3000]):
        meta["journal"] = "中国行政管理"

    # 关键词：［关键词］… 或 关键词：… 至 ［中图/［文献标识码/［文章编号
    m_kw = re.search(r"［?关键词］?\s*[：:]?\s*([^［\n]+?)(?=［中图|［文献标识码|［文章编号|\n\s*［|$)", text)
    if m_kw:
        kw_list = normalize_keywords(m_kw.group(1).strip())
        meta["keywords"] = ",".join(kw_list) if kw_list else ""

    return meta


def _title_author_from_filename(pdf_path: Path) -> tuple[str, list[str]]:
    """
    从「标题_作者.pdf」或「标题_作者_其他.pdf」形式解析标题与作者，作为正文解析的 fallback。
    规则：去掉 .pdf 后按最后一个下划线分割，前半为标题、后半为作者（或作者_其他，只取第一段作为作者）。
    """
    stem = pdf_path.stem
    if not stem or "_" not in stem:
        return "", []
    idx = stem.rfind("_")
    title_part = stem[:idx].strip()
    author_part = stem[idx + 1 :].strip()
    if not title_part or len(title_part) < 2:
        return "", []
    title_part = re.sub(r"\s+", " ", title_part)
    author_part = re.sub(r"\s+", " ", author_part)
    author = author_part.split("_")[0].strip() if author_part else ""
    authors = [normalize_author(author)] if author and 1 <= len(author) <= 50 else []
    return title_part, authors


def _is_title_likely_header(title: str) -> bool:
    """标题是否更像页眉/DOI/期刊名（应优先用文件名）。"""
    if not title or len(title) < 3:
        return True
    if re.search(r"DOI\s*[：:]", title):
        return True
    if re.search(r"\d{4}\s*年\s*第\s*\d+\s*期", title):
        return True
    # 期刊页眉常见：「中国行政管理」+ 英文名或期号，无真实论文标题
    if "中国行政管理" in title:
        t_upper = title.upper().replace(" ", "")
        if "ADMINISTRATION" in t_upper or "PUBLIC" in t_upper or "CHINESE" in t_upper:
            return True
        if re.search(r"中国行政管理\s*[A-Z\s]{5,}", title) or len(title) < 60:
            return True
    if len(title) > 250:
        return True
    return False


def _is_authors_likely_wrong(authors: list) -> bool:
    """作者列表是否明显异常（含期刊名、单字、摘要、副标题片段等）。"""
    if not authors:
        return True
    noise = {"中国行政管理", "摘要", "要］", "公共安全", "他山之石", "数字政府治理", "本刊专稿", "探索与争鸣"}
    for a in authors:
        a = (a or "").strip()
        if len(a) <= 1:
            return True
        if "？" in a or "——" in a or len(a) > 25:
            return True
        if a in noise or any(n in a for n in noise):
            return True
    return False


def _merge_filename_fallback(meta: dict, pdf_path: Path) -> None:
    """当正文解析的标题或作者为空/过短/明显错误时，用文件名解析结果回填。"""
    file_title, file_authors = _title_author_from_filename(pdf_path)
    if not file_title and not file_authors:
        return
    title = (meta.get("title") or "").strip()
    if not title or len(title) < 5 or _is_title_likely_header(title):
        if file_title:
            meta["title"] = file_title
    authors = meta.get("authors") or []
    if not authors or _is_authors_likely_wrong(authors):
        if file_authors:
            meta["authors"] = file_authors
    return


def clean_meta(meta: dict) -> dict:
    meta["year"] = normalize_year(meta.get("year"))
    if meta.get("title"):
        meta["title"] = re.sub(r"\s+", " ", meta["title"]).strip()
    if meta.get("authors"):
        # 过滤明显非人名的项：含？、——、过长（>25 字符多为标题/副标题片段）
        filtered = []
        for a in meta["authors"]:
            a = normalize_author(a)
            if not a:
                continue
            if "？" in a or "——" in a or len(a) > 25:
                continue
            filtered.append(a)
        meta["authors"] = filtered
    if meta.get("abstract"):
        meta["abstract"] = re.sub(r"^[［\][]*\s*", "", meta["abstract"].strip())
    if meta.get("journal"):
        meta["journal"] = normalize_journal(meta["journal"])
    if meta.get("keywords"):
        meta["keywords"] = normalize_keywords(meta["keywords"])
    return meta


def path_to_stored(p: Path) -> str:
    """将 PDF 路径转为存储用：优先相对 PROJECT_ROOT 的相对路径。"""
    try:
        return str(p.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(p.resolve())


def process_pdf(pdf_path: Path, source_label: str) -> dict:
    """
    解析单个 PDF，返回一条可入库的记录。
    source_label 由 discovery 传入（父文件夹名）。
    """
    try:
        text = extract_text(str(pdf_path))
    except Exception as e:
        return {"_error": str(e)}

    meta = extract_metadata_from_text(text)
    _merge_filename_fallback(meta, pdf_path)
    meta = clean_meta(meta)
    # 存储路径与来源
    meta["_path"] = path_to_stored(pdf_path)
    meta["_sha1"] = hashlib.sha1(text.encode("utf-8")).hexdigest()
    meta["source"] = source_label
    meta["_raw_text_snippet"] = text[:3000]
    return meta
