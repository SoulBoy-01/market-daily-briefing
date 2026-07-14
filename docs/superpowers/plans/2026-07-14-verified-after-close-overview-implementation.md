# A 股盘后市场概览（验证版）实施计划

日期：2026-07-14
依据：`docs/superpowers/specs/2026-07-07-real-data-source-mvp-design.md`

## 目标

在不破坏现有 fixture 教学路径的前提下，按依赖顺序实现：

1. 追加式审计底座与候选事实模型；
2. 黄金评测骨架与发布门禁；
3. 真实盘后数据、官方候选项人工审核和发布；
4. 可执行、可回执的单维护者反馈闭环。

每个行为变化都使用 TDD：先新增失败测试，再实现最小代码，通过目标测试后运行完整测试与 Ruff。网络冒烟测试始终显式启用，不进入默认测试套件。

## 总体架构

真实模式拆成三个显式动作：

```text
collect -> review candidates -> publish
```

- `collect`：抓取并写入 run 专属暂存区，保存快照、核对结果、候选项和警告；
- `review`：本地维护者批准或拒绝官方候选项，追加审核事件；
- `publish`：执行所有硬门禁，通过原子可见与恢复协议写入正常审阅账本并生成报告。

fixture 模式继续走现有教学管线，但共享 run 唯一性、快照哈希和终态保护等审计不变量。

## 建议提交边界

每个任务独立提交，避免把数据迁移、管线、真实网络和 UI 混在一个 commit 中：

1. `feat: enforce append-only audit records`
2. `feat: add evidence candidate review model`
3. `feat: add structured run warnings and coverage`
4. `test: add verified overview golden harness`
5. `feat: enforce after-close publication gates`
6. `feat: reconcile dual-source market data`
7. `feat: collect official evidence candidates`
8. `feat: add candidate review workflow`
9. `feat: publish verified after-close overview`
10. `feat: apply feedback directives to next report`
11. `docs: document source licenses and local operation`

---

## 阶段一：可信审计底座

### 任务 1：run 唯一性、状态机与追加式事件

涉及文件：

- 修改 `src/market_briefing/domain.py`
- 修改 `src/market_briefing/storage.py`
- 修改 `src/market_briefing/pipeline.py`
- 修改 `src/market_briefing/app.py`
- 修改 `tests/test_domain.py`
- 修改 `tests/test_storage.py`
- 修改 `tests/test_pipeline.py`
- 修改 `tests/test_web.py`

步骤：

1. 在测试中定义允许的状态迁移，并验证终态不可再次迁移。
2. 增加 `AWAITING_REVIEW`，并新增不可变 `RunEvent` 记录每次状态变化。
3. 新增 `BriefingStore.create_run()`：只允许插入，重复 `run_id` 抛出领域异常。
4. 新增 `transition_run()`：校验状态机，更新 run 投影并追加 `run_events`。
5. 保留旧 `save_run()` 仅用于迁移期内部兼容，随后把主管线和测试改为新 API；最终删除或限制它对终态的覆盖能力。
6. fixture CLI 与 Web 对重复 run 返回清晰中文错误，不覆盖旧文件或数据库记录。
7. 验证同一 report 日期允许多个不同 run ID，修订关系通过可选 `supersedes_run_id` 表达。

完成标准：

- 重复 run ID 在采集前被拒绝；
- 每次状态迁移有事件记录；
- 终态不可修改；
- 现有 fixture 正常运行。

### 任务 2：快照哈希、暂存区与诊断区

涉及文件：

- 修改 `src/market_briefing/domain.py`
- 修改 `src/market_briefing/config.py`
- 修改 `configs/default.yaml`
- 修改 `src/market_briefing/storage.py`
- 修改 `src/market_briefing/collectors/fixtures.py`
- 修改 `src/market_briefing/collectors/market_data.py`
- 修改 `src/market_briefing/collectors/official_sources.py`
- 新增 `src/market_briefing/audit.py`
- 修改对应 collector、storage、pipeline 测试

步骤：

1. 先测试同一快照文件可复算 SHA-256，文件被改动后校验失败。
2. 为 `RawSnapshot` 增加 `content_sha256`、实际提供方、许可登记引用和来源口径元数据。
3. 新增统一快照写入函数，按字节写入后计算哈希；collector 不再各自实现写文件细节。
4. 配置 `staging_dir` 与 `diagnostics_dir`，所有采集先进入 `staging/<run_id>`。
5. 门禁通过后把 run 目录原子重命名到最终不可变路径，再由数据库发布事务建立正常账本引用；失败时移动到 `diagnostics/<run_id>`。
6. 任何路径移动前后都校验路径位于配置根目录，避免目录穿越。
7. 增加测试：校验失败后正常账本无快照，诊断区存在明确标记的材料。

