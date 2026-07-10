"""网易校招官网适配器。

为什么这家用 httpx：
    网易互联网校招接口 campus.163.com/api/campuspc/position/getJobList 是公开
    JSON API，无签名、无登录，GET 即可。能在 GitHub Actions 稳定运行。

参数要点(探测得出)：
    - projectId=69 是"网易互联网2026届校园招聘"项目。招聘项目会随年份/批次
      变化，做成可配置(project_ids)，将来换届只改配置。
    - 返回 data.list[]，含 positionName/positionTypeName/workPlaceName/updateTime。
    - 网易 positionTypeName 用"人工智能/教育/销售"等业务分类，不像腾讯有统一
      "技术"标签，所以主要靠岗位名做技术岗过滤。
"""
from __future__ import annotations

import time
from typing import Any, List

from ..models import Job
from .base import BaseAdapter

API_URL = "https://campus.163.com/api/campuspc/position/getJobList"
DETAIL_URL = "https://campus.163.com/app/detail/index?id={job_id}&projectId={pid}"
# 默认监控的招聘项目：69=网易互联网2026届校招。可在 config 覆盖。
DEFAULT_PROJECT_IDS = [69]


class NeteaseAdapter(BaseAdapter):
    name = "netease"
    display = "网易"

    def __init__(
        self,
        timeout: float = 15.0,
        project_ids: list[int] | None = None,
        page_size: int = 50,
        max_pages: int = 10,
        page_pause: float = 0.4,
    ) -> None:
        super().__init__(timeout=timeout)
        self.project_ids = project_ids or list(DEFAULT_PROJECT_IDS)
        self.page_size = page_size
        self.max_pages = max_pages
        self.page_pause = page_pause

    def fetch(self) -> List[Job]:
        raw: list[tuple[dict[str, Any], int]] = []
        with self._client() as client:
            for pid in self.project_ids:
                for post in self._fetch_project(client, pid):
                    raw.append((post, pid))
        return [self._to_job(post, pid) for post, pid in raw]

    def _fetch_project(self, client, pid: int) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        for page in range(1, self.max_pages + 1):
            params = {
                "pageSize": str(self.page_size),
                "currentPage": str(page),
                "projectId": str(pid),
                "timeStamp": str(int(time.time() * 1000)),
            }
            resp = client.get(API_URL, params=params)
            data = resp.json().get("data") or {}
            items = data.get("list") or []
            if not items:
                break
            collected.extend(items)
            if page >= (data.get("pages") or 1):
                break
            time.sleep(self.page_pause)
        return collected

    def _to_job(self, post: dict[str, Any], pid: int) -> Job:
        job_id = str(post.get("id") or "")
        return Job(
            company=self.display,
            job_id=job_id,
            title=(post.get("positionName") or "").strip(),
            city=post.get("workPlaceName") or "",
            category=post.get("positionTypeName") or "",
            url=DETAIL_URL.format(job_id=job_id, pid=pid),
            publish_at=post.get("updateTime") or "",
            raw=post,
        )
