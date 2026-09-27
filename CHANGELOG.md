# 更新日志

> 倒序（最新在上）。版本唯一来源为 `metadata.yaml` 的 `version`，条目号与其严格一致。

## v1.0.0 (2026-09-27)

**首次公开发布**：M0-M7 全量完成（决策记录 D1-D11 见 `docs/PRD.md`）。

自 v0.1.0 起的完整功能面：每日确定论签（一日一签、全局统一、重复回发）、六档吉凶与六维星数、萌系图卡（幸运色驱动 + 暗色主题 + 字体多级查找）、anima AI 底图联动（先绘后卡、seed/尺寸透传、降级矩阵）、LLM 星语（可选增强默认关）、每日群推送（自管定时循环）、星座绑定与生日/节日/愚人节彩蛋、群玩法（榜单/PK/开关/连签徽章）、道具经济（星尘流水 + 四道具）、数据全量落库（fortunes/profiles/items/ledger/draw_jobs，为统计功能 F24 预留口径）。

首发前的收尾：PRD 移入仓库 `docs/PRD.md`；README 更新为全量指令与特性说明。

## v0.8.0 (2026-09-27)

M7 道具经济：星尘 + 四道具 + 商店/背包/补签/发放（F22/D8）。

- **星尘（独立娱乐积分，D8 口径）**：不可转账不可兑换；来源=每日抽签基础 `draw_reward_base`(10) + 吉凶修正（大吉+20/吉+15/中吉+12/小吉+10/凶+14/大凶+18，越倒霉补偿越多）+ 连签加成（≥3 天 +2、≥7 +4、≥30 +6）；**每一笔增减走 `ledger` 流水**（`add_ledger` 强制），余额=流水合计。首抽出签文案显示「星尘 +N」；换签重掷不重复发奖。
- **四道具**：换签卡（当日重抽覆盖旧结果，`reroll_count` 限每日 1 张，运势+AI 底图完整重做）；厄运护身符（抽签前佩戴→当日保底小吉，`amulet_weights`）；幸运香烛（佩戴→当日幸运指数 +8，幂等）；连签保护卡（断签 3 天内 `/运势补签` 补回昨天、streak 恢复；今日已抽则窗口关闭，防 streak 重算错乱）。持有上限 `item_hold_cap`(3)。
- **佩戴机制**：抽签前使用 → `ledger` 记 `use:<item>` 标记（ref_date=当日）；抽签时 `_roll_daily` 查标记生效；已抽签后使用提示明日再用来。
- **指令**：`/星尘`（余额+背包）、`/运势商店`、`/运势购买 <名称> [数量]`（余额不足提示差多少）、`/运势使用`、`/运势补签`、`/运势发放 @用户 <±n>`（仅管理员，必走流水）；中英文道具别名解析。
- **重构**：首抽逻辑抽成 `_roll_daily(uid, date, salt, profile, nonce, streak)`——换签/补签与首抽共用同一套生日特权/佩戴/彩蛋/确定种子逻辑，避免三处漂移。
- store 新增 `get_balance`/`add_ledger`/`has_ledger`/`get_item`/`add_item`（UPSERT）/`update_fortune_payload`；`fortune.stardust_reward` 纯函数 6 组断言；store 经济断言（流水合计/道具累加扣减/佩戴标记）。

## v0.7.0 (2026-09-27)

M6 anima 底图联动：AI 生成卡面底图（D11 先绘后卡）。

- **契约（已对照 anima 对接文档与源码核实，PRD §7.6）**：`get_llm_tool_manager().get_func("comfyui_draw")` 取 handler 直接 await；`source` 必传 anima 约定值「我会永远陪着你」才返回 JSON `image_paths` 由我方落库发图；`seed`＝运势种子整数化（一人一天一张底图、换签换 seed）、`width/height`＝卡布尺寸（不裁切）；`workflow`/`negative_prompt` 可配透传。
- **时序（先绘后卡）**：LLM 生成提示词 → comfyui_draw（受 `draw_timeout` 约束，默认 120s）→ 取 `image_paths[0]` → `render_card(bg_image=...)` 合卡 → 落盘 `cards/<qq>/<date>.png` → 一次发送。
- **提示词约束（D6）**：`draw_prompt_lang`（en/zh）+ `draw_prompt_format`（tags/natural）注入 LLM 模板（`builtin_draw_prompt`，en+tags 按动漫工作流 Danbooru 标签规范）；LLM 失败/空输出回退本地兜底提示词（吉凶氛围 + 幸运物，`local_draw_prompt`）。
- **降级矩阵**：anima 未装 / 工具未注册 → `skipped_no_anima`；超时 → `timeout`；异常或响应无路径 → `error`。全部静默回退幸运色渐变默认底图，运势卡照常发送；`draw_fail_hint` 可选附加一句提示（默认空=静默）。
- **draw_jobs 全链路落库（D6/D7）**：workflow/语言/形式/提示词原文/状态/耗时/底图与成品卡路径，`record_draw_job` + `get_draw_jobs`；`fortune.parse_draw_response` 容错解析（image_paths 列表、单数兼容、花括号截取）。
- 测试：解析 6 组断言、本地/模板提示词断言、draw_jobs 落库读回、结构守卫补 `_try_draw_background`/`_try_build_image_prompt`。

