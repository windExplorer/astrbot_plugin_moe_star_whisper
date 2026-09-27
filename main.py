# -*- coding: utf-8 -*-
"""萌萌星语：每日运势签插件入口。"""
import importlib
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, StarTools, register
from astrbot.api import logger
from astrbot.api.message_components import At

from . import fortune, lexicon, store

PLUGIN_NAME = "astrbot_plugin_moe_star_whisper"

_STREAK_BADGES = {
    3: "三星连签达成，运势开始聚拢 ✨",
    7: "七日连签达成，星星记住你了 🌙",
    14: "半月连签达成，毅力惊人 🌟",
    30: "三十日连签达成，星语者的挚友 🎇",
}

try:  # M2 起提供图卡；缺失/失败时回退纯文本
    from .card import render_card
except Exception:  # pragma: no cover
    render_card = None


@register(PLUGIN_NAME, "windExplorer", "萌萌星语：每日运势签", "0.4.0")

class StarWhisperPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self._store = None
        self._reload_modules()

    # ---------- 生命周期 ----------

    def _reload_modules(self):
        """热重载自研子模块（依赖序），避免热更后跑旧代码（PRD §7.7）。"""
        pkg = __package__
        for name in ("lexicon", "fortune", "store"):
            mod = sys.modules.get(f"{pkg}.{name}")
            if mod is not None:
                try:
                    importlib.reload(mod)
                    logger.info(f"[{PLUGIN_NAME}] 已热重载模块 {name}")
                except Exception:
                    logger.error(
                        f"[{PLUGIN_NAME}] 热重载 {name} 失败\n{traceback.format_exc()}"
                    )

    async def initialize(self):
        try:
            lexicon.load_lexicon(force_reload=True)
            data_dir = Path(StarTools.get_data_dir(PLUGIN_NAME))
            self._store = store.Store(data_dir / "star_whisper.db")
            logger.info(f"[{PLUGIN_NAME}] 初始化完成，数据目录：{data_dir}")
        except Exception:
            logger.error(f"[{PLUGIN_NAME}] 初始化失败\n{traceback.format_exc()}")
            raise

    async def terminate(self):
        if self._store is not None:
            self._store.close()
            self._store = None

    # ---------- 工具 ----------

    def _cfg(self, key: str, default):
        try:
            value = self.config.get(key, None)
        except Exception:
            return default
        if value is None or value == "":
            return default
        return value

    def _grade_weights(self) -> dict:
        raw = self._cfg("grade_weights", None)
        if isinstance(raw, dict) and raw:
            merged = {
                g: int(raw.get(g, w))
                for g, w in fortune.DEFAULT_GRADE_WEIGHTS.items()
            }
            if sum(merged.values()) > 0:
                return merged
        return dict(fortune.DEFAULT_GRADE_WEIGHTS)

    def _disabled_groups(self) -> set:
        raw = str(self._cfg("disabled_groups", "") or "")
        return {g.strip() for g in raw.replace("，", ",").split(",") if g.strip()}

    def _set_group_disabled(self, group_id: str, disabled: bool) -> None:
        """群开关落回配置（disabled_groups 逗号串），持久化并在配置页可见。"""
        groups = self._disabled_groups()
        if disabled:
            groups.add(group_id)
        else:
            groups.discard(group_id)
        self.config["disabled_groups"] = ",".join(sorted(groups))
        self.config.save_config()

    @staticmethod
    def _sender_avatar(event: AstrMessageEvent, uid: str) -> str:
        """头像 URL：QQ 平台用 qlogo 标准地址；其他平台留空（D10）。"""
        try:
            platform = str(event.get_platform_name() or "")
        except Exception:
            platform = ""
        if "aiocqhttp" in platform:
            return f"https://q1.qlogo.cn/g?qq={uid}&s=640"
        return ""

    def _try_render_card(self, result: dict, uid: str, nickname: str = "", avatar: str = ""):
        """渲染卡图，失败返回 None（调用方回退纯文本，绝不吞错不回，PRD §7.3）。"""
        if render_card is None:
            return None
        try:
            data_dir = Path(StarTools.get_data_dir(PLUGIN_NAME))
            return render_card(
                result,
                data_dir / "cards" / uid,
                font_path=self._cfg("card_font_path", "") or None,
                extra_font_dirs=[data_dir / "fonts", Path("data/fonts")],
                width=int(self._cfg("card_width", 1024)),
                height=int(self._cfg("card_height", 1536)),
                signer=str(self._cfg("fortune_signer", "星语者")),
                nickname=nickname,
                avatar_url=avatar,
                uid=uid,
            )
        except Exception:
            logger.error(
                f"[{PLUGIN_NAME}] 卡片渲染失败，回退纯文本\n{traceback.format_exc()}"
            )
            return None

    def _format_result(self, payload: dict, repeat: bool = False) -> str:
        dims = payload.get("dims") or {}
        dim_line = "  ".join(
            f"{k} {'★' * v}{'☆' * (5 - v)}" for k, v in dims.items()
        )
        color = payload.get("lucky_color") or {}
        phase = payload.get("phase") or {}
        lines = [
            "🌙 萌萌星语",
            f"—— 星语签 · {payload.get('grade', '?')} ——",
            payload.get("sign_text", ""),
            "",
            dim_line,
            f"幸运指数：{payload.get('score', '?')}",
            f"幸运物：{payload.get('lucky_item', '？')}",
            "幸运色：{} ｜ 幸运数字：{} ｜ 幸运方位：{}".format(
                color.get("name", "？"),
                payload.get("lucky_number", "？"),
                payload.get("lucky_dir", "？"),
            ),
            f"宜：{'、'.join(payload.get('yi') or [])}",
            f"忌：{'、'.join(payload.get('ji') or [])}",
            f"月相：{phase.get('name', '？')}——{phase.get('text', '')}",
        ]
        streak = payload.get("streak") or 0
        if streak >= 2:
            lines.append(f"连续抽签 {streak} 天 ✨")
            badge = _STREAK_BADGES.get(streak)
            if badge:
                lines.append(badge)
        lines.append("—— 星语者")
        if repeat:
            lines.insert(0, "（今天已经抽过啦，这是你今天的星语签～）")
        return "\n".join(lines)

    # ---------- 指令 ----------

    @filter.command("运势", alias={"今日运势", "星语", "占卜"})
    async def fortune_cmd(self, event: AstrMessageEvent):
        """抽当日专属星语签（一人一天一支，跨群/私聊一致）"""
        if self._store is None:
            yield event.plain_result("星语者还没整理好星盘（插件未初始化完成），稍后再试～")
            return
        uid = str(event.get_sender_id() or "").strip()
        if not uid:
            yield event.plain_result("星语者没看清你是谁，稍后再试一次～")
            return
        if not event.is_private_chat():
            gid = str(event.get_group_id() or "")
            if gid and gid in self._disabled_groups():
                yield event.plain_result("本群已停用星语签，管理员可用 /运势开关 on 开启～")
                return
        tz_name = str(self._cfg("timezone", "Asia/Shanghai"))
        date = fortune.local_today(tz_name)
        salt = str(self._cfg("salt", "moe-star-whisper"))

        # 一日一签（D5）：已有签直接回发（卡文件优先，其次文本），不重算不重绘
        existing = self._store.get_fortune(uid, date)
        if existing is not None:
            payload = existing.get("payload") or {}
            card_path = payload.get("card_path") or ""
            if card_path and Path(card_path).exists():
                yield event.image_result(card_path)
            else:
                yield event.plain_result(self._format_result(payload, repeat=True))
            return

        # 首次抽签
        seed = fortune.derive_seed(date, uid, salt, nonce=0)
        result = fortune.roll_fortune(
            seed, lexicon.load_lexicon(), self._grade_weights()
        )
        result["date"] = date
        streak = self._store.bump_streak(uid, date, fortune.prev_date(date))
        result["streak"] = streak

        nickname = event.get_sender_name() or "旅行者"
        avatar = self._sender_avatar(event, uid)
        group_id = "" if event.is_private_chat() else str(event.get_group_id() or "")

        mode = str(self._cfg("output_mode", "图卡"))
        card_path = None
        if mode != "纯文本":
            card_path = self._try_render_card(result, uid, nickname, avatar)

        saved = self._store.save_fortune(
            uid, date, result,
            nickname=nickname, avatar=avatar, group_id=group_id,
            card_path=card_path or "",
        )
        if not saved:  # 并发撞车：读回已存的那份
            existing = self._store.get_fortune(uid, date)
            payload = (existing or {}).get("payload") or result
            card_path = payload.get("card_path") or card_path
            if card_path and Path(card_path).exists():
                yield event.image_result(card_path)
            else:
                yield event.plain_result(self._format_result(payload))
            return

        if card_path:
            yield event.image_result(card_path)
            if mode == "图卡+文本":
                yield event.plain_result(self._format_result(result))
        else:
            yield event.plain_result(self._format_result(result))

    @filter.command("运势榜", alias={"星语榜"})
    async def rank_cmd(self, event: AstrMessageEvent):
        """群内幸运指数排行（/运势榜 日|周，默认日）"""
        if self._store is None:
            yield event.plain_result("星语者还没整理好星盘，稍后再试～")
            return
        if event.is_private_chat():
            yield event.plain_result("排行榜只在群聊里有意义，来群里玩吧～")
            return
        gid = str(event.get_group_id() or "")
        arg = str(event.message_str or "").replace(" ", "")
        span = "周" if ("周" in arg or "week" in arg.lower()) else "日"
        tz_name = str(self._cfg("timezone", "Asia/Shanghai"))
        today = fortune.local_today(tz_name)
        lines = ["🌙 萌萌星语"]
        if span == "周":
            d = datetime.strptime(today, "%Y-%m-%d").date()
            monday = (d - timedelta(days=d.weekday())).strftime("%Y-%m-%d")
            rows = self._store.list_group_range_avg(gid, monday)
            lines.append(f"—— 本周星语榜（{monday[5:]} 起）——")
            if rows:
                for i, r in enumerate(rows, 1):
                    lines.append(
                        f"{i}. {r.get('nickname') or '旅人'} · "
                        f"均分 {r['avg_score']:.0f}（{r['days']} 天）"
                    )
        else:
            rows = self._store.list_group_day(gid, today)
            lines.append("—— 今日星语榜 ——")
            if rows:
                for i, r in enumerate(rows, 1):
                    lines.append(f"{i}. {r.get('nickname') or '旅人'} · {r['score']}")
        if not rows:
            lines.append("还没有人抽签，快来当第一个！")
        yield event.plain_result("\n".join(lines))

    @filter.command("运势PK", alias={"星语PK", "运势pk", "星语pk"})
    async def pk_cmd(self, event: AstrMessageEvent):
        """与被 @ 的人比一比今日幸运指数（双方需已抽签）"""
        if self._store is None:
            yield event.plain_result("星语者还没整理好星盘，稍后再试～")
            return
        if event.is_private_chat():
            yield event.plain_result("PK 只在群聊里有意义，来群里玩吧～")
            return
        uid = str(event.get_sender_id() or "").strip()
        target = None
        for seg in event.get_messages():
            if isinstance(seg, At):
                q = str(getattr(seg, "qq", "") or "")
                if q and q != "all":
                    target = q
                    break
        if not target:
            yield event.plain_result("要和谁比？请 @ 一个群里的人～")
            return
        if target == uid:
            yield event.plain_result("和自己 PK？星星表示这局你赢麻了，也输麻了。")
            return
        tz_name = str(self._cfg("timezone", "Asia/Shanghai"))
        today = fortune.local_today(tz_name)
        salt = str(self._cfg("salt", "moe-star-whisper"))
        mine = self._store.get_fortune(uid, today)
        theirs = self._store.get_fortune(target, today)
        if mine is None:
            yield event.plain_result("你今天还没抽签，先 /运势 一下吧～")
            return
        if theirs is None:
            yield event.plain_result("对方今天还没抽签，让 TA 先来一支吧～")
            return
        m_name = mine.get("nickname") or "你"
        t_name = theirs.get("nickname") or "对方"
        m_score, t_score = int(mine["score"]), int(theirs["score"])
        pk = lexicon.load_lexicon()["pk"]
        seed = fortune.derive_seed(f"{today}|pk", "|".join(sorted([uid, target])), salt)
        if m_score > t_score:
            line = fortune.pick_text(seed, "pk", pk["win"])
            verdict = f"{m_name} 胜！"
        elif m_score < t_score:
            line = fortune.pick_text(seed, "pk", pk["lose"])
            verdict = f"{t_name} 胜！"
        else:
            line = fortune.pick_text(seed, "pk", pk["tie"])
            verdict = "平局！"
        yield event.plain_result(
            "—— 星语 PK ——\n"
            f"{m_name} {m_score} vs {t_name} {t_score}\n"
            f"{verdict}{line}"
        )

    @filter.command("运势开关", alias={"星语开关"})
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def switch_cmd(self, event: AstrMessageEvent):
        """群内启停星语签（/运势开关 on|off，仅 AstrBot 管理员）"""
        if event.is_private_chat():
            yield event.plain_result("群开关请在群聊里使用～")
            return
        gid = str(event.get_group_id() or "")
        arg = str(event.message_str or "").replace(" ", "")
        for w in ("运势开关", "星语开关", "/"):
            arg = arg.replace(w, "")
        if arg.lower() in ("on", "开", "开启", "打开"):
            try:
                self._set_group_disabled(gid, False)
                yield event.plain_result("已开启本群星语签 ✨")
            except Exception:
                yield event.plain_result("开启失败：配置保存出错，请看日志～")
        elif arg.lower() in ("off", "关", "关闭"):
            try:
                self._set_group_disabled(gid, True)
                yield event.plain_result("已停用本群星语签（/运势开关 on 可重新开启）")
            except Exception:
                yield event.plain_result("停用失败：配置保存出错，请看日志～")
        else:
            state = "停用" if gid in self._disabled_groups() else "开启"
            yield event.plain_result(f"本群星语签当前：{state}（/运势开关 on|off）")
