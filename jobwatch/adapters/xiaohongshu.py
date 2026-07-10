"""小红书(RED)校招官网适配器。

为什么这家用 httpx：
    小红书校招接口 job.xiaohongshu.com/websiterecruit/position/pageQueryPosition
    是公开 POST JSON API，无签名、无动态凭证，直接打就返回数据。能上 GitHub Actions。

参数要点(探测得出)：
    - POST body: {"recruitType":"campus","positionName":"","pageNum":N,"pageSize":N}
      recruitType=campus 是校招(含实习)。
    - 返回 data.list[]，含 total/totalPage 可判断翻页终点。
    - 每条含 positionName/workplace/publishTime/jobType(tech=技术类)/duty。
"""
from __future__ import annotations

import time
from typing import Any, List

from ..models import Job
from .base import BaseAdapter

API_URL = "https://job.xiaohongshu.com/websiterecruit/position/pageQueryPosition"
DETAIL_URL = "https://job.xiaohongshu.com/campus/position/{job_id}"


class XiaohongshuAdapter(BaseAdapter):
    name = "xiaohongshu"
    display = "小红书"

    def __init__(
        self,
        timeout: float = 15.0,
        recruit_type: str = "campus",
        page_size: int = 50,
        max_pages: int = 10,
        page_pause: float = 0.4,
    ) -> None:
        super().__init__(timeout=timeout)
        self.recruit_type = recruit_type
        self.page_size = page_size
        self.max_pages = max_pages
        self.page_pause = page_pause

    def _client(self):
        import httpx

        from .base import DEFAULT_HEADERS

        headers = dict(DEFAULT_HEADERS)
        headers["Content-Type"] = "application/json"
        headers["Origin"] = "https://job.xiaohongshu.com"
        headers["Referer"] = "https://job.xiaohongshu.com/campus/position"
        return httpx.Client(headers=headers, timeout=self.timeout)

    def fetch(self) -> List[Job]:
        raw: list[dict[str, Any]] = []
        with self._client() as client:
            for page in range(1, self.max_pages + 1):
                body = {
                    "recruitType": self.recruit_type,
                    "positionName": "",
                    "pageNum": page,
                    "pageSize": self.page_size,
                }
                resp = client.post(API_URL, json=body)
                data = resp.json().get("data") or {}
                items = data.get("list") or []
                if not items:
                    break
                raw.extend(items)
                if page >= (data.get("totalPage") or 1):
                    break
                time.sleep(self.page_pause)
        return [self._to_job(p) for p in raw]

    def _to_job(self, post: dict[str, Any]) -> Job:
        job_id = str(post.get("positionId") or "")
        # jobType 是 code(如 tech)，jobProjectName/岗位名承载可读信息。
        # 把 jobType 也拼进 category，配合 include 的"技术"关键词更易命中。
        category = post.get("jobType") or ""
        return Job(
            company=self.display,
            job_id=job_id,
            title=(post.get("positionName") or "").strip(),
            city=post.get("workplace") or "",
            category=category,
            url=DETAIL_URL.format(job_id=job_id),
            publish_at=post.get("publishTime") or "",
            raw=post,
        )