## v0.6.0 (2026-09-27)

M5 增强：LLM 星语（可选增强，默认关）与每日群推送。

- **修复回归（重要）**：M3 重写 imports 块时曾把 `from .card import render_card` 意外吞掉，导致 v0.4.0/v0.5.0 的图卡路径运行时 NameError（main.py 无运行时测试、编译与子模块测试均兜不住）。本轮恢复导入，并新增 `tests/test_main_structure.py`——AST 级结构守卫，锁死模块级名字定义（render_card/render_push_card/组件导入等）与全部指令/生命周期方法，防止此类回归再次静默通过。
- **LLM 星语（F16）**：`llm_enabled` 开启后，当日**首次**抽签用 `context.get_using_provider().text_chat()`（20 秒超时）按事实清单改写签文并写入 payload；无 provider/失败/空输出静默回退本地模板，绝不阻塞出卡。事实清单 `fortune.llm_facts` 只含运势事实、不含用户身份；内置人设可被 `llm_prompt_persona` 覆盖。
- **每日群推送（F17）**：`daily_push_enabled` + `daily_push_time`；插件自管 asyncio 循环（AstrBot 无插件侧定时装饰器，PRD §7.5），每分钟复查配置（开关/时刻改动即时生效）、距目标 30 分钟内小步睡眠、推送后避开同一时刻防重复。目标群 = 近 7 天有抽签的群（`list_active_group_ids`，fortunes 新增 platform 列 + 旧库 ALTER 迁移）且不在停用名单。内容 = 文本（日期/星期/月相/节日）+ 新增 `render_push_card`「今日星象」卡（日期大字/月相/节日/抽签引导，幸运色按日期种子轮换）。
- 测试：main 结构守卫、`llm_facts`/`now_in` 断言、推送卡冒烟、活跃群列表断言。

## v0.5.0 (2026-09-27)

M4 星座与彩蛋：绑定体系、特殊日期、暗色卡面。

- **`/星语绑定 <MM-DD>`**（别名 `/运势绑定` `/绑定生日`）：绑定生日（只存月日，不存年份），推导星座入库；2/29 稀有生日允许绑定并注明只在闰年生效。`fortune.constellation_of` 纯函数 + 20 组边界断言（含摩羯跨年）。
- **`/星座 [@某人]`**（别名 `/查询星座` `/星语星座`）：查看自己/他人的星座与今日吉凶——**不展示生日本身**（PRD F13 隐私口径）；生日当天追加 🎂 提示。
- **生日特权（F14）**：生日当天抽签权重强制为大吉，卡面加金环描边（`birthday_today` payload 字段驱动）。
- **特殊日期彩蛋（F14）**：4/1 全员吉凶显示 `（？）` 整活后缀 + 签文追加愚人节句；元旦/劳动/儿童/国庆/平安夜/圣诞 solar 节日池 + 周五摸鱼加成池，均按种子确定性抽取并写进 payload（回放一致）。农历节日（春节/中秋）需农历换算库，延后。
- **暗色卡面（F15）**：`card_theme` 配置（auto 目前等同 light，dark 为暗色）；暗色调色板（墨蓝底混幸运色、暗面板、亮文字），装饰与布局复用。
- **卡面星座角标**：QQ 行拼 `· 星座`；卡面大字与文本出签均使用 `grade_display` 显示态。
- 词库新增 `festivals` / `friday`，`validate_lexicon` 同步校验；测试新增星座边界、词库负例、暗色卡冒烟。

## v0.4.0 (2026-09-27)

M3 群玩法：榜单、PK 与群开关。

- **`/运势榜 [日|周]`**（别名 `/星语榜`）：群内当日幸运指数榜（默认展示昵称+分数，不展示吉凶文字，避免攀比不适）；`周` 按本周（周一起）人均分排序、同分按抽签天数。存储层新增 `list_group_day` / `list_group_range_avg`（`idx_fortunes_date` 索引在此兑现）。
- **`/运势PK @某人`**（别名 `/星语PK`）：双方当日幸运指数对决；双方需已抽签，胜方文案从词库 `pk.win/lose/tie` 池按**种子确定性**抽取（seed 含双方 ID 排序，同日同对手必同文案）。At 解析排除 `all`。
- **`/运势开关 on|off`**（别名 `/星语开关`，仅 AstrBot 管理员）：群级启停，写回配置 `disabled_groups` 并 `save_config()` 持久化（配置页可见；PRD 原文「群管理员」按 AstrBot 权限模型落地为 AstrBot 管理员口径）。停用群内 `/运势` 会得到一句开启提示。
- **连签徽章（F10）**：3/7/14/30 天达成时在出签文案追加专属徽章行。
- **词库**：新增 `pk` 节（win/lose/tie 各 5/5/3 条），`validate_lexicon` 同步校验（缺池/空池加载期报错）；`fortune.pick_text` 公开确定性选词接口。
- 测试：`test_store` 增群日榜/周榜聚合断言（跨群隔离、均分口径）；`test_lexicon` 增 pk 负例。

