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
    card_path = str(payload.get("card_path") or "")
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
    card_file = ((row or {}).get("payload") or {}).get("card_path") or ""
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
               "note": "已清除，用聊天 /运势 可重新抽取（星尘再次发放）"})


async def h_debug_state(plugin) -> dict:
    """调试面板状态：某 uid 的今日签/档案/背包/绘图任务/关键配置。"""
    if plugin._store is None:
        return err("插件未初始化完成")
    uid = await _uid_of()
    if not uid:
        return err("缺少 uid（要调试的 QQ 号）")
    return _debug_state_core(plugin._store, plugin._cfg, uid, _today(plugin))


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
    date = _today(plugin)
    existing = plugin._store.get_fortune(uid, date)
    if existing is None:
        return err("该用户今天还没有签记录，请先在聊天里 /运势 抽一支")
    payload = existing.get("payload") or {}
    nonce = int(payload.get("reroll_count", 0) or 0) + 1
    result = plugin._roll_daily(
        uid, date, _salt(plugin), plugin._store.get_profile(uid) or {},
        nonce=nonce, streak=int(payload.get("streak") or 1),
    )
    result["reroll_count"] = nonce
    await plugin._try_llm_sign(result)
    bg = _last_ok_bg(plugin, uid, date)
    card_path = plugin._try_render_card(
        result, uid,
        nickname=existing.get("nickname") or "", avatar=existing.get("avatar") or "",
        bg_image=bg,
    )
    plugin._store.update_fortune_payload(uid, date, result, card_path or "")
    return ok({
        "fortune": _fortune_summary({"payload": result, "nickname": existing.get("nickname")}),
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
    date = _today(plugin)
    row = plugin._store.get_fortune(uid, date)
    if row is None:
        return err("该用户今天还没有签记录")
    payload = row.get("payload") or {}
    bg = _last_ok_bg(plugin, uid, date)
    card_path = plugin._try_render_card(
        payload, uid,
        nickname=row.get("nickname") or "", avatar=row.get("avatar") or "",
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
    return _debug_reset_core(plugin._store, uid, _today(plugin))


def register(plugin) -> None:
    """把调试面板路由挂到 AstrBot（Dashboard 登录墙内，仅管理员使用）。"""
    routes = [
        ("/debug/state", h_debug_state, ["GET"]),
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
    logger.info(f"[astrbot_plugin_moe_star_whisper] 已注册 {len(routes)} 条调试面板路由")


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
