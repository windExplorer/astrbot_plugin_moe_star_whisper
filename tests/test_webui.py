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

    # card_path 权威来源是行内列，payload 同名键仅旧数据兜底（v1.8.7）
    row = {"nickname": "测试", "avatar": "", "card_path": "", "payload": {
        "grade": "吉", "score": 77, "streak": 4, "sign_text": "今天不错。",
        "lucky_color": {"name": "樱粉"}}}
    r = webui_api._debug_state_core(FakeStore(row), cfg, "10086", "2026-09-27")
    check(r["data"]["fortune"]["grade"] == "吉" and r["data"]["fortune"]["score"] == 77,
          "core：有签记录摘要完整")
    check(webui_api._fortune_summary(
        {"card_path": "a.png", "payload": {"card_path": "b.png"}})["card_path"] == "a.png",
        "摘要卡片路径以行内列为准")
    check(webui_api._fortune_summary({"payload": {"card_path": "b.png"}})["card_path"] == "b.png",
        "摘要卡片路径兼容 payload 旧数据")

    # reset core：无记录 err；有记录删卡+删行
    r = webui_api._debug_reset_core(FakeStore(), "10086", "2026-09-27")
    check(r["status"] == "error" and "还没有签记录" in r["message"], "reset core：无记录 err")

    import tempfile
    card_file = Path(tempfile.mkdtemp(prefix="moe_webui_")) / "card.png"
    card_file.write_bytes(b"x")
    row2 = {"nickname": "测试", "avatar": "", "card_path": str(card_file),
            "payload": {"grade": "吉"}}
    fs = FakeStore(row2)
    r = webui_api._debug_reset_core(fs, "10086", "2026-09-27")
    check(r["status"] == "ok" and fs.deleted and not card_file.exists(),
          "reset core：删行且卡文件被清")

    # ---- v1.9.0 控制台：聚合端点（真库真数据，验证 SQL 与形状） ----
    from store import Store as _Store

    tmp2 = Path(tempfile.mkdtemp(prefix="moe_console_"))
    st2 = _Store(tmp2 / "c.db")
    today_str = webui_api.fortune.local_today("Asia/Shanghai")
    st2.save_fortune("c1", today_str, {
        "grade": "大吉", "score": 90, "dims": {"恋爱运": 5}, "streak": 3,
        "lucky_item": "四叶草", "lucky_color": {"name": "樱粉", "hex": "#F0A0B8"},
        "constellation": "天蝎座", "sign_text": "很好。",
    }, nickname="面板甲", group_id="cg1", group_name="面板群", card_path="")
    st2.add_ledger("c1", 30, "draw", today_str)

    cfg_stub = lambda k, d=None: {"output_mode": "图卡", "timezone": "Asia/Shanghai"}.get(k, d)  # noqa: E731
    ov = webui_api._overview_core(st2, cfg_stub, "Asia/Shanghai", days=7)
    check(ov["status"] == "ok" and ov["data"]["totals"]["draws"] == 1, "overview core 聚合")
    check(ov["data"]["day"]["date"] == webui_api.fortune.local_today("Asia/Shanghai"),
          "overview core 用插件时区算今天")
    check(ov["data"]["switches"]["output_mode"] == "图卡", "overview core 带关键开关快照")

    rc = webui_api._records_core(st2, "Asia/Shanghai", page=1, size=10, days=30)
    check(rc["data"]["records"]["total"] == 1 and rc["data"]["records"]["rows"][0]["uid"] == "c1",
          "records core 返回记录行")
    check(rc["data"]["groups"][0]["group_id"] == "cg1", "records core 带群筛选项")

    stt = webui_api._stats_core(st2, "Asia/Shanghai", days=30)
    check(stt["status"] == "ok" and stt["data"]["grades"]["大吉"] == 1, "stats core 档位聚合")
    check(stt["data"]["ledger"]["income"] == 30, "stats core 星尘收支")
    check(stt["data"]["dims"]["恋爱运"] == 5.0, "stats core 六维均值")

    usr = webui_api._user_core(st2, cfg_stub, "Asia/Shanghai", "c1", 1)
    check(usr["data"]["uid"] == "c1" and usr["data"]["balance"] == 30, "user core 余额")
    check(len(usr["data"]["history"]) == 1 and len(usr["data"]["calendar"]) == 1, "user core 历史与日历")
    check(usr["data"]["fortune"] is not None and usr["data"]["fortune"]["has_card"] is False,
          "user core 今日签摘要")
    st2.close()

    # ---- v1.9.0 配置页：类型转换与白名单（防「一次保存清空配置」） ----
    check(webui_api._coerce_by_schema(True, {"type": "bool"}) is True, "bool 直通")
    check(webui_api._coerce_by_schema("off", {"type": "bool"}) is False, "bool 文本归一")
    check(webui_api._coerce_by_schema(None, {"type": "bool"}) is webui_api._SKIP,
          "None 必须被拒绝（否则一次保存把开关清成 False）")
    check(webui_api._coerce_by_schema("x", {"type": "int"}) is webui_api._SKIP, "int 非法值拒绝")
    check(webui_api._coerce_by_schema("42", {"type": "int"}) == 42, "int 字符串可转")
    check(webui_api._coerce_by_schema(1, {"type": "int", "slider": {"min": 30, "max": 600}}) == 30,
          "int 低于 slider 下限被夹紧")
    check(webui_api._coerce_by_schema(999, {"type": "int", "slider": {"min": 30, "max": 600}}) == 600,
          "int 高于 slider 上限被夹紧")
    check(webui_api._coerce_by_schema("x", {"type": "string", "options": ["a"]}) is webui_api._SKIP,
          "枚举外取值拒绝")
    check(webui_api._coerce_by_schema("a", {"type": "string", "options": ["a"]}) == "a", "枚举内取值通过")
    check(webui_api._coerce_by_schema({"大吉": "20"}, {"type": "dict"}) == {"大吉": 20}, "dict 数值转 int")
    check(webui_api._coerce_by_schema("a,b", {"type": "list"}) == ["a", "b"], "list 逗号串拆分")
    check(webui_api._coerce_by_schema([1, " b "], {"type": "list"}) == ["1", "b"], "list 元素归一")

    schema = webui_api._load_schema()
    check(bool(schema), "能读到 _conf_schema.json")
    key_bool = next((k for k, m in schema.items() if m.get("type") == "bool"), "")
    key_int = next((k for k, m in schema.items() if m.get("type") == "int"), "")
    check(bool(key_bool) and bool(key_int), "schema 里能找到 bool/int 字段")

    class FakeCfg(dict):
        def __init__(self):
            super().__init__({key_bool: False, key_int: 10})
            self.saved = 0

        def save_config(self):
            self.saved += 1

    plugin_stub = types.SimpleNamespace(config=FakeCfg())
    res = webui_api._config_set_core(plugin_stub, {
        key_bool: True, key_int: 77, "不存在的键": 1, key_bool + "_x": None,
    })
    check(res["status"] == "ok", "config set 返回 ok")
    check(res["data"]["changed"] == [key_bool, key_int],
          f"只写入白名单内且合法的键，实际 {res['data']['changed']}")
    check(len(res["data"]["skipped"]) == 2, f"白名单外的键被跳过，实际 {res['data']['skipped']}")
    check(plugin_stub.config[key_bool] is True and plugin_stub.config[key_int] == 77, "配置写入内存")
    check(plugin_stub.config.saved == 1, "写盘恰好一次")

    bad = webui_api._config_set_core(plugin_stub, {key_bool: None})
    check(bad["status"] == "ok" and bad["data"]["changed"] == [] and plugin_stub.config.saved == 1,
          "None 不触发写盘（防清空配置）")

    cfg_view = webui_api._config_get_core(types.SimpleNamespace(config=FakeCfg()))
    check(cfg_view["status"] == "ok" and cfg_view["data"]["meta"]["field_count"] == len(schema),
          "config get 返回 schema 与字段数")
    check(set(cfg_view["data"]["values"]) == set(schema), "config get 的 values 覆盖全部 schema 键")

    if FAILED:
        print(f"\n{len(FAILED)} 项失败")
        return 1
    print("\nwebui_api.py 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async()))
