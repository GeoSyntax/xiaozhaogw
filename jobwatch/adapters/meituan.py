"""美团校招官网适配器。

为什么这家用 httpx：
    美团校招接口 zhaopin.meituan.com/api/official/job/getJobList 是公开 POST
    JSON API。请求 body 里官网带了 u_query_id/r_query_id 等埋点参数，但实测
    去掉后接口照常返回数据，无签名、无登录，能上 GitHub Actions。

参数要点(探测得出)：
    - POST body 里 jobType: 1=应届生(校招正式), 2=实习。默认两者都抓。
    - page.pageNo/pageSize 翻页，返回 data.page 带 totalPage/totalCount。
    - 每条含 jobUnionId/name/jobFamily/cityList/firstPostTime。
    - 详情页 URL 用 jobUnionId：zhaopin.meituan.com/web/position/{jobUnionId}
    - jobFamily 是业务分类(技术类/运营类/产品类...)，配合关键词过滤。
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any, List

from ..models import Job
from .base import BaseAdapter

API_URL = "https://zhaopin.meituan.com/api/official/job/getJobList"
DETAIL_URL = "https://zhaopin.meituan.com/web/position/{job_id}"
# jobType: 1=应届生(校招), 2=实习
DEFAULT_JOB_TYPES = ["1", "2"]


class MeituanAdapter(BaseAdapter):
    name = "meituan"
    display = "美团"

    def __init__(
        self,
        timeout: float = 15.0,
        job_types: list[str] | None = None,
        page_size: int = 20,
        max_pages: int = 15,
        page_pause: float = 0.4,
    ) -> None:
        super().__init__(timeout=timeout)
        self.job_types = job_types or list(DEFAULT_JOB_TYPES)
        self.page_size = page_size
        self.max_pages = max_pages
        self.page_pause = page_pause

    def _client(self):
        import httpx

        from .base import DEFAULT_HEADERS

        headers = dict(DEFAULT_HEADERS)
        headers["Content-Type"] = "application/json"
        headers["Origin"] = "https://zhaopin.meituan.com"
        headers["Referer"] = "https://zhaopin.meituan.com/web/campus"
        return httpx.Client(headers=headers, timeout=self.timeout)

    def fetch(self) -> List[Job]:
        raw: list[dict[str, Any]] = []
        job_type_param = [{"code": c, "subCode": []} for c in self.job_types]
        with self._client() as client:
            for page in range(1, self.max_pages + 1):
                body = {
                    "page": {"pageNo": page, "pageSize": self.page_size},
                    "jobShareType": "1",
                    "keywords": "",
                    "cityList": [],
                    "department": [],
                    "jfJgList": [],
                    "jobType": job_type_param,
                    "typeCode": [],
                    "specialCode": [],
                }
                resp = client.post(API_URL, json=body)
                data = resp.json().get("data") or {}
                items = data.get("list") or []
                if not items:
                    break
                raw.extend(items)
                page_info = data.get("page") or {}
                if page >= (page_info.get("totalPage") or 1):
                    break
                time.sleep(self.page_pause)
        return [self._to_job(p) for p in raw]

    def _to_job(self, post: dict[str, Any]) -> Job:
        job_id = str(post.get("jobUnionId") or "")

        # cityList 是 [{name:...}, ...]，拼成多城市
        city = ""
        cl = post.get("cityList")
        if isinstance(cl, list):
            city = "/".join(
                c.get("name", "") for c in cl if isinstance(c, dict) and c.get("name")
            )

        # 招聘类型(应届/实习)拼进分类，方便上层过滤区分
        category = post.get("jobFamily") or ""
        jt = str(post.get("jobType") or "")
        recruit = {"1": "校招", "2": "实习"}.get(jt, "")
        if recruit:
            category = f"{category}/{recruit}" if category else recruit

        # firstPostTime 可能是毫秒时间戳
        publish_at = ""
        pt = post.get("firstPostTime") or post.get("refreshTime")
        if isinstance(pt, (int, float)) and pt > 0:
            try:
                publish_at = datetime.fromtimestamp(pt / 1000).strftime("%Y-%m-%d %H:%M")
            except Exception:
                publish_at = ""
        elif isinstance(pt, str):
            publish_at = pt

        return Job(
            company=self.display,
            job_id=job_id,
            title=(post.get("name") or "").strip(),
            city=city,
            category=category,
            url=DETAIL_URL.format(job_id=job_id),
            publish_at=publish_at,
            raw=post,
        )
