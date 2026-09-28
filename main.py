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
    from .card import (
        render_card, render_push_card, render_help_card,
        render_wallet_card, render_shop_card, render_rank_card,
        render_pk_card, render_notice_card, render_calendar_card,
    )
except Exception:  # pragma: no cover
    render_card = None
    render_push_card = None
    render_help_card = None
    render_wallet_card = None
    render_shop_card = None
    render_rank_card = None
    render_pk_card = None
    render_notice_card = None
    render_calendar_card = None

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
    "streak_guard": ("连签保护卡", "断签 3 天内 /星语补签 补回昨天"),
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


@register(PLUGIN_NAME, "windExplorer", "萌萌星语：每日运势签", "1.8.5")
class StarWhisperPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig = None):
        # ⚠️ 必须接受 config kwarg：star_manager 注入 AstrBotConfig 时若构造函数
        # 不接受该参数会 TypeError 被静默降级（只传 context），self.config 缺失
        # 导致 _cfg 全部回落默认值——所有配置开关在真机上"永远不生效"。
        super().__init__(context)
        self.config = config
        self._store = None
        self._push_task = None
        self._member_cache: dict = {}  # group_id -> (monotonic_ts, {成员 id})，榜单用（v1.9.4）
        self._reload_modules()

    # ---------- 生命周期 ----------

    def _reload_modules(self):
        """热重载自研子模块（依赖序），避免热更后跑旧代码（PRD §7.7）。

        v1.9.0 起把 webui_api 也纳入：控制台接口（总览/统计/配置读写）都在里面，
        不重载的话热更上来的实例会一直跑旧接口（新增路由静默 404）。
        """
        pkg = __package__
        for name in ("lexicon", "fortune", "store", "webui_api"):
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

    async def _group_name_of(self, event: AstrMessageEvent) -> str:
        """群名快照（v1.9.3）：优先取事件自带的群名（OneBot/NapCat 下发的 group_name），
        取不到时调平台 API 兜底（`event.get_group()` 在 aiocqhttp 下会走 OneBot
        `get_group_info`）。私聊或彻底取不到返回空串——展示层按 `group_name or group_id` 兜底。
        取群名失败绝不影响抽签，只记日志。
        """
        if event.is_private_chat():
            return ""
        try:
            group = getattr(event.message_obj, "group", None)
            name = str(getattr(group, "group_name", "") or "").strip()
            if name:
                return name
        except Exception:
            pass
        try:
            group = await event.get_group()
            return str(getattr(group, "group_name", "") or "").strip()
        except Exception:
            logger.warning(
                f"[{PLUGIN_NAME}] 取群名失败，本次只记录群号\n{traceback.format_exc()}"
            )
            return ""

    # 群成员缓存的 TTL（秒）：榜单是高频指令，不宜每次都打平台 API（v1.9.4）
    _MEMBER_TTL = 600
    _MEMBER_CACHE_MAX = 200

    async def _group_member_ids(self, event: AstrMessageEvent, gid: str) -> set | None:
        """本群成员 id 集合（带 TTL 缓存）；取不到返回 None。

        用途（v1.9.4 榜单口径）：用户今天可能在别的群抽签，但只要他人在本群，
        就应该出现在本群的星语榜里——所以榜是按「群成员」筛，而不是按「在本群抽签」筛。
        取群成员走 `event.get_group()`（aiocqhttp 下会调 OneBot `get_group_info` +
        `get_group_member_list`）；平台不支持或调用失败时返回 None，调用方回落旧口径。
        """
        gid = str(gid or "")
        if not gid:
            return None
        now = time.monotonic()
        cached = self._member_cache.get(gid)
        if cached and (now - cached[0]) < self._MEMBER_TTL:
            return cached[1]
        ids: set = set()
        try:
            group = await event.get_group()
            for member in (getattr(group, "members", None) or []):
                uid = str(getattr(member, "user_id", "") or "").strip()
                if uid:
                    ids.add(uid)
        except Exception:
            logger.warning(
                f"[{PLUGIN_NAME}] 取群成员失败，星语榜回落「本群抽签」口径\n{traceback.format_exc()}"
            )
            return None
        if not ids:
            logger.info(f"[{PLUGIN_NAME}] 群 {gid} 成员列表为空，星语榜回落「本群抽签」口径")
            return None
        if len(self._member_cache) >= self._MEMBER_CACHE_MAX:
            self._member_cache.clear()
        self._member_cache[gid] = (now, ids)
        return ids

    @staticmethod
    async def _send_plain(event: AstrMessageEvent, text: str) -> None:
        """直发纯文本，**绕开结果链装饰**——不会被自动 @ 发送者。

        背景（AstrBot 4.28.1 `core/pipeline/result_decorate/stage.py`）：当
        `platform_settings.reply_with_mention` 打开时，框架会给「只含 Plain/Image
        的结果链」在最前面插一个 `At(发送者)`；而 `event.send()` 不进结果链，
        所以拿它发「占卜中」这类过程提示最合适。结果消息仍走 `yield`，保持 @。
        """
        try:
            await event.send(MessageChain([Plain(str(text))]))
        except Exception:
            logger.warning(
                f"[{PLUGIN_NAME}] 过程提示直发失败（忽略）\n{traceback.format_exc()}"
            )

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

    def _font_dirs(self, data_dir: Path) -> list:
        """卡片字体候选目录（v1.9.7）。

        只认两个位置，**不依赖任何其它插件**：
          1. 本插件数据目录下的 `fonts/`（`data/plugin_data/<插件名>/fonts/`）
          2. AstrBot 的公共字体目录 `data/fonts/`（由数据目录反推两级拿到）

        都找不到就继续走 card.py 里的系统字体候选（Windows 微软雅黑 / Linux Noto CJK）。
        """
        data_dir = Path(data_dir)
        dirs = [data_dir / "fonts", data_dir.parent.parent / "fonts"]
        legacy = Path("data/fonts")  # cwd 不在 AstrBot 根目录时的兜底写法
        if legacy not in dirs:
            dirs.append(legacy)
        return dirs

    def _card_font_path(self, data_dir: Path) -> str | None:
        """本次渲染实际使用的字体路径（v1.9.7）。

        优先级：显式配置 `card_font_path` → 圆体风格时在候选目录里按名字挑圆体 →
        None（交给 card.find_font 走系统字体）。挑不到圆体只记日志、不报错，
        绝不影响出卡（回落默认字体）。
        """
        explicit = str(self._cfg("card_font_path", "") or "").strip()
        if explicit:
            return explicit
        if str(self._cfg("card_font_style", "auto")).strip().lower() == "rounded":
            dirs = self._font_dirs(data_dir)
            picked = card.find_font_by_hint(dirs, ("rounded",))
            if picked:
                return picked
            logger.info(
                f"[{PLUGIN_NAME}] 圆体风格未找到圆体字体（已找 "
                f"{[str(d) for d in dirs]}），本次回落默认字体；"
                "把 Resource Han Rounded 等圆体放进 AstrBot 的 data/fonts/ 即可"
            )
        return None

    def _try_render_card(self, result: dict, uid: str, nickname: str = "",
                         avatar_bytes: bytes | None = None, bg_image=None):
        """渲染卡图，失败返回 None（调用方回退纯文本，绝不吞错不回，PRD §7.3）。"""
        if render_card is None:
            return None
        try:
            data_dir = Path(StarTools.get_data_dir(PLUGIN_NAME))
            # 星尘展示（M9）：当日获得（reason='draw' 流水）+ 累计余额；经济关/无库时不画
            sd_today = sd_total = None
            if self._store is not None and self._economy_on():
                try:
                    draw_date = str(result.get("date") or "")
                    if draw_date:
                        sd_today = self._store.day_stardust(uid, draw_date)
                    sd_total = self._store.get_balance(uid)
                except Exception:
                    sd_today = sd_total = None
            return render_card(
                result,
                data_dir / "cards" / uid,
                font_path=self._card_font_path(data_dir),
                extra_font_dirs=self._font_dirs(data_dir),
                width=int(self._cfg("card_width", 1024)),
                height=int(self._cfg("card_height", 1536)),
                signer=str(self._cfg("fortune_signer", "星语者")),
                nickname=nickname,
                avatar_data=avatar_bytes,
                uid=uid,
                bg_image=bg_image,
                theme=str(self._cfg("card_theme", "auto")),
                tarot_label_on_image=bool(self._cfg("tarot_label_on_image", False)),
                stardust_today=sd_today,
                stardust_total=sd_total,
            )
        except Exception:
            logger.error(
                f"[{PLUGIN_NAME}] 卡片渲染失败，回退纯文本\n{traceback.format_exc()}"
            )
            return None

    # ---------- 提示卡（M9）：星尘/商店/榜单/PK/通知/日历 ----------

    def _utility_cards_on(self) -> bool:
        """提示卡跟随出签方式：纯文本模式下所有提示一并回到文字。"""
        return str(self._cfg("output_mode", "图卡")) != "纯文本"

    def _accent_hex(self, uid: str, date: str) -> str:
        """提示卡主题色：优先用当日签的幸运色，没抽签则用默认粉。"""
        row = self._store.get_fortune(uid, date) if self._store is not None else None
        color = ((row or {}).get("payload") or {}).get("lucky_color") or {}
        hexv = str(color.get("hex") or "")
        return hexv if hexv.startswith("#") else "#F6C6D3"

    def _try_utility_card(self, render_fn, *args, **kwargs):
        """渲染提示卡，失败返回 None（调用方回退纯文本）。字体/落款/主题统一注入。"""
        if render_fn is None:
            return None
        try:
            data_dir = Path(StarTools.get_data_dir(PLUGIN_NAME))
            kwargs.setdefault("cards_root", data_dir / "cards" / "_misc")
            kwargs.setdefault("font_path", self._card_font_path(data_dir))
            kwargs.setdefault("extra_font_dirs", self._font_dirs(data_dir))
            kwargs.setdefault("signer", str(self._cfg("fortune_signer", "星语者")))
            kwargs.setdefault("theme", str(self._cfg("card_theme", "auto")))
            return render_fn(*args, **kwargs)
        except Exception:
            logger.error(
                f"[{PLUGIN_NAME}] 提示卡渲染失败，回退纯文本\n{traceback.format_exc()}"
            )
            return None

    # ---------- 萌绘底图联动（F23/D6/D11，契约见 PRD §7.6） ----------

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
                    provider.text_chat(prompt=prompt, system_prompt=fortune.draw_system_hint(lang)),
                    timeout=20,
                )
                text = str(getattr(resp, "completion_text", "") or "").strip()
                if not text and getattr(resp, "result_chain", None) is not None:
                    text = "".join(
                        str(getattr(s, "text", "") or "") for s in resp.result_chain.chain
                    ).strip()
                if text:
                    text = text.strip('`" \n')[:300]
                    if fortune.lang_matches(text, lang):
                        return text, template
                    logger.warning(
                        f"[{PLUGIN_NAME}] 封面图提示词语言不符合配置（{lang}），回退本地模板"
                    )
        except Exception:
            logger.error(
                f"[{PLUGIN_NAME}] 封面图提示词 LLM 生成失败，改用本地模板\n{traceback.format_exc()}"
            )
        return fortune.local_draw_prompt(result, lang, fmt), template

    async def _try_draw_background(self, event: AstrMessageEvent, result: dict,
                                   uid: str, date: str, salt: str):
        """萌绘 comfyui_draw 出底图。返回 (bg_path|None, job|None)。

        契约（萌绘 docs/cross-plugin-draw-guide.md，源码已核实）：
        get_llm_tool_manager().get_func("comfyui_draw") → handler(event, ...)；
        source 必传萌绘约定值「我会永远陪着你」才返回 JSON 路径由我方发图；
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
            # ⚠️ 状态值 skipped_no_anima 是历史落库枚举（draw_jobs 里已有旧记录），
            # 只把界面文案改成「萌绘未安装」，不要改这个值，否则新旧数据要双份映射
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
            width=int(self._cfg("card_width", 700)),
            height=int(self._cfg("card_height", 1200)),
        )
        if job["workflow"]:
            kwargs["workflow"] = job["workflow"]
        # v1.8.6：配置留空时用内置负向提示词兜底（排除男性角色），填写则整体覆盖
        negative = str(self._cfg("draw_negative_prompt", "") or "") or fortune.DEFAULT_DRAW_NEGATIVE
        if negative:
            kwargs["negative_prompt"] = negative
        # 萌绘 v7.7.46+：静默生图（不发过程消息）与提示词透传（跳过其 LLM 处理/翻译）
        if bool(self._cfg("draw_silent", True)):
            kwargs["silent"] = True
        if bool(self._cfg("draw_raw_prompt", True)):
            kwargs["raw_prompt"] = True

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
            result["stardust_total"] = self._store.get_balance(uid)
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
                "今日运势事实清单（仅供你判断运势走向；吉凶、四件套、宜忌等"
                "已展示在卡面上，签文里不要复述）：\n" + fortune.llm_facts(result)
                + "\n请据此写今日签文。"
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
                    font_path=self._card_font_path(data_dir),
                    extra_font_dirs=self._font_dirs(data_dir),
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
            total = payload.get("stardust_total")
            tail = f"累计 {total}，" if total is not None else ""
            lines.append(f"星尘 +{stardust}（{tail}/星尘 查看背包）")
        lines.append("—— 星语者")
        if repeat:
            lines.insert(0, "（今天已经抽过啦，这是你今天的星语签～）")
        return "\n".join(lines)

    # ---------- 指令 ----------

    @filter.command("星语", alias={"运势", "今日运势", "占卜"})
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
                yield event.plain_result("本群已停用星语签，管理员可用 /星语开关 on 开启～")
                return
        tz_name = str(self._cfg("timezone", "Asia/Shanghai"))
        date = fortune.local_today(tz_name)
        salt = str(self._cfg("salt", "moe-star-whisper"))

        # 一日一签（D5）：已有签直接回发（卡文件优先，其次文本），不重算不重绘
        existing = self._store.get_fortune(uid, date)
        if existing is not None:
            payload = existing.get("payload") or {}
            # ⚠️ card_path 是 fortunes 表的独立列，payload JSON 里没有该键
            # （v1.8.7 前的 bug：只读 payload → 当日第二次抽签必然退回纯文本）
            card_path = str(existing.get("card_path") or payload.get("card_path") or "")
            if card_path and Path(card_path).exists():
                # 图与文合并成一条结果链：框架的自动 @ 只跟一条结果走，
                # 分两次 yield 会在群里 @ 两次（v1.9.3 修）
                comps: list = [Image.fromFileSystem(card_path)]
                if str(self._cfg("output_mode", "图卡")) == "图卡+文本":
                    comps.append(Plain("\n" + self._format_result(payload, repeat=True)))
                yield event.chain_result(comps)
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
        group_name = await self._group_name_of(event) if group_id else ""  # 群名快照入库（v1.9.3）

        mode = str(self._cfg("output_mode", "图卡"))
        card_path = None
        bg_fail_hint = ""
        if mode != "纯文本":
            # D11 先绘后卡：萌绘底图（可选）→ 合卡 → 发送；失败静默回退幸运色渐变
            if bool(self._cfg("draw_enabled", False)):
                # 过程提示直发：不在群里 @ 用户（结果那条才 @，见 _send_plain 说明）
                await self._send_plain(event, "🔮 占卜中，星盘铺开……请稍候")
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
            nickname=nickname, avatar=avatar_url, group_id=group_id, group_name=group_name,
            card_path=card_path or "",
            platform=self._sender_platform(event),
        )
        if not saved:  # 并发撞车：读回已存的那份
            existing = self._store.get_fortune(uid, date)
            payload = (existing or {}).get("payload") or result
            card_path = str(
                (existing or {}).get("card_path") or payload.get("card_path") or card_path or ""
            )
            if card_path and Path(card_path).exists():
                yield event.chain_result([Image.fromFileSystem(card_path)])
            else:
                yield event.plain_result(self._format_result(payload))
            return

        # 结果合并成一条链：图 + 文本 + 失败提示一起发，群里只 @ 一次（v1.9.3）
        comps: list = []
        if card_path:
            comps.append(Image.fromFileSystem(card_path))
            if mode == "图卡+文本":
                comps.append(Plain("\n" + self._format_result(result)))
        else:
            comps.append(Plain(self._format_result(result)))
        if bg_fail_hint:
            comps.append(Plain("\n" + bg_fail_hint))
        yield event.chain_result(comps)

    @filter.command("星语榜", alias={"运势榜"})
    async def rank_cmd(self, event: AstrMessageEvent):
        """群内幸运指数排行（/星语榜 日|周，默认日；榜单卡）

        口径（v1.9.4）：**本群成员**——用户今天可能在别的群抽的签，只要他人在本群
        就该上榜，所以按群成员筛而不是按「在本群抽签」筛；群成员列表取不到时回落
        到「本群抽签」口径，并在标题里如实标注，绝不假装。
        """
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
        members = await self._group_member_ids(event, gid)

        if span == "周":
            d = datetime.strptime(today, "%Y-%m-%d").date()
            monday = (d - timedelta(days=d.weekday())).strftime("%Y-%m-%d")
            if members is not None:
                src = self._store.list_range_avg_all(monday, 300)
                rows_src = [r for r in src if str(r.get("user_id") or "") in members][:10]
                scope = f"本群成员 {len(members)} 人"
            else:
                rows_src = self._store.list_group_range_avg(gid, monday)
                scope = "本群抽签"
            title = f"本周星语榜（{monday[5:]} 起）"
            rows = [
                (i, r.get("nickname") or "旅人", f"{r['avg_score']:.0f}",
                 f"均分 · {r['days']} 天")
                for i, r in enumerate(rows_src, 1)
            ]
        else:
            if members is not None:
                src = self._store.list_day(today)
                rows_src = [r for r in src if str(r.get("user_id") or "") in members][:10]
                scope = f"本群成员 {len(members)} 人"
            else:
                rows_src = self._store.list_group_day(gid, today)
                scope = "本群抽签"
            title = "今日星语榜"
            rows = [
                (i, r.get("nickname") or "旅人", str(r["score"]), "")
                for i, r in enumerate(rows_src, 1)
            ]
        empty_text = ("本群成员都还没抽签，快来当第一个！"
                      if members is not None else "本群还没有人抽签，快来当第一个！")
        card_path = None
        if self._utility_cards_on():
            card_path = self._try_utility_card(
                render_rank_card, title=title, rows=rows, date_str=today,
                subtitle=f"萌萌星语 · {scope}",
                empty_text=empty_text,
                # file_key 带口径标记：同一天换了口径不会复用旧卡（v1.9.4）
                file_key=f"{span}_{gid}_{today}_{'mem' if members is not None else 'grp'}",
            )
        if card_path:
            yield event.image_result(card_path)
            return
        lines = ["🌙 萌萌星语", f"—— {title}（{scope}）——"]
        if rows:
            for i, r in enumerate(rows, 1):
                rank, name, main_text, sub_text = r
                lines.append(
                    f"{i}. {name} · {main_text}" + (f"（{sub_text}）" if sub_text else "")
                )
        else:
            lines.append(empty_text)
        yield event.plain_result("\n".join(lines))

    @filter.command("星语PK", alias={"星语pk", "运势PK", "运势pk"})
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
            yield event.plain_result("你今天还没抽签，先 /星语 一下吧～")
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
            winner = "left"
        elif m_score < t_score:
            line = fortune.pick_text(seed, "pk", pk["lose"])
            verdict = f"{t_name} 胜！"
            winner = "right"
        else:
            line = fortune.pick_text(seed, "pk", pk["tie"])
            verdict = "平局！"
            winner = "tie"

        def _hex_of(row):
            return str(((row or {}).get("payload") or {}).get("lucky_color") or {}).get("hex") or ""

        card_path = None
        if self._utility_cards_on():
            # 主题色用胜者（平局用发起人）的当日幸运色
            accent = _hex_of(mine if winner != "right" else theirs) or "#F6C6D3"
            card_path = self._try_utility_card(
                render_pk_card,
                m_name, m_score, t_name, t_score, verdict, line,
                winner=winner, accent_hex=accent, file_key=f"{uid}_{today}",
            )
        if card_path:
            yield event.image_result(card_path)
            return
        yield event.plain_result(
            "—— 星语 PK ——\n"
            f"{m_name} {m_score} vs {t_name} {t_score}\n"
            f"{verdict}{line}"
        )

    @filter.command("星语开关", alias={"运势开关"})
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def switch_cmd(self, event: AstrMessageEvent):
        """群内启停星语签（/星语开关 on|off，仅 AstrBot 管理员）"""
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
                yield event.plain_result("已停用本群星语签（/星语开关 on 可重新开启）")
            except Exception:
                yield event.plain_result("停用失败：配置保存出错，请看日志～")
        else:
            state = "停用" if gid in self._disabled_groups() else "开启"
            yield event.plain_result(f"本群星语签当前：{state}（/星语开关 on|off）")

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
        card_path = None
        if self._utility_cards_on():
            card_path = self._try_utility_card(
                render_notice_card,
                title="生日绑定成功",
                lines=[
                    f"生日：{mmdd} · {cons}",
                    extra,
                    "生日当天会收到必中大吉的生日签",
                ],
                subtitle="萌萌星语 · 星座档案", accent_hex=self._accent_hex(uid, fortune.local_today(str(self._cfg("timezone", "Asia/Shanghai")))),
                file_key=f"{uid}_bind",
            )
        if card_path:
            yield event.image_result(card_path)
            return
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
        today_line = (
            f"今日：{row['grade']}（{row['score']}）" if row is not None else "今日：还没抽签（/星语 抽一支）"
        )
        if (prof.get("birthday") or "") == today[5:]:
            today_line += " ｜ 🎂 今天是生日！"
        card_path = None
        if self._utility_cards_on():
            lines = [f"星座：{prof['constellation']}", today_line]
            if (prof.get("birthday") or "") == today[5:]:
                lines.append("今天是生日！生日签已就位")
            card_path = self._try_utility_card(
                render_notice_card,
                title="星座查询",
                lines=lines,
                subtitle="萌萌星语 · 星座档案",
                accent_hex=self._accent_hex(target_id, today),
                file_key=f"{target_id}_const",
            )
        if card_path:
            yield event.image_result(card_path)
            return
        yield event.plain_result(line + " ｜ " + today_line)

    # ---------- 运势日历（M9） ----------

    @filter.command("星语日历", alias={"运势日历", "运势月历"})
    async def calendar_cmd(self, event: AstrMessageEvent):
        """当月运势日历：每日吉凶与分数，未占卜的日子以小点标记"""
        if self._store is None:
            yield event.plain_result("星语者还没整理好星盘，稍后再试～")
            return
        uid = str(event.get_sender_id() or "").strip()
        if not uid:
            yield event.plain_result("星语者没看清你是谁，稍后再试一次～")
            return
        tz_name = str(self._cfg("timezone", "Asia/Shanghai"))
        today = fortune.local_today(tz_name)
        arg = str(event.message_str or "").replace(" ", "")
        for w in ("运势日历", "星语日历", "运势月历", "/"):
            arg = arg.replace(w, "")
        year, month = int(today[:4]), int(today[5:7])
        m = re.search(r"(\d{4})[-./年](\d{1,2})", arg)
        if m:
            year, month = int(m.group(1)), int(m.group(2))
        else:
            m2 = re.search(r"(\d{1,2})", arg)
            if m2:
                month = int(m2.group(1))
        if not (1 <= month <= 12) or not (2000 <= year <= 2100):
            yield event.plain_result(
                "格式：/星语日历 [月份]——/星语日历、/星语日历 8、/星语日历 2026-08"
            )
            return
        month_prefix = f"{year:04d}-{month:02d}"
        rows = self._store.month_fortunes(uid, month_prefix)
        days = {r["date"]: (r["grade"], int(r["score"])) for r in rows}
        nickname = self._store.last_nickname(uid) or "旅行者"
        stats = {
            "drawn": len(rows),
            "daji": sum(1 for g, _s in days.values() if g == "大吉"),
            "avg": round(sum(s for _g, s in days.values()) / len(rows)) if rows else 0,
            "stardust": self._store.get_balance(uid) if self._economy_on() else None,
        }
        card_path = None
        if self._utility_cards_on():
            card_path = self._try_utility_card(
                render_calendar_card,
                year, month, days,
                file_key=f"{uid}_{month_prefix}",
                today=today, nickname=nickname,
                accent_hex=self._accent_hex(uid, today),
                grade_colors=lexicon.load_lexicon().get("grade_colors") or {},
                stats=stats,
            )
        if card_path:
            yield event.image_result(card_path)
            return
        lines = [f"🌙 萌萌星语 · {year} 年 {month} 月运势日历"]
        for r in rows:
            lines.append(f"{r['date'][8:]} 日：{r['grade']}（{r['score']}）")
        if not rows:
            lines.append("本月还没有占卜记录，/星语 抽一支吧～")
        if stats["stardust"] is not None:
            lines.append(f"累计星尘 {stats['stardust']}")
        yield event.plain_result("\n".join(lines))

    # ---------- 道具经济指令（M7/D8） ----------

    @filter.command("星尘", alias={"运势背包"})
    async def wallet_cmd(self, event: AstrMessageEvent):
        """查星尘余额与道具背包（星尘钱包卡）"""
        if self._store is None or not self._economy_on():
            yield event.plain_result("道具经济未开放～")
            return
        uid = str(event.get_sender_id() or "").strip()
        tz_name = str(self._cfg("timezone", "Asia/Shanghai"))
        today = fortune.local_today(tz_name)
        balance = self._store.get_balance(uid)
        items = [
            (name, self._store.get_item(uid, item_id))
            for item_id, (name, _desc) in ITEM_DEFS.items()
        ]
        card_path = None
        if self._utility_cards_on():
            card_path = self._try_utility_card(
                render_wallet_card,
                nickname=event.get_sender_name() or "旅行者",
                balance=balance, items=items,
                today_gain=max(0, self._store.day_stardust(uid, today)),
                uid=uid, avatar_data=await self._fetch_avatar_bytes(uid),
                date_str=today, accent_hex=self._accent_hex(uid, today),
                file_key=f"{uid}_{today}",
            )
        if card_path:
            yield event.image_result(card_path)
            return
        lines = [f"✨ 星尘余额：{balance}", "—— 背包 ——"]
        for item_id, (name, _desc) in ITEM_DEFS.items():
            count = self._store.get_item(uid, item_id)
            lines.append(f"{name} ×{count}")
        lines.append("用 /星语商店 看看有什么好东西～")
        yield event.plain_result("\n".join(lines))

    @filter.command("星语商店", alias={"运势商店"})
    async def shop_cmd(self, event: AstrMessageEvent):
        """道具与价格一览（商店卡）"""
        if self._store is None or not self._economy_on():
            yield event.plain_result("道具经济未开放～")
            return
        uid = str(event.get_sender_id() or "").strip()
        tz_name = str(self._cfg("timezone", "Asia/Shanghai"))
        today = fortune.local_today(tz_name)
        entries = [
            (name, self._price_of(item_id), desc, self._store.get_item(uid, item_id))
            for item_id, (name, desc) in ITEM_DEFS.items()
        ]
        card_path = None
        if self._utility_cards_on():
            card_path = self._try_utility_card(
                render_shop_card,
                nickname=event.get_sender_name() or "旅行者",
                entries=entries, uid=uid,
                avatar_data=await self._fetch_avatar_bytes(uid),
                accent_hex=self._accent_hex(uid, today),
                file_key=f"{uid}_{today}",
            )
        if card_path:
            yield event.image_result(card_path)
            return
        lines = ["🛒 萌萌星语 · 道具商店", ""]
        for name, price, desc, held in entries:
            lines.append(f"【{name}】{price} 星尘\n　{desc}\n　持有 ×{held}")
        lines.append("\n购买：/星语购买 <名称> [数量]")
        yield event.plain_result("\n".join(lines))

    @filter.command("星语购买", alias={"运势购买"})
    async def buy_cmd(self, event: AstrMessageEvent):
        """购买道具：/星语购买 <名称> [数量]"""
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
            yield event.plain_result("要买什么？/星语商店 看看货架～")
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
        tz_name = str(self._cfg("timezone", "Asia/Shanghai"))
        today = fortune.local_today(tz_name)
        card_path = None
        if self._utility_cards_on():
            card_path = self._try_utility_card(
                render_notice_card,
                title="购买成功",
                lines=[
                    f"{name} ×{count}",
                    f"花费 {price} 星尘，余额 {balance - price}",
                    f"当前持有 ×{new_count}",
                ],
                subtitle="萌萌星语 · 道具经济", accent_hex=self._accent_hex(uid, today),
                file_key=f"{uid}_{today}_buy",
                footer="使用：/星语使用 <名称>",
            )
        if card_path:
            yield event.image_result(card_path)
            return
        yield event.plain_result(
            f"购买成功：{name} ×{count}（-{price} 星尘）\n当前持有 ×{new_count}，余额 {balance - price}。"
        )

    @filter.command("星语使用", alias={"运势使用"})
    async def use_cmd(self, event: AstrMessageEvent):
        """使用道具：/星语使用 <换签卡|厄运护身符|幸运香烛>"""
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
                yield event.plain_result("今天还没抽签，不用换——先 /星语 抽一支吧～")
                return
            payload = existing.get("payload") or {}
            used = int(payload.get("reroll_count", 0) or 0)
            if used >= 1:
                yield event.plain_result("今天已经换过一次签了，命运不接受讨价还价～")
                return
            if self._store.get_item(uid, "reroll") < 1:
                yield event.plain_result("背包里没有换签卡（/星语商店 有售）。")
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
                yield event.plain_result(f"背包里没有{ITEM_DEFS[item_id][0]}（/星语商店 有售）。")
                return
            self._store.add_item(uid, item_id, -1)
            self._store.add_ledger(uid, 0, f"use:{item_id}", date)
            card_path = None
            if self._utility_cards_on():
                card_path = self._try_utility_card(
                    render_notice_card,
                    title="道具已使用",
                    lines=[
                        ITEM_DEFS[item_id][0],
                        "佩戴成功，今天抽签时生效 ✨" if item_id == "amulet"
                        else "已点燃，今天抽签时幸运指数 +8",
                        "抽签：/星语",
                    ],
                    subtitle="萌萌星语 · 道具经济", accent_hex=self._accent_hex(uid, date),
                    file_key=f"{uid}_{date}_use",
                )
            if card_path:
                yield event.image_result(card_path)
                return
            yield event.plain_result(f"已使用{ITEM_DEFS[item_id][0]}：今天抽签时生效 ✨")
            return

        yield event.plain_result("这个道具不需要手动使用（见 /星语商店 说明）。")

    @filter.command("星语补签", alias={"运势补签"})
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
            yield event.plain_result("还没抽过签就谈不上补签——先 /星语 抽第一支吧～")
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
            yield event.plain_result("背包里没有连签保护卡（/星语商店 有售）。")
            return
        self._store.add_item(uid, "streak_guard", -1)
        result = self._roll_daily(uid, prev, salt, profile)
        nickname = profile.get("nickname") or self._store.last_nickname(uid) or "旅行者"
        card_path = None
        if str(self._cfg("output_mode", "图卡")) != "纯文本":
            card_path = self._try_render_card(result, uid, nickname=nickname)
        self._store.save_fortune(
            uid, prev, result, nickname=nickname,
            avatar=profile.get("avatar") or "", platform=self._sender_platform(event),
            card_path=card_path or "",
        )
        if card_path:
            yield event.image_result(card_path)
        yield event.plain_result(
            f"补签成功（{prev}）✨ 连签恢复到 {result['streak']} 天"
        )

    @filter.command("星语发放", alias={"运势发放"})
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def grant_cmd(self, event: AstrMessageEvent):
        """手动调整星尘：/星语发放 @用户 <±n>（必走流水）"""
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
            yield event.plain_result("格式：/星语发放 @用户 <±n>")
            return
        delta = int(m.group(1))
        if delta == 0:
            yield event.plain_result("0 颗星尘？星星当你是空气。")
            return
        self._store.add_ledger(target, delta, "admin")
        yield event.plain_result(
            f"已{'发放' if delta > 0 else '扣除'} {abs(delta)} 颗星尘，当前余额 {self._store.get_balance(target)}。"
        )

    @filter.command("星语帮助", alias={"运势帮助"})
    async def help_cmd(self, event: AstrMessageEvent):
        """查看萌萌星语的全部指令（帮助图）"""
        data_dir = Path(StarTools.get_data_dir(PLUGIN_NAME))
        font_path = self._cfg("card_font_path", "") or None
        extra_dirs = [data_dir / "fonts", Path("data/fonts")]
        signer = str(self._cfg("fortune_signer", "星语者"))
        groups = [
            ("占卜", [
                ("/星语", "抽当日专属星语签（别名 /运势 /今日运势 /占卜）"),
                ("/星语日历 [月份]", "当月运势日历：每日吉凶与分数"),
                ("/星语帮助", "查看本帮助图"),
            ]),
            ("群内排行", [
                ("/星语榜 [日|周]", "群成员幸运指数排行"),
                ("/星语PK @某人", "当日幸运指数对决"),
                ("/星语开关 on|off", "群级启停（管理员）"),
            ]),
            ("星座", [
                ("/星语绑定 <MM-DD>", "绑定生日，解锁星座与生日彩蛋"),
                ("/星座 [@某人]", "查看星座与今日吉凶"),
            ]),
            ("道具经济", [
                ("/星尘", "星尘余额与背包"),
                ("/星语商店", "道具与价格"),
                ("/星语购买 <名称> [数量]", "购买道具"),
                ("/星语使用 <名称>", "使用换签卡/护身符/香烛"),
                ("/星语补签", "断签 3 天内补回昨天"),
                ("/星语发放 @用户 <±n>", "手动调整星尘（管理员）"),
            ]),
        ]
        if render_help_card is not None:
            try:
                path = render_help_card(
                    groups, data_dir / "help",
                    font_path=font_path, extra_font_dirs=extra_dirs, signer=signer,
                    theme=str(self._cfg("card_theme", "auto")),
                )
                yield event.image_result(path)
                return
            except Exception:
                logger.error(f"[{PLUGIN_NAME}] 帮助图渲染失败，回退文本\n{traceback.format_exc()}")
        lines = ["🌙 萌萌星语 · 指令帮助"]
        for title, rows in groups:
            lines.append(f"—— {title} ——")
            lines += [f"{cmd}　{desc}" for cmd, desc in rows]
        yield event.plain_result("\n".join(lines))
