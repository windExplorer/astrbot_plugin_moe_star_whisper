# -*- coding: utf-8 -*-
"""萌萌星语：每日运势签插件入口。"""
import asyncio
import importlib
import re
import sys
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, StarTools, register
from astrbot.api import logger
from astrbot.api.message_components import At, Image, Plain
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.message.message_event_result import MessageChain
import aiohttp

from . import fortune, lexicon, store

PLUGIN_NAME = "astrbot_plugin_moe_star_whisper"

try:  # M2 起提供图卡；缺失/失败时回退纯文本
    from .card import render_card, render_push_card
except Exception:  # pragma: no cover
    render_card = None
    render_push_card = None

_STREAK_BADGES = {
    3: "三星连签达成，运势开始聚拢 ✨",
    7: "七日连签达成，星星记住你了 🌙",
    14: "半月连签达成，毅力惊人 🌟",
    30: "三十日连签达成，星语者的挚友 🎇",
}

# 道具经济（M7/D8）：id -> (名称, 效果一句话)；星尘不可转账不可兑换
ITEM_DEFS = {
    "reroll": ("换签卡", "当日重抽一次，新结果覆盖旧结果（运势与底图完整重做）"),
    "amulet": ("厄运护身符", "佩戴后当日抽签保底小吉（抽签前使用）"),
    "streak_guard": ("连签保护卡", "断签 3 天内 /运势补签 补回昨天"),
    "candle": ("幸运香烛", "当日幸运指数 +8（抽签前使用）"),
}
DEFAULT_PRICES = {"reroll": 80, "amulet": 50, "streak_guard": 30, "candle": 20}
_ITEM_ALIASES = {
    "reroll": "reroll", "换签卡": "reroll", "换签": "reroll", "改运卡": "reroll",
    "amulet": "amulet", "厄运护身符": "amulet", "护身符": "amulet", "护身": "amulet",
    "streak_guard": "streak_guard", "连签保护卡": "streak_guard",
    "保护卡": "streak_guard", "补签卡": "streak_guard",
    "candle": "candle", "幸运香烛": "candle", "香烛": "candle",
}

try:  # M2 起提供图卡；缺失/失败时回退纯文本
    from .card import render_card
except Exception:  # pragma: no cover
    render_card = None


