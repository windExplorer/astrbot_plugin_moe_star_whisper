# 萌萌星语（astrbot_plugin_moe_star_whisper）

AstrBot 今日运势插件：每个用户每天一支专属「星语签」——AI 可选底图 + 萌系图卡 + 签文话语 + 萌化宜忌 + 星座与道具经济。

## 特性

- **每日确定论**：运势由 `SHA-256(日期|用户|盐|nonce)` 确定性推导，一天一签、跨群/私聊全局一致；当天重复请求直接回发已存卡片，零生成成本。
- **签面内容**：吉凶六档（大吉→大凶，权重可配）、六维星数 + 幸运指数、幸运物/色/数字/方位、宜忌各两条、签文话语（点评 + 幸运物联动 + 祝语）。
- **萌系图卡**：Pillow 本地渲染，幸运色驱动卡面配色（每天不同观感），暗色主题可配；字体不打包、多级查找。
- **AI 星象底图**（可选）：安装 [astrbot-comfyui-anima](https://github.com/windExplorer/astrbot-comfyui-anima) 后，LLM 依当日运势生成英文标签提示词，anima 出图作为卡面底图；seed/尺寸透传，失败自动回退渐变底图。
- **LLM 星语**（可选，默认关）：当日首次抽签由 LLM 按运势事实清单改写签文，失败回退本地词库。
- **星座与彩蛋**：生日绑定（只存月日）、星座角标、生日必大吉+金环卡面、愚人节整活、节日词库池、周五摸鱼加成、连签徽章。
- **道具经济**：星尘积分（每签必得、越倒霉补偿越多）+ 换签卡/厄运护身符/幸运香烛/连签保护卡四道具；全流水落库，不可转账不可兑换。
- **群玩法**：`/运势榜`（日/周）、`/运势PK`、群开关、连签徽章。
- **数据全量落库**：SQLite 于 `data/plugin_data/astrbot_plugin_moe_star_whisper/star_whisper.db`（抽签/档案/绘图任务/星尘流水），为统计功能预留口径。

## 指令

| 指令 | 说明 |
| --- | --- |
| `/运势`（别名 `/今日运势` `/星语` `/占卜`） | 抽当日专属星语签 |
| `/运势帮助` | 查看全部指令（帮助图） |
| `/运势榜 [日\|周]` | 群内幸运指数排行 |
| `/运势PK @某人` | 当日幸运指数对决 |
| `/星语绑定 <MM-DD>` | 绑定生日（解锁星座与生日彩蛋） |
| `/星座 [@某人]` | 查看星座与今日吉凶（不泄露生日） |
| `/星尘`（`/运势背包`） | 星尘余额与背包 |
| `/运势商店` | 道具与价格 |
| `/运势购买 <名称> [数量]` | 购买道具 |
| `/运势使用 <名称>` | 使用换签卡/护身符/香烛 |
| `/运势补签` | 断签 3 天内消耗连签保护卡补回昨天 |
| `/运势开关 on\|off` | 群级启停（仅 AstrBot 管理员） |
| `/运势发放 @用户 <±n>` | 手动调整星尘（仅 AstrBot 管理员） |
| `/运势调试 [重抽\|重绘\|重置]` | 测试用（仅管理员）：重抽=换种子重跑全流程；重绘=按已存结果重渲染卡面；重置=清除今日记录 |

## 配置

`_conf_schema.json` 全量键位（AstrBot 配置页自动生成）：时区、盐值、吉凶权重、输出方式、卡面主题/字体/尺寸、LLM 星语、每日推送（时间/开关）、anima 联动（工作流/提示词语言与形式/超时）、道具价格等。

## 字体说明（图卡）

不打包字体，按以下顺序查找：配置 `card_font_path` → `data/plugin_data/astrbot_plugin_moe_star_whisper/fonts/` → `data/fonts/` → 系统字体（Windows 微软雅黑 / Linux Noto CJK）。找不到可用字体时自动回退纯文本出签。

## 依赖

- AstrBot 4.28+
- `pillow`（图卡）
- `tzdata`（时区；缺省环境自动回退 UTC+8）
- anima 底图联动需另装 astrbot-comfyui-anima 并开启 `draw_enabled`

## 开发

```powershell
# 运行测试（核心模块无 astrbot 运行时依赖，直接跑；退出码即结论）
uv run --no-project python tests/test_lexicon.py
uv run --no-project python tests/test_fortune.py
uv run --no-project python tests/test_store.py
uv run --no-project --with pillow python tests/test_card.py
uv run --no-project python tests/test_main_structure.py

# 打包（产物在 dist/，同名版本已存在会拒绝打包）
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_zip.ps1
```

设计文档见 `docs/PRD.md`（含全部决策记录 D1-D11 与 API 依据）。
