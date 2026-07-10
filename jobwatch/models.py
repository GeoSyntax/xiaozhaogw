"""标准岗位数据结构。

各家公司的官网 API 返回格式五花八门，解析器(parser)负责把它们
统一转换成这里定义的 Job 对象，后续所有模块只跟 Job 打交道。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Job:
    """一个标准化后的岗位。

    字段说明：
    - company:    公司名，如 "字节跳动"
    - job_id:     该公司内部的岗位唯一ID(用于去重)。注意不同公司的ID
                  可能重复，所以数据库里用 (company, job_id) 联合唯一。
    - title:      岗位名称，如 "后端开发工程师"
    - city:       工作城市，多个城市用 "/" 连接
    - category:   岗位大类(公司自带的分类，可能为空)
    - url:        投递/详情链接
    - publish_at: 发布时间(字符串，格式因公司而异，仅供展示)
    - raw:        原始数据留档，方便调试和后续扩展
    """

    company: str
    job_id: str
    title: str
    city: str = ""
    category: str = ""
    url: str = ""
    publish_at: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def uniq_key(self) -> str:
        """全局唯一键：公司 + 岗位ID。"""
        return f"{self.company}:{self.job_id}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
