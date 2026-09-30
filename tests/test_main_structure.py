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
        "_group_name_of", "_send_plain", "_group_member_ids",
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

    # v1.10.1：首签渲染失败时，当日复用分支必须补渲染（不重算运势、不重调萌绘）
    check("def _retry_render_card" in src, "必须提供 _retry_render_card（缺卡补渲染）")
    check("_retry_render_card(existing, uid, date)" in src,
          "fortune_cmd 复用分支缺卡时必须走补渲染")
    check("self._store.set_card_path(uid, date, card)" in src,
          "补渲染成功必须回写 card_path 列（避免之后每次请求都重试渲染）")

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

    # v1.9.4：星语榜按「本群成员」筛（人在本群就该上榜，哪怕今天在别的群抽签）
    check("await self._group_member_ids(event, gid)" in src,
          "rank_cmd 必须取本群成员集合（榜单口径）")
    check("self._store.list_range_avg_all(monday" in src,
          "周榜必须用不限群的 list_range_avg_all + 成员过滤")
    check("in members][:limit]" in src, "榜单必须按成员集合过滤后再按配置人数截断")
    check("list_group_range_avg(gid, monday, limit=limit)" in src
          and "list_group_day(gid, today, limit=limit)" in src,
          "取不到群成员时必须保留「本群抽签」回落口径（并把人数传下去）")
    # v1.9.5：榜单行不再标注「来自 X 群」（用户明确要求去掉）
    check("_from_tag" not in src and "来自 " not in src,
          "榜单不得再标注抽签来源群")

    # v1.9.7：字体风格（字体统一放公共目录，不借用其它插件）
    root = Path(__file__).resolve().parents[1]
    card_src = (root / "card.py").read_text(encoding="utf-8")
    check("def find_font_by_hint" in card_src, "card.py 缺少 find_font_by_hint（按名字挑圆体）")
    check("sibling_font_dirs" not in card_src and "astrbot_plugin_box" not in card_src,
          "字体不得借用其它插件目录（统一放 AstrBot data/fonts）")
    check("_SKIP_FONT_NAME_HINTS" in card_src, "字体候选必须跳过 emoji/symbol 字体")
    check("def _font_loadable" in card_src, "必须探测字体可否加载（woff2 依赖 FreeType）")
    check("*.woff2" in card_src, "字体查找要支持 woff2")
    check("def _font_dirs" in src and "card_font_style" in src,
          "main.py 必须按 card_font_style 处理字体")
    check("def font_dirs" in card_src and 'parent.parent / "fonts"' in card_src,
          "公共字体目录应由数据目录反推（data/fonts），且集中在 card.font_dirs")
    check("card.font_dirs" in src, "main.py 的字体候选目录应委托 card.font_dirs")
    check("def _card_font_path" in src, "字体路径必须集中解析（含圆体挑选与回落）")
    check("def _find_rounded_font" in src, "圆体查找应集中在 _find_rounded_font")
    check("card.find_font_by_hint" in src, "圆体风格必须走 find_font_by_hint")
    # v1.9.8：曾因只 `from .card import 函数名`、却写 `card.find_font_by_hint` 而 NameError
    check("from . import card" in src, "main.py 必须导入 card 模块本体（否则 card.xxx 必崩）")
    check("list_fonts_by_hint" in card_src, "card.py 需提供 list_fonts_by_hint（区分没字体/读不了）")
    # v1.9.9：card_font_path 支持「字体名 / 文件名 / 路径」三种写法
    check("def resolve_font" in card_src, "card.py 需提供 resolve_font（解析字体名/文件名/路径）")
    check("card.resolve_font" in src, "card_font_path 必须走 card.resolve_font")
    check("自定义字体未解析到可用字体" in src,
          "自定义字体解析失败必须告警（不能静默回落）")

    # v1.10.0：「字体选择」是唯一的字体开关（默认/圆体/自定义），自定义字体条件出现
    import json

    schema = json.loads((root / "_conf_schema.json").read_text(encoding="utf-8"))
    style = schema.get("card_font_style") or {}
    check(style.get("options") == ["auto", "rounded", "custom"],
          f"「字体选择」必须是三选一，实际 {style.get('options')}")
    check(len(style.get("labels") or []) == 3, "「字体选择」三个选项都要有中文标签")
    check((schema.get("card_font_path") or {}).get("description") == "自定义字体",
          "card_font_path 的说明应为「自定义字体」")
    check('style != "custom"' in src, "非自定义时必须忽略 card_font_path（不能两个配置打架）")
    check("_font_conflict_noted" in src, "忽略 card_font_path 时应有一次性日志提示")
    vue = (root / "webui-src" / "src" / "views" / "ConfigView.vue").read_text(encoding="utf-8")
    check('card_font_path: { key: "card_font_style", values: ["custom"] }' in vue,
          "控制台配置页必须把「自定义字体」联动到「字体选择=自定义」")
    check("visibleKeys(group)" in vue, "配置页渲染必须按可见性过滤字段")
    check("visibleKeys(group).filter" in vue, "保存时不应提交被条件隐藏的字段")

    # v1.10.2：昵称上卡前必须清洗（QQ 昵称可能带换行/零宽字符，撑破单行排版）
    check("def sanitize_name" in card_src, "card.py 需提供 sanitize_name（昵称清洗）")
    uses = card_src.count("sanitize_name(")
    check(uses >= 8, f"运势卡/塔罗卡/身份行/榜单/PK/日历等入口都要清洗昵称，当前 {uses} 处")

    # v1.10.3：提示卡多主题（边框/装饰随主题变）+ 榜单头像 + 帮助图按主题分文件
    check("_THEME_DEFS" in card_src and "_draw_card_frame" in card_src,
          "card.py 需提供主题表与主题化外框绘制")
    check(card_src.count("theme=theme") >= 7, "每个提示卡底座调用都要传 theme")
    check("avatars=None" in card_src and "avatars=avatars" in src,
          "榜单卡必须有头像列参数，主程序必须传 avatars")
    check('f"help_{str(theme' in card_src, "帮助图文件名必须带主题（换风格即新文件）")
    check("_download_avatar_bytes" in src and "_avatar_cache" in src,
          "头像下载必须带 TTL 缓存（榜单一次拉 10 个）")
    # v1.10.5：塔罗双联左联只放 AI 牌面原图，不得叠加渲染层装饰（AI 图自带边框）
    check("sdraw.rectangle" not in card_src and "_sparkle(sdraw" not in card_src,
          "双联左联不得再画塔罗框/星饰（会与 AI 自带边框叠成双边）")

    # v1.10.7：负向提示词必须有开关（关闭后完全不传，含内置兜底）
    check('self._cfg("draw_negative_enabled", True)' in src,
          "负向提示词必须受 draw_negative_enabled 开关控制")
    schema_txt = (root / "_conf_schema.json").read_text(encoding="utf-8")
    check('"draw_negative_enabled"' in schema_txt,
          "schema 必须声明 draw_negative_enabled 开关")
    check("extra_font_dirs=self._font_dirs(data_dir)" in src,
          "运势卡渲染必须使用 _font_dirs 的候选目录")
    schema_src = (root / "_conf_schema.json").read_text(encoding="utf-8")
    check("card_font_style" in schema_src, "_conf_schema.json 缺少 card_font_style")
    view_src = (root / "webui-src" / "src" / "views" / "ConfigView.vue").read_text(encoding="utf-8")
    check('"card_font_style"' in view_src,
          "新配置键必须进 ConfigView 的分区表（否则掉进「其他」分区）")

    # v1.10.10：榜单人数可配（rank_size，3-50）+ 每行吉凶徽章
    store_src = (root / "store.py").read_text(encoding="utf-8")
    check("def _rank_size" in src, "榜单人数必须集中解析（_rank_size，含 3-50 夹取）")
    check('self._cfg("rank_size", 10)' in src, "榜单人数必须走 rank_size 配置")
    check("list_group_range_avg(gid, monday, limit=limit)" in src
          and "list_group_day(gid, today, limit=limit)" in src,
          "回落口径取数必须把 limit 传下去（不能再写死 10）")
    check('str(r.get("grade") or "")' in src and 'str(r.get("last_grade") or "")' in src,
          "日榜/周榜两行都要带吉凶（周榜取 last_grade）")
    check("last_grade" in store_src, "store 周榜聚合必须返回 last_grade（最近一签吉凶）")
    check('"rank_size"' in schema_src, "schema 必须声明 rank_size（榜单人数）")
    check('"rank_size"' in view_src,
          "新配置键必须进 ConfigView 的分区表（否则掉进「其他」分区）")

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
