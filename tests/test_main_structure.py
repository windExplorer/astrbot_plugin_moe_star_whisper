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
        "bind_cmd", "constellation_cmd", "calendar_cmd", "push_cmd",
        "wallet_cmd", "shop_cmd", "buy_cmd", "use_cmd", "makeup_cmd", "grant_cmd",
        "_roll_daily", "_economy_on", "_price_of",
        "_try_render_card", "_try_utility_card", "_accent_hex", "_try_llm_sign",
        "_try_draw_background", "_try_build_image_prompt",
        "_group_name_of", "_send_plain", "_send_chain", "_announce_drawing", "_group_member_ids",
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
    check("in members]" in src and "rows_src = candidates[:limit]" in src,
          "榜单必须按成员集合过滤后再按配置人数截断")
    check("list_group_range_avg(gid, monday, limit=200)" in src
          and "list_group_day(gid, today, limit=200)" in src,
          "取不到群成员时必须保留「本群抽签」回落口径，且显式给大 limit"
          "（store 默认 limit=10 会把榜单和「参与 N 人」一起截到 10）")
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

    # v1.10.12：跨界绘图契约改为「自己的标识 + external=True」（萌绘 v7.7.58+）。
    # 不许再借伙伴插件的口令——那是萌绘侧的兼容层，新插件不该继续依赖它。
    check('source="萌萌星语"' in src,
          "调用 comfyui_draw 必须用本插件自己的标识作 source（便于萌绘日志/审计区分来源）")
    check("external=True" in src,
          "调用 comfyui_draw 必须显式 external=True，否则拿不到图片路径")
    check('source="我会永远陪着你"' not in src,
          "不得再把伴侣插件的口令当契约传出去（兼容层只在萌绘侧保留）")

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
    check("list_group_range_avg(gid, monday, limit=200)" in src
          and "list_group_day(gid, today, limit=200)" in src,
          "回落口径取数必须显式给大 limit（store 默认 10，会隐形截榜）")
    # v1.10.14：榜单必须自证「筛出多少人 / 取前几名」，否则「配置 20 却只看到
    # 10 个人」这类问题分不清是配置没生效还是当天就只筛出这么多人
    check("eligible = len(candidates)" in src and "rows_src = candidates[:limit]" in src,
          "榜单必须先数出候选人数（eligible）再按 rank_size 截断")
    check('note = f"参与 {eligible} 人 · 榜单取前 {limit} 名"' in src,
          "榜单要给出「参与 N 人 · 取前 M 名」的说明")
    check("footer=note" in src, "榜单卡页脚必须显示参与人数与取前名次")
    check("lines.append(f\"（{note}）\")" in src, "纯文本榜单也要带上同一句说明")
    check("_{limit}_{eligible}" in src,
          "榜单卡文件名要带参与人数（白天陆续有人抽签时不会复用早上的旧卡）")
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

    # v1.10.15 / v1.10.16：每日推送扩成「星象日报」，并把它搬到 /星语星象 指令上。
    # 两处必须共用同一份内容——所以内容生成/渲染/文字回退都抽成了方法，这里逐个锁死。
    check("def _push_board_line" in src, "推送必须有本群数据行（_push_board_line）")
    check("list_group_day(gid, prev, limit=200)" in src,
          "推送的本群数据必须按「本群抽签」口径取昨日榜，且显式给大 limit")
    for helper in ("_push_public", "_push_card", "_push_caption",
                   "_push_text_fallback", "_push_message"):
        check(f"def {helper}" in src,
              f"推送/星象指令必须共用 {helper}（内容只能有一份，抄两份必然跑偏）")
    check('PUSH_HINT = "发送 /星语' in src,
          "指令引导文案必须抽成模块级常量 PUSH_HINT")
    check(src.count("PUSH_HINT") >= 3,
          "PUSH_HINT 要同时给卡渲染与文字部分用（别再手抄一份）")

    m_pub = _re.search(r"def _push_public\(self.*?(?=\n    (?:@|def ))", src, _re.S)
    check(bool(m_pub), "找不到 _push_public 方法体")
    pub_body = m_pub.group(0) if m_pub else ""
    for token, why in (
        ('fortune.pick_two(seed, "push_yi"', "宜两条必须来自词库（pick_two）"),
        ('fortune.pick_two(seed, "push_ji"', "忌两条必须来自词库（pick_two）"),
        ("fortune.pick_number(seed", "幸运数字必须确定性抽取（pick_number）"),
        ('fortune.pick_text(seed, "push_dir"', "幸运方位必须来自词库"),
        ('"yiji"', "公共内容要带宜忌块"),
        ('"lucky"', "公共内容要带幸运块"),
        ('"weekday_name"', "公共内容要带星期（指令与推送共用）"),
    ):
        check(token in pub_body, f"_push_public 缺少：{why}")
    # v1.10.22：两份种子——客观历法（月相/农历/节气/节日）各群一致，
    # 本群宜忌/幸运/主色按群派生（否则「每个群的卡都一样」）
    check('def _push_public(self, gid: str = "") -> dict:' in src,
          "_push_public 必须接受群号（私聊/预览传空）")
    check('seed_day = fortune.derive_seed(today, "daily-push", salt)' in pub_body,
          "客观历法要用日期种子 seed_day")
    check('fortune.derive_seed(today, f"daily-push:{gid}", salt)' in pub_body,
          "本群宜忌/幸运要用「日期 + 群号」种子 seed_gid")
    check('fortune.pick_text(seed_day, "push_phase"' in pub_body,
          "月相必须走 seed_day（天上只有一个月亮，不同群不该不一样）")
    check('fortune.pick_text(seed_day, "push_fest"' in pub_body
          and 'fortune.pick_text(seed_day, f"push_jieqi:' in pub_body,
          "节日/节气文案也必须走 seed_day（同一天各群一致）")
    check('accent = fortune.pick_text(seed, "push_color"' in pub_body,
          "卡片主色要跟本群种子走（每群配色不同，一眼看出不是同一张图）")

    # v1.10.17：历法块（农历 / 节气 / 节日）——数据来自自带 lunar.py，节日走词库两条路
    check("from . import fortune, lexicon, lunar, store" in src,
          "main.py 必须以相对导入引入 lunar（包内模块）")
    check(bool(m) and '"lunar"' in m.group(1),
          "_reload_modules 必须带上 lunar（否则热更上来的实例用的是旧模块）")
    check("lunar.describe(today)" in pub_body,
          "公共内容必须用 lunar.describe 取农历/节气（超范围时它返回空 dict）")
    check('lex.get("lunar_festivals")' in pub_body and 'lex.get("jieqi")' in pub_body,
          "农历节日与节气文案必须走词库（可自定义），缺键就降级不打崩")
    check('"lunar_line"' in pub_body and '"jieqi_line"' in pub_body,
          "公共内容要带 lunar_line / jieqi_line 两个键")
    check('"　".join' in pub_body,
          "公历与农历节日撞同一天时两个都要发（拼在一行）")

    m_cardfn = _re.search(r"def _push_card\(self.*?(?=\n    def )", src, _re.S)
    check(bool(m_cardfn), "找不到 _push_card 方法体")
    card_body = m_cardfn.group(0) if m_cardfn else ""
    check("file_key=file_key" in card_body and "yiji=public[\"yiji\"]" in card_body,
          "卡渲染必须把宜忌/幸运/文件名键都透传下去")
    for token in ("lunar_line=public.get(\"lunar_line\", \"\")",
                  "jieqi_line=public.get(\"jieqi_line\", \"\")"):
        check(token in card_body, f"卡渲染必须透传历法行：{token}")
    check("return None" in card_body, "卡渲染失败必须返回 None（由调用方回落文字）")

    m_push = _re.search(r"async def _do_daily_push\(self.*?(?=\n    (?:async )?def )", src, _re.S)
    check(bool(m_push), "找不到 _do_daily_push 方法体")
    push_body = m_push.group(0) if m_push else ""
    check('self._push_message(public, board_line, gid, with_card=want_card)' in push_body,
          "推送必须按群取内容（文件名键 = 群号，否则多群同名互相覆盖）")
    check("public = self._push_public(gid)" in push_body
          and "_push_text_fallback" not in push_body,
          "推送要在群循环里按群取内容 + 共用组装方法（回退逻辑不该在推送里再写一遍）")
    # v1.10.19：推送跟随「出签方式」——仅文字时不发卡，图卡模式只发卡（不带标题文字）
    check('mode = str(self._cfg("output_mode", "图卡"))' in push_body
          and 'want_card = mode != "纯文本"' in push_body,
          "推送必须读 output_mode 决定要不要卡")
    check('if mode != "图卡" or card is None:' in push_body,
          "图卡模式下推送只发卡；卡渲染失败才回落到那段文字（消息不能是空的）")

    # v1.11.3：推送循环「到点即推」。旧逻辑是 wait = _next_push_delay(); if wait > 0:
    # sleep——该函数时刻已过就顺延明天、**恒为正**，_do_daily_push 是死代码，
    # 推送从上线起一次都没真正触发过（用户：配了推送从来没收到）。锁死新结构。
    check("def _push_target_dt(self)" in src,
          "必须有 _push_target_dt（今天的推送时刻本身，顺延由调用方处理）")
    m_loop = _re.search(r"async def _push_loop\(self.*?(?=\n    def )", src, _re.S)
    check(bool(m_loop), "找不到 _push_loop 方法体")
    loop_body = m_loop.group(0) if m_loop else ""
    for token, why in (
        ("self._push_target_dt()", "循环必须现场算今天的目标时刻（改配置即时生效）"),
        ("now >= target", "循环必须按「现在 >= 今天目标时刻」触发推送（到点即推）"),
        ("pending = await self._do_daily_push()", "循环必须拿 _do_daily_push 的「还有待推群」返回值"),
        ("self._PUSH_RETRY_WAIT", "有群没推成功时必须稍后重试（失败要能当天自愈）"),
    ):
        check(token in loop_body, f"_push_loop 缺少：{why}")
    check("if wait > 0" not in loop_body,
          "禁止回退「wait>0 就睡」的死代码模式（_next_push_delay 恒为正 → 永远推不了）")
    check("attempted_today" not in loop_body,
          "禁止回退「今天试过一次就整天不推」的内存闸（v1.11.5：一次失败会连累一整天）")

    # v1.11.5：推送主体按「群+日期」去重 + 失败重试，返回是否仍有待推群
    for token, why in (
        ("async def _do_daily_push(self) -> bool:", "推送主体必须返回「是否还有群待重试」"),
        ("self._store.pushed_group_ids(today)", "必须按当天已推成功的群集合去重（绝不重发）"),
        ("self._PUSH_MAX_TRIES", "每群每天必须限制尝试次数（防失败死循环刷事件）"),
        ("self._push_tries", "必须维护每群今日尝试计数"),
        ("self._push_empty_noted", "「无推送目标」当天只留痕一次（否则每 30 分钟刷一条）"),
        ("return True", "还有待推群时返回 True（循环据此安排重试）"),
        ("return False", "没有待推群时返回 False（循环睡到明天）"),
    ):
        check(token in push_body, f"_do_daily_push 缺少：{why}")
    check("count_push_history" not in push_body and "attempted" not in push_body,
          "推送主体不应再用「今天试过一次」的粗粒度闸，去重按群算")
    # _next_push_delay 保留给面板展示，但必须基于 _push_target_dt（时刻解析只此一份）
    check("target = self._push_target_dt()" in src,
          "_next_push_delay 必须复用 _push_target_dt（别把时刻解析抄第二份）")

    # v1.11.4：平台必须存**实例 id**（send_message 只认 platform.meta().id），
    # 旧记录（适配器类型名）推送前解析兜底——「未匹配到平台适配器」的根因。
    check("def _resolve_platform_id(self" in src,
          "必须有 _resolve_platform_id（旧记录类型名→实例 id 解析）")
    m_sp = _re.search(r"def _sender_platform\(.*?(?=\n    def )", src, _re.S)
    sp_body = m_sp.group(0) if m_sp else ""
    check("get_platform_id" in sp_body and "get_platform_name" not in sp_body,
          "_sender_platform 必须存平台实例 id，不能再存适配器类型名（get_platform_name）")
    m_res = _re.search(r"def _resolve_platform_id\(self.*?(?=\n    def )", src, _re.S)
    res_body = m_res.group(0) if m_res else ""
    for token, why in (
        ("inst.meta().id == stored", "实例 id 直接命中（新数据）"),
        ("inst.meta().name == stored", "旧数据按类型名找同类型实例"),
        ("len(same) == 1", "同类型多个实例（多机器人）时不猜，发错群比不发更糟"),
    ):
        check(token in res_body, f"_resolve_platform_id 缺少：{why}")
    check("platform = self._resolve_platform_id(platform)" in src,
          "推送发送前必须解析平台 id（旧数据否则全部 no_platform）")

    # v1.11.7：本群数据的昵称必须清洗（零宽字符造空白名 / 换行打乱卡面 / 空昵称）
    check("def _clean_nickname(" in src, "必须有昵称清洗包装（card 不可用时的兜底）")
    check('_clean_nickname(top.get("nickname"), "旅人")' in src,
          "_push_board_line 的昵称必须过清洗，不能直接取原值")
    check("clean_nickname," in src and "from .card import" in src,
          "main 必须从 card 复用清洗实现（不许抄第二份规则）")

    # v1.10.16：/星语星象 —— 把每日推送搬到指令上（随时看 / 不用等 08:00 / 不用真开推送）
    check("push_cmd" in methods, "缺少 /星语星象 指令（push_cmd）")
    check('@filter.command("星语星象"' in src, "指令名必须是 /星语星象（主指令统一「星语」前缀）")
    m_cmd = _re.search(r"async def push_cmd\(self.*?(?=\n    @filter)", src, _re.S)
    check(bool(m_cmd), "找不到 push_cmd 方法体")
    cmd_body = m_cmd.group(0) if m_cmd else ""
    for token, why in (
        ("self._push_public(gid)", "星象指令必须与推送共用按群内容（同一个群两边逐字一致）"),
        ('self._push_message(', "星象指令必须共用同一套组装（私聊用 private 当文件名键）"),
        ('gid or "private"', "私聊用 private 当文件名键"),
        ('with_card=mode != "纯文本"', "仅文字模式不渲染卡（省一次绘图）"),
        ("self._push_board_line(gid, public[\"prev\"]) if gid else \"\"",
         "群里才带昨日摘要（私聊没有群可算）"),
        ("_disabled_groups()", "停用群要拒发（与推送口径一致）"),
        ('mode = str(self._cfg("output_mode", "图卡"))', "星象指令必须读 output_mode"),
        ('if mode == "图卡+文本":', "「图卡加文字」才追加正文；默认图卡模式只发图"),
        ("await self._send_chain(event, comps)", "必须直发（绕开结果装饰）才能不 @ 发送者"),
    ):
        check(token in cmd_body, f"push_cmd 缺少：{why}")
    check("yield event.chain_result" not in cmd_body and "yield event.image_result" not in cmd_body,
          "星象指令不能再 yield 结果链——那会被框架自动 @ 发送者（群公告性质，不需要 @）")

    # v1.10.18：帮助图必须与指令表严格一一对应——加了指令忘了写帮助图，
    # 用户永远不知道有这个功能（v1.10.16 加 /星语星象 时就差了半截描述）
    cmds_registered = set(_re.findall(r'@filter\.command\("([^"]+)"', src))
    # 注意：help_cmd 是文件里最后一个方法，正则必须允许「到文件结尾」（\Z），
    # 否则非贪婪匹配找不到后续 def 就直接匹配失败
    m_help = _re.search(r"async def help_cmd\(self.*?(?=\n    (?:async )?def |\Z)", src, _re.S)
    check(bool(m_help), "找不到 help_cmd 方法体")
    help_body = m_help.group(0) if m_help else ""
    help_listed = set()
    for line in help_body.splitlines():
        # 只认「以斜杠开头」的行——分区标题也是 ("占卜", [...)，别把它们当指令
        mm = _re.match(r'\s*\("/([^\s"\[<]+)', line)
        if mm:
            help_listed.add(mm.group(1))
    missing_in_help = sorted(cmds_registered - help_listed)
    check(not missing_in_help, f"帮助图漏了指令: {missing_in_help}")
    ghost_in_help = sorted(help_listed - cmds_registered)
    check(not ghost_in_help, f"帮助图写了不存在的指令: {ghost_in_help}")
    check(len(cmds_registered) >= 14, f"指令数异常（{len(cmds_registered)}），检查 @filter.command 是否被误删")

    # v1.10.13：使用道具（换签卡）也要走「先绘后卡」那条流程——过程提示 + 输出方式
    check("def _announce_drawing" in src,
          "「占卜中」过程提示必须集中到 _announce_drawing（首签/换签共用同一份）")
    check(src.count("await self._announce_drawing(event)") >= 2,
          "首签与换签都要给「占卜中」提示（换签卡此前直接调 _try_draw_background，用户干等无提示）")
    m_use = _re.search(r"async def use_cmd\(self.*?(?=\n    @filter)", src, _re.S)
    check(bool(m_use), "找不到 use_cmd 方法体")
    use_body = m_use.group(0) if m_use else ""
    check("_announce_drawing" in use_body,
          "换签卡触发萌绘出图前必须提示「占卜中」")
    check('mode != "纯文本"' in use_body,
          "换签也必须看输出方式（纯文本模式下不得生成底图、不得回图）")
    check('self._cfg("draw_fail_hint", "")' in use_body,
          "换签的萌绘失败提示（draw_fail_hint）也要跟着发，不能丢")
    check("yield event.chain_result(comps)" in use_body,
          "换签结果图+文必须合并为一条链（与首签一致，群里只 @ 一次）")

    # v1.10.25：当日出图失败过 → 重复抽签要能补一次出图（绘图服务器恢复即换回双联）
    check("def _ai_art_of_day" in src and "async def _try_redraw_today" in src,
          "需要 _ai_art_of_day / _try_redraw_today 支撑「当日补出图」")
    m_f = _re.search(r"async def fortune_cmd\(self.*?(?=\n    @filter)", src, _re.S)
    check(bool(m_f), "找不到 fortune_cmd 方法体")
    f_body = m_f.group(0) if m_f else ""
    check("not self._ai_art_of_day(uid, date)" in f_body,
          "重复抽签时必须先判断当天有没有画出过图（画过就不许重画，保持一日一签幂等）")
    check("await self._try_redraw_today(" in f_body,
          "当日画图失败过时，重复抽签要调用补出图")
    check("_redraw_gate" in f_body,
          "补出图必须节流（否则服务器一直挂着时每次抽签都干等一轮超时）")
    m_r = _re.search(r"async def _try_redraw_today\(self.*?(?=\n    # ---------- )", src, _re.S)
    check(bool(m_r), "找不到 _try_redraw_today 方法体")
    r_body = m_r.group(0) if m_r else ""
    check("await self._announce_drawing(event)" in r_body
          and "await self._try_draw_background(" in r_body,
          "补出图必须复用 _announce_drawing + _try_draw_background（不许再写一套出图流程）")
    check("set_card_path(uid, date, card_path)" in r_body,
          "补出图成功后要把新卡路径写回 fortunes.card_path")
    check("update_fortune_payload(" not in r_body,
          "补出图不得重写 payload（运势是当日既定的，只换卡）")

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
