"""科大讯飞校招官网适配器。

为什么这家用 httpx：
    科大讯飞招聘接口 POST iflytek.zhiye.com/api/Jobad/GetJobAdPageList 是公开
    POST JSON API，无签名、无登录，直接打就返回数据。能上 GitHub Actions。
    底层是北森(Beisen)招聘SaaS，zhiye.com 是北森旗下招聘门户域名。

参数要点(探测得出)：
    - POST body: {"PageIndex":0,"PageSize":20,"Category":["1"],...}
      Category: "1"=社招(695条), "2"=校招(当前0条), "3"=实习(27条)
      默认抓 ["2","3"](校招+实习)。
    - 返回 Code:200, Data[] 是岗位列表, Count 是总数。
    - 每条含 Id/JobAdId/JobAdName/Category/ClassificationOne/LocNames/PostDate/Duty/Require。
      ClassificationOne 是岗位大类(研发类/资源类/产品序列...)。
      LocNames 是城市列表(["安徽省·合肥市"])。
    - 域名 iflytek.zhiye.com 是北森平台（响应头 web: BeiSen），详情页在
      iflytek.zhiye.com/social/job-details/{Id}
"""
from __future__ import annotations

import ssl
import time
from datetime import datetime
from typing import Any, List

from ..models import Job
from .base import BaseAdapter

API_URL = "https://iflytek.zhiye.com/api/Jobad/GetJobAdPageList"
DETAIL_URL = "https://iflytek.zhiye.com/social/job-details/{job_id}"
# 默认抓校招+实习
DEFAULT_CATEGORIES = ["2", "3"]


class IflytekAdapter(BaseAdapter):
    name = "iflytek"
    display = "科大讯飞"

    def __init__(
        self,
        timeout: float = 15.0,
        categories: list[str] | None = None,
        page_size: int = 50,
        max_pages: int = 15,
        page_pause: float = 0.4,
    ) -> None:
        super().__init__(timeout=timeout)
        self.categories = categories or list(DEFAULT_CATEGORIES)
        self.page_size = page_size
        self.max_pages = max_pages
        self.page_pause = page_pause

    def _client(self):
        import httpx

        from .base import DEFAULT_HEADERS

        headers = dict(DEFAULT_HEADERS)
        headers["Content-Type"] = "application/json"
        headers["Accept"] = "application/json"
        headers["X-Requested-With"] = "xmlhttprequest"
        headers["langtype"] = "zh_CN"
        headers["Referer"] = "https://iflytek.zhiye.com/social/jobs"
        # 北森平台用自签名证书，需要禁用验证
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return httpx.Client(headers=headers, timeout=self.timeout, verify=ctx)

    def fetch(self) -> List[Job]:
        raw: list[dict[str, Any]] = []
        with self._client() as client:
            for page in range(self.max_pages):
                body = {
                    "PageIndex": page,
                    "PageSize": self.page_size,
                    "Category": self.categories,
                    "KeyWords": "",
                    "SpecialType": 0,
                    "PortalId": "",
                }
                resp = client.post(API_URL, json=body)
                data = resp.json()
                items = data.get("Data") or []
                if not items:
                    break
                raw.extend(items)
                if len(raw) >= (data.get("Count") or 0):
                    break
                time.sleep(self.page_pause)
        return [self._to_job(p) for p in raw]

    def _to_job(self, post: dict[str, Any]) -> Job:
        job_id = str(post.get("Id") or "")

        # LocNames 是 ["安徽省·合肥市", ...]，取市名部分
        locs = post.get("LocNames") or []
        city_parts = []
        for loc in locs:
            if "·" in loc:
                city_parts.append(loc.split("·")[-1])
            else:
                city_parts.append(loc)
        city = "/".join(city_parts)

        # ClassificationOne 是岗位大类
        category = post.get("ClassificationOne") or ""
        recruit = post.get("Category") or ""  # 社招/校招/实习
        if recruit:
            category = f"{category}/{recruit}" if category else recruit

        # PostDate 是 ISO 格式
        publish_at = ""
        pd = post.get("PostDate") or ""
        if pd:
            try:
                publish_at = datetime.fromisoformat(pd).strftime("%Y-%m-%d %H:%M")
            except Exception:
                publish_at = pd

        return Job(
            company=self.display,
            job_id=job_id,
            title=(post.get("JobAdName") or "").strip(),
            city=city,
            category=category,
            url=DETAIL_URL.format(job_id=job_id),
            publish_at=publish_at,
            raw=post,
        )
