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
  max_streak   INTEGER DEFAULT 0
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
            self._db.execute("ALTER TABLE fortunes ADD COLUMN platform TEXT")
            self._db.commit()
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
        }
        for key, value in fields.items():
            if value is not None:
                row[key] = value
        self._db.execute(
            "INSERT OR REPLACE INTO profiles (user_id, birthday, constellation, nickname,"
            " avatar, streak, last_draw_date, max_streak) VALUES (?,?,?,?,?,?,?,?)",
            (
                user_id,
                row.get("birthday"),
                row.get("constellation"),
                row.get("nickname"),
                row.get("avatar"),
                int(row.get("streak") or 0),
                row.get("last_draw_date"),
                int(row.get("max_streak") or 0),
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
