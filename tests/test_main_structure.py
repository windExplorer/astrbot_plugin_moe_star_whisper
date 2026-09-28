# -*- coding: utf-8 -*-
"""main.py 结构守卫（AST 级，不需要 astrbot 运行时）。

背景：M3 重写 imports 块时曾意外吞掉 `from .card import render_card`，
导致 v0.4.0/v0.5.0 的图卡路径运行时 NameError（main.py 无运行时测试，
编译与子模块测试都兜不住）。本测试锁死 main.py 的关键结构与名字定义。
退出码即结论。"""
import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FAILED = []


def check(cond, msg):
    if not cond:
        FAILED.append(msg)
        print(f"FAIL: {msg}")


def _module_level_names(tree) -> set:
    """模块级可赋值名：导入、赋值（含 try 块内）、def/class。"""
    names = set()

    def collect(node):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                names.add((a.asname or a.name).split(".")[0])
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)

    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.Assign)):
            collect(node)
        elif isinstance(node, ast.Try):
            for sub in ast.walk(node):
                if isinstance(sub, (ast.Import, ast.ImportFrom, ast.Assign)):
                    collect(sub)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
    return names


def main() -> int:
    src = Path(__file__).resolve().parents[1].joinpath("main.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    check(len(classes) == 1 and classes[0].name == "StarWhisperPlugin",
          "main.py 应只定义 StarWhisperPlugin 一个类")
    if not classes:
        return 1

    # ⚠️ __init__ 必须接受 config 参数：AstrBot star_manager 注入 AstrBotConfig
    # 时若 TypeError 会被静默降级为只传 context → self.config 缺失 →
    # 所有配置开关真机上"永远不生效"（v1.3.4 前的教训）
    init_fn = next((n for n in classes[0].body
                    if isinstance(n, ast.FunctionDef) and n.name == "__init__"), None)
    check(init_fn is not None, "缺少 __init__")
    if init_fn is not None:
        init_args = ([a.arg for a in init_fn.args.args]
                     + [a.arg for a in init_fn.args.kwonlyargs])
        check("config" in init_args,
              "__init__ 必须接受 config 参数（否则 AstrBotConfig 不会注入，配置全部回落默认值）")

    methods = {
        n.name for n in classes[0].body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    required = {
        "fortune_cmd", "rank_cmd", "pk_cmd", "switch_cmd",
        "bind_cmd", "constellation_cmd", "calendar_cmd",
        "wallet_cmd", "shop_cmd", "buy_cmd", "use_cmd", "makeup_cmd", "grant_cmd",
        "_roll_daily", "_economy_on", "_price_of",
        "_try_render_card", "_try_utility_card", "_accent_hex", "_try_llm_sign",
        "_try_draw_background", "_try_build_image_prompt",
        "_group_name_of", "_send_plain",
        "_push_loop", "_do_daily_push", "_next_push_delay",
        "initialize", "terminate",
    }
    missing = required - methods
    check(not missing, f"类缺少方法: {missing or '无'}")

    names = _module_level_names(tree)
    for must in ("render_card", "render_push_card", "render_wallet_card",
                 "render_calendar_card", "PLUGIN_NAME",
                 "MessageChain", "Plain", "Image", "At"):
        check(must in names, f"模块级缺少名字定义: {must}（import 块可能被误删）")

    # 抽签复用分支必须从 fortunes 行读 card_path：该字段是独立列，payload JSON 里
    # 没有这个键（v1.8.6 及以前只读 payload → 当日第二次抽签必然退回纯文本）
    check('existing.get("card_path")' in src,
          "fortune_cmd 复用分支必须读 existing['card_path']（列），不能只读 payload")

    # v1.9.3：群名必须随抽签落库（group_name 一直是空的，控制台只能显示群号）
    check("group_name=group_name" in src,
          "save_fortune 必须带 group_name（否则控制台只能显示群号）")
    check("await self._group_name_of(event)" in src, "fortune_cmd 必须调用 _group_name_of 取群名")
    # v1.9.3：过程提示必须直发（不进结果链），否则会被框架自动 @ 一次
    check("await self._send_plain(event" in src,
          "「占卜中」提示必须用 _send_plain 直发，避免被 ResultDecorateStage 自动 @")
    check('yield event.plain_result("🔮 占卜中' not in src,
          "「占卜中」提示不能再用 plain_result（会被自动 @）")
    # 结果图 + 文合并成一条链，群里只 @ 一次
    check("yield event.chain_result(comps)" in src, "抽签结果必须合并为单条 chain_result")

    # 热重载列表必须包含 webui_api（v1.9.0）：控制台接口都在里面，
    # 不重载的话热更上来的实例会一直跑旧接口（新增路由静默 404）
    import re as _re

    root = Path(__file__).resolve().parents[1]
    m = _re.search(r"def _reload_modules\(self\):(.*?)(?=\n    (?:async )?def )", src, _re.S)
    check(bool(m), "找不到 _reload_modules 方法体")
    check(bool(m) and '"webui_api"' in m.group(1),
          "_reload_modules 必须包含 webui_api（否则控制台接口热更不生效）")

    # v1.9.0：控制台页面产物必须与源码一起进仓库（zip 打包依赖 pages/console）
    check((root / "webui-src" / "package.json").is_file(), "缺少 webui-src/package.json（控制台源码）")
    check((root / "pages" / "console" / "index.html").is_file(),
          "缺少 pages/console/index.html（控制台构建产物，需先跑 build_webui.ps1）")

    # 调试面板（M7.5）：后端模块与页面文件必须存在，聊天侧不得再出现调试指令
    root = Path(__file__).resolve().parents[1]
    check((root / "webui_api.py").is_file(), "缺少 webui_api.py（调试面板后端）")
    check((root / "pages" / "debug" / "index.html").is_file(), "缺少 pages/debug/index.html（调试面板页面）")
    check("debug_cmd" not in methods, "聊天侧不应再有 debug_cmd（调试已移至 WebUI 面板）")

    # WebUI 后端契约审计：webui_api 引用的 plugin.<attr> 必须真实存在于主类
    # （真机教训：stub 测试里 store 恰好存在，掩盖了 main.py 里是 _store 的错位）
    webui_src = (root / "webui_api.py").read_text(encoding="utf-8")
    used_attrs = set(__import__("re").findall(r"plugin\.(\w+)", webui_src))
    members = set(methods)
    for node in ast.walk(classes[0]):
        target = None
        if isinstance(node, ast.Assign) and node.targets:
            target = node.targets[0]
        elif isinstance(node, ast.AnnAssign):
            target = node.target
        if (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)
                and target.value.id == "self"):
            members.add(target.attr)
    external = {"context"}  # Star 基类提供
    bad = used_attrs - members - external
    check(not bad, f"webui_api 引用了主类不存在的属性: {bad or '无'}（契约错位）")

    if FAILED:
        print(f"\n{len(FAILED)} 项失败")
        return 1
    print("\nmain.py 结构守卫全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
