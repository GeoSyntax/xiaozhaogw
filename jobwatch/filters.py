"""技术岗过滤。

思路：命中任一 include 关键词 且 不命中任何 exclude 关键词，才算技术岗。
关键词来自 config.yaml，可随时调整，不用改代码。
"""
from __future__ import annotations

from .models import Job


class JobFilter:
    def __init__(self, include: list[str], exclude: list[str] | None = None) -> None:
        # 统一小写，做大小写不敏感匹配
        self.include = [k.lower() for k in include]
        self.exclude = [k.lower() for k in (exclude or [])]

    def match(self, job: Job) -> bool:
        # 岗位名 + 分类 一起参与匹配，覆盖面更广
        text = f"{job.title} {job.category or ''}".lower()
        if self.exclude and any(k in text for k in self.exclude):
            return False
        if not self.include:
            return True
        return any(k in text for k in self.include)

    def apply(self, jobs: list[Job]) -> list[Job]:
        return [j for j in jobs if self.match(j)]
