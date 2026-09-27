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
    methods = {
        n.name for n in classes[0].body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    required = {
        "fortune_cmd", "rank_cmd", "pk_cmd", "switch_cmd",
        "bind_cmd", "constellation_cmd",
        "wallet_cmd", "shop_cmd", "buy_cmd", "use_cmd", "makeup_cmd", "grant_cmd",
        "_roll_daily", "_economy_on", "_price_of",
        "_try_render_card", "_try_llm_sign",
        "_try_draw_background", "_try_build_image_prompt",
        "_push_loop", "_do_daily_push", "_next_push_delay",
        "initialize", "terminate",
    }
    missing = required - methods
    check(not missing, f"类缺少方法: {missing or '无'}")

    names = _module_level_names(tree)
    for must in ("render_card", "render_push_card", "PLUGIN_NAME",
                 "MessageChain", "Plain", "Image", "At"):
        check(must in names, f"模块级缺少名字定义: {must}（import 块可能被误删）")

    # 调试面板（M7.5）：后端模块与页面文件必须存在，聊天侧不得再出现调试指令
    root = Path(__file__).resolve().parents[1]
    check((root / "webui_api.py").is_file(), "缺少 webui_api.py（调试面板后端）")
    check((root / "pages" / "debug" / "index.html").is_file(), "缺少 pages/debug/index.html（调试面板页面）")
    check("debug_cmd" not in methods, "聊天侧不应再有 debug_cmd（调试已移至 WebUI 面板）")

    if FAILED:
        print(f"\n{len(FAILED)} 项失败")
        return 1
    print("\nmain.py 结构守卫全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
