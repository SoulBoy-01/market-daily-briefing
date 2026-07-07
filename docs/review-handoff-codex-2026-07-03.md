# 给 Codex 的交付文档 · 第一性原理审查与补丁草案

> 来源：2026-07-03 由独立审查者基于 `claude.md`（第一性原理代码审查专家）出具的审查报告。
> 范围：本次未提交改动（`src/market_briefing/*`、`tests/*`、模板、CSS、新 fixture）。
> 写给你：本文件**只有结论与可落地补丁草案**，不含我把代码逐行复述。可直接据此实现，也可作为 PR/commit 的拆分依据。

---

## 0. 一句话总览

本次改动在"事实账本 → 简报 → 反馈 → 下轮"骨架上完成了审计隔离与安全校验（`_scope_facts_to_run`、`_validate_fixture_path`、`safe_source_url` 都踩到了本质），但**有 4 条基本真理在用户视野里被违反**，导致本次主打的"事实/观点/推测分栏"与"循环"在可视层是假的。下面 5 条 🚨 是上线阻断线，按顺序改即可。

---

## 1. 基本真理（评判标尺）

| # | 基本真理 | 被违反处 |
|---|---|---|
| TR-1 | 可审计性 = 用户视野内任何输出可回指源（fact_id → snapshot → 原始文件） | inference 派生链未展示 |
| TR-2 | 不构成投资建议 = 显式声明 + 结构性阻止软性方向暗示 | 无免责声明；结论段可塞 opinion |
| TR-3 | 事实/观点/推测分离 = **用户看到的呈现**有视觉分级 | `<pre>` 渲染 markdown 使分级失效 |
| TR-4 | 循环 = 反馈**真的影响下一轮** | pipeline 不读 `summarize_feedback`，循环断 |
| TR-5 | onboarding 应在用户最需要时出现 | tour 包在 `{% if review_report %}`，新用户反而看不到 |

---

## 2. 🚨 紧急补丁（上线阻断）

### 紧急 1 · 修复"分栏在用户视野失效"（TR-3，P0-1）

**根因**：`_format_fact_line`（reporting.py:212）输出 `**{label}** {claim} [{fact_id}]`，但模板 `report.html:25` 与 `dashboard.html:93` 用 `<pre class="section-body">{{ section.body }}</pre>` 原样输出——markdown 的 `**` 在浏览器里显示成字面星号。`render_html(markdown)` 只在导出静态 `.html` 文件时走，那个文件大多没人看。

**推荐方案：把分类从字符串约定升级为 DOM 结构**（彻底化见第 5 节实验性方案）。

#### 2.1.1 `domain.py` · 给 `ReportSection` 加结构化 fact 子项

```python
@dataclass(frozen=True)
class FactLine:
    fact_id: str
    classification: FactClassification
    claim: str
    derived_from_fact_ids: tuple[str, ...] = ()

@dataclass(frozen=True)
class ReportSection:
    section_id: str
    title: str
    body: str                 # 仍保留，供 markdown 导出与回退
    fact_ids: list[str]
    status: str
    fact_lines: list[FactLine] = field(default_factory=list)   # 新增：结构化渲染源
```

> `storage.save_report` 里 `sections` 序列化要随之带上 `fact_lines`；`get_report` 反序列化兼容旧记录（缺 `fact_lines` 时回退为空列表，渲染回退到 `body`）。

#### 2.1.2 `reporting.py` · 让 `_section` 顺手构造 `fact_lines`

```python
def _section(section_id: str, lines: list[str], facts: list[AtomicFact]) -> ReportSection:
    return ReportSection(
        section_id=section_id,
        title=BEGINNER_AFTER_CLOSE_SECTION_TITLES[section_id],
        body="\n".join(lines),
        fact_ids=[fact.fact_id for fact in facts],
        status="ok",
        fact_lines=[
            FactLine(
                fact_id=fact.fact_id,
                classification=fact.classification,
                claim=fact.claim,
                derived_from_fact_ids=tuple(fact.derived_from_fact_ids),
            )
            for fact in facts
        ],
    )
```

`_classification_lines` 段同理：把每条 fact 包成 `FactLine`，分类作为分组键。

