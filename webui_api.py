# -*- coding: utf-8 -*-
"""调试面板后端（AstrBot 插件 Page 的桥接 API，M7.5）。

路由前缀 ``/astrbot_plugin_moe_star_whisper``，前端经
``window.AstrBotPluginPage.apiGet/apiPost`` 调用（Dashboard 登录墙内，
沿 user_gateway 控制台同一套访问口径：仅管理员账号使用）。

返回信封遵循 AstrBot 桥接约定（Dashboard 会剥一层 data、status=error 抛错）：
  成功 → {"status": "ok", "data": ...}
  失败 → {"status": "error", "message": "..."}
"""

from __future__ import annotations

import json
import re
import traceback
from datetime import timedelta
from pathlib import Path

try:  # AstrBot 运行期
    from astrbot.api import logger
except Exception:  # pragma: no cover - 本地平铺调试（无 astrbot 运行时）
    import logging

    logger = logging.getLogger("moe_star_whisper")

try:  # quart 是 AstrBot 的运行期依赖
    from quart import request
except Exception:  # pragma: no cover
    request = None  # type: ignore

try:  # 与 main.py 同样的双形态导入（包内正常加载 / 平铺调试）
    from . import fortune
except ImportError:  # pragma: no cover - 本地平铺调试
    import fortune  # type: ignore

ROUTE_PREFIX = "/astrbot_plugin_moe_star_whisper"
PLUGIN_NAME = "astrbot_plugin_moe_star_whisper"
SCHEMA_FILE = "_conf_schema.json"


def ok(data=None) -> dict:
    return {"status": "ok", "data": data if data is not None else {}}


def err(message: str) -> dict:
    return {"status": "error", "message": str(message)}


def _q(name: str, default=None):
    if request is None:
        return default
    try:
        return request.args.get(name, default)
    except Exception:
        return default


async def _body() -> dict:
    if request is None:
        return {}
    try:
        data = await request.get_json(silent=True)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


async def _uid_of() -> str:
    """uid：query 优先，body 兜底（GET/POST 双通道）。"""
    uid = str(_q("uid", "") or "").strip()
    if uid:
        return uid
    body = await _body()
    return str(body.get("uid", "") or "").strip()


def _today(plugin) -> str:
    return fortune.local_today(str(plugin._cfg("timezone", "Asia/Shanghai")))


def _salt(plugin) -> str:
    return str(plugin._cfg("salt", "moe-star-whisper"))


def _fortune_summary(row) -> dict:
    payload = (row or {}).get("payload") or {}
    # card_path 权威来源是 fortunes 行内的独立列；payload 里的同名键仅作旧数据兜底
    card_path = str((row or {}).get("card_path") or payload.get("card_path") or "")
    return {
        "grade": payload.get("grade_display") or payload.get("grade", "？"),
        "score": payload.get("score"),
        "streak": payload.get("streak"),
        "sign_text": payload.get("sign_text", ""),
        "signer": payload.get("lucky_item"),
        "lucky_color": (payload.get("lucky_color") or {}).get("name", ""),
        "card_path": card_path,
        "has_card": bool(card_path) and Path(card_path).exists(),
        "reroll_count": int(payload.get("reroll_count", 0) or 0),
        "llm_used": bool(payload.get("llm_used")),
        "llm_note": str(payload.get("llm_note") or ""),
    }


def _last_ok_bg(plugin, uid: str, date: str):
    """当日 draw_jobs 里最近一次成功的 AI 底图（重绘/重抽复用）。"""
    try:
        for job in reversed(plugin._store.get_draw_jobs(uid, date)):
            p = job.get("image_path") or ""
            if job.get("status") == "ok" and p and Path(p).exists():
                return p
    except Exception:
        pass
    return None


def _remove_card(plugin, row) -> None:
    card_file = str(
        (row or {}).get("card_path")
        or ((row or {}).get("payload") or {}).get("card_path")
        or ""
    )
    if card_file and Path(card_file).exists():
        try:
            Path(card_file).unlink()
        except Exception:
            pass


# ---------------------------------------------------------------------- #
# handlers：签名 fn(plugin) -> dict（经 _bind 包装，异常转 err 信封）
# ---------------------------------------------------------------------- #

