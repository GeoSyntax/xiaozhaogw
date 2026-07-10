"""适配器注册表。

集中登记所有公司适配器，main.py 按 config 里 enabled 的名字构造对应适配器，
不用在入口硬编码。新增公司 = 写一个适配器文件 + 在这里登记一行。

每个条目是 (适配器类, 是否需要浏览器)：
    needs_browser=True 的公司(如字节)在 GitHub Actions 云环境上跑浏览器
    又慢又易被风控，CI 里可通过 config 关掉，只在本地跑。
"""
from __future__ import annotations

from .bilibili import BilibiliAdapter
from .feishu import BytedanceAdapter, LiAutoAdapter, NioAdapter
from .jd import JDAdapter
from .leihuo import LeihuoAdapter
from .meituan import MeituanAdapter
from .mihoyo import MihoyoAdapter
from .netease import NeteaseAdapter
from .tencent import TencentAdapter
from .xiaohongshu import XiaohongshuAdapter

# name -> (adapter_class, needs_browser)
REGISTRY: dict[str, tuple[type, bool]] = {
    # httpx 直连，能上 GitHub Actions
    "tencent": (TencentAdapter, False),
    "netease": (NeteaseAdapter, False),
    "xiaohongshu": (XiaohongshuAdapter, False),
    "meituan": (MeituanAdapter, False),
    "mihoyo": (MihoyoAdapter, False),
    "leihuo": (LeihuoAdapter, False),
    "jd": (JDAdapter, False),
    # 浏览器(签名/动态凭证反爬)，仅本地
    "bilibili": (BilibiliAdapter, True),
    "bytedance": (BytedanceAdapter, True),
    "nio": (NioAdapter, True),
    "liauto": (LiAutoAdapter, True),
}


def build_enabled(cfg: dict) -> list:
    """按 config 构造启用的适配器实例。

    config 结构：
        companies:
          tencent:
            enabled: true
          bytedance:
            enabled: true
            max_pages: 3
    额外的键(max_pages 等)会作为构造参数传给适配器。
    ci_skip_browser: true 时跳过所有 needs_browser 的公司(用于 CI)。
    """
    companies_cfg = cfg.get("companies", {}) or {}
    ci_skip_browser = cfg.get("ci_skip_browser", False)

    adapters = []
    for name, (cls, needs_browser) in REGISTRY.items():
        entry = companies_cfg.get(name, {}) or {}
        if not entry.get("enabled", False):
            continue
        if needs_browser and ci_skip_browser:
            print(f"  (跳过 {name}：CI 环境不跑浏览器)")
            continue
        # 把除 enabled 外的配置项作为构造参数传入
        kwargs = {k: v for k, v in entry.items() if k != "enabled"}
        try:
            adapters.append(cls(**kwargs))
        except TypeError as e:
            print(f"  ✗ 构造 {name} 适配器失败(配置项不匹配): {e}")
    return adapters
