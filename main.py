"""校招岗位监控 —— 入口。

一轮完整链路：
    采集(Fetcher) → 过滤(Filter) → 去重(Storage) → 通知(Notifier)

首次运行(数据库为空)只"播种"不推送：把当前所有岗位记入库作为基线，
否则第一次就会把几百个存量岗位当成"新增"全推给你。
之后每轮只推真正新出现的岗位。
"""
from __future__ import annotations

import os
import sys

# Windows 控制台默认 GBK，打印中文/emoji 会崩。强制 stdout 用 UTF-8。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import yaml

from jobwatch.adapters.registry import build_enabled
from jobwatch.filters import JobFilter
from jobwatch.notifier import build_notifier
from jobwatch.storage import Storage


def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    # CI 环境用环境变量 CI_SKIP_BROWSER=1 覆盖，跳过浏览器型公司(字节/B站)，
    # 不必为 CI 维护单独的 config。
    if os.environ.get("CI_SKIP_BROWSER", "").strip() in ("1", "true", "True"):
        cfg["ci_skip_browser"] = True
    return cfg


def run_once(cfg: dict) -> None:
    storage = Storage(cfg.get("db_path", "jobs.db"))
    flt = JobFilter(
        include=cfg["filter"].get("include", []),
        exclude=cfg["filter"].get("exclude", []),
    )
    notifier = build_notifier(cfg)
    adapters = build_enabled(cfg)
    if not adapters:
        print("没有启用任何公司，请在 config.yaml 的 companies 段把想监控的公司 enabled 设为 true。")
        storage.close()
        return

    # 首次运行判定：库里一条都没有 → 只播种
    seeding = storage.count() == 0
    if seeding:
        print("[首次运行] 本轮只建立基线(不推送)，之后才会推新岗位。\n")

    total_fetched = 0
    total_matched = 0
    all_new: list = []

    for adapter in adapters:
        print(f"→ 采集 {adapter.display} ...")
        try:
            jobs = adapter.fetch()
        except Exception as e:
            print(f"  ✗ {adapter.display} 采集失败: {e}")
            continue

        total_fetched += len(jobs)
        matched = flt.apply(jobs)
        total_matched += len(matched)
        print(f"  抓到 {len(jobs)} 条，命中技术岗 {len(matched)} 条")

        new_jobs = storage.filter_new(matched)
        storage.save(matched)          # 命中的都入库(含已见过的，IGNORE)
        all_new.extend(new_jobs)

    print(f"\n本轮合计：抓取 {total_fetched}，命中 {total_matched}，"
          f"其中新增 {len(all_new)}。库存共 {storage.count()} 条。")

    if seeding:
        print("（基线已建立，下次运行起将只推送新岗位）")
        storage.close()
        return

    # 推送限流：一次新增太多(如刚接入新数据源)全推会炸，且微信推送有长度限制。
    # 按发布时间倒序，只推最新 max_push 条，其余仅提示数量。
    max_push = int(cfg.get("notify", {}).get("max_push", 30))
    to_push = sorted(all_new, key=lambda j: j.publish_at or "", reverse=True)
    overflow = 0
    if len(to_push) > max_push:
        overflow = len(to_push) - max_push
        to_push = to_push[:max_push]
        print(f"（新增 {len(all_new)} 条，超过单次上限 {max_push}，本次推最新 {max_push} 条，"
              f"其余 {overflow} 条已入库不再重复提醒）")

    notifier.notify(to_push, overflow=overflow)
    storage.close()


def main() -> None:
    cfg = load_config()
    run_once(cfg)


if __name__ == "__main__":
    sys.exit(main())
