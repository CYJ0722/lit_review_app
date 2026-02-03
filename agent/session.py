"""
规格 4.4.1 会话状态与用户历史：当前主题/时间/已选文献/分析结果/大纲/已生成章节/最近指令；可选用户关注角度（模式 B）。
"""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SessionState:
    topic: str = ""
    start_year: int | None = None
    end_year: int | None = None
    paper_ids: list[str] = field(default_factory=list)
    papers: list[dict] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    clusters: list[dict] = field(default_factory=list)
    topic_distribution: list[dict] = field(default_factory=list)
    year_distribution: list[dict] = field(default_factory=list)
    outline: list[str] = field(default_factory=list)
    generated_chapters: dict[str, str] = field(default_factory=dict)
    last_instruction: str = ""
    last_question: str = ""
    user_focus_angles: list[str] = field(default_factory=list)

    def to_context_summary(self, max_papers: int = 20) -> str:
        """生成给 LLM 的简短上下文说明（不含结构化摘要，用于简短摘要）。"""
        lines = []
        if self.topic:
            lines.append(f"当前主题：{self.topic}")
        if self.start_year or self.end_year:
            y = f"{self.start_year or '?'}–{self.end_year or '?'}"
            lines.append(f"时间范围：{y}")
        if self.papers:
            n = min(len(self.papers), max_papers)
            lines.append(f"当前文献集合共 {len(self.papers)} 篇，以下为前 {n} 篇摘要：")
            for i, p in enumerate(self.papers[:n]):
                title = (p.get("title") or "")[:80]
                abstract = (p.get("abstract") or "")[:200]
                lines.append(f"  [{i+1}] {title} ... {abstract}...")
        if self.stats:
            yc = self.stats.get("yearlyCounts", [])
            if yc:
                lines.append("年度发文量：" + ", ".join(f"{x['year']}({x['count']})" for x in yc[:5]))
            kw = self.stats.get("topKeywords", [])[:5]
            if kw:
                lines.append("高频关键词：" + ", ".join(x["name"] for x in kw))
        if self.user_focus_angles:
            lines.append("用户关注角度：" + "；".join(self.user_focus_angles))
        return "\n".join(lines) if lines else "（暂无文献集合）"