#### 2.1.3 模板 · 用 Jinja 循环渲染fact_lines，CSS 四色分级

`report.html` / `dashboard.html` 把 `<pre class="section-body">{{ section.body }}</pre>` 替换为：

```django
<div class="section-body" data-section="{{ section.section_id }}">
  {% if section.fact_lines %}
    <ul class="fact-lines">
      {% for fl in section.fact_lines %}
        {% set cls = fl.classification.value %}
        <li class="fact-line fact-{{ cls }}" id="fact-{{ fl.fact_id }}">
          <span class="cls-badge cls-{{ cls }}">{{ fl.classification|fact_classification_label }}</span>
          <span class="fact-claim">{{ fl.claim }}</span>
          {% if fl.derived_from_fact_ids %}
            <span class="derived-from">据 {{ fl.derived_from_fact_ids|join('、') }}</span>
          {% endif %}
          <a class="fact-id" href="#fact-{{ fl.fact_id }}">{{ fl.fact_id }}</a>
        </li>
      {% endfor %}
    </ul>
  {% else %}
    <pre class="section-body-legacy">{{ section.body }}</pre>
  {% endif %}
</div>
```

#### 2.1.4 `styles.css` · 四分类视觉分级

```css
.cls-badge { padding: 0 6px; border-radius: 3px; font-size: .85em; font-weight: 600; }
.cls-fact      { color: #fff; background: #1d4ed8; }                       /* 蓝：已发生 */
.cls-opinion   { color: #fff; background: #b45309; }                       /* 琥珀：别人判断 */
.cls-inference { color: #fff; background: #6d28d9; }                       /* 紫：系统归纳 */
.cls-unverified { color: #1f2937; background: #e5e7eb; }                    /* 灰：待确认 */
.derived-from { color: var(--muted); font-size: .85em; }
```

> 颜色语义要写进 tour 第 4 步旁白（见紧急 5）。

#### 2.1.5 测试补充

```python
def test_section_carries_structured_fact_lines_with_classification():
    # 断言每个 section.fact_lines[i].classification 来自对应 fact，
    # 且 fact_lines 非空时 DOM 渲染走结构化路径
```

`test_web.py`：断言 report.html 响应里出现 `class="fact-line fact-fact"` 与 `class="cls-badge cls-fact"`，且**正文不再出现字面 `**`**。

---

### 紧急 2 · `今日一句话结论` 加分类白名单（TR-2，P0-2）

**根因**：`_first_non_empty(market_facts, facts)[:2]`（reporting.py:122）在市场事实为空时回退到**全部 facts 前两条**，可能抓到 opinion / inference。一个叫"今日一句话结论"的段藏一条`多家券商认为…修复` → 散户只读标题就行动的伪结论。

#### 补丁（`reporting.py`）

```python
def _build_beginner_after_close_sections(facts: list[AtomicFact]) -> list[ReportSection]:
    market_facts = _facts_for_modules(facts, {"market_indices", "market_temperature"})
    sector_facts = _facts_for_modules(facts, {"sector_moves"})
    policy_facts = _facts_for_modules(facts, {"policy_regulation"})
    risk_facts = _facts_for_modules(facts, {"risk_points"})

    # 仅事实可作"一句话结论"；空态显式占位，禁止跨模块兜底
    lead_facts = [f for f in market_facts if f.classification == FactClassification.FACT][:2]

    watch_facts = _dedupe_facts([*risk_facts, *policy_facts, *sector_facts])
    # next_watchlist 不允许 opinion；inference 必须有派生链
    watch_facts = [
        f for f in watch_facts
        if f.classification != FactClassification.OPINION
        and (f.classification != FactClassification.INFERENCE or f.derived_from_fact_ids)
    ]

    return [
        _section(
            "one_sentence_conclusion",
            _format_fact_lines_or_empty(lead_facts, "今日暂无可结论的硬事实。"),
            lead_facts,
        ),
        # market_overview / sector_strength / fact_opinion_inference 同前
        ...
        _section("next_watchlist", _format_watchlist_lines(watch_facts), watch_facts),
    ]
```

`_format_watchlist_lines` 去掉暗示性前缀：

