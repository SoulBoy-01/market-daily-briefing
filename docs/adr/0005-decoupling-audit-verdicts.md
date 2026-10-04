# ADR 0005：2026-10 解耦审计结论与执行顺序

- 状态：已接受
- 日期：2026-10-04

## 背景

阶段一（审计底座）与阶段二（黄金评测骨架 + 双源核对 + 发布门禁）已完成，阶段三（真实数据源接入）未开始。2026-10-04 以 59 个独立代理对全仓做了对抗性解耦审计：深读 10 个子系统、三透镜耦合图谱、生成 14 条解耦候选，每条候选再由事实核验、审计安全、成本收益三个透镜独立证伪。结果为 9 条证伪、5 条修正、0 条按原方案完全存活；多个独立透镜在互不知情的情况下指向同一结论。

审计同时以实验确认了两个零保护缺口：删除 `app.py` 启动时的孤儿目录回收整块后 234 个测试仍然全绿（该副作用零测试覆盖）；向 schema 注入 ADR 0002 类列漂移（加列不写迁移）后测试同样全绿（SCHEMA 与 `_migrate_schema` 的一致性无任何测试守护）。

## 决策

1. ADR 0002（哈希已发布报告文件）的实施优先于任何解耦重构。它是唯一命中「保留完整审计链」硬约束的缺口，需求已接受而代码未实现。
2. 阶段三接线前否决以下解耦方案（对后续所有实现者生效，避免重复评估）：
   - 向 `run_fixture_pipeline` 注入 Collector 协议并保留 `fixture_path` 回退——真实采集器的门禁输入在 pipeline 内零消费者，注入会产出账本中与 fixture 无法区分、未经双源核对的报告；
   - 为 Web 层抽 `ReportReader` 可替换端口——实测一个返回空 `published_run_locations` 的替身会把磁盘上合法发布的目录当孤儿删除；
   - 为 `official_sources` 抽 `HttpFetcher` 协议——httpx 在 src 内仅 2 行、单实现无方差，且该文件已排期整体重写；
   - 把快照文件读取下沉为新存储原语——完整性门禁已在读取前一行执行；
   - 拆出候选审核生命周期模块——`save_candidate` 经终态守卫读第三张表 `runs`，不是自洽聚合；
   - 拆出 publication 规则模块——`_assert_run_accepts_ledger_append` 属于六条普通写路径而非发布协议，且宣称的 import 消减算术上不成立；
   - 引入可注入 Clock 协议——声称不可测的场景仓库已有绿测试，既有惯用法是把时间戳当数据传入 frozen dataclass；
   - 为 `generation_provider` 接 build_provider 工厂——当前收益为零，且 `llm.py` 回退路径丢失 `previous_feedback_summary`，接线前必须先修。
3. 批准并在本阶段执行的小步：
   - 新增 SCHEMA 与 `_migrate_schema` 的一致性漂移测试，作为 ADR 0002 动 schema 前的安全网；
   - 统一 run 身份校验强度，使 `report_date=2026-02-30` 返回 400 而非 500；
   - `validate_report_sections` 对词汇表外的 section_id 显式拒绝，替换静默放行；
   - 为存储层引入信任根校验，持久化路径必须落在配置目录树内；
   - 清理死代码：`save_run` 别名、`published_run_ids`、`facts_by_id` 死上下文、配置中的死键。
4. 阶段三接线前的两个已知雷，修复必须先于接线：
   - `official_sources.py` 直接产出 `classification=FACT`、`confidence="high"` 的 AtomicFact，claim 取自页面 h1 与首个段落，违反设计文档第 8 节；
   - `llm.py` 的回退报告丢失 `previous_feedback_summary`，接通后会静默打断反馈闭环。

## 后果

- `schema.py` 拆分、`app.py` lifespan 化等被修正后的方案，在 ADR 0002 落地且漂移测试就位后另行评估，不与本批次混做。
- `app.py` 孤儿回收路径的零测试覆盖是已登记缺口，留待独立小单元补齐，不在本批次范围内。
- 本 ADR 的否决清单是双向的：无论 Codex 还是 Claude Code 实现，都不得在没有新证据的情况下重提已否决方案。