完成标准：

- 正常账本里的每个快照均可通过哈希验证；
- 失败 run 的文件不出现在正常来源索引；
- collector 不再提前写入正式 `raw_dir`。

### 任务 3：已发布记录禁止覆盖与可恢复发布

涉及文件：

- 修改 `src/market_briefing/storage.py`
- 修改 `src/market_briefing/pipeline.py`
- 修改 `tests/test_storage.py`
- 修改 `tests/test_pipeline.py`

步骤：

1. 先测试重复 `snapshot_id`、`fact_id`、`report_id` 被拒绝，而不是 update。
2. 将 `source_snapshots`、`facts`、`reports` 的写入从 upsert 改为 insert-only。
3. 新增 `publish_run_bundle()`，在一个 SQLite 事务中写入快照、事实、报告、警告引用和最终 run 状态；该事务是正常审阅账本可见性的唯一开关。
4. 发布前将已通过门禁的目录从暂存区原子重命名到最终不可变路径，再提交数据库事务。
5. 新增恢复扫描：最终路径中没有已发布 run 引用的孤立目录移入诊断区；数据库引用的文件缺失或哈希错误则标记审计损坏并阻断展示。
6. 增加故障注入测试，模拟目录重命名前失败、重命名后数据库提交前崩溃、数据库事务失败和已发布文件损坏。

完成标准：

- 已发布材料不可覆盖；
- 任意发布步骤失败时，不产生半份可见的正常报告；重启后可确定性恢复孤立文件。

### 任务 4：候选项与审核事件模型

涉及文件：

- 修改 `src/market_briefing/domain.py`
- 修改 `src/market_briefing/storage.py`
- 新增 `src/market_briefing/review.py`
- 修改 `tests/test_domain.py`
- 修改 `tests/test_storage.py`
- 新增 `tests/test_review.py`

步骤：

1. 定义并测试 `EvidenceCandidate`、`CandidateReviewEvent`、`CandidateReviewStatus`。
2. 候选项本体 insert-only；批准/拒绝通过追加审核事件表达。
3. 实现当前审核状态投影，拒绝对已终结候选项重复审核。
4. 实现“批准候选项生成新 `AtomicFact`”的纯函数；事实指向候选项与快照。
5. 保留旧 fixture 对 `UNVERIFIED` 的读取兼容，但真实模式发布器拒绝该分类。

完成标准：

- 审核历史不可被覆盖；
- 只有批准候选项能生成正式事实；
- 拒绝候选项不会进入报告。

### 任务 5：结构化警告与模块覆盖状态

涉及文件：

- 修改 `src/market_briefing/domain.py`
- 修改 `src/market_briefing/storage.py`
- 修改 `src/market_briefing/labels.py`
- 修改 `src/market_briefing/templates/dashboard.html`
- 修改 `src/market_briefing/templates/report.html`
- 修改 storage/web 测试

步骤：

1. 定义 `RunWarning` 和 `ModuleCoverage`，覆盖 `covered / no_updates / pending_review / failed / unsupported`。
2. 新增 `run_warnings`、`module_coverage` 表和查询 API。
3. Dashboard 与报告页显示来源、模块、错误摘要和覆盖状态，不展示堆栈。
4. `error_message` 只保留运行级失败摘要，不承担警告集合存储。

完成标准：

- “无新增”“待审核”“检查失败”“暂未支持”在数据层和 UI 中可区分；
- 警告可在重启后恢复显示。

---

## 阶段二：黄金评测与发布门禁

### 任务 6：10 日黄金评测数据格式与运行器

涉及文件：

- 新增 `tests/golden/README.md`
- 新增 `tests/golden/schema.json` 或等价 Pydantic 模型
- 新增 `tests/golden/cases/*.json`
- 新增 `tests/test_golden_evaluation.py`
- 新增 `src/market_briefing/evaluation.py`

步骤：

1. 先用两个最小案例定义格式：正常日与来源失败日。
2. 每个案例保存核心指数、交易日、市场温度、板块口径、官方检查结果、预期警告和来源证据引用。
3. 实现离线评测器，输出逐项错误而非单一布尔值。
4. 扩展到 10 个代表性交易日/场景：普涨、普跌、放量、缩量、板块分化、有官方事项、无新增、官方失败、双源冲突、过期数据。
5. 将黄金集测试加入默认 pytest，但不请求网络。