```python
def _format_watchlist_lines(facts: list[AtomicFact]) -> list[str]:
    if not facts:
        return ["- 暂无可追踪的下一轮观察事实。"]
    return [
        f"- 待验证：{fact.claim} [{fact.fact_id}]"
        + (f"（据 {','.join(fact.derived_from_fact_ids)}）" if fact.derived_from_fact_ids else "")
        for fact in facts
    ]
```

#### 测试补充

```python
def test_one_sentence_conclusion_only_accepts_facts_not_opinions():
    # fixture: market_facts 空 + 一条 opinion fact → lead_facts 应为空
    # 断言 body 含 "今日暂无可结论的硬事实。"，不含 opinion claim 文案

def test_watchlist_rejects_opinion_and_unrooted_inference():
    # 一条无 derived_from_fact_ids 的 inference → 不进入 next_watchlist
```

`test_validation.py` 增：`one_sentence_conclusion` 段出现 `OPINION` 时 `validate_report_sections` 报错（见第 5 节结构化校验）。

---

### 紧急 3 · 加产品级免责声明（TR-2，P0-2）

#### `base.html` 顶部固定栏

```django
<body>
  <div class="disclaimer-bar" role="note">
    本简报仅供研究，不构成任何投资建议。所有数据来自公开来源，可能存在延迟或偏差。
  </div>
  <main class="shell"> ... </main>
</body>
```

```css
.disclaimer-bar {
  background: var(--warn); color: #fff; padding: 6px 16px;
  font-size: .85em; text-align: center;
}
```

#### 报告文末再加一句（`report.html`）

```django
<footer class="report-footer">
  本简报基于 {{ facts|length }} 条原子事实生成。仅供研究，不构成任何投资建议。
</footer>
```

#### 测试

`test_web.py`：`/` 与 `/reports/{id}` 均断言含 `不构成任何投资建议`。

---

### 紧急 4 · 闭环真正接通（TR-4，根本性缺漏）

**根因**：`pipeline.py:run_fixture_pipeline` 全程没调用 `store.list_feedback` / `summarize_feedback`。"上一轮反馈影响下一轮"在代码层缺失，项目名"loop"名不副实。

#### 补丁（`pipeline.py`）

```python
def run_fixture_pipeline(
    request: PipelineRequest,
    config: AppConfig,
    store: BriefingStore,
    previous_feedback_summary: str | None = None,   # 新增
) -> PipelineResult:
    # ... 现有流程 ...

    if previous_feedback_summary is None:
        previous_feedback_summary = _load_previous_feedback(store, request.report_type, request.report_date)

    # 写入"上一轮反馈回执"段（追加到 sections）
    report = build_report(..., previous_feedback_summary=previous_feedback_summary)
    ...
```

`_load_previous_feedback`：

```python
def _load_previous_feedback(store: BriefingStore, report_type: ReportType, report_date: str) -> str:
    # 在 reports 表里取同 report_type、report_date < 当前 的最近一条 report，
    # 取其 list_feedback 后 summarize_feedback；无则 "暂无历史反馈。"
```

`build_report` 增参 `previous_feedback_summary: str = "暂无历史反馈。"`，在 beginners 段列表追加：

```python
_section(
    "previous_feedback",
    [f"- {previous_feedback_summary}"] if previous_feedback_summary.strip() else ["- 暂无历史反馈。"],
    [],   # 不挂 fact_id；该段不属审计原子事实
),
```

加进 `BEGINNER_AFTER_CLOSE_SECTION_TITLES`：`"previous_feedback": "上一轮反馈回执"`。

#### `app.py` web 路径接线

`POST /runs/fixture` 调 `run_fixture_pipeline(..., previous_feedback_summary=None)`，让它自动拉取；CLI 同理。

#### 测试

```python
def test_pipeline_carries_previous_feedback_into_next_run():
    # run-1 → submit feedback(score=3, "风险点要更具体")
    # run-2 同 report_type → 断言 run-2 的 report.sections 中含 "previous_feedback"，
    # body 含 "风险点要更具体"
```

`test_web.py`：跑两次 run，断言第二次的报告页含第一次的反馈备注。

---

