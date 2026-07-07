# PR Description Draft

## Summary

A 股每日市场简报 MVP。本次迭代完成从 fixture 流水线骨架到「事实账本 -> 简报 -> 反馈 -> 下一轮」的核心 loop engineering 闭环。

## What Changed

**事实分类可视化**

- 使用结构化 `FactLine` 展示原子事实。
- 将事实按「事实 / 观点 / 推测 / 待确认」分类渲染，并用统一标签与样式区分。
- 报告页和工作台不再依赖 `<pre>` 原样显示 Markdown 星号来表达分栏。

**反馈闭环**

- 新报告会读取上一份同类型报告的反馈，并生成「上一轮反馈回执」章节。
- `AFTER_CLOSE` 与 `PRE_OPEN_UPDATE` 都参与反馈闭环。
- 上一轮语义为严格上一交易日；同日重跑不算上一轮。

**校验结构不变量**

- `one_sentence_conclusion` 只允许 FACT。
- `next_watchlist` / `today_watchpoints` 拒绝 OPINION 和 UNVERIFIED。
- `market_overview` / `sector_strength` 拒绝 UNVERIFIED，并要求 INFERENCE 有派生事实链。
- Pipeline validation 失败时不写入正常报告、事实和快照账本，run 标记为 FAILED，`PipelineResult.report` 为 `None`。

**中文 UI 与新手体验**

- 全站中文界面与产品级免责声明。
- 工作台提供新手引导 tour。
- 运行表单默认中国市场当天日期。
- 反馈评分提示 `1=最差 · 5=最好`。

**工程卫生**

- 标签集中到 `labels.py`，减少模板和报告生成逻辑中的中文标签分叉。
- `static/*.js` 纳入 package data。
- pytest 使用项目内临时目录并禁用 cacheprovider，避免 Windows 临时目录清理导致测试退出码污染。
- 本地过程文件与调试目录通过 `.gitignore` 排除。

## Test Coverage

- `pytest -q`: 105 passed, 1 warning
- `ruff check src tests`: All checks passed

Known warning: Starlette/httpx deprecation warning from FastAPI TestClient; unrelated to this MVP behavior.

## Not Included

- Real market data source integration.
- Browser-level automated tests for `tour.js`.
- FastAPI/httpx dependency upgrade to remove the TestClient deprecation warning.

