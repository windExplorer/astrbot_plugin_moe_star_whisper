# -*- coding: utf-8 -*-
"""萌萌星语：每日运势签插件入口。"""
import importlib
import sys
import traceback
from pathlib import Path

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, StarTools, register
from astrbot.api import logger

from . import fortune, lexicon, store

PLUGIN_NAME = "astrbot_plugin_moe_star_whisper"

try:  # M2 起提供图卡；缺失/失败时回退纯文本
    from .card import render_card
except Exception:  # pragma: no cover
    render_card = None


@register(PLUGIN_NAME, "windExplorer", "萌萌星语：每日运势签", "0.3.0")
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
