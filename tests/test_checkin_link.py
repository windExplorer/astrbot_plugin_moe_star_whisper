# -*- coding: utf-8 -*-
"""签到联动守卫（可直接运行，退出码即结论）。

口径（v1.13.0）：
- 常态由「萌萌今日老婆」编排：它抢在 get_px 之前建任务，抽完老婆再来调本插件的
  ``linked_fortune()``；本插件的入口只是兜底（老婆没装 / 没开联动时自己响应）；
- 入口 handler 必须 priority > 0，且不能 stop_event / yield——否则会拦掉
  get_px 自己的 /签到 卡片；
- ``linked_fortune`` 只发当日首签：今天已抽过 / 正在抽的一律静默跳过，
  用户手发 /星语 仍走原指令的重发逻辑。
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWED = {"int", "float", "bool", "string", "text", "list", "file",
           "object", "template_list", "dict"}


def check(name, cond, detail=""):
    if not cond:
        print(f"FAIL: {name} {detail}")
        sys.exit(1)
    print(f"ok: {name}")


src = (ROOT / "main.py").read_text(encoding="utf-8")
schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))


def body_of(name: str) -> str:
    start = src.index(f"def {name}(")
    rest = src[start + 10:]
    m = re.search(r"\n    (?:@|async def |def )", rest)
    return rest[: m.start()] if m else rest


# ---------- 配置 ----------
keys = {"checkin_link_enabled", "checkin_link_only_first"}
check("签到联动配置键齐全", keys.issubset(schema.keys()),
      f"缺：{sorted(keys - set(schema.keys()))}")
bad = [k for k in keys if schema.get(k, {}).get("type") not in ALLOWED]
check("签到联动配置 type 合法", not bad, f"非法：{bad}")
check("签到联动默认关闭", schema["checkin_link_enabled"].get("default") is False)
check("默认仅当日首签", schema["checkin_link_only_first"].get("default") is True)

# ---------- 入口 ----------
entry = body_of("checkin_link_entry")
check("注册裸词「签到」入口", '@filter.regex(CHECKIN_LINK_RE, priority=10)' in src)
check("入口优先级高于 get_px（>0）", "priority=10" in src)
check("入口不吞事件", "stop_event" not in entry)
check("入口是普通协程（不 yield）", "yield" not in entry)
check("入口只建后台任务", "create_task" in entry)
check("老婆已接管时让位", "CHECKIN_LINK_EXTRA" in entry)
check("入口掐掉 LLM 兜底", "should_call_llm(False)" in entry)

# ---------- 首签判定 ----------
linked = body_of("linked_fortune")
check("查当天是否已抽", "get_fortune(" in linked)
check("查是否正在抽", "_draw_inflight" in linked)
check("受 only_first 控制", "checkin_link_only_first" in linked)
check("沿用群停用守卫", "_disabled_groups()" in linked)
check("复用原指令生成器", "fortune_cmd(event)" in linked)
check("公开入口可被跨插件调用", "async def linked_fortune" in src)

# ---------- 发送与生命周期 ----------
check("联动结果走 context 主动发送", "context.send_message" in body_of("_send_linked_result"))
check("terminate 取消联动任务", "link_tasks" in body_of("terminate"))

print("\nRESULT: 签到联动守卫全部通过")
