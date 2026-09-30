# -*- coding: utf-8 -*-
"""card.py 冒烟测试。需 pillow：
uv run --no-project --with pillow python tests/test_card.py
退出码即结论。"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fortune  # noqa: E402
import lexicon  # noqa: E402
import card  # noqa: E402
from PIL import Image  # noqa: E402

FAILED = []


def check(cond, msg):
    if not cond:
        FAILED.append(msg)
        print(f"FAIL: {msg}")


def main() -> int:
    lex = lexicon.load_lexicon()
    ff = card.find_font(None)
    if ff is None:
        print("SKIP: 未找到系统中文字体，跳过渲染断言（部署机按多级查找兜底）")
        return 0
    print(f"font: {ff}")

    r = fortune.roll_fortune(
        fortune.derive_seed("2026-09-27", "utest", "card"), lex, None
    )
    r["date"] = "2026-09-27"
    r["streak"] = 3

    tmp = Path(tempfile.mkdtemp(prefix="moe_card_"))

    # 1) 默认尺寸落盘、可打开、非空白（单联内容多时画布自动加高：高≥配置值）
    p1 = card.render_card(r, tmp, nickname="测试旅人", uid="10086")
    check(Path(p1).is_file(), "卡文件应落盘")
    img = Image.open(p1)
    img.load()
    check(img.size[0] == 1024 and img.size[1] >= 1536,
          f"宽 1024、高≥1536（自动加高），实际 {img.size}")
    lo, hi = img.convert("L").getextrema()
    check(hi - lo > 30, f"卡面应有明暗层次（extrema {lo}~{hi}）")

    # 2) 确定性：同输入两次渲染字节一致（不同目录避免同名覆盖）
    p2 = card.render_card(dict(r), Path(tempfile.mkdtemp(prefix="moe_card_")),
                          nickname="测试旅人", uid="10086")
    check(Path(p1).read_bytes() == Path(p2).read_bytes(), "同输入渲染必须字节一致")

    # 3) 小尺寸：宽按配置，高随内容只增不减
    p3 = card.render_card(r, Path(tempfile.mkdtemp(prefix="moe_card_")),
                          width=512, height=768, nickname="小", uid="2")
    _s3 = Image.open(p3).size
    check(_s3[0] == 512 and _s3[1] >= 768, f"小尺寸宽 512、高≥768，实际 {_s3}")

    # 3.5) M4：暗色主题 / 生日描边 / 星座角标 / grade_display 渲染冒烟
    r4 = dict(r)
    r4["birthday_today"] = True
    r4["grade_display"] = "大吉（？）"
    r4["constellation"] = "天秤座"
    p4 = card.render_card(r4, Path(tempfile.mkdtemp(prefix="moe_card_")),
                          theme="dark", nickname="夜旅人", uid="4")
    img4 = Image.open(p4)
    img4.load()
    check(img4.size[0] == 1024 and img4.size[1] >= 1536, f"暗色卡宽 1024、高≥1536，实际 {img4.size}")
    lo4, hi4 = img4.convert("L").getextrema()
    check(hi4 - lo4 > 30, "暗色卡应有明暗层次")

    # 3.6) M5：推送卡冒烟
    p5 = card.render_push_card(
        "2026-09-27", "星期日", {"name": "新月", "text": "许愿的好时机"},
        festival_line="元旦快乐！", accent_hex="#A8D8EA",
        cards_root=Path(tempfile.mkdtemp(prefix="moe_card_")),
    )
    check(Image.open(p5).size == (1024, 620), "推送卡尺寸 1024x620")

    # 3.7) M8：塔罗双联（有 AI 牌面 → 1400x1200 横图；无图 → 单联 700x1200 不留空白）
    fake_side = Path(tempfile.mkdtemp(prefix="moe_card_")) / "ai.png"
    Image.new("RGB", (700, 1200), (40, 36, 80)).save(fake_side)
    r6 = dict(r)
    r6["tarot"] = {"name_cn": "星星", "name_en": "The Star",
                   "keywords": "希望 · 疗愈 · 星光", "reversed": False, "label": "正位"}
    p6 = card.render_card(r6, Path(tempfile.mkdtemp(prefix="moe_card_")),
                          width=700, height=1200, nickname="塔罗客", uid="6",
                          bg_image=str(fake_side))
    check(Image.open(p6).size == (1400, 1200), f"塔罗双联应 1400x1200，实际 {Image.open(p6).size}")
    p7 = card.render_card(r6, Path(tempfile.mkdtemp(prefix="moe_card_")),
                          width=700, height=1200, nickname="塔罗客", uid="6",
                          bg_image=None)
    _s7 = Image.open(p7).size
    check(_s7[0] == 700 and _s7[1] >= 1200, f"无图单联宽 700、高≥1200（自动加高），实际 {_s7}")

    # 4) 长签文换行：每行不超宽（允许单字超宽的容差）
    f40 = card._font(ff, 40)
    lines = card._wrap("星" * 120, f40, 800)
    check(len(lines) > 1, "长文本应换行")
    check(all(card.draw_len(l, f40) <= 840 for l in lines), "每行宽度应受限")

    # 5) 粗体变体：msyh 环境应命中 msyhbd
    bv = card._bold_variant(ff)
    check(Path(bv).is_file(), "粗体变体必须指向存在的字体文件")

    # 6) M9 星尘展示：单联/塔罗双联带 stardust 参数渲染冒烟（不炸即过）
    p8 = card.render_card(r, Path(tempfile.mkdtemp(prefix="moe_card_")),
                          nickname="攒星人", uid="8",
                          stardust_today=23, stardust_total=456)
    _s8 = Image.open(p8).size
    check(Path(p8).is_file() and _s8[0] == 1024 and _s8[1] >= 1536,
          f"单联星尘行渲染（宽 1024、高≥1536），实际 {_s8}")
    p9 = card.render_card(r6, Path(tempfile.mkdtemp(prefix="moe_card_")),
                          width=700, height=1200, nickname="塔罗客", uid="8",
                          bg_image=str(fake_side), stardust_today=23, stardust_total=456)
    check(Image.open(p9).size == (1400, 1200), "塔罗双联星尘块渲染")

    # 7) M9 提示卡六件套：落盘 + 可打开 + 非空白
    misc = Path(tempfile.mkdtemp(prefix="moe_card_"))
    pw = card.render_wallet_card("攒星人", 456, [("换签卡", 1), ("厄运护身符", 2),
                                                 ("连签保护卡", 0), ("幸运香烛", 3)],
                                 misc, file_key="t", uid="10086", today_gain=23,
                                 date_str="2026-09-27", accent_hex="#A8D8EA")
    check(Path(pw).is_file(), "钱包卡落盘")
    ps = card.render_shop_card("攒星人", [(n, 80 + i * 10, f"道具 {n} 的说明文字，测试换行宽度是否正常",
                                           i) for i, n in
                                          enumerate(("换签卡", "厄运护身符", "连签保护卡", "幸运香烛"))],
                               misc, file_key="t", uid="10086")
    check(Path(ps).is_file(), "商店卡落盘")
    pr = card.render_rank_card("今日星语榜", [(1, "甲", "95", ""), (2, "乙", "88", ""),
                                             (3, "丙", "80", ""), (4, "丁", "70", "")],
                               misc, file_key="t", date_str="2026-09-27")
    check(Path(pr).is_file(), "榜单卡落盘")
    pr0 = card.render_rank_card("今日星语榜", [], misc, file_key="empty")
    check(Path(pr0).is_file(), "空榜单卡（空状态）落盘")
    pp = card.render_pk_card("甲", 95, "乙", 88, "甲 胜！", "今天的星星偏向了你。",
                             misc, file_key="t", winner="left", accent_hex="#F0A0B8")
    check(Path(pp).is_file(), "PK 卡落盘")
    pn = card.render_notice_card("购买成功", ["换签卡 ×1", "花费 80 星尘，余额 20", "当前持有 ×2"],
                                 misc, file_key="t", footer="使用：/星语使用 <名称>")
    check(Path(pn).is_file(), "通知卡落盘")
    # 日历：2026-09（1 号周二，30 天，跨 5 周）；含已占卜/未占卜/未来/今日
    cal_days = {"2026-09-05": ("大吉", 92), "2026-09-14": ("凶", 33), "2026-09-27": ("吉", 77)}
    pc = card.render_calendar_card(2026, 9, cal_days, misc, file_key="t",
                                   today="2026-09-27", nickname="攒星人",
                                   accent_hex="#A8D8EA", stats={"drawn": 3, "daji": 1, "avg": 67, "stardust": 456})
    check(Path(pc).is_file(), "日历卡落盘")
    pc2 = card.render_calendar_card(2026, 2, {}, misc, file_key="t2",
                                    today="", nickname="攒星人", stats={"drawn": 0, "daji": 0, "avg": 0, "stardust": None})
    check(Image.open(pc2).size[0] == 1000, "平年二月（4 周）日历渲染")
    for p in (pw, ps, pr, pr0, pp, pn, pc, pc2):
        im = Image.open(p)
        im.load()
        lo_, hi_ = im.convert("L").getextrema()
        check(hi_ - lo_ > 30, f"提示卡应有明暗层次：{Path(p).name} {lo_}~{hi_}")

    # 8) 字体风格（v1.9.7）：按文件名挑圆体、坏候选不挡路、emoji 字体必须被跳过。
    #    不依赖任何其它插件——测试用「系统字体改名」造样本。
    import shutil

    font_dir = Path(tempfile.mkdtemp(prefix="moe_font_"))
    base_font = card.find_font(None, [])
    check(bool(base_font), "应能找到系统字体用于构造测试样本")
    rounded_like = font_dir / "MyRoundedCN-Regular.ttf"
    emoji_like = font_dir / "NotoColorEmoji.ttf"
    broken_like = font_dir / "AaaRoundedBroken.ttf"  # 垃圾内容：必须探测为不可加载
    if base_font and Path(str(base_font)).is_file():
        shutil.copyfile(str(base_font), str(rounded_like))
        shutil.copyfile(str(base_font), str(emoji_like))
    broken_like.write_bytes(b"not a font file")

    named = [Path(p).name for p in card.list_fonts_by_hint([font_dir], ("rounded",))]
    check(named == ["AaaRoundedBroken.ttf", "MyRoundedCN-Regular.ttf"],
          f"list_fonts_by_hint 应列出全部名字匹配项（含读不了的、跳过 emoji），实际 {named}")
    picked = card.find_font_by_hint([font_dir], ("rounded",))
    check(picked is not None and Path(str(picked)).name == "MyRoundedCN-Regular.ttf",
          f"应按名字挑到可加载的圆体（坏候选不挡路），实际 {picked}")
    check(card._display_font_file(str(rounded_like)) == str(rounded_like),
          "圆体风格下展示字体不再替换为楷体")
    check(card.find_font_by_hint([font_dir], ("不存在的关键词",)) is None,
          "名字对不上时返回 None（不硬塞别的字体）")
    check(card.find_font_by_hint([font_dir / "no_such_dir"], ("rounded",)) is None,
          "目录不存在时返回 None")
    check(card._font_loadable(str(font_dir / "nope.ttf")) is False, "坏路径应探测为不可加载")
    check(card.find_font(str(font_dir / "nope.ttf"), []) is not None, "显式路径不存在时回落系统")
    check("sibling_font_dirs" not in dir(card), "不得再有「借用其它插件字体」的接口")

    # 8.1) 真实 woff2 圆体（模拟 data/fonts/ResourceHanRoundedCN-Medium.woff2）：
    #      仅当本机恰好存在样本时才跑——不是依赖，是拿真文件验证 FreeType 的 woff2 能力。
    samples = sorted(
        (Path(__file__).resolve().parents[2] / "astrbot_plugin_box").glob(
            "core/resource/*ounded*.woff2")
    )
    if samples:
        pub = Path(tempfile.mkdtemp(prefix="moe_pub_")) / "fonts"
        pub.mkdir(parents=True, exist_ok=True)
        target = pub / "ResourceHanRoundedCN-Medium.woff2"
        shutil.copyfile(str(samples[0]), str(target))
        picked_w2 = card.find_font_by_hint([pub], ("rounded",))
        check(picked_w2 == str(target),
              f"公共目录里的真实 woff2 圆体应被挑中，实际 {picked_w2}")
        check(card._font_loadable(str(target)),
              "本机 FreeType 应能加载 woff2（不能加载时插件会告警并回落默认字体）")

    # 8.2) resolve_font（v1.9.9）：路径 / 文件名 / 字体名三种写法都要能解析到同一个文件
    named_dir = Path(tempfile.mkdtemp(prefix="moe_res_"))
    only = named_dir / "ResourceHanRoundedCN-Medium.ttf"
    shutil.copyfile(str(base_font), str(only))
    decoy_dir = Path(tempfile.mkdtemp(prefix="moe_decoy_"))
    decoy = decoy_dir / "ResourceHanRoundedCN-Medium-Bold.ttf"  # 同样能模糊命中：测试精确优先
    shutil.copyfile(str(base_font), str(decoy))

    p_file, why_file = card.resolve_font("ResourceHanRoundedCN-Medium.ttf", [named_dir])
    check(p_file == str(only) and "文件名" in why_file,
          f"resolve_font 文件名写法应命中（{why_file}）")
    p_case, _ = card.resolve_font("resourcehanroundedcn-medium.TTF", [named_dir])
    check(p_case == str(only), "resolve_font 文件名匹配忽略大小写")
    p_name, why_name = card.resolve_font("Resource Han Rounded", [named_dir])
    check(p_name == str(only) and "字体名" in why_name,
          f"resolve_font 字体名写法应命中（{why_name}）")
    p_short, _ = card.resolve_font("resourcehanrounded", [named_dir])
    check(p_short == str(only), "resolve_font 简写字体名应模糊命中")
    p_path, why_path = card.resolve_font(str(only), [])
    check(p_path == str(only) and "路径" in why_path, f"resolve_font 绝对路径应命中（{why_path}）")
    check(card.resolve_font("", [named_dir])[0] is None, "空配置应解析为 None")
    p_pri, _ = card.resolve_font("ResourceHanRoundedCN-Medium.ttf", [decoy_dir, named_dir])
    check(p_pri == str(only), f"文件名精确匹配优先于模糊匹配（不被前一个目录抢走），实际 {p_pri}")
    p_miss, why_miss = card.resolve_font("NoSuchFont", [named_dir])
    check(p_miss is None and "没有名为" in why_miss, f"找不到需说明原因，实际 {why_miss}")
    p_bad, why_bad = card.resolve_font(str(broken_like), [])
    check(p_bad is None and "无法加载" in why_bad, f"坏字体需给出可读原因，实际 {why_bad}")

    # 8.3) 字体候选目录（v1.9.9）：AstrBot 公共 data/fonts 由插件数据目录反推两级
    dd = "/AstrBot/data/plugin_data/astrbot_plugin_moe_star_whisper"
    dirs = card.font_dirs(dd)
    check(Path(dirs[0]) == Path(dd) / "fonts",
          f"第一候选应是插件自己的 fonts/，实际 {dirs[0]}")
    check(Path(dirs[1]) == Path("/AstrBot/data/fonts"),
          f"第二候选应是 AstrBot 公共 data/fonts（反推两级），实际 {dirs[1]}")
    check(Path(dirs[2]) == Path("data/fonts"),
          f"第三候选为 cwd 兜底写法，实际 {dirs[2]}")

    # 9) sanitize_name（v1.10.2）：QQ 昵称里的换行/制表/零宽字符不能上卡
    check(card.sanitize_name("小\n明\t吧  ") == "小 明 吧",
          "换行/制表/多余空格应压成单个空格")
    check(card.sanitize_name("A\u200bB\ufeffC") == "ABC",
          "零宽字符应直接删除而不是变成空格")
    check(card.sanitize_name(None) == "" and card.sanitize_name("   ") == "",
          "空/None 应得到空串")
    check(card.sanitize_name("  星语者  ") == "星语者", "首尾空白应去掉")
    cleaned_long = card.sanitize_name("很" * 30)
    check(len(cleaned_long) == 16 and cleaned_long.endswith("…"),
          f"超长昵称应截断到 16 字并带省略号，实际长度 {len(cleaned_long)}")

    # 10) 多主题（v1.10.3）：主题不止换色——边框/装饰随主题变；榜单头像列
    import io

    for t in ("tarot", "sakura", "mint"):
        tdef = card._THEME_DEFS.get(t)
        check(bool(tdef) and tdef.get("border") and tdef.get("ink") and tdef.get("line"),
              f"主题 {t} 的定义必须完整（border/ink/line）")
    p_tarot = card.render_notice_card("主题冒烟", ["塔罗牌主题"], misc,
                                      file_key="theme_tarot", theme="tarot")
    im_t = Image.open(p_tarot)
    im_t.load()
    lo_t, hi_t = im_t.convert("L").getextrema()
    check(hi_t - lo_t > 30, f"塔罗主题卡应正常渲染，实际 {lo_t}~{hi_t}")
    p_sakura = card.render_notice_card("主题冒烟", ["樱花主题"], misc,
                                       file_key="theme_sakura", theme="sakura")
    check(Path(str(p_sakura)).is_file(), "樱花主题卡应正常渲染")
    p_mint = card.render_notice_card("主题冒烟", ["薄荷主题"], misc,
                                     file_key="theme_mint", theme="mint")
    check(Path(str(p_mint)).is_file(), "薄荷主题卡应正常渲染")

    # 榜单头像列：真头像 bytes 与 None（首字占位）都要渲染成功
    av_buf = io.BytesIO()
    Image.new("RGB", (60, 60), (200, 120, 160)).save(av_buf, "PNG")
    p_av = card.render_rank_card(
        "今日星语榜", [(1, "甲", "95", ""), (2, "乙", "88", "")], misc,
        file_key="av", subtitle="萌萌星语 · 本群成员 3 人", date_str="2026-09-28",
        avatars=[av_buf.getvalue(), None],
    )
    im_a = Image.open(p_av)
    im_a.load()
    lo_a, hi_a = im_a.convert("L").getextrema()
    check(hi_a - lo_a > 30, f"带头像榜单应正常渲染，实际 {lo_a}~{hi_a}")

    # 吉凶徽章（v1.10.10）：rows 第 5 项填档位就要真画出档位色徽章；
    # 4 元组老写法（上面 pr/p_av）继续可用且不画徽章列
    p_gr = card.render_rank_card(
        "今日星语榜",
        [(1, "甲", "95", "", "大吉"), (2, "乙", "90", "", "吉"), (3, "丙", "85", "", "中吉"),
         (4, "丁", "80", "", "小吉"), (5, "戊", "75", "", "凶"), (6, "己", "70", "", "大凶")],
        misc, file_key="grade", subtitle="萌萌星语 · 本群成员 3 人", date_str="2026-09-28",
        accent_hex="#A8D8EA",  # 蓝色强调色，避免与档位色撞车影响下面的取色断言
        grade_colors=lex.get("grade_colors"),
    )
    im_g = Image.open(p_gr).convert("RGB")
    im_g.load()
    gw, gh = im_g.size
    px = im_g.load()

    def _hits(rgb):
        return sum(1 for x in range(0, gw, 2) for y in range(0, gh, 2)
                   if px[x, y] == rgb)

    # 六档徽章都必须画**词库原色**（不许调深浅：一调「小吉」就撞「大凶」），
    # 对比度靠字色解决，所以这里只校验底色
    for grade, want in (("大吉", (232, 106, 138)), ("吉", (240, 160, 184)),
                        ("中吉", (232, 196, 106)), ("小吉", (168, 200, 232)),
                        ("凶", (155, 168, 184)), ("大凶", (122, 134, 168))):
        hit = _hits(want)
        check(hit > 200, f"「{grade}」徽章应画出词库档位色 {want}，实际采样命中 {hit}")

    # 帮助图文件名带主题：换风格即新文件，避免协议端拿旧缓存图充数
    p_help = card.render_help_card([("基础", [("/星语", "抽一支今日签")])], misc, theme="tarot")
    check(Path(str(p_help)).name == "help_tarot.png", f"帮助图文件名应带主题，实际 {p_help}")

    # 圆体渲染冒烟：能落盘且非空白
    p_rounded = card.render_rank_card(
        "今日星语榜", [(1, "甲", "95", ""), (2, "乙", "88", "")], misc,
        file_key="rounded", subtitle="萌萌星语 · 本群成员 3 人", date_str="2026-09-28",
        font_path=str(rounded_like), extra_font_dirs=[font_dir],
    )
    im_r = Image.open(p_rounded)
    im_r.load()
    lo_r, hi_r = im_r.convert("L").getextrema()
    check(hi_r - lo_r > 30, f"圆体风格卡应正常渲染，实际 {lo_r}~{hi_r}")

    if FAILED:
        print(f"\n{len(FAILED)} 项失败")
        return 1
    print("\ncard.py 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