完成标准：

- 黄金集完全离线、可复现；
- 错误能定位到日期、指标、来源和门禁。

### 任务 7：盘后市场完整性与新鲜度门禁

涉及文件：

- 新增 `src/market_briefing/gates.py`
- 修改 `src/market_briefing/domain.py`
- 新增 `tests/test_gates.py`
- 修改 `tests/test_validation.py`

步骤：

1. 用表驱动测试固定三个核心指数代码和必需字段。
2. 定义中国市场交易日输入契约；第一版由数据源返回交易日并与请求日期严格匹配，非交易日显式拒绝。
3. 核心指数缺失、重复、过期或数值非法时产生阻断错误。
4. 市场温度和板块缺失产生结构化警告，不阻断发布。
5. 正式真实报告拒绝 `UNVERIFIED`；推测必须引用当前发布账本中的事实。

完成标准：

- 黄金集中所有硬门禁漏拦截为 0；
- 所有可降级缺口都有明确警告。

### 任务 8：双来源核对器

涉及文件：

- 修改 `src/market_briefing/collectors/market_data.py`
- 新增 `src/market_briefing/reconciliation.py`
- 修改 `tests/test_real_source_adapters.py`
- 新增 `tests/test_reconciliation.py`

步骤：

1. 将市场客户端输出规范化为带 `provider_id`、`trade_date`、`symbol`、`close`、`change_pct` 的记录。
2. 测试来源独立性：相同 `provider_id` 的两个客户端不能算双来源。
3. 按报告展示精度比较收盘点位和涨跌幅；比较精度作为显式配置或常量并写入快照元数据。
4. 一致时生成核对通过结果；冲突时生成阻断错误和诊断记录，不生成正式事实。
5. 板块数据保留单源路径，但必须带供应商和分类口径。

完成标准：

- 核心指数只能由双源一致结果生成事实；
- 冲突绝不被静默选择或平均。

---

## 阶段三：真实盘后采集、审核与发布

### 任务 9：来源登记与客户端装配

涉及文件：

- 新增 `configs/sources.yaml`
- 新增 `docs/source-register.md`
- 修改 `src/market_briefing/config.py`
- 新增 `src/market_briefing/sources.py`
- 修改 `pyproject.toml`（仅在明确需要依赖时）
- 修改配置测试

步骤：

1. 定义来源登记配置模型和许可字段，缺少许可审查状态时拒绝 real 模式启用。
2. 登记两个独立核心指数来源及板块来源的实际提供方，不把 AkShare 当作提供方。
3. 登记证监会、上交所、深交所的列表页/详情页和允许用途结论。
4. 通过依赖注入装配客户端，测试中仍使用 fake/mock。
5. 若真实条款尚未核清，将来源标记为 `evaluation_only`，Web 不开放真实运行。

完成标准：

- 每次真实采集都能追溯到来源登记；
- 许可状态可以阻止不允许的运行模式。

### 任务 10：真实市场采集

涉及文件：

- 修改 `src/market_briefing/collectors/market_data.py`
- 新增实际客户端模块，例如 `src/market_briefing/clients/market_*.py`
- 修改 `tests/test_real_source_adapters.py`
- 新增 opt-in 冒烟测试脚本，不加入默认 pytest

步骤：

1. 先用录制的、许可允许保存的响应 fixture 完成解析测试。
2. 实现两个来源的核心指数客户端与一个板块/温度来源客户端。
3. 保存原始响应，不只保存规范化后的列表。
4. 将真实响应交给阶段二核对器和门禁，不在客户端内决定是否发布。
5. 增加超时、HTTP 错误、字段变化和空数据的结构化错误映射。

完成标准：

- 默认测试无网络；
- opt-in 冒烟可以获取真实数据并生成暂存快照；
- 数据未过门禁前不会成为正式事实。

### 任务 11：官方列表页、详情页与候选项

涉及文件：

- 修改 `src/market_briefing/collectors/official_sources.py`
- 修改 `tests/test_real_source_adapters.py`
- 新增按来源拆分的解析 fixture 和测试

步骤：

1. 为每个官方来源建立专用解析器，不使用通用“第一个标题 + 第一个段落”。
2. 列表页提取标题、详情 URL、发布时间；严格应用中国市场时区窗口。
3. 详情页保存独立快照，并提取直接可核对的短摘录。
4. 输出 `checked_no_updates`、`candidates_found` 或 `check_failed`。
5. 详情失败时保留列表候选信息并产生警告；不得编造摘要。

完成标准：

