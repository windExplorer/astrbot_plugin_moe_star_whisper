# -*- coding: utf-8 -*-
"""webui_api.py 测试：信封契约与错误路径（quart 缺席时 _body/_q 降级可跑）。
退出码即结论。"""
import asyncio
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import webui_api  # noqa: E402

FAILED = []


def check(cond, msg):
    if not cond:
        FAILED.append(msg)
        print(f"FAIL: {msg}")


async def main_async() -> int:
    # 信封契约（Dashboard 会剥 data 层、status=error 抛错——格式不能跑偏）
    ok = webui_api.ok({"a": 1})
    check(ok == {"status": "ok", "data": {"a": 1}}, "ok 信封形状")
    e = webui_api.err("boom")
    check(e == {"status": "error", "message": "boom"}, "err 信封形状")

    # 未初始化：store None → err（不炸）
    r = await webui_api.h_debug_state(types.SimpleNamespace(_store=None))
    check(r["status"] == "error" and "初始化" in r["message"], "state 未初始化返回 err 信封")

    # 缺 uid：store 存在但未传 uid → err
    stub = types.SimpleNamespace(_store=object())
    r = await webui_api.h_debug_state(stub)
    check(r["status"] == "error" and "uid" in r["message"], "state 缺 uid 返回 err")
    r = await webui_api.h_debug_redraw(stub)
    check(r["status"] == "error" and "uid" in r["message"], "redraw 缺 uid 返回 err")
    r = await webui_api.h_debug_rerender(stub)
    check(r["status"] == "error" and "uid" in r["message"], "rerender 缺 uid 返回 err")
    r = await webui_api.h_debug_reset(stub)
    check(r["status"] == "error" and "uid" in r["message"], "reset 缺 uid 返回 err")

    # core：无签记录 → fortune=None；有签记录 → 完整摘要
    class FakeStore:
        def __init__(self, row=None):
            self._row = row
            self.deleted = False

        def get_fortune(self, uid, date):
            return self._row

        def get_profile(self, uid):
            return {"constellation": "天秤座", "streak": 4, "max_streak": 9}

        def get_draw_jobs(self, uid, date):
            return [{"id": 1, "status": "ok", "image_path": "bg.png", "duration_ms": 800}]

        def get_balance(self, uid):
            return 42

        def get_item(self, uid, item_id):
            return {"reroll": 1, "amulet": 0, "streak_guard": 2, "candle": 3}.get(item_id, 0)

        def delete_fortune(self, uid, date):
            self.deleted = True
            return True

    cfg = lambda k, d=None: {"draw_enabled": True}.get(k, "")  # noqa: E731
    r = webui_api._debug_state_core(FakeStore(), cfg, "10086", "2026-09-27")
    check(r["status"] == "ok" and r["data"]["fortune"] is None, "core：无签记录 fortune=None")
    check(r["data"]["date"] == "2026-09-27" and r["data"]["balance"] == 42
          and r["data"]["items"]["candle"] == 3 and r["data"]["config"]["draw_enabled"] is True,
          "core：余额/背包/配置齐备")

    row = {"nickname": "测试", "avatar": "", "payload": {
        "grade": "吉", "score": 77, "streak": 4, "sign_text": "今天不错。",
        "lucky_color": {"name": "樱粉"}, "card_path": ""}}
    r = webui_api._debug_state_core(FakeStore(row), cfg, "10086", "2026-09-27")
    check(r["data"]["fortune"]["grade"] == "吉" and r["data"]["fortune"]["score"] == 77,
          "core：有签记录摘要完整")

    # reset core：无记录 err；有记录删卡+删行
    r = webui_api._debug_reset_core(FakeStore(), "10086", "2026-09-27")
    check(r["status"] == "error" and "还没有签记录" in r["message"], "reset core：无记录 err")

    import tempfile
    card_file = Path(tempfile.mkdtemp(prefix="moe_webui_")) / "card.png"
    card_file.write_bytes(b"x")
    row2 = {"nickname": "测试", "avatar": "", "payload": {"grade": "吉", "card_path": str(card_file)}}
    fs = FakeStore(row2)
    r = webui_api._debug_reset_core(fs, "10086", "2026-09-27")
    check(r["status"] == "ok" and fs.deleted and not card_file.exists(),
          "reset core：删行且卡文件被清")

    if FAILED:
        print(f"\n{len(FAILED)} 项失败")
        return 1
    print("\nwebui_api.py 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async()))