@register(PLUGIN_NAME, "windExplorer", "萌萌星语：每日运势签", "1.6.2")
class StarWhisperPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig = None):
        # ⚠️ 必须接受 config kwarg：star_manager 注入 AstrBotConfig 时若构造函数
        # 不接受该参数会 TypeError 被静默降级（只传 context），self.config 缺失
        # 导致 _cfg 全部回落默认值——所有配置开关在真机上"永远不生效"。
        super().__init__(context)
        self.config = config
        self._store = None
        self._push_task = None
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
            self._start_push_loop()
            try:  # WebUI 调试面板（Dashboard 登录墙内，仅管理员使用）
                from . import webui_api
                webui_api.register(self)
            except Exception:
                logger.error(
                    f"[{PLUGIN_NAME}] WebUI 调试面板注册失败\n{traceback.format_exc()}"
                )
            logger.info(f"[{PLUGIN_NAME}] 初始化完成，数据目录：{data_dir}")
        except Exception:
            logger.error(f"[{PLUGIN_NAME}] 初始化失败\n{traceback.format_exc()}")
            raise

    async def terminate(self):
        task = self._push_task
        if task is not None:
            task.cancel()
            self._push_task = None
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
        """停用群集合；兼容 list（schema v1.3.0 起）与旧版逗号分隔字符串。"""
        raw = self._cfg("disabled_groups", "")
        if isinstance(raw, (list, tuple)):
            return {str(g).strip() for g in raw if str(g).strip()}
        return {g.strip() for g in str(raw or "").replace("，", ",").split(",") if g.strip()}

    def _set_group_disabled(self, group_id: str, disabled: bool) -> None:
        """群开关落回配置（disabled_groups 逗号串，与 string schema 一致），持久化并在配置页可见。"""
        groups = self._disabled_groups()
        if disabled:
            groups.add(group_id)
        else:
            groups.discard(group_id)
        self.config["disabled_groups"] = ",".join(sorted(groups))
        self.config.save_config()

    @staticmethod
    def _sender_avatar(event: AstrMessageEvent, uid: str) -> str:
        """头像 URL 快照（D10）：q4 headimg_dl 官方接口（box 同款，已验证可用）。"""
        if StarWhisperPlugin._sender_platform(event):
            return f"https://q4.qlogo.cn/headimg_dl?dst_uin={uid}&spec=640"
        return ""

    @staticmethod
    def _sender_platform(event: AstrMessageEvent) -> str:
        try:
            return str(event.get_platform_name() or "")
        except Exception:
            return ""

    async def _fetch_avatar_bytes(self, uid: str) -> bytes | None:
        """服务端下载头像 bytes（aiohttp，box 同款接口）；失败返回 None。"""
        url = f"https://q4.qlogo.cn/headimg_dl?dst_uin={uid}&spec=640"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=8)
                ) as resp:
                    resp.raise_for_status()
                    data = await resp.read()
                    if data and len(data) > 100:
                        return data
                    logger.warning(f"[{PLUGIN_NAME}] 头像响应过小（{len(data or '')}B），视为失败")
        except Exception as e:
            logger.warning(f"[{PLUGIN_NAME}] 头像下载失败：{type(e).__name__}: {e}")
        return None

    def _try_render_card(self, result: dict, uid: str, nickname: str = "",
                         avatar_bytes: bytes | None = None, bg_image=None):
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
                avatar_data=avatar_bytes,
                uid=uid,
                bg_image=bg_image,
                theme=str(self._cfg("card_theme", "auto")),
            )
        except Exception:
            logger.error(
                f"[{PLUGIN_NAME}] 卡片渲染失败，回退纯文本\n{traceback.format_exc()}"
            )
            return None

    # ---------- anima 底图联动（F23/D6/D11，契约见 PRD §7.6） ----------

    async def _try_build_image_prompt(self, result: dict, event: AstrMessageEvent | None = None):
        """生图提示词：LLM 生成（受语言/形式约束）→ 失败回退本地模板（PRD §7.6-4）。"""
        lang = str(self._cfg("draw_prompt_lang", "en"))
        fmt = str(self._cfg("draw_prompt_format", "tags"))
        template = str(
            self._cfg("draw_llm_prompt", "") or fortune.builtin_draw_prompt(lang, fmt)
        )
        prompt = template.replace("{facts}", fortune.llm_facts(result))
        try:
            umo = getattr(event, "unified_msg_origin", None) if event is not None else None
            provider = self.context.get_using_provider(umo)
            if provider is not None:
                resp = await asyncio.wait_for(
                    provider.text_chat(prompt=prompt, system_prompt=fortune.DRAW_SYSTEM_HINT),
                    timeout=20,
                )
                text = str(getattr(resp, "completion_text", "") or "").strip()
                if not text and getattr(resp, "result_chain", None) is not None:
                    text = "".join(
                        str(getattr(s, "text", "") or "") for s in resp.result_chain.chain
                    ).strip()
                if text:
                    return text.strip('`" \n')[:300], template
        except Exception:
            logger.error(
                f"[{PLUGIN_NAME}] 生图提示词 LLM 生成失败，改用本地模板\n{traceback.format_exc()}"
            )
        return fortune.local_draw_prompt(result, lang, fmt), template

    async def _try_draw_background(self, event: AstrMessageEvent, result: dict,
                                   uid: str, date: str, salt: str):
        """anima comfyui_draw 出底图。返回 (bg_path|None, job|None)。

        契约（anima docs/cross-plugin-draw-guide.md，源码已核实）：
        get_llm_tool_manager().get_func("comfyui_draw") → handler(event, ...)；
        source 必传 anima 约定值「我会永远陪着你」才返回 JSON 路径由我方发图；
        seed/width/height 透传（D11：底图一人一天一张、尺寸与卡布一致）；
        超时/异常静默降级到幸运色默认底图，绝不阻塞出卡。
        """
        if not bool(self._cfg("draw_enabled", False)):
            return None, None
        job = {
            "workflow": str(self._cfg("draw_workflow", "") or ""),
            "prompt_lang": str(self._cfg("draw_prompt_lang", "en")),
            "prompt_fmt": str(self._cfg("draw_prompt_format", "tags")),
            "image_prompt": "",
            "llm_prompt": "",
            "status": "error",
            "error": "",
            "duration_ms": 0,
            "image_path": "",
        }
        try:
            manager = self.context.get_llm_tool_manager()
            tool = manager.get_func("comfyui_draw") if manager is not None else None
            handler = (getattr(tool, "handler", None) or tool) if tool is not None else None
        except Exception:
            handler = None
        if handler is None:
            job["status"] = "skipped_no_anima"
            return None, job

        image_prompt, llm_prompt = await self._try_build_image_prompt(result, event)
        job["image_prompt"] = image_prompt
        job["llm_prompt"] = llm_prompt
        seed_int = int.from_bytes(
            fortune.derive_seed(date, uid, salt, 0)[:8], "big"
        ) % (2 ** 31)
        kwargs = dict(
            prompt=image_prompt,
            source="我会永远陪着你",
            seed=seed_int,
            width=int(self._cfg("card_width", 1024)),
            height=int(self._cfg("card_height", 1536)),
        )
        if job["workflow"]:
            kwargs["workflow"] = job["workflow"]
        negative = str(self._cfg("draw_negative_prompt", "") or "")
        if negative:
            kwargs["negative_prompt"] = negative

        t0 = time.monotonic()
        try:
            raw = await asyncio.wait_for(
                handler(event, **kwargs),
                timeout=int(self._cfg("draw_timeout", 120)),
            )
            job["duration_ms"] = int((time.monotonic() - t0) * 1000)
            paths = fortune.parse_draw_response(raw)
            if paths and Path(paths[0]).exists():
                job["status"] = "ok"
                job["image_path"] = paths[0]
                return paths[0], job
            job["error"] = f"响应中无有效图片路径: {str(raw)[:200]}"
            return None, job
        except asyncio.TimeoutError:
            job["duration_ms"] = int((time.monotonic() - t0) * 1000)
            job["status"] = "timeout"
            return None, job
        except Exception as e:
            job["duration_ms"] = int((time.monotonic() - t0) * 1000)
            job["status"] = "error"
            job["error"] = str(e)[:200]
            return None, job

    def _roll_daily(self, uid: str, date: str, salt: str, profile: dict,
                    nonce=None, streak=None) -> dict:
        """确定性掷出当日签（M7 重构）：生日特权 / 佩戴道具 / 彩蛋 / 首抽星尘。

        nonce 缺省时按档案中的当日种子序号自增（seed_date/seed_nonce 持久在
        profiles，不随签记录删除而丢失）——换签卡、调试重置后的重抽都会得到新签；
        streak 传值时沿用（补签/换签场景），缺省时按首签推进（当日幂等）。
        """
        if nonce is None:
            nonce = 0
            if str(profile.get("seed_date") or "") == date:
                nonce = int(profile.get("seed_nonce") or 0) + 1
        weights = self._grade_weights()
        birthday_today = str(profile.get("birthday") or "") == date[5:]
        if birthday_today:
            weights = {"大吉": 100}  # 生日特权（F14）
        wearing_amulet = self._store.has_ledger(uid, date, "use:amulet")
        if wearing_amulet:
            weights = fortune.amulet_weights(weights)
        lex = lexicon.load_lexicon()
        seed = fortune.derive_seed(date, uid, salt, nonce)
        result = fortune.roll_fortune(seed, lex, weights)
        result["date"] = date
        result["reroll_count"] = nonce
        result["tarot"] = fortune.tarot_of(seed)  # 今日大阿卡纳（M8 塔罗卡面）
        if streak is None:
            streak = self._store.bump_streak(uid, date, fortune.prev_date(date))
        result["streak"] = streak
        # 种子序号持久到档案：重置删记录后，下次抽签依然自动换种子
        self._store.upsert_profile(uid, seed_date=date, seed_nonce=nonce)
        if profile.get("constellation"):
            result["constellation"] = profile["constellation"]
        if birthday_today:
            result["birthday_today"] = True
        result["boosts"]["amulet"] = wearing_amulet
        if self._store.has_ledger(uid, date, "use:candle"):
            fortune.apply_candle(result)
        # 特殊日期彩蛋（F14），写进 payload 保证回放一致
        mmdd = date[5:]
        if mmdd == "04-01":
            result["grade_display"] = f"{result['grade']}（？）"
            if result["grade"] == "大吉":
                result["sign_text"] += "（真的是大吉，星星发誓——今天可是愚人节。）"
            else:
                result["sign_text"] += "（愚人节快乐，以上运势真假自辨。）"
        else:
            extras = []
            fest = lex.get("festivals") or {}
            if mmdd in fest:
                extras.append(fortune.pick_text(seed, "festival", fest[mmdd]))
            if datetime.strptime(date, "%Y-%m-%d").weekday() == 4:
                extras.append(fortune.pick_text(seed, "friday", lex["friday"]))
            if extras:
                result["sign_text"] = result["sign_text"] + "".join(extras)
        if nonce == 0 and self._economy_on():
            reward = fortune.stardust_reward(
                result["grade"], streak, int(self._cfg("draw_reward_base", 10))
            )
            self._store.add_ledger(uid, reward, "draw", date)
            result["stardust"] = reward
        return result

    def _economy_on(self) -> bool:
        return bool(self._cfg("economy_enabled", True))

    def _price_of(self, item_id: str) -> int:
        raw = self._cfg("item_prices", None)
        if isinstance(raw, dict) and raw.get(item_id) is not None:
            try:
                return max(0, int(raw[item_id]))
            except Exception:
                pass
        return DEFAULT_PRICES[item_id]

    async def _try_llm_sign(self, result: dict, event: AstrMessageEvent | None = None) -> None:
        """LLM 星语（F16，可选增强默认关）：当日首次抽签改写签文；失败静默回退本地模板。

        event 缺省（WebUI 触发）时用全局默认提供商。
        """
        try:
            if not bool(self._cfg("llm_enabled", False)):
                result["llm_note"] = "LLM 星语未开启"
                return
            umo = getattr(event, "unified_msg_origin", None) if event is not None else None
            provider = self.context.get_using_provider(umo)
            if provider is None:
                result["llm_note"] = "当前会话未绑定可用 LLM（提供商为空）"
                return
            persona = str(
                self._cfg("llm_prompt_persona", "") or fortune.DEFAULT_LLM_PERSONA
            )
            prompt = (
                "今日运势事实清单：\n" + fortune.llm_facts(result) + "\n请据此写今日签文。"
            )
            resp = await asyncio.wait_for(
                provider.text_chat(prompt=prompt, system_prompt=persona),
                timeout=20,
            )
            text = str(getattr(resp, "completion_text", "") or "").strip()
            if not text and getattr(resp, "result_chain", None) is not None:
                parts = []
                for seg in resp.result_chain.chain:
                    t = getattr(seg, "text", None)
                    if t:
                        parts.append(str(t))
                text = "".join(parts).strip()
            if not text:
                result["llm_note"] = "LLM 返回为空"
                return
            result["sign_text"] = text[:160]
            result["llm_used"] = True
        except asyncio.TimeoutError:
            result["llm_note"] = "LLM 星语超时（20s），已用内置签文"
            logger.warning(f"[{PLUGIN_NAME}] LLM 星语超时，回退本地签文")
        except Exception as e:
            result["llm_note"] = f"LLM 星语失败：{str(e)[:100]}"
            logger.error(
                f"[{PLUGIN_NAME}] LLM 星语失败，回退本地签文\n{traceback.format_exc()}"
            )

    # ---------- 每日群推送（F17，插件自管定时循环，PRD §7.5） ----------

    def _start_push_loop(self):
        self._push_task = asyncio.create_task(self._push_loop())

    def _next_push_delay(self) -> float:
        """距下次推送时刻的秒数（时刻已过则顺延到明天）。"""
        tz_name = str(self._cfg("timezone", "Asia/Shanghai"))
        now = fortune.now_in(tz_name)
        raw = str(self._cfg("daily_push_time", "08:00") or "08:00")
        try:
            hh, mm = raw.split(":")[:2]
            hour, minute = int(hh), int(mm)
        except Exception:
            hour, minute = 8, 0
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return (target - now).total_seconds()

    async def _push_loop(self):
        while True:
            try:
                if not bool(self._cfg("daily_push_enabled", False)):
                    await asyncio.sleep(60)
                    continue
                wait = self._next_push_delay()
                if wait > 0:
                    await asyncio.sleep(min(wait, 1800))
                    continue
                await self._do_daily_push()
                await asyncio.sleep(120)  # 推完避开同一时刻，防重复
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.error(f"[{PLUGIN_NAME}] 推送循环异常\n{traceback.format_exc()}")
                await asyncio.sleep(300)

    async def _do_daily_push(self):
        if self._store is None:
            return
        tz_name = str(self._cfg("timezone", "Asia/Shanghai"))
        today = fortune.local_today(tz_name)
        salt = str(self._cfg("salt", "moe-star-whisper"))
        lex = lexicon.load_lexicon()
        seed = fortune.derive_seed(today, "daily-push", salt)
        phase = fortune.pick_text(seed, "push_phase", lex["phases"])
        accent = fortune.pick_text(seed, "push_color", lex["lucky_colors"])
        fest = (lex.get("festivals") or {}).get(today[5:])
        fest_line = fortune.pick_text(seed, "push_fest", fest) if fest else ""
        weekday_name = "星期" + "一二三四五六日"[fortune.now_in(tz_name).weekday()]

        data_dir = Path(StarTools.get_data_dir(PLUGIN_NAME))
        push_card_path = None
        if render_push_card is not None:
            try:
                push_card_path = render_push_card(
                    today, weekday_name, phase, fest_line,
                    accent_hex=accent.get("hex", "#F6C6D3"),
                    cards_root=data_dir / "push",
                    font_path=self._cfg("card_font_path", "") or None,
                    extra_font_dirs=[data_dir / "fonts", Path("data/fonts")],
                    signer=str(self._cfg("fortune_signer", "星语者")),
                )
            except Exception:
                logger.error(f"[{PLUGIN_NAME}] 推送卡渲染失败，回退纯文本\n{traceback.format_exc()}")
                push_card_path = None

        caption = (
            "🌙 萌萌星语 · 今日星象\n"
            f"{today} {weekday_name} ｜ 月相：{phase.get('name', '？')}——{phase.get('text', '')}"
        )
        if fest_line:
            caption += f"\n{fest_line}"

        disabled = self._disabled_groups()
        targets = [g for g in self._store.list_active_group_ids(7) if g[0] not in disabled]
        for gid, platform in targets:
            if not platform:
                continue  # 没有平台信息无法定位会话
            session = f"{platform}:GroupMessage:{gid}"
            chain = MessageChain(chain=[Plain(caption)])
            if push_card_path:
                chain.chain.append(Image.fromFileSystem(push_card_path))
            try:
                ok = await StarTools.send_message(session, chain)
                logger.info(f"[{PLUGIN_NAME}] 推送 {gid}: {'ok' if ok else 'no platform matched'}")
            except Exception:
                logger.error(f"[{PLUGIN_NAME}] 推送 {gid} 失败\n{traceback.format_exc()}")

    def _format_result(self, payload: dict, repeat: bool = False) -> str:
        dims = payload.get("dims") or {}
        dim_line = "  ".join(
            f"{k} {'★' * v}{'☆' * (5 - v)}" for k, v in dims.items()
        )
        color = payload.get("lucky_color") or {}
        phase = payload.get("phase") or {}
        lines = [
            "🌙 萌萌星语",
            f"—— 星语签 · {payload.get('grade_display') or payload.get('grade', '?')} ——",
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
        stardust = payload.get("stardust")
        if stardust:
            lines.append(f"星尘 +{stardust}（/星尘 查看背包）")
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

        # 首次抽签（生日特权/佩戴道具/彩蛋/星尘奖励统一在 _roll_daily）
        profile = self._store.get_profile(uid) or {}
        result = self._roll_daily(uid, date, salt, profile)

        await self._try_llm_sign(result, event)

        nickname = event.get_sender_name() or "旅行者"
        avatar_url = self._sender_avatar(event, uid)  # URL 快照入库（D10）
        avatar_bytes = await self._fetch_avatar_bytes(uid) if avatar_url else None
        group_id = "" if event.is_private_chat() else str(event.get_group_id() or "")

        mode = str(self._cfg("output_mode", "图卡"))
        card_path = None
        bg_fail_hint = ""
        if mode != "纯文本":
            # D11 先绘后卡：anima 底图（可选）→ 合卡 → 发送；失败静默回退幸运色渐变
            bg_path, job = await self._try_draw_background(event, result, uid, date, salt)
            card_path = self._try_render_card(result, uid, nickname, avatar_bytes, bg_image=bg_path)
            if job is not None:
                job["card_path"] = card_path or ""
                try:
                    self._store.record_draw_job(uid, date, **job)
                except Exception:
                    logger.error(f"[{PLUGIN_NAME}] draw_jobs 落库失败\n{traceback.format_exc()}")
                if job.get("status") in ("timeout", "error", "skipped_no_anima"):
                    bg_fail_hint = str(self._cfg("draw_fail_hint", "") or "")

        saved = self._store.save_fortune(
            uid, date, result,
            nickname=nickname, avatar=avatar_url, group_id=group_id,
            card_path=card_path or "",
            platform=self._sender_platform(event),
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
        if bg_fail_hint:
            yield event.plain_result(bg_fail_hint)

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

    @filter.command("星语绑定", alias={"运势绑定", "绑定生日"})
    async def bind_cmd(self, event: AstrMessageEvent):
        """绑定生日（MM-DD，不存年份）以解锁星座与生日彩蛋"""
        if self._store is None:
            yield event.plain_result("星语者还没整理好星盘，稍后再试～")
            return
        uid = str(event.get_sender_id() or "").strip()
        raw = str(event.message_str or "").replace(" ", "")
        for w in ("星语绑定", "运势绑定", "绑定生日", "/"):
            raw = raw.replace(w, "")
        m = re.search(r"(\d{1,2})[月./\-](\d{1,2})", raw)
        if not m:
            yield event.plain_result("格式：/星语绑定 08-15（月-日，不用年份）")
            return
        mo, dy = int(m.group(1)), int(m.group(2))
        try:
            datetime(2000, mo, dy)  # 2000 为闰年，2/29 允许
        except ValueError:
            yield event.plain_result(f"{mo} 月 {dy} 日？星星翻遍日历也没找到这一天。")
            return
        mmdd = f"{mo:02d}-{dy:02d}"
        cons = fortune.constellation_of(mmdd)
        self._store.upsert_profile(uid, birthday=mmdd, constellation=cons)
        extra = "（2 月 29 日的稀有生日！只在闰年的今天生效哦）" if (mo, dy) == (2, 29) else ""
        yield event.plain_result(
            f"绑定成功：{mmdd} · {cons}{extra}\n生日当天你会收到必中大吉的生日签 🎂"
        )

    @filter.command("星座", alias={"查询星座", "星语星座"})
    async def constellation_cmd(self, event: AstrMessageEvent):
        """查看自己或被 @ 的人的星座与今日吉凶（不展示生日）"""
        if self._store is None:
            yield event.plain_result("星语者还没整理好星盘，稍后再试～")
            return
        uid = str(event.get_sender_id() or "").strip()
        target = None
        for seg in event.get_messages():
            if isinstance(seg, At):
                q = str(getattr(seg, "qq", "") or "")
                if q and q != "all":
                    target = q
                    break
        target_id = target or uid
        prof = self._store.get_profile(target_id) or {}
        if not prof.get("constellation"):
            name = "你" if target_id == uid else "TA"
            yield event.plain_result(f"{name}还没绑定生日，/星语绑定 MM-DD 即可解锁～")
            return
        today = fortune.local_today(str(self._cfg("timezone", "Asia/Shanghai")))
        line = f"星座：{prof['constellation']}"
        row = self._store.get_fortune(target_id, today)
        if row is not None:
            line += f" ｜ 今日：{row['grade']}（{row['score']}）"
        else:
            line += " ｜ 今日：还没抽签"
        if (prof.get("birthday") or "") == today[5:]:
            line += " ｜ 🎂 今天是生日！"
        yield event.plain_result(line)

    # ---------- 道具经济指令（M7/D8） ----------

    @filter.command("星尘", alias={"运势背包"})
    async def wallet_cmd(self, event: AstrMessageEvent):
        """查星尘余额与道具背包"""
        if self._store is None or not self._economy_on():
            yield event.plain_result("道具经济未开放～")
            return
        uid = str(event.get_sender_id() or "").strip()
        balance = self._store.get_balance(uid)
        lines = [f"✨ 星尘余额：{balance}", "—— 背包 ——"]
        for item_id, (name, _desc) in ITEM_DEFS.items():
            count = self._store.get_item(uid, item_id)
            lines.append(f"{name} ×{count}")
        lines.append("用 /运势商店 看看有什么好东西～")
        yield event.plain_result("\n".join(lines))

    @filter.command("运势商店", alias={"星语商店"})
    async def shop_cmd(self, event: AstrMessageEvent):
        """道具与价格一览"""
        if self._store is None or not self._economy_on():
            yield event.plain_result("道具经济未开放～")
            return
        uid = str(event.get_sender_id() or "").strip()
        lines = ["🛒 萌萌星语 · 道具商店", ""]
        for item_id, (name, desc) in ITEM_DEFS.items():
            lines.append(
                f"【{name}】{self._price_of(item_id)} 星尘\n　{desc}\n　持有 ×{self._store.get_item(uid, item_id)}"
            )
        lines.append("\n购买：/运势购买 <名称> [数量]")
        yield event.plain_result("\n".join(lines))

    @filter.command("运势购买", alias={"星语购买"})
    async def buy_cmd(self, event: AstrMessageEvent):
        """购买道具：/运势购买 <名称> [数量]"""
        if self._store is None or not self._economy_on():
            yield event.plain_result("道具经济未开放～")
            return
        uid = str(event.get_sender_id() or "").strip()
        raw = str(event.message_str or "").replace(" ", "")
        for w in ("运势购买", "星语购买", "/"):
            raw = raw.replace(w, "")
        m_num = re.search(r"(\d+)", raw)
        count = 1
        if m_num:
            count = max(1, min(10, int(m_num.group(1))))
            raw = raw[:m_num.start()] + raw[m_num.end():]
        item_id = _ITEM_ALIASES.get(raw.strip())
        if item_id is None:
            yield event.plain_result("要买什么？/运势商店 看看货架～")
            return
        cap = max(1, int(self._cfg("item_hold_cap", 3)))
        held = self._store.get_item(uid, item_id)
        if held + count > cap:
            yield event.plain_result(
                f"持有已达上限（{cap}）——现在 ×{held}，最多再买 {max(0, cap - held)} 张。"
            )
            return
        price = self._price_of(item_id) * count
        balance = self._store.get_balance(uid)
        if balance < price:
            yield event.plain_result(
                f"星尘不够啦：需要 {price}，你还差 {price - balance}。明天记得来抽签攒星尘～"
            )
            return
        self._store.add_ledger(uid, -price, f"buy:{item_id}")
        new_count = self._store.add_item(uid, item_id, count)
        name = ITEM_DEFS[item_id][0]
        yield event.plain_result(
            f"购买成功：{name} ×{count}（-{price} 星尘）\n当前持有 ×{new_count}，余额 {balance - price}。"
        )

    @filter.command("运势使用", alias={"星语使用"})
    async def use_cmd(self, event: AstrMessageEvent):
        """使用道具：/运势使用 <换签卡|厄运护身符|幸运香烛>"""
        if self._store is None or not self._economy_on():
            yield event.plain_result("道具经济未开放～")
            return
        uid = str(event.get_sender_id() or "").strip()
        raw = str(event.message_str or "").replace(" ", "")
        for w in ("运势使用", "星语使用", "/"):
            raw = raw.replace(w, "")
        item_id = _ITEM_ALIASES.get(raw.strip())
        if item_id is None:
            yield event.plain_result("要使用哪个道具？背包见 /星尘")
            return
        tz_name = str(self._cfg("timezone", "Asia/Shanghai"))
        date = fortune.local_today(tz_name)
        salt = str(self._cfg("salt", "moe-star-whisper"))

        if item_id == "reroll":
            existing = self._store.get_fortune(uid, date)
            if existing is None:
                yield event.plain_result("今天还没抽签，不用换——先 /运势 抽一支吧～")
                return
            payload = existing.get("payload") or {}
            used = int(payload.get("reroll_count", 0) or 0)
            if used >= 1:
                yield event.plain_result("今天已经换过一次签了，命运不接受讨价还价～")
                return
            if self._store.get_item(uid, "reroll") < 1:
                yield event.plain_result("背包里没有换签卡（/运势商店 有售）。")
                return
            self._store.add_item(uid, "reroll", -1)
            new_result = self._roll_daily(
                uid, date, salt, self._store.get_profile(uid) or {},
                streak=int(payload.get("streak") or 1),
            )
            bg_path, job = await self._try_draw_background(event, new_result, uid, date, salt)
            avatar_bytes = await self._fetch_avatar_bytes(uid)
            card_path = self._try_render_card(
                new_result, uid,
                nickname=existing.get("nickname") or "", avatar_bytes=avatar_bytes,
                bg_image=bg_path,
            )
            if job is not None:
                job["card_path"] = card_path or ""
                try:
                    self._store.record_draw_job(uid, date, **job)
                except Exception:
                    logger.error(f"[{PLUGIN_NAME}] draw_jobs 落库失败\n{traceback.format_exc()}")
            self._store.update_fortune_payload(uid, date, new_result, card_path or "")
            if card_path:
                yield event.image_result(card_path)
            else:
                yield event.plain_result(self._format_result(new_result))
            return

        if item_id in ("amulet", "candle"):
            if self._store.get_fortune(uid, date) is not None:
                yield event.plain_result("今天的签已经出来了，这个道具明天再用吧～")
                return
            if self._store.has_ledger(uid, date, f"use:{item_id}"):
                yield event.plain_result("今天已经佩戴过了，不用重复使用～")
                return
            if self._store.get_item(uid, item_id) < 1:
                yield event.plain_result(f"背包里没有{ITEM_DEFS[item_id][0]}（/运势商店 有售）。")
                return
            self._store.add_item(uid, item_id, -1)
            self._store.add_ledger(uid, 0, f"use:{item_id}", date)
            yield event.plain_result(f"已使用{ITEM_DEFS[item_id][0]}：今天抽签时生效 ✨")
            return

        yield event.plain_result("这个道具不需要手动使用（见 /运势商店 说明）。")

    @filter.command("运势补签", alias={"星语补签"})
    async def makeup_cmd(self, event: AstrMessageEvent):
        """断签 3 天内消耗连签保护卡补回昨天的签"""
        if self._store is None or not self._economy_on():
            yield event.plain_result("道具经济未开放～")
            return
        uid = str(event.get_sender_id() or "").strip()
        tz_name = str(self._cfg("timezone", "Asia/Shanghai"))
        today = fortune.local_today(tz_name)
        salt = str(self._cfg("salt", "moe-star-whisper"))
        prev = fortune.prev_date(today)
        profile = self._store.get_profile(uid) or {}
        last = str(profile.get("last_draw_date") or "")
        if not last:
            yield event.plain_result("还没抽过签就谈不上补签——先 /运势 抽第一支吧～")
            return
        if last == today:
            yield event.plain_result("今天已经抽过啦，不用补签～")
            return
        if self._store.get_fortune(uid, prev) is not None:
            yield event.plain_result("昨天的签还在，没有缺口可补。")
            return
        if self._store.get_fortune(uid, today) is not None:
            yield event.plain_result("今天已经抽过，补签窗口关闭（明天断签再来）。")
            return
        gap_days = (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(last, "%Y-%m-%d")).days
        if gap_days > 3:
            yield event.plain_result("断签超过 3 天，连不上啦——从今天重新开始连签吧。")
            return
        if self._store.get_item(uid, "streak_guard") < 1:
            yield event.plain_result("背包里没有连签保护卡（/运势商店 有售）。")
            return
        self._store.add_item(uid, "streak_guard", -1)
        result = self._roll_daily(uid, prev, salt, profile)
        nickname = profile.get("nickname") or "旅行者"
        self._store.save_fortune(
            uid, prev, result, nickname=nickname,
            avatar=profile.get("avatar") or "", platform=self._sender_platform(event),
        )
        yield event.plain_result(
            f"补签成功（{prev}）✨ 连签恢复到 {result['streak']} 天\n\n" + self._format_result(result)
        )

    @filter.command("运势发放", alias={"星语发放"})
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def grant_cmd(self, event: AstrMessageEvent):
        """手动调整星尘：/运势发放 @用户 <±n>（必走流水）"""
        if self._store is None or not self._economy_on():
            yield event.plain_result("道具经济未开放～")
            return
        target = None
        for seg in event.get_messages():
            if isinstance(seg, At):
                q = str(getattr(seg, "qq", "") or "")
                if q and q != "all":
                    target = q
                    break
        if not target:
            yield event.plain_result("请 @ 要发放（或扣除）星尘的用户。")
            return
        raw = str(event.message_str or "")
        m = re.search(r"([+-]?\d+)", raw)
        if not m:
            yield event.plain_result("格式：/运势发放 @用户 <±n>")
            return
        delta = int(m.group(1))
        if delta == 0:
            yield event.plain_result("0 颗星尘？星星当你是空气。")
            return
        self._store.add_ledger(target, delta, "admin")
        yield event.plain_result(
            f"已{'发放' if delta > 0 else '扣除'} {abs(delta)} 颗星尘，当前余额 {self._store.get_balance(target)}。"
        )