### 紧急 5 · onboarding 对真正的新用户可用（TR-5，P0-3）

**根因**：`dashboard.html:172` 整个 tour 包在 `{% if review_report %}`；`dashboard.html:11` "重新查看引导" 按钮在 `{% if latest_report %}`。**首次进入空工作台时两者都不渲染**——最需要引导的新用户一无所有。

#### 补丁（`dashboard.html`）

把 tour 容器移出 `{% if review_report %}`，始终渲染；当无 `review_report` 时把首步 target 切到运行表单：

```django
{% block overlays %}
<div id="onboarding-tour" class="tour-overlay" data-tour hidden>
  ...现有结构...
  <ol class="tour-steps" hidden>
    {% if review_report %}
      <li data-tour-step data-tour-target="review-one_sentence_conclusion" ...></li>
      ...5 步...
    {% else %}
      <li data-tour-step data-tour-target="run-fixture-form"
          data-tour-title="先运行一次样例数据"
          data-tour-body="工作台还没有简报。先点这里跑一次样例数据，之后就能看到完整审阅页。"></li>
    {% endif %}
  </ol>
</div>
{% endblock %}
```

给运行表单加 id：`<form id="run-fixture-form" ...>`。`重新查看引导`按钮移出 `{% if latest_report %}`，永远显示（无报告时点击也是引导空态步骤）。

`tour.js`：确保 `if (!steps.length) return;` 之外，**target 不存在时跳过该步**而非崩。

#### 测试

```python
def test_dashboard_renders_tour_for_empty_workspace():
    client, _ = _client_with_no_runs(tmp_path)
    resp = client.get("/")
    assert "先运行一次样例数据" in resp.text          # 空态引导文案
    assert "重新查看引导" in resp.text                 # 不再被 latest_report 门控
```

---

## 3. 🔧 重要（本期内）

6. **反馈校验中文化 + 回填保留**：`validate_feedback_entry`（feedback.py:10）改返回 `list[dict]`：`{"field": "score", "code": "out_of_range", "message": "评分必须在 1 到 5 之间"}`。`app.py:submit_feedback` 失败时回渲染 `report.html`，把 `errors` 与原 `note`/`tags` 一起回传；表单显示内联中文错误。
7. **失败/警告在 dashboard 可见**：
   - `app.py` dashboard 上下文加 `runs = briefing_store.list_runs()`（需在 storage 加方法）。
   - `dashboard.html` "最新简报" panel 增加 `run.status / warning_count`，`--warn` 染色 warn/failed。
   - 新增 `GET /runs/{run_id}` 渲染 run 日志（含 `validation_errors`、各 source 状态）。
8. **标签单一来源**：删除 `reporting.py` 的 `SECTION_TITLES`/`REPORT_TITLES`/`CLASSIFICATION_LABELS`，全部 import `labels.py`。`build_report` 标题用 `report_type_label(report_type)`。
9. **inference 展示派生链 + 中性前缀**：见紧急 1 模板（`据 fact-a、fact-b`）与紧急 2（`_format_watchlist_lines` 改 `待验证：`）。
10. **散户首屏友好化**：fact id chip 渲染成中文序号 `<span class="fact-chip">①</span>` + `aria-label`；运行/报告 ID 收进 `<details>`；评分表单加 `1=最差 · 5=最好`；运行表单默认日期填今天 `{{ today }}`（route 传入）。

---

## 4. 💡 可选

11. 模块 enable/disable 经 web 暴露（设计 Primary functions；MVP 可接受 YAML）。
12. `work/` 临时 chrome profile 目录纳入 `.gitignore` 并清出仓库（git status 现在留着 `work/` 与 `task1..5.txt`）。
13. `_select_review_report`（app.py:194）改按时间最新而非盘后优先，避免"最新简报"与"审阅样稿"指向不同报告。

---

## 5. 🔬 实验性（第一性原理的颠覆性替代，强烈推荐至少做 5.1）

### 5.1 把 `validation` 从"黑名单"升级为"分类合规性"结构不变量

**第一性**：当前 `BANNED_PHRASES`（validation.py:9）是词形穷举，**永远滞后于新话术**——`应继续跟踪`、`值得关注`、`情绪修复`都不命中。改用分类结构约束：

