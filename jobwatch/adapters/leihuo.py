"""网易雷火校招官网适配器。

为什么这家用 httpx：
    雷火校招接口 xiaozhao.leihuo.netease.com/api/apply/job/list/show 是公开
    GET JSON API，无签名、无登录，直接打就返回数据。能上 GitHub Actions。

参数要点(探测得出)：
    - GET /api/apply/job/list/show?job_name=&page_size=N&page_number=N&project_id=N
      project_id=72 是"雷火2026届校招"。招收届数会变，做成可配置。
      page_number 从 1 开始(不是 0)。
    - 返回 data.apply_job_list[]，data.count_number 是总数，data.last_page 判断翻页终点。
    - 接口通但当前(2026年7月)count_number=0——正处于夏秋换季空档，校招尚未放量。
      接好后一到放量期会自动开始抓取。
    - 字段：待接口有数据后补充（目前为空列表，字段来自 filter/show 接口推断）。
"""
from __future__ import annotations

import time
from typing import Any, List

from ..models import Job
from .base import BaseAdapter

API_URL = "https://xiaozhao.leihuo.netease.com/api/apply/job/list/show"
DETAIL_URL = "https://leihuo.163.com/campus/#/full/detail/{job_id}"
# 默认项目：72=雷火2026届校招。可在 config 覆盖。
DEFAULT_PROJECT_ID = 72


class LeihuoAdapter(BaseAdapter):
    name = "leihuo"
    display = "网易雷火"

    def __init__(
        self,
        timeout: float = 15.0,
        project_id: int = DEFAULT_PROJECT_ID,
        page_size: int = 50,
        max_pages: int = 20,
        page_pause: float = 0.4,
    ) -> None:
        super().__init__(timeout=timeout)
        self.project_id = project_id
        self.page_size = page_size
        self.max_pages = max_pages
        self.page_pause = page_pause

    def fetch(self) -> List[Job]:
        raw: list[dict[str, Any]] = []
        with self._client() as client:
            for page in range(1, self.max_pages + 1):
                params = {
                    "job_name": "",
                    "page_size": str(self.page_size),
                    "page_number": str(page),
                    "project_id": str(self.project_id),
                }
                resp = client.get(API_URL, params=params)
                data = resp.json().get("data") or {}
                items = data.get("apply_job_list") or []
                if not items:
                    break
                raw.extend(items)
                if data.get("last_page", False):
                    break
                time.sleep(self.page_pause)
        return [self._to_job(p) for p in raw]

    def _to_job(self, post: dict[str, Any]) -> Job:
        job_id = str(post.get("id") or post.get("job_id") or "")
        return Job(
            company=self.display,
            job_id=job_id,
            title=(post.get("job_name") or post.get("position_name") or "").strip(),
            city=post.get("work_place") or post.get("city") or "",
            category=post.get("category") or post.get("job_type") or "",
            url=DETAIL_URL.format(job_id=job_id),
            publish_at=post.get("update_time") or post.get("publish_time") or "",
            raw=post,
        )