def _debug_state_core(store, cfg_get, uid: str, date: str) -> dict:
    """state 业务核心（参数齐备后的纯逻辑，便于脱离 quart 直测）。"""
    row = store.get_fortune(uid, date)
    profile = store.get_profile(uid) or {}
    jobs = []
    for job in store.get_draw_jobs(uid, date)[-10:]:
        jobs.append({
            "id": job.get("id"),
            "status": job.get("status"),
            "workflow": job.get("workflow") or "",
            "error": (job.get("error") or "")[:120],
            "duration_ms": job.get("duration_ms"),
            "image_path": job.get("image_path") or "",
        })
    return ok({
        "uid": uid,
        "date": date,
        "fortune": _fortune_summary(row) if row else None,
        "profile": {
            "constellation": profile.get("constellation") or "",
            "birthday": profile.get("birthday") or "",
            "streak": profile.get("streak") or 0,
            "max_streak": profile.get("max_streak") or 0,
            "last_draw_date": profile.get("last_draw_date") or "",
        },
        "balance": store.get_balance(uid),
        "items": {item_id: store.get_item(uid, item_id) for item_id in
                  ("reroll", "amulet", "streak_guard", "candle")},
        "draw_jobs": jobs,
        "config": {key: cfg_get(key, "") for key in
                   ("draw_enabled", "llm_enabled", "output_mode", "card_theme",
                    "economy_enabled", "daily_push_enabled", "daily_push_time",
                    "draw_workflow", "draw_prompt_lang", "draw_prompt_format")},
    })


def _debug_reset_core(store, uid: str, date: str) -> dict:
    row = store.get_fortune(uid, date)
    if row is None:
        return err("该用户今天还没有签记录")
    _remove_card(None, row)
    store.delete_fortune(uid, date)
    return ok({"deleted": True, "uid": uid, "date": date,
               "note": "已清除；下次抽签会自动换一颗种子，得到新的运势"})


async def h_debug_state(plugin) -> dict:
    """调试面板状态：某 uid 的今日签/档案/背包/绘图任务/关键配置。"""
    if plugin._store is None:
        return err("插件未初始化完成")
    uid = await _uid_of()
    if not uid:
        return err("缺少 uid（要调试的 QQ 号）")
    plugin._store.record_debug_uid(uid)
    state = _debug_state_core(plugin._store, plugin._cfg, uid, _today(plugin))
    if state.get("status") == "ok":
        state["data"]["recent_uids"] = plugin._store.list_debug_uids()
    return state


async def h_debug_history(plugin) -> dict:
    """最近调试过的 QQ 号（面板历史标签）。"""
    if plugin._store is None:
        return err("插件未初始化完成")
    return ok({"recent_uids": plugin._store.list_debug_uids()})


async def h_debug_redraw(plugin) -> dict:
    """重抽：换种子重算运势 + LLM 签文 + 重渲染卡（复用当日成功 AI 底图）。

    说明：WebUI 触发没有聊天事件，无法新绘 anima 底图；底图复用当日
    draw_jobs 的成功记录或默认幸运色渐变。AI 底图新绘请在聊天内抽签触发。
    """
    if plugin._store is None:
        return err("插件未初始化完成")
    uid = await _uid_of()
    if not uid:
        return err("缺少 uid")
    plugin._store.record_debug_uid(uid)
    date = _today(plugin)
    existing = plugin._store.get_fortune(uid, date)
    if existing is None:
        return err("该用户今天还没有签记录，请先在聊天里 /运势 抽一支")
    payload = existing.get("payload") or {}
    result = plugin._roll_daily(
        uid, date, _salt(plugin), plugin._store.get_profile(uid) or {},
        streak=int(payload.get("streak") or 1),
    )
    await plugin._try_llm_sign(result)
    bg = _last_ok_bg(plugin, uid, date)
    avatar_bytes = await plugin._fetch_avatar_bytes(uid)
    card_path = plugin._try_render_card(
        result, uid,
        nickname=existing.get("nickname") or "", avatar_bytes=avatar_bytes,
        bg_image=bg,
    )
    plugin._store.update_fortune_payload(uid, date, result, card_path or "")
    return ok({
        "fortune": _fortune_summary({"payload": result, "nickname": existing.get("nickname"),
                                     "card_path": card_path or ""}),
        "card_path": card_path or "",
        "ai_bg_reused": bool(bg),
        "note": "重抽不含新绘 AI 底图（WebUI 无聊天事件），底图为复用或默认渐变",
    })