- 无新增与抓取失败可重复测试；
- 抓取结果始终先进入候选项，不直接生成高置信度事实。

### 任务 12：真实 run 收集与发布服务

涉及文件：

- 修改 `src/market_briefing/pipeline.py`
- 可新增 `src/market_briefing/real_pipeline.py`
- 修改 CLI 参数与测试
- 新增 `tests/test_real_pipeline.py`

步骤：

1. 将 `PipelineRequest` 拆分为共享字段与 fixture/real 专用请求，避免 real 请求携带 `fixture_path`。
2. 实现 `collect_real_after_close()`：创建 run、采集暂存材料、核对市场数据、保存候选项/警告/覆盖状态。
3. 有待审核候选项时进入 `AWAITING_REVIEW`；没有候选项且门禁满足时允许直接发布。
4. 实现 `publish_real_after_close()`：确认无 pending 候选、构造事实和报告、执行最终门禁，并通过可恢复发布协议进入正常账本。
5. CLI 增加显式子命令或动作：`collect-real`、`review-candidate`、`publish-run`；fixture 命令保持兼容。

完成标准：

- real 模式拒绝 `pre_open_update`；
- 采集、审核、发布可以独立失败并保留清晰状态；
- 不存在 fixture 静默回退。

### 任务 13：人工审核与真实盘后 Web 工作流

涉及文件：

- 修改 `src/market_briefing/app.py`
- 新增或修改 Jinja 模板
- 修改 `src/market_briefing/static/styles.css`
- 修改 `tests/test_web.py`

步骤：

1. Dashboard 增加真实盘后采集入口，只允许 `after_close`。
2. 增加 run 详情页，展示双源核对、覆盖状态、警告和待审核候选项。
3. 候选项展示标题、发布时间、原始链接、直接摘录和快照哈希；提供批准/拒绝及审核备注。
4. 所有候选项处理完成后显示“发布盘后概览”操作；发布前再次执行门禁。
5. 真实报告标题改为“A 股盘后市场概览（验证版）”，并醒目标识未覆盖模块。
6. 用 TestClient 覆盖 collect -> review -> publish 全流程和所有错误回填。

完成标准：

- 用户不需要 CLI 即可完成真实盘后工作流；
- 页面不会把候选项、警告或 fixture 内容伪装成正式事实。

---

## 阶段四：可执行反馈闭环

### 任务 14：反馈指令编译与安全边界

涉及文件：

- 修改 `src/market_briefing/domain.py`
- 修改 `src/market_briefing/feedback.py`
- 修改 `src/market_briefing/storage.py`
- 新增 `tests/test_feedback_directives.py`

步骤：

1. 定义 `FeedbackDirective` 和 `DirectiveApplication`。
2. 将标签映射为有限、结构化动作：压缩章节、强化引用、检查风险覆盖、降低观点密度等。
3. 用户备注仅作为维护者上下文保存，不直接成为可执行指令或 LLM 提示。
4. 指令不得修改事实、审核结果、置信度、双源核对或发布门禁。
5. 保存每条指令的 `applied / not_applied` 和原因。

完成标准：

- 每种允许反馈都有确定性行为或明确的不可执行原因；
- 恶意备注不会穿透到生成控制层。

### 任务 15：报告生成应用反馈并展示回执

涉及文件：

- 修改 `src/market_briefing/reporting.py`
- 修改 `src/market_briefing/pipeline.py`
- 修改报告模板
- 修改 reporting、pipeline、web 测试

步骤：

1. 报告构建接收结构化指令，不再只接收反馈摘要字符串。
2. 对章节长度、排序、覆盖检查和引用可见度应用允许动作。
3. 新增“上一轮反馈执行回执”，区分已执行与未执行及原因。
4. 增加回归测试：表达发生预期变化，但事实集合、分类和来源不变。
5. 在黄金评测中加入反馈前后对照案例。

完成标准：

- feedback -> directive -> changed report -> receipt 全链路可观察；
- 事实正确性与覆盖硬指标不下降。

---

## 最终验证

每个任务先运行最小相关测试，阶段完成后运行：

```powershell
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m ruff check src tests
```

阶段三还需手动执行一次 opt-in 网络冒烟和浏览器演练，记录：

- 两个核心指数来源的实际提供方和核对结果；
- 官方来源无新增、发现候选、抓取失败三种状态；
- 候选批准/拒绝与发布；
- 快照哈希复算；
- 警告与未覆盖模块显示；
- 反馈指令在下一轮的执行回执。

只有 10 日黄金集硬指标全部通过，才可以称为“真实数据 MVP 完成”。
