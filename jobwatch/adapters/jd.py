"""京东校招官网适配器。

为什么这家用 httpx：
    京东校招接口 POST campus.jd.com/api/wx/position/page?type=present 是公开
    POST JSON API，无签名、无登录，直接打就返回数据。能上 GitHub Actions。
    关键：type=present 才有数据(type=1/2/3/返回0条)。

参数要点(探测得出)：
    - POST body: {"pageSize":N,"pageIndex":N,"parameter":{...}}
      pageIndex 从 0 开始(不是 1)。
    - 返回 body.items[]，body.totalNumber 是总数，body.pageCount 是总页数。
    - 每条含 publishId/positionName/workCity/positionDept/jobDirection/publishTime。
      注意：positionName 是岗位方向名(如"物流方向")，不是具体岗位名。
      positionDept 是具体部门/项目名，才是真正有用的岗位名。
    - 详情页：campus.jd.com/#/jobs/detail/{publishId}
    - 当前(7月)type=present 返回16条校招岗位。
"""
from __future__ import annotations

import time
from typing import Any, List

from ..models import Job
from .base import BaseAdapter

API_URL = "https://campus.jd.com/api/wx/position/page"
DETAIL_URL = "https://campus.jd.com/#/jobs/detail/{job_id}"


class JDAdapter(BaseAdapter):
    name = "jd"
    display = "京东"

    def __init__(
        self,
        timeout: float = 15.0,
        job_type: str = "present",
        page_size: int = 50,
        max_pages: int = 10,
        page_pause: float = 0.4,
    ) -> None:
        super().__init__(timeout=timeout)
        # present=当前校招在招。intern/internship=实习(当前为空)。
        self.job_type = job_type
        self.page_size = page_size
        self.max_pages = max_pages
        self.page_pause = page_pause

    def _client(self):
        import httpx

        from .base import DEFAULT_HEADERS

        headers = dict(DEFAULT_HEADERS)
        headers["Content-Type"] = "application/json; charset=UTF-8"
        headers["X-Requested-With"] = "XMLHttpRequest"
        headers["Origin"] = "https://campus.jd.com"
        headers["Referer"] = "https://campus.jd.com/"
        return httpx.Client(headers=headers, timeout=self.timeout)

    def fetch(self) -> List[Job]:
        raw: list[dict[str, Any]] = []
        with self._client() as client:
            for page in range(self.max_pages):
                body = {
                    "pageSize": self.page_size,
                    "pageIndex": page,
                    "parameter": {
                        "positionName": "",
                        "planIdList": [],
                        "jobDirectionCodeList": [],
                        "workCityCodeList": [],
                        "positionDeptList": [],
                    },
                }
                resp = client.post(f"{API_URL}?type={self.job_type}", json=body)
                data = resp.json().get("body") or {}
                items = data.get("items") or []
                if not items:
                    break
                raw.extend(items)
                if len(raw) >= (data.get("totalNumber") or 0):
                    break
                time.sleep(self.page_pause)
        return [self._to_job(p) for p in raw]

    def _to_job(self, post: dict[str, Any]) -> Job:
        job_id = str(post.get("publishId") or "")
        # positionDept 是具体岗位名，positionName 是方向
        title = post.get("positionDept") or post.get("positionName") or ""
        # workCity 可能是 None
        city = post.get("workCity") or ""
        # positionDeptLevel + jobDirection 拼成分类
        dept = post.get("positionDeptLevel") or ""
        direction = post.get("jobDirection") or ""
        category = f"{dept}/{direction}" if dept and direction else (dept or direction)
        return Job(
            company=self.display,
            job_id=job_id,
            title=title.strip(),
            city=city,
            category=category,
            url=DETAIL_URL.format(job_id=job_id),
            publish_at=post.get("publishTime") or "",
            raw=post,
        )