async def h_debug_rerender(plugin) -> dict:
    """重绘：不重抽，按已存 payload 重渲染卡面（改 card.py 样式后看效果）。"""
    if plugin._store is None:
        return err("插件未初始化完成")
    uid = await _uid_of()
    if not uid:
        return err("缺少 uid")
    plugin._store.record_debug_uid(uid)
    date = _today(plugin)
    row = plugin._store.get_fortune(uid, date)
    if row is None:
        return err("该用户今天还没有签记录")
    payload = row.get("payload") or {}
    bg = _last_ok_bg(plugin, uid, date)
    avatar_bytes = await plugin._fetch_avatar_bytes(uid)
    card_path = plugin._try_render_card(
        payload, uid,
        nickname=row.get("nickname") or "", avatar_bytes=avatar_bytes,
        bg_image=bg,
    )
    if not card_path:
        return err("重绘失败（渲染抛错），详情见 AstrBot 日志")
    plugin._store.update_fortune_payload(uid, date, payload, card_path)
    return ok({"fortune": _fortune_summary(row), "card_path": card_path, "ai_bg_reused": bool(bg)})


async def h_debug_reset(plugin) -> dict:
    """重置：删除某 uid 的今日签记录与卡文件（星尘会随重抽再次发放，仅测试用）。"""
    if plugin._store is None:
        return err("插件未初始化完成")
    uid = await _uid_of()
    if not uid:
        return err("缺少 uid")
    plugin._store.record_debug_uid(uid)
    return _debug_reset_core(plugin._store, uid, _today(plugin))


# ---------------------------------------------------------------------- #
# 控制台（v1.9.0）：总览 / 抽签记录 / 数据统计 / 用户查询 / 配置读写
#
# 口径与前缀：
#   * 路由仍挂在 ROUTE_PREFIX 下（前端 apiGet 传「不带前导斜杠、不带插件名」的
#     端点，如 "overview"、"config"，由 Dashboard 拼 /api/v1/plugins/extensions/…）。
#   * 「近 N 天」区间一律按插件配置时区推导，起始日含今天。
#   * 聚合口径写在 store.py 的「统计与面板查询」一节。
# ---------------------------------------------------------------------- #

GRADE_ORDER = ("大吉", "吉", "中吉", "小吉", "凶", "大凶")


def _plugin_dir() -> Path:
    return Path(__file__).resolve().parent


def _plugin_version() -> str:
    """metadata.yaml 的 version（唯一版本来源）；读取失败返回空串。"""
    try:
        text = (_plugin_dir() / "metadata.yaml").read_text(encoding="utf-8")
    except Exception:
        return ""
    m = re.search(r"(?m)^\s*version:\s*v?([0-9][^\s#]*)", text)
    return m.group(1).strip() if m else ""


def _load_schema() -> dict:
    """插件自己的 _conf_schema.json —— 配置页字段与类型的唯一来源。"""
    try:
        data = json.loads((_plugin_dir() / SCHEMA_FILE).read_text(encoding="utf-8"))
    except Exception:
        logger.warning(f"[{PLUGIN_NAME}] 读取 {SCHEMA_FILE} 失败，配置页不可用")
        return {}
    return data if isinstance(data, dict) else {}


def _days_from(tz_name: str, days: int) -> str:
    """近 N 天区间的起始日期（含今天）。"""
    d = fortune.now_in(tz_name)
    return (d - timedelta(days=max(0, int(days) - 1))).strftime("%Y-%m-%d")


def _tz_of(plugin) -> str:
    return str(plugin._cfg("timezone", "Asia/Shanghai"))


# ---------- 总览 ----------

def _overview_core(store, cfg_get, tz_name: str, days: int = 14) -> dict:
    """总览核心（参数齐备后的纯逻辑，便于脱离 quart 直测）。"""
    today = fortune.local_today(tz_name)
    date_from = _days_from(tz_name, days)
    return ok({
        "version": _plugin_version(),
        "today": today,
        "range_from": date_from,
        "totals": store.stats_totals(),
        "day": store.stats_day(today),
        "trend": store.stats_trend(date_from),
        "grades": store.stats_grades(date_from),
        "recent": store.list_records(page=1, size=10)["rows"],
        "recent_users": store.recent_users(12),
        "counts": store.count_all(),
        "switches": {
            "timezone": cfg_get("timezone", ""),
            "output_mode": cfg_get("output_mode", ""),
            "economy_enabled": cfg_get("economy_enabled", False),
            "llm_enabled": cfg_get("llm_enabled", False),
            "draw_enabled": cfg_get("draw_enabled", False),
            "daily_push_enabled": cfg_get("daily_push_enabled", False),
            "daily_push_time": cfg_get("daily_push_time", ""),
            "draw_workflow": cfg_get("draw_workflow", ""),
        },
    })


