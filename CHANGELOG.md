# 更新日志

> 倒序（最新在上）。版本唯一来源为 `metadata.yaml` 的 `version`，条目号与其严格一致。

## v1.3.2 (2026-09-27)

真机联调修复：LLM 星语不生效、头像占位、诊断可见性。

- **LLM 星语/生图提示词取不到模型（关键）**：`get_using_provider()` 此前未传会话标识——AstrBot 的模型按会话（umo）绑定，缺省可能取到空提供商，导致「LLM 星语开启但没生效」「底图提示词退回本地模板」。两处改为 `get_using_provider(event.unified_msg_origin)`。
- **失败原因可见**：LLM 链路的每种结局（未开启 / 会话无提供商 / 超时 / 返回为空 / 异常）都写入 payload 的 `llm_note`，调试面板的今日签摘要以红色标签直接显示原因，不再静默瞎猜。
- **QQ 头像占位（问题 4）**：头像下载失败在容器环境最常见的原因是缺 CA 证书导致 HTTPS 校验失败。`card._fetch_avatar` 现在失败后自动降级「跳过证书校验」重试一次，仍失败才用昵称首字占位，并把失败原因写进 AstrBot 日志（`moe_star_whisper` logger）。
- 关于「重置后还是同一支签」：v1.3.1 的种子序号修复已生效（已核对落盘代码），但**升级前抽的签没有存过序号**——升级后第一次「重置→重抽」仍会同签一次，从第二次重置起每次都是新签。另外面板的「重绘」是按已存结果重渲染（不换签），要换签请用「重抽」或聊天内抽签。

## v1.3.1 (2026-09-27)

修复：调试重置后再抽得到一模一样的签。

- **根因**：重置只删除签记录，种子序号（nonce）存在签 payload 里随之丢失——下次抽签回落到 nonce=0 的同一颗种子，确定论算出完全相同的结果。
- **修复**：种子序号迁移到**用户档案**（`profiles.seed_date` / `seed_nonce`，旧库自动补列）。`_roll_daily` 的 nonce 缺省时按「当日档案序号 + 1」自增并回写——首抽为 0，换签卡、WebUI 重抽、调试重置后的重抽都会自动换种子；同一天内每次抽签都是新签，且删除记录也无法重置种子（防刷星尘的重抽不再发奖，nonce=0 首抽才发）。
- **统一机制**：换签卡与 WebUI 重抽不再自行计算 nonce，全部走 `_roll_daily` 的档案序号自增，`reroll_count` 由其统一写入 payload。
- store：`upsert_profile` 支持 seed 字段；测试补「删签后序号仍在档案」断言。

## v1.3.0 (2026-09-27)

配置页重做：按 Dashboard 实际渲染规则修正表单组件与文案分层（对照 `dashboard/src/components/shared/ConfigItemRenderer.vue` 源码）。

- **label / hint 分层**：`description` 是表单字段名（全部改为一行短名，如「种子盐值」「出图超时」），原先塞在里面的格式说明、注意事项、默认行为全部移入 `hint`（字段下方灰色说明）——之前 24 个键全是长句 description、无 hint，label 与描述混为一谈。
- **组件修正**：LLM 人设与底图提示词模板从 `string`（单行框）改为 **`text`**（多行 textarea）；`draw_timeout` 加滑条（30~600 秒）；`disabled_groups` 从逗号分隔字符串改为 **`list`** 动态条目列表（加一行删一行，main 读取兼容新旧两种类型，群开关写回同步改为列表）。
- **下拉中文显示**：四个枚举（出签方式/卡面主题/提示词语言/形式）加 `labels` 数组——渲染器按 index 与 options 配对显示中文名，存储值不变。注意 labels 写字符串是 i18n 键不会按逗号拆分，必须用数组。
- **守卫升级**：`test_config_schema` 新增两条——description 必填且 ≤40 字（逼短 label）、string+options 的 labels 必须是与 options 等长的数组。
- 配置兼容：旧档的字符串型 `disabled_groups` 仍可读（类型不匹配时 AstrBot 会按新 schema 自动回填默认空列表）。

## v1.2.3 (2026-09-27)

修复调试面板报错：`'StarWhisperPlugin' object has no attribute 'store'`。

- **根因**：`webui_api.py` 沿用了 user_gateway 的命名习惯访问 `plugin.store`，而本插件 main.py 的属性名是 `self._store`——本地测试的 stub 恰好也带 `store` 属性，契约错位被掩盖到真机才炸。
- **修复**：`webui_api.py` 全部 13 处 `plugin.store` → `plugin._store`。
- **守卫**：`test_main_structure` 新增**跨模块契约审计**——收集 main.py 主类的全部成员（方法 + `self.X` 实例属性赋值），断言 `webui_api.py` 引用的每个 `plugin.<attr>` 都真实存在（`context` 等基类属性白名单豁免）；stub 与真实接口的契约漂移今后在本地测试期拦截。

