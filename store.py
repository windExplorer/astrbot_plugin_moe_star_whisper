# -*- coding: utf-8 -*-
"""萌萌星语 · SQLite 存储层（同步 sqlite3，操作均为毫秒级小事务）。

表结构见 PRD §6：fortunes / profiles / items / ledger / draw_jobs（后两张 M7 起用）。
落库位置固定 data/plugin_data/ 下（StarTools.get_data_dir），升级目录不丢数据。
一日一签由 fortunes 的 (user_id, date) 主键保证：INSERT OR IGNORE，撞车返回 False。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS fortunes (
  user_id   TEXT NOT NULL,
  date      TEXT NOT NULL,
  grade     TEXT NOT NULL,
  score     INTEGER NOT NULL,
  payload   TEXT NOT NULL,
  nickname  TEXT,
  avatar    TEXT,
  group_id  TEXT,
  group_name TEXT,
  card_path TEXT,
  platform  TEXT,
  created_at TEXT NOT NULL,
  PRIMARY KEY (user_id, date)
);
CREATE TABLE IF NOT EXISTS profiles (
  user_id      TEXT PRIMARY KEY,
  birthday     TEXT,
  constellation TEXT,
  nickname     TEXT,
  avatar       TEXT,
  streak       INTEGER DEFAULT 0,
  last_draw_date TEXT,
  max_streak   INTEGER DEFAULT 0,
  seed_date    TEXT,
  seed_nonce   INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS items (
  user_id TEXT NOT NULL,
  item_id TEXT NOT NULL,
  count   INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, item_id)
);
CREATE TABLE IF NOT EXISTS ledger (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id    TEXT NOT NULL,
  delta      INTEGER NOT NULL,
  reason     TEXT NOT NULL,
  ref_date   TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS draw_jobs (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id     TEXT NOT NULL,
  date        TEXT NOT NULL,
  workflow    TEXT,
  prompt_lang TEXT,
  prompt_fmt  TEXT,
  image_prompt TEXT,
  llm_prompt  TEXT,
  status      TEXT NOT NULL,
  error       TEXT,
  duration_ms INTEGER,
  image_path  TEXT,
  card_path   TEXT,
  created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS debug_history (
  uid     TEXT PRIMARY KEY,
  used_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fortunes_date ON fortunes(date);
"""