async def h_overview(plugin) -> dict:
    if plugin._store is None:
        return err("插件未初始化完成")
    try:
        days = int(_q("days", 14) or 14)
    except (TypeError, ValueError):
        days = 14
    return _overview_core(plugin._store, plugin._cfg, _tz_of(plugin), max(3, min(days, 180)))


# ---------- 抽签记录 ----------

def _records_core(store, tz_name: str, page=1, size=20, days=0, date_from="",
                  date_to="", grade="", group_id="", keyword="") -> dict:
    try:
        page = max(1, int(page))
    except (TypeError, ValueError):
        page = 1
    try:
        size = max(1, min(int(size), 100))
    except (TypeError, ValueError):
        size = 20
    if days and not date_from:
        date_from = _days_from(tz_name, int(days))
    data = store.list_records(
        page=page, size=size, date_from=str(date_from or ""), date_to=str(date_to or ""),
        grade=str(grade or ""), group_id=str(group_id or ""), keyword=str(keyword or ""),
    )
    return ok({
        "records": data,
        "groups": store.list_groups(200),
        "grades": list(GRADE_ORDER),
        "filters": {
            "days": int(days or 0), "date_from": date_from, "date_to": date_to,
            "grade": grade, "group_id": group_id, "keyword": keyword,
        },
        "today": fortune.local_today(tz_name),
    })


async def h_records(plugin) -> dict:
    if plugin._store is None:
        return err("插件未初始化完成")
    days = _q("days", "0") or "0"
    try:
        days_int = int(days)
    except (TypeError, ValueError):
        days_int = 0
    return _records_core(
        plugin._store, _tz_of(plugin),
        page=_q("page", 1), size=_q("size", 20), days=days_int,
        date_from=_q("date_from", ""), date_to=_q("date_to", ""),
        grade=_q("grade", ""), group_id=_q("group_id", ""), keyword=_q("q", ""),
    )


async def h_users(plugin) -> dict:
    """最近抽签用户（控制台快捷入口）。"""
    if plugin._store is None:
        return err("插件未初始化完成")
    return ok({"users": plugin._store.recent_users(12)})


# ---------- 数据统计 ----------

def _stats_core(store, tz_name: str, days: int = 30) -> dict:
    date_from = _days_from(tz_name, days)
    payload = store.stats_payload(date_from)
    return ok({
        "days": int(days),
        "range_from": date_from,
        "range_to": fortune.local_today(tz_name),
        "trend": store.stats_trend(date_from),
        "grades": store.stats_grades(date_from),
        "grades_all": store.stats_grades(""),
        "grade_daily": store.stats_grade_daily(date_from),
        "hours": store.stats_hours(date_from),
        "groups": store.stats_groups(date_from, 10),
        "jobs": store.stats_jobs(date_from),
        "ledger": store.stats_ledger(date_from),
        "dims": payload["dims"],
        "dims_sampled": payload["sampled"],
        "lucky_items": payload["items"],
        "lucky_colors": payload["colors"],
        "constellations": payload["constellations"],
        "streaks": payload["streaks"],
    })


async def h_stats(plugin) -> dict:
    if plugin._store is None:
        return err("插件未初始化完成")
    try:
        days = int(_q("days", 30) or 30)
    except (TypeError, ValueError):
        days = 30
    return _stats_core(plugin._store, _tz_of(plugin), max(1, min(days, 365)))


# ---------- 用户查询 ----------

def _profile_summary(profile: dict) -> dict:
    return {
        "constellation": profile.get("constellation") or "",
        "birthday": profile.get("birthday") or "",
        "streak": int(profile.get("streak") or 0),
        "max_streak": int(profile.get("max_streak") or 0),
        "last_draw_date": profile.get("last_draw_date") or "",
        "nickname": profile.get("nickname") or "",
        "seed_nonce": int(profile.get("seed_nonce") or 0),
    }


