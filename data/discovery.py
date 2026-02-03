"""
文献发现：从配置的多个根目录递归查找 PDF，并根据「最后一级父文件夹名」推断来源。

来源规则：
  - 每个 PDF 的 source 取「其所在目录的文件夹名」（即 parent.name），
    例如： .../中文文献(29)/中文文献(29)/xxx.pdf -> source = "中文文献(29)"
  - 若 PDF 直接放在根目录下，则 source 取根目录名。
"""
from pathlib import Path
from typing import List, Tuple

from lit_review_app.config.settings import LIT_SOURCE_ROOTS, PROJECT_ROOT


def find_pdfs(
    roots: List[Path] | None = None,
    exclude_dirs: set | None = None,
) -> List[Tuple[Path, str]]:
    """
    在给定根目录下递归查找所有 PDF，返回 [(pdf_path, source_label), ...]。

    source_label：该 PDF 所在「最后一级父文件夹」名称，用于区分文献来源。
    exclude_dirs：要跳过的目录名集合（如 __pycache__, .git）。
    """
    if roots is None:
        roots = [Path(p) for p in LIT_SOURCE_ROOTS]
    if exclude_dirs is None:
        exclude_dirs = {"__pycache__", ".git", "raw_texts", "embeddings", "out"}

    out: List[Tuple[Path, str]] = []
    seen_paths = set()

    for root in roots:
        if not root.exists():
            continue
        if root.is_file():
            if root.suffix.lower() == ".pdf":
                src_label = root.parent.name or root.stem
                out.append((root, src_label))
            continue
        for path in root.rglob("*.pdf"):
            if path in seen_paths:
                continue
            # 跳过在排除目录下的文件
            parts = path.relative_to(root).parts
            if any(p in exclude_dirs for p in parts):
                continue
            seen_paths.add(path)
            # 来源：最后一级父文件夹名（即 PDF 所在目录名）
            source = path.parent.name or root.name
            out.append((path, source))

    return out


def get_source_roots_help() -> str:
    """返回如何设置 LIT_SOURCE_ROOTS 的说明。"""
    return (
        "请设置环境变量 LIT_SOURCE_ROOTS，多个路径用分号 ; 分隔。\n"
        "例如：LIT_SOURCE_ROOTS=第二批文献收集;2023-2025_extracted\n"
        "若 2023-2025 下的 zip/rar 已解压到 2023-2025_extracted，请将解压后的目录加入。"
    )
