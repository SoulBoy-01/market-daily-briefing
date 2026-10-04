# ADR 0006：阶段三真实盘后编排契约

- 状态：提议（待所有者批准）
- 日期：2026-10-05

## 背景

阶段一（审计底座）与阶段二（双源核对 + 发布门禁 + 黄金评测骨架）已合并，接线前的两个已知雷与覆盖缺口已排除（ADR 0005 修订节）。阶段三按设计文档 §14 进入真实数据接入。ADR 0003 已固定单运行生命周期，实施计划任务 12/13 已定义动作拆分与 Web 工作流；本契约把「采集、审核、发布如何组合成一次真实运行」写死，作为施工依据。批准本契约不等于解锁真实模式——真实模式的启用仍被 ADR 0001 的来源登记阻塞。

## 决策（提议）

1. **入口拆分**：`PipelineRequest` 拆为共享字段（`run_id` / `report_date` / `report_type` / `enabled_modules`）加上 fixture 专用请求（携带 `fixture_path`）与 real 专用请求（不携带）。real 模式只接受 `after_close`，对 `pre_open_update` 显式拒绝；不存在 fixture 静默回退。
2. **三个可独立失败、可恢复的动作，共享同一 `run_id`**（落实 ADR 0003）：
   - `collect-real-after-close`：创建 run → 双来源市场数据采集（两个 `MarketDataCollector` 实例）→ 官方来源采集（产出待审核候选与三态检查结果）→ `reconcile_core_indices` 双源核对 → `evaluate_after_close_gate` → 暂存快照 → 持久化候选 / 警告 / 覆盖状态。有待审核候选 → `AWAITING_REVIEW`；无候选且门禁满足 → 允许直接进入发布动作。
   - `review-candidate`：存储层 `review_candidate` 已存在，CLI 与 Web 做薄包装；pending → approved/rejected 不可逆。
   - `publish-real-after-close`：确认无 pending 候选 → 构造事实（批准候选项经 `build_fact_from_approved_candidate`；核对通过的指数观测；板块行）→ `validate_real_publishable_facts` → `build_report` + `validate_report_sections` → `publish_run_bundle`（哈希、信任根、审计链接校验全部沿用既有协议）。
3. **事实构造归属**：核对器输出「已核对观测」不直接成为事实（阶段二既定边界）；真实事实只来自 (a) 人工批准的官方候选、(b) 核对通过的指数观测、(c) 板块行情行。市场温度第一版允许整体缺失并降级为警告（设计 §7.2），其采集器随阶段三本体补建。
4. **真实校验接线点**：`validate_real_publishable_facts`（当前无调用点）只挂在真实发布动作中；fixture 教学路径保持现状，`UNVERIFIED` 仅用于教学分栏展示。
5. **装配方式**：`real_pipeline` 显式构造 collector 实例，不引入 Collector 协议注入（ADR 0005 否决清单）；数据提供方经已登记来源注册表选择，注册表为空时真实模式整体禁用并给出明确错误。
6. **Web 工作流**（任务 13）：审核队列与「发布盘后概览」操作调用同一管线动作，入口层不复制发布规则；候选展示标题、发布时间、原始链接、摘录与快照哈希。

## 后果

- CLI 新增 `collect-real` / `review-candidate` / `publish-run` 子命令；fixture 命令保持兼容。
- 两个真实 `MarketDataClient` 实现与按来源定制的官方解析器是阶段三本体任务，依赖来源登记结果（调研进行中）。
- 市场温度、板块等可降级项缺失时走 `COMPLETED_WITH_WARNINGS`，界面按既有覆盖状态展示。
- 本契约获批后，任务 12 可直接开工且不依赖来源登记完成——管线骨架可先用合成客户端验证（`mock_real` 模式），真实客户端随登记结果接入。