def _user_core(store, cfg_get, tz_name: str, uid: str, months: int = 3) -> dict:
    today = fortune.local_today(tz_name)
    row = store.get_fortune(uid, today)
    profile = store.get_profile(uid) or {}

    months = max(1, min(int(months), 12))
    prefixes: list[str] = []
    cursor = fortune.now_in(tz_name)
    for _ in range(months):
        prefixes.append(cursor.strftime("%Y-%m"))
        cursor = cursor.replace(day=1) - timedelta(days=1)
    calendar: list[dict] = []
    for pfx in reversed(prefixes):
        calendar.extend(store.month_fortunes(uid, pfx))

    jobs = []
    for job in store.get_draw_jobs(uid, today)[-10:]:
        jobs.append({
            "id": job.get("id"),
            "status": job.get("status"),
            "workflow": job.get("workflow") or "",
            "error": (job.get("error") or "")[:120],
            "duration_ms": job.get("duration_ms"),
            "image_path": job.get("image_path") or "",
        })
    return ok({
        "uid": uid,
        "today": today,
        "nickname": row.get("nickname") if row else store.last_nickname(uid),
        "fortune": _fortune_summary(row) if row else None,
        "profile": _profile_summary(profile),
        "balance": store.get_balance(uid),
        "items": {item_id: store.get_item(uid, item_id) for item_id in
                  ("reroll", "amulet", "streak_guard", "candle")},
        "draw_jobs": jobs,
        "history": store.user_history(uid, 60),
        "ledger": store.user_ledger(uid, 30),
        "calendar": calendar,
        "config": {key: cfg_get(key, "") for key in
                   ("draw_enabled", "llm_enabled", "output_mode",
                    "economy_enabled", "daily_push_enabled")},
    })


async def h_user(plugin) -> dict:
    if plugin._store is None:
        return err("插件未初始化完成")
    uid = await _uid_of()
    if not uid:
        return err("缺少 uid（要查询的 QQ 号）")
    plugin._store.record_debug_uid(uid)
    months = _q("months", "3") or "3"
    try:
        months_int = int(months)
    except (TypeError, ValueError):
        months_int = 3
    state = _user_core(plugin._store, plugin._cfg, _tz_of(plugin), uid, months_int)
    if state.get("status") == "ok":
        state["data"]["recent_uids"] = plugin._store.list_debug_uids()
    return state


# ---------- 配置读写 ----------

# 不可信值一律丢弃的哨兵：绝不像 box v0.12.7 那样把 None 变成 False/[]（那会一次保存清空配置）
_SKIP = object()


def _config_values(plugin, schema: dict) -> dict:
    """按 schema 键取当前生效值（config 缺失时回落 schema 默认值）。"""
    cfg = getattr(plugin, "config", None)
    values = {}
    for key, meta in schema.items():
        default = meta.get("default") if isinstance(meta, dict) else None
        current = default
        if cfg is not None:
            try:
                got = cfg.get(key, None)
            except Exception:
                got = None
            if got is not None:
                current = got
        values[key] = current
    return values


def _coerce_by_schema(value, meta):
    """按 schema 的 type/options/slider 转换前端提交值；不可信时返回 _SKIP。"""
    if not isinstance(meta, dict):
        return _SKIP
    if value is None:  # ⚠️ 关键防御：None 绝不落成 False/0/""
        return _SKIP
    kind = str(meta.get("type") or "string").strip().lower()
    try:
        if kind == "bool":
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return bool(int(value))
            text = str(value).strip().lower()
            if text in ("1", "true", "yes", "on", "开", "是"):
                return True
            if text in ("0", "false", "no", "off", "关", "否"):
                return False
            return _SKIP
        if kind == "int":
            num = int(value) if isinstance(value, (int, float)) else int(float(str(value).strip()))
            slider = meta.get("slider") if isinstance(meta.get("slider"), dict) else {}
            if slider.get("min") is not None:
                num = max(int(slider["min"]), num)
            if slider.get("max") is not None:
                num = min(int(slider["max"]), num)
            return num
        if kind == "float":
            return float(value)
        if kind in ("string", "text"):
            text = str(value)
            options = meta.get("options")
            if isinstance(options, list) and options:
                if text not in [str(o) for o in options]:
                    return _SKIP  # 枚举外的值拒绝，避免写坏下游分支
            return text
        if kind == "dict":
            if not isinstance(value, dict):
                return _SKIP
            out = {}
            for k, v in value.items():
                if v is None or str(k).strip() == "":
                    continue
                try:
                    out[str(k)] = int(v)
                except (TypeError, ValueError):
                    try:
                        out[str(k)] = float(v)
                    except (TypeError, ValueError):
                        out[str(k)] = str(v)
            return out
        if kind == "list":
            items = value
            if isinstance(items, str):
                items = [s for s in items.replace("，", ",").split(",")]
            if not isinstance(items, (list, tuple)):
                return _SKIP
            return [str(v).strip() for v in items if str(v).strip()]
    except (TypeError, ValueError):
        return _SKIP
    return _SKIP


