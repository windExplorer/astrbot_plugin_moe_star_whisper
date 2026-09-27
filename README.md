# 萌萌星语（astrbot_plugin_moe_star_whisper）

AstrBot 今日运势插件：每个用户每天一支专属「星语签」——签文话语 + 六维运势 + 萌化宜忌 + 萌系图卡。

## 特性

- **每日确定论**：运势由 `SHA-256(日期|用户|盐)` 确定性推导，当天无论查多少次、在哪个群查结果都一样；次日自动换签。
- **一日一签**：签全局统一（跨群/私聊一致），当天重复请求直接回发已存卡片，零生成成本。
- **签面内容**：吉凶六档（大吉→大凶，权重可配）、六维星数 + 幸运指数、幸运物/幸运色/幸运数字/幸运方位、今日宜忌、2~3 句签文话语。
- **萌系图卡**：Pillow 本地渲染，幸运色驱动卡面配色；字体不打包、多级查找（见下）。
- **数据全量落库**：SQLite 存于 `data/plugin_data/astrbot_plugin_moe_star_whisper/star_whisper.db`，抽签记录 / 用户档案 / 绘图任务 / 星尘流水全量保留，为统计功能做准备。

## 指令

| 指令 | 说明 |
| --- | --- |
| `/运势`（别名 `/今日运势` `/星语` `/占卜`） | 抽当日专属星语签 |

## 字体说明（图卡）

为保证安装包体积，**不打包字体**。按以下顺序查找中文字体：

1. 配置项 `card_font_path` 指定的路径；
2. `data/plugin_data/astrbot_plugin_moe_star_whisper/fonts/` 下的任意 `.ttf/.ttc/.otf`；
3. `data/fonts/`；
4. 系统字体目录（Windows：微软雅黑等；Linux：Noto Sans CJK 等）。

找不到可用字体时自动回退纯文本出签，不会报错刷屏。

## 开发

```powershell
# 运行测试（无 astrbot 运行时依赖，直接跑）
uv run --no-project python tests/test_fortune.py
uv run --no-project python tests/test_store.py

# 打包（产物在 dist/，同名版本已存在会拒绝打包）
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_zip.ps1
```

设计文档：见工作区 `docs/astrbot_plugin_moe_star_whisper_PRD.md`。
