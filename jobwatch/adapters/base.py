"""适配器基类。

约定所有公司适配器的统一接口：给定配置，返回一批标准化的 Job 对象。
各家官网 API 千差万别，差异都封装在各自的子类里，
上层(采集->过滤->去重->通知)只跟这个统一接口打交道。
"""
from __future__ import annotations

import abc
from typing import List

import httpx

from ..models import Job


# 伪装成正常浏览器，降低被反爬拦截的概率。各适配器可按需覆盖。
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


class BaseAdapter(abc.ABC):
    """所有公司适配器的基类。

    子类必须提供:
      - name:    公司标识(英文, 用于日志/存储)
      - display: 公司中文名(用于通知展示)
      - fetch(): 请求官网 API 并返回 List[Job]
    """

    name: str = ""
    display: str = ""

    def __init__(self, timeout: float = 15.0):
        self.timeout = timeout

    @abc.abstractmethod
    def fetch(self) -> List[Job]:
        """抓取当前全部在招岗位，返回标准化 Job 列表。

        注意：这里返回的是"全量"当前岗位，
        "哪些是新增"由上层的去重器(storage)负责判断。
        """
        raise NotImplementedError

    def _client(self) -> httpx.Client:
        """构造一个带默认请求头的 HTTP 客户端。"""
        return httpx.Client(headers=DEFAULT_HEADERS, timeout=self.timeout)