def _config_get_core(plugin) -> dict:
    schema = _load_schema()
    cfg = getattr(plugin, "config", None)
    return ok({
        "schema": schema,
        "values": _config_values(plugin, schema),
        "meta": {
            "plugin": PLUGIN_NAME,
            "version": _plugin_version(),
            "writable": cfg is not None and callable(getattr(cfg, "save_config", None)),
            "field_count": len(schema),
        },
    })


def _config_set_core(plugin, values: dict) -> dict:
    """白名单 + 类型转换后写入 self.config 并落盘；返回 changed/skipped。"""
    schema = _load_schema()
    if not schema:
        return err("读取插件配置 schema 失败，已拒绝写入（避免写坏配置）")
    cfg = getattr(plugin, "config", None)
    if cfg is None or not callable(getattr(cfg, "save_config", None)):
        return err("插件配置不可写（self.config 缺失）")
    changed: list[str] = []
    skipped: list[str] = []
    for key, value in values.items():
        meta = schema.get(key)
        if meta is None:  # schema 之外的键一律忽略（防越权写入）
            skipped.append(f"{key}（未在 _conf_schema.json 中定义）")
            continue
        coerced = _coerce_by_schema(value, meta)
        if coerced is _SKIP:
            skipped.append(f"{key}（类型或取值不符合 schema）")
            continue
        try:
            cfg[key] = coerced
            changed.append(str(key))
        except Exception:
            skipped.append(f"{key}（写入失败）")
    if changed:
        try:
            cfg.save_config()
        except Exception:
            logger.error(f"[{PLUGIN_NAME}] 配置写盘失败\n{traceback.format_exc()}")
            return err("配置已在内存更新但写盘失败，请查看 AstrBot 日志")
    if changed:
        logger.info(f"[{PLUGIN_NAME}] 控制台更新配置：{changed}")
    return ok({"changed": changed, "skipped": skipped})


async def h_config_get(plugin) -> dict:
    return _config_get_core(plugin)


async def h_config_set(plugin) -> dict:
    body = await _body()
    values = body.get("values")
    if not isinstance(values, dict):
        return err("缺少 values 字段（形状：{values: {配置键: 值}}）")
    if not values:
        return ok({"changed": [], "skipped": []})
    return _config_set_core(plugin, values)


def register(plugin) -> None:
    """把控制台 + 调试面板路由挂到 AstrBot（Dashboard 登录墙内，仅管理员使用）。"""
    routes = [
        # 控制台（v1.9.0）
        ("/overview", h_overview, ["GET"]),
        ("/records", h_records, ["GET"]),
        ("/users", h_users, ["GET"]),
        ("/stats", h_stats, ["GET"]),
        ("/user", h_user, ["GET"]),
        ("/config", h_config_get, ["GET"]),
        ("/config", h_config_set, ["POST"]),
        # 调试（M7.5，控制台「调试」页沿用）
        ("/debug/state", h_debug_state, ["GET"]),
        ("/debug/history", h_debug_history, ["GET"]),
        ("/debug/redraw", h_debug_redraw, ["POST"]),
        ("/debug/rerender", h_debug_rerender, ["POST"]),
        ("/debug/reset", h_debug_reset, ["POST"]),
    ]
    for path, fn, methods in routes:
        plugin.context.register_web_api(
            f"{ROUTE_PREFIX}{path}",
            _bind(plugin, fn),
            methods,
            f"MoeStarWhisper {path}",
        )
    logger.info(f"[{PLUGIN_NAME}] 已注册 {len(routes)} 条控制台路由")


def _bind(plugin, fn):
    """把 fn(plugin) 绑定成 AstrBot 可直接调用的无参协程（异常转 err 信封）。"""

    async def handler():
        try:
            return await fn(plugin)
        except Exception as e:
            logger.exception(f"[astrbot_plugin_moe_star_whisper] {fn.__name__} 处理异常")
            return err(f"{fn.__name__} 失败: {e}")

    handler.__name__ = f"msw_{fn.__name__}"
    return handler