```python
SECTION_CLASS_RULES = {
    "one_sentence_conclusion":   {"allow": {FactClassification.FACT}, "require_derivation": False},
    "next_watchlist":             {"deny": {FactClassification.OPINION},
                                   "inference_must_have_derivation": True},
    "today_watchpoints":          {"deny": {FactClassification.OPINION},
                                   "inference_must_have_derivation": True},
    "market_overview":            {"allow_only": {FactClassification.FACT, FactClassification.OPINION}},
    # 其它段不约束
}

def validate_report_sections(...) -> ValidationResult:
    # 现有：missing fact_id + BANNED_PHRASES（保留作粗筛）
    # 新增：每段 fact 的分类必须满足 SECTION_CLASS_RULES
    #       inference 的 derived_from_fact_ids 必须 ⊆ 当前 ledger
    #       UNVERIFIED 不得进入除"待确认"以外任何段
```

这样"不构成投资建议"从**抓词**变成**结构不变量**，天然不被话术绕过。

### 5.2 让 `ReportSection.body` 变成派生字段

`body` 由 `fact_lines` 在 `render_markdown` 时拼出，而不是反向。这样 DOM 渲染、markdown 导出、无障碍三者共享唯一源 `fact_lines`，P0-1 那类"声明 vs 真实分裂"在结构上无法再发生。

---

## 6. 测试缺口清单（以上补丁顺带补）

按"失败路径而非 happy path"组织：

| 路径 | 应有的测试 |
|---|---|
| 反馈 web 端校验 | `score=0/6`、`note>240`、`unknown tag` → 中文错误 + 原值回填（当前只测了 unknown section_id） |
| pipeline 空态 | `facts=[]` → 各段显式占位；结论段不抓跨模块 fact |
| 模块开关 | yaml 全关 → 报告只剩固定回执段；少关一个 → 验证 facts 被过滤 |
| LLM 走 web | `provider=llm` 经 `/runs/fixture` → 验证 fallback 落入模板 |
| feedback 闭环 | 紧急 4 的端到端（见上） |
| tour 空态 | 紧急 5 的测试 |
| vandalism | fixture 是**结构破损 JSON** → 友好错误而非 raw 500 |
| tour 行为 | 从 `tour.js` 抽 `positionTourCard(target, card, viewport)` 纯函数单测边界（target 紧贴右边缘、viewport 窄于卡片宽），**取代** `"scrollIntoView" in js_src` 这类源码字面断言 |

---

## 7. 待你确认的开放问题

1. 设计文档把"模块开关"和"run logs"列为 dashboard Primary functions。本次未在 web 暴露——是 MVP **主动延期**还是遗漏？影响第 3 节第 7 条的判级。
2. `storage.list_reports` 当前是否带 `run.status`？我没读 storage.py 改动；若已带，第 7 条仅需改模板而非加方法。
3. `llm.py` 实现里是否已把 `previous_feedback_summary` 作参数注入 LLM？我只看了测试，若已注入，紧急 4 的 LLM 路径接线可简化。
4. `report.html` 我确认仍是 `<pre class="section-body">{{ section.body }}</pre>`（Read 过）；但我没读它的最近提交。若你**本意**就是要预格式化渲染，请说，我会改紧急 1 的方案为"前置 markdown 渲染"而非"结构化 FactLine"。

---

## 8. 落地顺序建议

按依赖而非优先级排：

1. 紧急 2 + 紧急 3（纯文案 + `reporting.py` 一处函数）—— 半小时内可合，先合规抢险。
2. 紧急 1（domain + reporting + 两个模板 + CSS）—— 最大的视觉级改动，建议单独 PR。
3. 紧急 4（pipeline + feedback 闭环）—— 单独 PR，配端到端测试。
4. 紧急 5（tour 空态）—— 小改动，可与 3 合并。
5. 第 5 节 5.1（结构不变量校验）—— 与紧急 2 同源，建议同一 PR 推到极致。
6. 其余 🔧 / 💡 项按月中节奏。

---

*本文件由独立审查者生成，未直接改动任何代码。所有补丁均为草案，落地请以你的实现为准。*