## v0.3.0 (2026-09-27)

M2 图卡：纯文本出签升级为萌系图卡。

- **card.py（纯 Pillow，无 astrbot 依赖）**：卡面按 PRD §7.3 七层信息层级——身份头（头像+昵称+QQ号+日期）→ 吉凶大字 → 签文话语区（主体文字，自动换行）→ 六维星数 → 幸运指数 → 宜忌章 → 幸运四件套 + 月相/连签 + 落款。
- **幸运色驱动**：底图为幸运色淡彩渐变（白底为主，幸运色只做氛围），吉凶大字/星星/幸运指数用档位色——不同用户不同签不同色。
- **字体不打包（沿 model_panel 方案）**：多级查找（`card_font_path` → 插件 `fonts/` → `data/fonts` → 系统候选），吉凶大字与幸运指数自动用粗体变体（msyhbd/Noto Bold）；找不到字体抛错、由 main 回退纯文本出签。
- **头像（D10）**：QQ 平台 qlogo 头像圆形裁切上卡，下载失败用昵称首字占位圆，无网络依赖。
- **渲染失败兜底**：`main._try_render_card` 捕获一切异常回退纯文本，绝不吞错不回。
- **M6 预留**：`render_card(bg_image=...)` 已支持透传 AI 底图（cover 对齐 + 白纱罩保证文字对比度），anima 联动只需传图。
- **视觉迭代**：三轮预览样图修正——渐变浓度（更白）、底部溢出（月相行与落款重叠）、吉凶大字粗体、幸运网格间距。
- 测试：`tests/test_card.py`（落盘/尺寸/非空白/渲染确定性/换行/粗体变体；需 pillow）。

## v0.2.1 (2026-09-27)

M1 代码审查修复：

- **词库深度校验**：原实现只查顶层键存在——池被清空/档位缺失要到用户抽签时才以 ZeroDivisionError/KeyError 炸掉。抽出 `validate_lexicon()`（池非空、宜忌池 ≥2、点评/祝语覆盖六档、lucky_colors 含 name/hex、phases 含 name/text），加载期即拦截；新增 `tests/test_lexicon.py` 8 组负例。
- **榜单索引**：`list_day` 按 date 查询但主键 (user_id, date) 帮不上忙，补 `idx_fortunes_date` 索引（M3 榜单/PK 的前置准备）。

## v0.2.0 (2026-09-27)

M1 核心抽签：从骨架到可用的纯文本出签。

- **确定性种子**：`seed = SHA-256(日期|用户|盐|nonce)` 派生全部维度（hashlib，无全局随机），同一天同一人跨时刻/跨群结果恒定；`nonce` 供换签卡（M7）重掷。
- **一日一签（D5）**：`(user_id, date)` 主键保证；当日重复请求直接回发已存记录（卡文件优先，其次文本），不重算不重绘。
- **签面内容**：六档吉凶（权重可配）、六维星数（按档位区间取值）、幸运指数（六维合成）、幸运物/色/数字/方位、宜忌各两条（池内不重复）、签文 = 点评 + 幸运物联动句 + 祝语。
- **连续抽签 streak**：首日 1 → 同日幂等 → 次日 +1 → 断签回 1，随签落库并在文案展示（≥2 天）。
- **身份快照（D10）**：昵称/头像/群号随签入库；QQ 平台头像用 qlogo 标准地址。
- **健壮性**：时区非法/无 tzdata 环境两级回退（Asia/Shanghai → 固定 UTC+8）；卡渲染缺失/失败回退纯文本；词库缺键在加载期即报错。
- **测试**：`tests/test_fortune.py`（确定性/分布/词库来源/道具钩子/日期工具）与 `tests/test_store.py`（一日一签/streak 序列/档案 upsert），`uv run --no-project python tests/xxx.py` 直接运行，退出码即结论。

## v0.1.0 (2026-09-27)

- 项目骨架：确定插件定位「萌萌星语 · 每日运势签」，落盘目录规划（`fortune.py` 核心 / `lexicon.py` 词库 / `store.py` 存储 / `card.py` 图卡）。
- 内置词库数据雏形 `data/lexicon/fortune_lexicon.json`：吉凶点评与祝语（六档各池）、幸运物 / 幸运色（含 hex）/ 幸运方位、萌化宜忌、八相月相。
- 打包脚本 `build_zip.ps1`：显式 includeList + 顶层 `.py` 守卫（漏列直接报错），.NET `System.IO.Compression` 手工写条目、正斜杠、套一层插件目录。
- 本版本仅骨架，无功能实现，未打包。