## v1.2.2 (2026-09-27)

修复真机安装失败：`_conf_schema.json` 的 object 类型缺 `items` 导致 `KeyError: 'items'`。

- **根因**（真机日志定位）：AstrBotConfig 的 `_parse_schema` 对 `type: "object"` 会递归解析 `v["items"]` 子 schema，缺 `items` 直接 `KeyError`，整个插件加载失败。`grade_weights` 与 `item_prices` 用了无 `items` 的 object。
- **修复**：两键类型改为 **`dict`**（自由键值映射，AstrBot 4.28.1 合法类型，用户自定义键保留、无需 items 子 schema），默认值保留。
- **守卫**：新增 `tests/test_config_schema.py`——校验 `_conf_schema.json` 全部 type 在 `DEFAULT_VALUE_MAP` 合法集内、object 必须带非空 items、list 建议带 items 模板；此类问题今后在本地测试期拦截，不必再等真机。

## v1.2.1 (2026-09-27)

修复调试面板的确认交互：原生 confirm 在 sandbox iframe 里会被静默忽略。

- **问题（根因）**：v1.2.0 的重抽/重绘/重置确认用 `window.confirm`。AstrBot 插件 Page 的 sandbox 是 `allow-scripts allow-forms allow-downloads`（不含 `allow-modals`），按 sandbox 规范原生 confirm/alert 会被浏览器**静默忽略**——confirm 恒返回 false，三个操作在真机上永远「取消」，面板废掉。本地 file:// 冒烟没有 sandbox，恰好掩盖了这一点。
- **修复**：确认改为**页面内两段式按钮**——第一次点击按钮变「再点一次确认」，6 秒内再点才执行，超时自动恢复原文案；零原生弹窗依赖。结果提示仍是页面内消息条（从未用过 alert）。
- **冒烟（桩桥真浏览器）**：单次点击进确认态零误发、两连点正确执行、6 秒超时自动恢复、全程 confirm/alert 调用计数为 0；顺带修复重抽成功提示被状态刷新清空的交互问题（上轮已修）。

## v1.2.0 (2026-09-27)

调试迁移到 WebUI：插件 Page 调试面板（仅管理员），撤掉 v1.1.0 的聊天调试指令。

- **`pages/debug/index.html`（单文件面板，零依赖原生 JS）**：输入任意 QQ 号 → 查看今日签摘要（吉凶/指数/签文/连签/星尘与背包/卡文件状态）、档案与关键配置标签、当日绘图任务表（状态/工作流/耗时/错误）；操作按钮：重抽（换种子重算 + LLM 签文 + 复用当日 AI 底图渲染）、重绘（按已存结果重渲染，改卡面样式后看效果）、重置（删记录与卡文件，带确认）。
- **`webui_api.py`（桥接 API）**：`/debug/state|redraw|rerender|reset` 四路由，经 `register_web_api` 挂 Dashboard 登录墙内（沿 user_gateway 控制台访问口径，仅管理员账号使用）；返回信封严格遵循 AstrBot 桥接约定（`status=ok/error`）；uid 支持 query/body 双通道。后端核心逻辑抽成 `_debug_state_core` / `_debug_reset_core` 纯函数，脱离 quart 可直测。
- **边界说明**：WebUI 触发没有聊天事件，重抽不新绘 anima AI 底图（复用当日 `draw_jobs` 成功记录或默认渐变）；AI 底图新绘仍由聊天内抽签/换签触发。
- **撤回**：v1.1.0 的 `/运势调试` 聊天指令移除（结构守卫反向锁定：main.py 不得再出现 debug_cmd）。
- 测试：新增 `tests/test_webui.py`（信封形状、缺 uid/未初始化错误路径、state/reset core 含删卡验证），六套测试全绿。

## v1.1.0 (2026-09-27)

调试支持：`/运势调试`（仅 AstrBot 管理员，测试期用）。

- **重抽**（默认）：换种子重跑完整首抽流程——LLM 签文、anima 底图、合卡全部重来，每次出新图；streak 保持不变，不重复发星尘（nonce 递增，与换签卡同机制但不消耗卡）。
- **重绘**：不重抽，按已存 payload 重渲染卡面（底图优先复用当日 `draw_jobs` 里成功的 AI 底图）——调 `card.py` 样式后立即看效果，不必重抽。
- **重置**：删除今日签记录与卡文件，用普通 `/运势` 重新抽取（星尘会再次发放，仅测试环境使用）。
- store 新增 `delete_fortune`；测试补删除断言、结构守卫补 `debug_cmd`。

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