class Store:
    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(SCHEMA)
        try:  # 旧库补列（列已存在时报错吞掉）
            for stmt in (
                "ALTER TABLE fortunes ADD COLUMN platform TEXT",
                "ALTER TABLE profiles ADD COLUMN seed_date TEXT",
                "ALTER TABLE profiles ADD COLUMN seed_nonce INTEGER DEFAULT 0",
            ):
                try:
                    self._db.execute(stmt)
                    self._db.commit()
                except Exception:
                    pass
        except Exception:
            pass

    def close(self) -> None:
        try:
            self._db.close()
        except Exception:
            pass

    # ---------- fortunes ----------

    def get_fortune(self, user_id: str, date: str) -> dict | None:
        row = self._db.execute(
            "SELECT * FROM fortunes WHERE user_id=? AND date=?", (user_id, date)
        ).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["payload"] = json.loads(data.get("payload") or "{}")
        return data

    def save_fortune(
        self,
        user_id: str,
        date: str,
        result: dict,
        nickname: str = "",
        avatar: str = "",
        group_id: str = "",
        group_name: str = "",
        card_path: str = "",
        platform: str = "",
    ) -> bool:
        """写入当日签；主键冲突（当日已签）时忽略并返回 False，由调用方读回已存记录。"""
        cur = self._db.execute(
            "INSERT OR IGNORE INTO fortunes (user_id, date, grade, score, payload,"
            " nickname, avatar, group_id, group_name, card_path, platform, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                user_id,
                date,
                str(result.get("grade", "")),
                int(result.get("score", 0)),
                json.dumps(result, ensure_ascii=False),
                nickname,
                avatar,
                group_id,
                group_name,
                card_path,
                platform,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        self._db.commit()
        return cur.rowcount == 1

    def update_fortune_payload(self, user_id: str, date: str, result: dict,
                               card_path: str | None = None) -> None:
        """换签卡（M7）：覆盖当日签的运势内容（grade/score/payload/卡路径同步）。"""
        self._db.execute(
            "UPDATE fortunes SET grade=?, score=?, payload=?,"
            " card_path=COALESCE(?, card_path) WHERE user_id=? AND date=?",
            (
                str(result.get("grade", "")),
                int(result.get("score", 0)),
                json.dumps(result, ensure_ascii=False),
                card_path,
                user_id,
                date,
            ),
        )
        self._db.commit()

    def delete_fortune(self, user_id: str, date: str) -> bool:
        """删除当日签记录（仅调试指令使用，D5 的运营后手）。"""
        cur = self._db.execute(
            "DELETE FROM fortunes WHERE user_id=? AND date=?", (user_id, date)
        )
        self._db.commit()
        return cur.rowcount == 1

    def list_active_group_ids(self, days: int = 7) -> list:
        """近 N 天有过抽签的群（group_id, platform）——每日推送的目标集。"""
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        rows = self._db.execute(
            "SELECT group_id, MAX(platform) AS platform FROM fortunes"
            " WHERE group_id!='' AND date>=? GROUP BY group_id",
            (since,),
        ).fetchall()
        return [(r["group_id"], r["platform"] or "") for r in rows]

    def record_draw_job(
        self,
        user_id: str,
        date: str,
        workflow: str = "",
        prompt_lang: str = "",
        prompt_fmt: str = "",
        image_prompt: str = "",
        llm_prompt: str = "",
        status: str = "",
        error: str = "",
        duration_ms: int = 0,
        image_path: str = "",
        card_path: str = "",
    ) -> int:
        """绘图任务全链路落库（D6/D7），返回 job id。"""
        cur = self._db.execute(
            "INSERT INTO draw_jobs (user_id, date, workflow, prompt_lang, prompt_fmt,"
            " image_prompt, llm_prompt, status, error, duration_ms, image_path,"
            " card_path, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                user_id, date, workflow, prompt_lang, prompt_fmt,
                image_prompt, llm_prompt, status, error, int(duration_ms),
                image_path, card_path,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        self._db.commit()
        return int(cur.lastrowid or 0)

    def get_draw_jobs(self, user_id: str, date: str) -> list:
        rows = self._db.execute(
            "SELECT * FROM draw_jobs WHERE user_id=? AND date=? ORDER BY id",
            (user_id, date),
        ).fetchall()
        return [dict(r) for r in rows]

    # ---------- 调试面板（M7.5） ----------

    def record_debug_uid(self, uid: str) -> None:
        """记录/刷新调试过的 QQ 号（面板历史，按最近使用排序）。"""
        self._db.execute(
            "INSERT INTO debug_history (uid, used_at) VALUES (?, ?)"
            " ON CONFLICT(uid) DO UPDATE SET used_at = excluded.used_at",
            (uid, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        self._db.commit()

    def list_debug_uids(self, limit: int = 8) -> list:
        """最近调试过的 QQ 号（新→旧）。"""
        rows = self._db.execute(
            "SELECT uid FROM debug_history ORDER BY used_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [r["uid"] for r in rows]

    # ---------- 道具经济（M7，D8） ----------

    def get_balance(self, user_id: str) -> int:
        """星尘余额 = ledger 流水合计。"""
        row = self._db.execute(
            "SELECT COALESCE(SUM(delta), 0) AS total FROM ledger WHERE user_id=?",
            (user_id,),
        ).fetchone()
        return int(row["total"] or 0)

    def add_ledger(self, user_id: str, delta: int, reason: str, ref_date: str = "") -> None:
        """每一笔星尘增减都必须走这里（D8：全流水可审计）。"""
        self._db.execute(
            "INSERT INTO ledger (user_id, delta, reason, ref_date, created_at)"
            " VALUES (?,?,?,?,?)",
            (user_id, int(delta), reason, ref_date,
             datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        self._db.commit()

    def has_ledger(self, user_id: str, ref_date: str, reason: str) -> bool:
        """当日是否已有某类记录（护身符/香烛佩戴标记、防重复使用）。"""
        row = self._db.execute(
            "SELECT 1 FROM ledger WHERE user_id=? AND ref_date=? AND reason=? LIMIT 1",
            (user_id, ref_date, reason),
        ).fetchone()
        return row is not None

    def day_stardust(self, user_id: str, date: str) -> int:
        """当日抽签获得的星尘（reason='draw' 流水合计；换签卡不重复发奖，天然幂等）。"""
        row = self._db.execute(
            "SELECT COALESCE(SUM(delta), 0) AS total FROM ledger"
            " WHERE user_id=? AND ref_date=? AND reason='draw'",
            (user_id, date),
        ).fetchone()
        return int(row["total"] or 0)

    def month_fortunes(self, user_id: str, month_prefix: str) -> list[dict]:
        """某月全部签记录（运势日历用）：date/grade/score，按日期升序。"""
        rows = self._db.execute(
            "SELECT date, grade, score FROM fortunes"
            " WHERE user_id=? AND date LIKE ? ORDER BY date",
            (user_id, month_prefix + "%"),
        ).fetchall()
        return [dict(r) for r in rows]

    def last_nickname(self, user_id: str) -> str:
        """最近一次抽签用的昵称（日历等场景的身份展示；profiles.nickname 从未回填）。"""
        row = self._db.execute(
            "SELECT nickname FROM fortunes WHERE user_id=? AND nickname!=''"
            " ORDER BY date DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        return str(row["nickname"] or "") if row else ""

    def get_item(self, user_id: str, item_id: str) -> int:
        row = self._db.execute(
            "SELECT count FROM items WHERE user_id=? AND item_id=?",
            (user_id, item_id),
        ).fetchone()
        return int(row["count"] or 0) if row else 0

    def add_item(self, user_id: str, item_id: str, delta: int) -> int:
        """增减道具持有量（delta 可负），返回新数量。"""
        self._db.execute(
            "INSERT INTO items (user_id, item_id, count) VALUES (?,?,?)"
            " ON CONFLICT(user_id, item_id) DO UPDATE SET count = count + ?",
            (user_id, item_id, int(delta), int(delta)),
        )
        self._db.commit()
        return self.get_item(user_id, item_id)

    def list_day(self, date: str) -> list[dict]:
        """当日全部抽签记录（榜单/PK 用，M3 接线）。"""
        rows = self._db.execute(
            "SELECT * FROM fortunes WHERE date=? ORDER BY score DESC", (date,)
        ).fetchall()
        out = []
        for row in rows:
            data = dict(row)
            data["payload"] = json.loads(data.get("payload") or "{}")
            out.append(data)
        return out

    def list_group_day(self, group_id: str, date: str, limit: int = 10) -> list[dict]:
        """群内当日榜：分数降序，同分先抽在前。"""
        rows = self._db.execute(
            "SELECT user_id, nickname, grade, score FROM fortunes"
            " WHERE group_id=? AND date=? ORDER BY score DESC, created_at ASC LIMIT ?",
            (group_id, date, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_group_range_avg(
        self, group_id: str, date_from: str, limit: int = 10
    ) -> list[dict]:
        """群内区间均分榜（周榜）：平均分降序，同分按抽签天数。"""
        rows = self._db.execute(
            "SELECT user_id, MAX(nickname) AS nickname, AVG(score) AS avg_score,"
            " COUNT(*) AS days FROM fortunes"
            " WHERE group_id=? AND date>=? GROUP BY user_id"
            " ORDER BY avg_score DESC, days DESC LIMIT ?",
            (group_id, date_from, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # ---------- profiles ----------

    def get_profile(self, user_id: str) -> dict | None:
        row = self._db.execute(
            "SELECT * FROM profiles WHERE user_id=?", (user_id,)
        ).fetchone()
        return dict(row) if row else None

    def upsert_profile(self, user_id: str, **fields) -> None:
        row = self.get_profile(user_id) or {
            "user_id": user_id,
            "birthday": None,
            "constellation": None,
            "nickname": None,
            "avatar": None,
            "streak": 0,
            "last_draw_date": None,
            "max_streak": 0,
            "seed_date": None,
            "seed_nonce": 0,
        }
        for key, value in fields.items():
            if value is not None:
                row[key] = value
        self._db.execute(
            "INSERT OR REPLACE INTO profiles (user_id, birthday, constellation, nickname,"
            " avatar, streak, last_draw_date, max_streak, seed_date, seed_nonce)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                user_id,
                row.get("birthday"),
                row.get("constellation"),
                row.get("nickname"),
                row.get("avatar"),
                int(row.get("streak") or 0),
                row.get("last_draw_date"),
                int(row.get("max_streak") or 0),
                row.get("seed_date"),
                int(row.get("seed_nonce") or 0),
            ),
        )
        self._db.commit()

    def bump_streak(self, user_id: str, date: str, yesterday: str) -> int:
        """首签时推进连续天数（幂等：当天重复调用不变）。"""
        row = self.get_profile(user_id) or {}
        last = row.get("last_draw_date")
        streak = int(row.get("streak") or 0)
        if last == date:
            pass
        elif last == yesterday:
            streak += 1
        else:
            streak = 1
        max_streak = max(int(row.get("max_streak") or 0), streak)
        self.upsert_profile(
            user_id, streak=streak, last_draw_date=date, max_streak=max_streak
        )
        return streak

    # ---------- 统计与面板查询（v1.9.0 WebUI 控制台） ----------
    #
    # 口径说明：
    #  * 「区间」过滤 fortunes 一律用 date 列（YYYY-MM-DD），ledger / draw_jobs
    #    没有 date 列，用 created_at 的前 10 位（历史上两者写入时刻一致）。
    #  * 需要读 payload 的分布（六维均值、幸运物/色、星座、连签档位）在 Python 侧
    #    解析 JSON —— 数千行量级足够快，且不依赖 SQLite 的 JSON1 扩展。

    def _query(self, sql: str, params: tuple = ()) -> list[dict]:
        return [dict(r) for r in self._db.execute(sql, params).fetchall()]

    def _one(self, sql: str, params: tuple = ()) -> dict:
        rows = self._query(sql, params)
        return rows[0] if rows else {}

    def stats_totals(self) -> dict:
        """全量规模：累计抽签数 / 用户数 / 群数 / 覆盖天数 / 已出卡数。"""
        row = self._one(
            "SELECT COUNT(*) AS draws,"
            " COUNT(DISTINCT user_id) AS users,"
            " COUNT(DISTINCT CASE WHEN group_id!='' THEN group_id END) AS groups,"
            " COUNT(DISTINCT date) AS days,"
            " COALESCE(SUM(CASE WHEN card_path!='' THEN 1 ELSE 0 END), 0) AS cards"
            " FROM fortunes"
        )
        return {k: int(v or 0) for k, v in row.items()}

    def stats_day(self, date: str) -> dict:
        """某日概览：抽签数/人数/均分/吉签数/凶签数。"""
        row = self._one(
            "SELECT COUNT(*) AS draws, COUNT(DISTINCT user_id) AS users,"
            " COALESCE(ROUND(AVG(score), 1), 0) AS avg_score,"
            " COALESCE(SUM(CASE WHEN grade IN ('大吉','吉') THEN 1 ELSE 0 END), 0) AS lucky,"
            " COALESCE(SUM(CASE WHEN grade IN ('凶','大凶') THEN 1 ELSE 0 END), 0) AS unlucky"
            " FROM fortunes WHERE date=?",
            (date,),
        )
        return {
            "date": date,
            "draws": int(row.get("draws") or 0),
            "users": int(row.get("users") or 0),
            "avg_score": float(row.get("avg_score") or 0),
            "lucky": int(row.get("lucky") or 0),
            "unlucky": int(row.get("unlucky") or 0),
        }

    def stats_trend(self, date_from: str) -> list[dict]:
        """按日趋势（抽签数/人数/均分/大吉数/凶签数），日期升序。"""
        rows = self._query(
            "SELECT date, COUNT(*) AS draws, COUNT(DISTINCT user_id) AS users,"
            " COALESCE(ROUND(AVG(score), 1), 0) AS avg_score,"
            " SUM(CASE WHEN grade='大吉' THEN 1 ELSE 0 END) AS great,"
            " SUM(CASE WHEN grade IN ('凶','大凶') THEN 1 ELSE 0 END) AS bad"
            " FROM fortunes WHERE date>=? GROUP BY date ORDER BY date",
            (date_from,),
        )
        return [
            {
                "date": r["date"],
                "draws": int(r["draws"] or 0),
                "users": int(r["users"] or 0),
                "avg_score": float(r["avg_score"] or 0),
                "great": int(r["great"] or 0),
                "bad": int(r["bad"] or 0),
            }
            for r in rows
        ]

    def stats_grades(self, date_from: str = "") -> dict:
        """吉凶档位分布：{档位: 次数}（date_from 为空表示全量）。"""
        sql = "SELECT grade, COUNT(*) AS n FROM fortunes"
        params: tuple = ()
        if date_from:
            sql += " WHERE date>=?"
            params = (date_from,)
        sql += " GROUP BY grade"
        return {str(r["grade"]): int(r["n"]) for r in self._query(sql, params)}

    def stats_grade_daily(self, date_from: str) -> list[dict]:
        """按日 × 档位的计数（供堆叠柱状图，前端自行透视）。"""
        rows = self._query(
            "SELECT date, grade, COUNT(*) AS n FROM fortunes"
            " WHERE date>=? GROUP BY date, grade ORDER BY date",
            (date_from,),
        )
        return [{"date": r["date"], "grade": str(r["grade"]), "n": int(r["n"])} for r in rows]

    def stats_hours(self, date_from: str = "") -> list[int]:
        """抽签时刻分布（0~23 点，取 created_at 的小时位）。"""
        sql = "SELECT substr(created_at, 12, 2) AS h, COUNT(*) AS n FROM fortunes"
        params: tuple = ()
        if date_from:
            sql += " WHERE date>=?"
            params = (date_from,)
        sql += " GROUP BY h"
        out = [0] * 24
        for r in self._query(sql, params):
            try:
                idx = int(str(r["h"]))
            except (TypeError, ValueError):
                continue
            if 0 <= idx < 24:
                out[idx] = int(r["n"])
        return out

    def stats_groups(self, date_from: str = "", limit: int = 10) -> list[dict]:
        """群活跃榜：抽签数降序。

        ⚠️ 归属口径（需求明确要求，勿改）：fortunes 主键是 (user_id, date)，
        且 save_fortune 用 INSERT OR IGNORE —— 同一用户当天在别的群再抽不会写新行，
        换签卡也只改 payload/card_path 不动 group_id。所以每条记录天然就是
        「该用户当天第一次抽签所在的群」，一人一天只计入一个群，不会重复计算。
        """
        sql = (
            "SELECT group_id, MAX(group_name) AS group_name, COUNT(*) AS draws,"
            " COUNT(DISTINCT user_id) AS users, COALESCE(ROUND(AVG(score), 1), 0) AS avg_score,"
            " SUM(CASE WHEN grade='大吉' THEN 1 ELSE 0 END) AS great,"
            " SUM(CASE WHEN grade IN ('凶','大凶') THEN 1 ELSE 0 END) AS bad,"
            " COALESCE(SUM(CASE WHEN card_path!='' THEN 1 ELSE 0 END), 0) AS cards,"
            " MAX(date) AS last_date"
            " FROM fortunes WHERE group_id!=''"
        )
        params: list = []
        if date_from:
            sql += " AND date>=?"
            params.append(date_from)
        sql += " GROUP BY group_id ORDER BY draws DESC, users DESC LIMIT ?"
        params.append(max(1, int(limit)))
        return [
            {
                "group_id": r["group_id"],
                "group_name": r["group_name"] or "",
                "draws": int(r["draws"] or 0),
                "users": int(r["users"] or 0),
                "avg_score": float(r["avg_score"] or 0),
                "great": int(r["great"] or 0),
                "bad": int(r["bad"] or 0),
                "cards": int(r["cards"] or 0),
                "last_date": r["last_date"] or "",
            }
            for r in self._query(sql, tuple(params))
        ]

    def stats_private(self, date_from: str = "") -> dict:
        """私聊抽签的占比（与群聊互补口径，同样一人一天一次）。"""
        sql = "SELECT COUNT(*) AS draws, COUNT(DISTINCT user_id) AS users FROM fortunes WHERE group_id=''"
        params: tuple = ()
        if date_from:
            sql += " AND date>=?"
            params = (date_from,)
        row = self._one(sql, params)
        return {"draws": int(row.get("draws") or 0), "users": int(row.get("users") or 0)}

    def stats_payload(self, date_from: str = "") -> dict:
        """payload 分布聚合：六维均值、幸运物/色 Top、星座分布、连签档位。

        注意：fortunes 表没有 streak 列（连签只在 payload JSON 里），别在 SQL 里选它。
        """
        sql = "SELECT payload FROM fortunes"
        params: tuple = ()
        if date_from:
            sql += " WHERE date>=?"
            params = (date_from,)
        dim_sum: dict[str, float] = {}
        dim_n = 0
        items: dict[str, int] = {}
        colors: dict[str, dict] = {}
        constel: dict[str, int] = {}
        streaks = {"1": 0, "2": 0, "3-6": 0, "7-29": 0, "30+": 0}
        for r in self._query(sql, params):
            try:
                p = json.loads(r.get("payload") or "{}")
            except Exception:
                p = {}
            if not isinstance(p, dict):
                p = {}
            dims = p.get("dims")
            if isinstance(dims, dict) and dims:
                dim_n += 1
                for k, v in dims.items():
                    try:
                        dim_sum[str(k)] = dim_sum.get(str(k), 0.0) + float(v)
                    except (TypeError, ValueError):
                        continue
            item = p.get("lucky_item")
            if item:
                items[str(item)] = items.get(str(item), 0) + 1
            color = p.get("lucky_color")
            if isinstance(color, dict) and color.get("name"):
                name = str(color["name"])
                node = colors.setdefault(name, {"name": name, "hex": "", "n": 0})
                node["n"] += 1
                if not node["hex"] and color.get("hex"):
                    node["hex"] = str(color["hex"])
            if p.get("constellation"):
                cs = str(p["constellation"])
                constel[cs] = constel.get(cs, 0) + 1
            try:
                s = int(p.get("streak") or 0)
            except (TypeError, ValueError):
                s = 0
            if s >= 30:
                streaks["30+"] += 1
            elif s >= 7:
                streaks["7-29"] += 1
            elif s >= 3:
                streaks["3-6"] += 1
            elif s == 2:
                streaks["2"] += 1
            else:
                streaks["1"] += 1

        def _top(pool: dict, limit: int) -> list[dict]:
            return [
                {"name": k, "n": int(v)}
                for k, v in sorted(pool.items(), key=lambda kv: -kv[1])[:limit]
            ]

        return {
            "dims": {k: round(v / dim_n, 2) for k, v in dim_sum.items()} if dim_n else {},
            "sampled": dim_n,
            "items": _top(items, 10),
            "colors": sorted(colors.values(), key=lambda c: -c["n"])[:10],
            "constellations": _top(constel, 12),
            "streaks": streaks,
        }

    def stats_jobs(self, date_from: str = "") -> dict:
        """绘图任务成功率与耗时（anima 联动质量）。"""
        sql = (
            "SELECT status, COUNT(*) AS n, COALESCE(ROUND(AVG(duration_ms)), 0) AS avg_ms"
            " FROM draw_jobs"
        )
        params: list = []
        if date_from:
            sql += " WHERE date>=?"
            params.append(date_from)
        sql += " GROUP BY status"
        by_status = {
            str(r["status"]): {"n": int(r["n"] or 0), "avg_ms": int(r["avg_ms"] or 0)}
            for r in self._query(sql, tuple(params))
        }
        total = sum(v["n"] for v in by_status.values())
        ok = by_status.get("ok", {}).get("n", 0)

        sql2 = (
            "SELECT date, COUNT(*) AS total,"
            " SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) AS ok FROM draw_jobs"
        )
        params2: list = []
        if date_from:
            sql2 += " WHERE date>=?"
            params2.append(date_from)
        sql2 += " GROUP BY date ORDER BY date"
        by_day = [
            {"date": r["date"], "total": int(r["total"] or 0), "ok": int(r["ok"] or 0)}
            for r in self._query(sql2, tuple(params2))
        ]
        return {
            "by_status": by_status,
            "total": total,
            "ok": ok,
            "success_rate": round(ok / total * 100, 1) if total else 0.0,
            "by_day": by_day,
        }

    def stats_ledger(self, date_from: str = "") -> dict:
        """星尘流水：按原因聚合 + 按日收支（全流水可审计，D8）。"""
        where = " WHERE substr(created_at, 1, 10)>=?" if date_from else ""
        params: tuple = (date_from,) if date_from else ()
        by_reason = [
            {
                "reason": str(r["reason"]),
                "total": int(r["total"] or 0),
                "n": int(r["n"] or 0),
            }
            for r in self._query(
                "SELECT reason, SUM(delta) AS total, COUNT(*) AS n FROM ledger"
                + where
                + " GROUP BY reason ORDER BY ABS(SUM(delta)) DESC",
                params,
            )
        ]
        by_day = [
            {
                "day": str(r["day"]),
                "income": int(r["income"] or 0),
                "spend": int(r["spend"] or 0),
            }
            for r in self._query(
                "SELECT substr(created_at, 1, 10) AS day,"
                " COALESCE(SUM(CASE WHEN delta>0 THEN delta ELSE 0 END), 0) AS income,"
                " COALESCE(-SUM(CASE WHEN delta<0 THEN delta ELSE 0 END), 0) AS spend"
                " FROM ledger"
                + where
                + " GROUP BY day ORDER BY day",
                params,
            )
        ]
        return {
            "by_reason": by_reason,
            "by_day": by_day,
            "income": sum(r["income"] for r in by_day),
            "spend": sum(r["spend"] for r in by_day),
        }

    def list_records(
        self,
        page: int = 1,
        size: int = 20,
        date_from: str = "",
        date_to: str = "",
        grade: str = "",
        group_id: str = "",
        keyword: str = "",
    ) -> dict:
        """分页签记录（控制台「抽签记录」页），条件全部可选。"""
        where: list[str] = []
        params: list = []
        if date_from:
            where.append("date>=?")
            params.append(date_from)
        if date_to:
            where.append("date<=?")
            params.append(date_to)
        if grade:
            where.append("grade=?")
            params.append(grade)
        if group_id:
            where.append("group_id=?")
            params.append(group_id)
        if keyword:
            where.append("(user_id LIKE ? OR nickname LIKE ?)")
            params.extend([f"%{keyword}%", f"%{keyword}%"])
        clause = (" WHERE " + " AND ".join(where)) if where else ""

        total = int(self._one("SELECT COUNT(*) AS n FROM fortunes" + clause, tuple(params)).get("n") or 0)
        size = max(1, min(int(size), 200))
        page = max(1, int(page))
        rows = self._query(
            "SELECT user_id, nickname, avatar, date, grade, score, group_id, group_name,"
            " card_path, created_at, payload FROM fortunes"
            + clause
            + " ORDER BY date DESC, created_at DESC LIMIT ? OFFSET ?",
            tuple(params) + (size, (page - 1) * size),
        )
        out = []
        for r in rows:
            card_path = str(r.get("card_path") or "")
            try:
                payload = json.loads(r.get("payload") or "{}")
            except Exception:
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            out.append({
                "uid": r["user_id"],
                "nickname": r["nickname"] or "",
                "avatar": r.get("avatar") or "",
                "date": r["date"],
                "grade": payload.get("grade_display") or r["grade"],
                "score": int(r["score"] or 0),
                "group_id": r["group_id"] or "",
                "group_name": r["group_name"] or "",
                "created_at": r["created_at"] or "",
                "streak": int(payload.get("streak") or 0),
                "lucky_color": (payload.get("lucky_color") or {}).get("name", "")
                if isinstance(payload.get("lucky_color"), dict) else "",
                "lucky_item": payload.get("lucky_item") or "",
                "llm_used": bool(payload.get("llm_used")),
                "sign_text": payload.get("sign_text") or "",
                "has_card": bool(card_path),
            })
        return {"total": total, "page": page, "size": size, "rows": out}

    def list_groups(self, limit: int = 100) -> list[dict]:
        """群列表（记录页的筛选下拉：群号 + 别名 + 抽签数）。"""
        return [
            {
                "group_id": r["group_id"],
                "group_name": r["group_name"] or "",
                "draws": int(r["draws"] or 0),
            }
            for r in self._query(
                "SELECT group_id, MAX(group_name) AS group_name, COUNT(*) AS draws"
                " FROM fortunes WHERE group_id!='' GROUP BY group_id"
                " ORDER BY draws DESC LIMIT ?",
                (max(1, int(limit)),),
            )
        ]

    def recent_users(self, limit: int = 12) -> list[dict]:
        """最近抽签的用户（面板快捷入口）。"""
        return [
            {
                "uid": r["user_id"],
                "nickname": r["nickname"] or "",
                "last_date": r["last_date"] or "",
                "draws": int(r["draws"] or 0),
            }
            for r in self._query(
                "SELECT user_id, MAX(nickname) AS nickname, MAX(date) AS last_date,"
                " COUNT(*) AS draws FROM fortunes GROUP BY user_id"
                " ORDER BY last_date DESC, draws DESC LIMIT ?",
                (max(1, int(limit)),),
            )
        ]

    def list_users(self, page: int = 1, size: int = 24, keyword: str = "",
                   order: str = "last") -> dict:
        """抽过签的用户列表（头像/昵称/QQ/抽签数/最近与首次日期/均分/最高分/群数）。

        口径：fortunes 主键 (user_id, date) → draws 就是「有效抽签天数」，
        也就是「参与天数」，不存在同一用户同一天重复计数。
        头像与昵称取该用户**最近一条有值**的记录（旧数据可能没存头像）。
        """
        where: list[str] = []
        params: list = []
        if keyword:
            where.append("(user_id LIKE ? OR nickname LIKE ?)")
            params.extend([f"%{keyword}%", f"%{keyword}%"])
        clause = (" WHERE " + " AND ".join(where)) if where else ""

        total = int(self._one(
            "SELECT COUNT(DISTINCT user_id) AS n FROM fortunes" + clause, tuple(params)
        ).get("n") or 0)

        order_sql = {
            "draws": "draws DESC, last_date DESC",
            "score": "avg_score DESC, draws DESC",
        }.get(str(order), "last_date DESC, draws DESC")

        size = max(1, min(int(size), 100))
        page = max(1, int(page))
        rows = self._query(
            "SELECT f.user_id, COUNT(*) AS draws, MIN(f.date) AS first_date,"
            " MAX(f.date) AS last_date, COALESCE(ROUND(AVG(f.score), 1), 0) AS avg_score,"
            " MAX(f.score) AS best_score,"
            " COUNT(DISTINCT CASE WHEN f.group_id!='' THEN f.group_id END) AS groups,"
            " (SELECT nickname FROM fortunes WHERE user_id=f.user_id AND nickname!=''"
            "  ORDER BY date DESC LIMIT 1) AS nickname,"
            " (SELECT avatar FROM fortunes WHERE user_id=f.user_id AND avatar!=''"
            "  ORDER BY date DESC LIMIT 1) AS avatar,"
            " (SELECT group_name FROM fortunes WHERE user_id=f.user_id AND group_name!=''"
            "  ORDER BY date DESC LIMIT 1) AS last_group_name,"
            " (SELECT group_id FROM fortunes WHERE user_id=f.user_id AND group_id!=''"
            "  ORDER BY date DESC LIMIT 1) AS last_group_id"
            " FROM fortunes f"
            + clause
            + f" GROUP BY f.user_id ORDER BY {order_sql} LIMIT ? OFFSET ?",
            tuple(params) + (size, (page - 1) * size),
        )
        out = []
        for r in rows:
            out.append({
                "uid": r["user_id"],
                "nickname": r["nickname"] or "",
                "avatar": r["avatar"] or "",
                "draws": int(r["draws"] or 0),
                "first_date": r["first_date"] or "",
                "last_date": r["last_date"] or "",
                "avg_score": float(r["avg_score"] or 0),
                "best_score": int(r["best_score"] or 0),
                "groups": int(r["groups"] or 0),
                "last_group_id": r["last_group_id"] or "",
                "last_group_name": r["last_group_name"] or "",
            })
        return {"total": total, "page": page, "size": size, "rows": out}

    def user_history(self, user_id: str, limit: int = 60) -> list[dict]:
        """单用户最近签记录（新→旧，含卡文件状态）。"""
        rows = self._query(
            "SELECT date, grade, score, card_path, payload FROM fortunes"
            " WHERE user_id=? ORDER BY date DESC LIMIT ?",
            (user_id, max(1, min(int(limit), 400))),
        )
        out = []
        for r in rows:
            try:
                payload = json.loads(r.get("payload") or "{}")
            except Exception:
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            out.append({
                "date": r["date"],
                "grade": payload.get("grade_display") or str(r["grade"]),
                "score": int(r["score"] or 0),
                "streak": int(payload.get("streak") or 0),
                "lucky_color": (payload.get("lucky_color") or {}).get("name", "")
                if isinstance(payload.get("lucky_color"), dict) else "",
                "has_card": bool(str(r.get("card_path") or "")),
            })
        return out

    def user_ledger(self, user_id: str, limit: int = 30) -> list[dict]:
        """单用户最近星尘流水（新→旧）。"""
        return [
            {
                "delta": int(r["delta"] or 0),
                "reason": str(r["reason"] or ""),
                "ref_date": r["ref_date"] or "",
                "created_at": r["created_at"] or "",
            }
            for r in self._query(
                "SELECT delta, reason, ref_date, created_at FROM ledger"
                " WHERE user_id=? ORDER BY id DESC LIMIT ?",
                (user_id, max(1, min(int(limit), 200))),
            )
        ]

    def count_all(self) -> dict:
        """库内各表行数（控制台「数据」概览）。"""
        out = {}
        for table in ("fortunes", "profiles", "items", "ledger", "draw_jobs"):
            try:
                out[table] = int(self._one(f"SELECT COUNT(*) AS n FROM {table}").get("n") or 0)
            except Exception:
                out[table] = 0
        return out
