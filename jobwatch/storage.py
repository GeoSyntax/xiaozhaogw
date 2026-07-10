"""SQLite 存储 + 去重。

核心职责：记住"见过哪些岗位"，从而分辨出本轮抓取里哪些是新增的。
这是"第一时间发现新岗位"的技术落点。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .models import Job


class Storage:
    def __init__(self, db_path: str = "jobs.db") -> None:
        self.db_path = db_path
        # check_same_thread=False 方便将来多线程/调度器场景
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                company    TEXT NOT NULL,
                job_id     TEXT NOT NULL,
                title      TEXT NOT NULL,
                city       TEXT,
                category   TEXT,
                url        TEXT,
                publish_at TEXT,
                first_seen TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                PRIMARY KEY (company, job_id)
            );
            """
        )
        self.conn.commit()
        self._migrate()

    def _migrate(self) -> None:
        """轻量迁移：给老库补上后加的列，兼容已有 jobs.db。"""
        cols = {row["name"] for row in self.conn.execute("PRAGMA table_info(jobs)")}
        if "applied" not in cols:
            # 0=未投递 1=已投递，用于 Web 看板标记
            self.conn.execute("ALTER TABLE jobs ADD COLUMN applied INTEGER NOT NULL DEFAULT 0")
            self.conn.commit()

    def filter_new(self, jobs: list[Job]) -> list[Job]:
        """返回 jobs 里数据库尚未记录过的(即新增)岗位，不写库。"""
        new_jobs: list[Job] = []
        cur = self.conn.cursor()
        for job in jobs:
            row = cur.execute(
                "SELECT 1 FROM jobs WHERE company = ? AND job_id = ?",
                (job.company, job.job_id),
            ).fetchone()
            if row is None:
                new_jobs.append(job)
        return new_jobs

    def save(self, jobs: list[Job]) -> None:
        """把岗位写入数据库(已存在的忽略)。"""
        cur = self.conn.cursor()
        cur.executemany(
            """
            INSERT OR IGNORE INTO jobs
                (company, job_id, title, city, category, url, publish_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (j.company, j.job_id, j.title, j.city, j.category, j.url, j.publish_at)
                for j in jobs
            ],
        )
        self.conn.commit()

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]

    # ---- 看板查询 ----

    # 允许的排序方式 -> ORDER BY 片段。白名单，杜绝 SQL 注入。
    _SORTS = {
        # 发布时间倒序(默认)：空发布时间排后面，再按入库时间兜底
        "publish": "(publish_at = '') ASC, publish_at DESC, first_seen DESC",
        # 入库时间倒序：最近抓到的在最前，最贴合"第一时间发现"
        "recent": "first_seen DESC, publish_at DESC",
        # 公司分组
        "company": "company ASC, publish_at DESC",
    }

    def _build_where(
        self,
        company: str = "",
        keyword: str = "",
        city: str = "",
        applied: str = "",
        days: int = 0,
    ) -> tuple[str, list]:
        """构建 WHERE 子句和参数，query 与 count_where 共用，避免逻辑漂移。

        days>0 时只保留最近 N 天入库(first_seen)的岗位。
        """
        sql = " WHERE 1=1"
        params: list = []
        if company:
            sql += " AND company = ?"
            params.append(company)
        if keyword:
            sql += " AND (title LIKE ? OR category LIKE ?)"
            params += [f"%{keyword}%", f"%{keyword}%"]
        if city:
            sql += " AND city LIKE ?"
            params.append(f"%{city}%")
        if applied in ("0", "1"):
            sql += " AND applied = ?"
            params.append(int(applied))
        if days and days > 0:
            # first_seen 存的是本地时间字符串，用 SQLite 的 datetime 比较
            sql += " AND first_seen >= datetime('now', 'localtime', ?)"
            params.append(f"-{int(days)} days")
        return sql, params

    def query(
        self,
        company: str = "",
        keyword: str = "",
        city: str = "",
        applied: str = "",
        days: int = 0,
        sort: str = "publish",
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        """按条件查岗位，供 Web 看板用。返回 dict 列表。

        applied: ""=全部, "0"=未投, "1"=已投。
        days: >0 只看最近 N 天入库的岗位。
        sort: publish(发布时间)/recent(入库时间)/company(公司)，见 _SORTS。
        """
        where, params = self._build_where(company, keyword, city, applied, days)
        order = self._SORTS.get(sort, self._SORTS["publish"])
        sql = f"SELECT * FROM jobs{where} ORDER BY {order} LIMIT ? OFFSET ?"
        rows = self.conn.execute(sql, params + [limit, offset]).fetchall()
        return [dict(r) for r in rows]

    def count_where(
        self,
        company: str = "",
        keyword: str = "",
        city: str = "",
        applied: str = "",
        days: int = 0,
    ) -> int:
        """与 query 相同条件下的总数(用于分页)。"""
        where, params = self._build_where(company, keyword, city, applied, days)
        return self.conn.execute(
            f"SELECT COUNT(*) FROM jobs{where}", params
        ).fetchone()[0]

    def companies(self) -> list[str]:
        """库里出现过的公司列表(用于看板筛选下拉)。"""
        rows = self.conn.execute(
            "SELECT DISTINCT company FROM jobs ORDER BY company"
        ).fetchall()
        return [r[0] for r in rows]

    def set_applied(self, company: str, job_id: str, applied: bool) -> None:
        """标记/取消某岗位为已投递。"""
        self.conn.execute(
            "UPDATE jobs SET applied = ? WHERE company = ? AND job_id = ?",
            (1 if applied else 0, company, job_id),
        )
        self.conn.commit()

    def stats(self, recent_days: int = 3) -> dict:
        """看板顶部的汇总数字。recent_days 天内入库的算"最近新增"。"""
        total = self.count()
        applied = self.conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE applied = 1"
        ).fetchone()[0]
        recent = self.conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE first_seen >= datetime('now','localtime',?)",
            (f"-{int(recent_days)} days",),
        ).fetchone()[0]
        by_company = {
            r[0]: r[1]
            for r in self.conn.execute(
                "SELECT company, COUNT(*) FROM jobs GROUP BY company ORDER BY COUNT(*) DESC"
            ).fetchall()
        }
        return {
            "total": total,
            "applied": applied,
            "recent": recent,
            "recent_days": recent_days,
            "by_company": by_company,
        }

    def close(self) -> None:
        self.conn.close()
