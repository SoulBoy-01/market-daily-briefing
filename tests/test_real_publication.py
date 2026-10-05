from datetime import datetime, timezone
from pathlib import Path

import pytest

from market_briefing.collectors.market_data import MarketDataCollector
from market_briefing.domain import (
    AtomicFact,
    CandidateReviewStatus,
    FactClassification,
    ReportType,
    RunStatus,
    SourceType,
)
from market_briefing.real_pipeline import (
    collect_real_after_close,
    publish_real_after_close,
)
from market_briefing.domain import Run
from market_briefing.storage import (
    BriefingStore,
    InvalidPublicationBundleError,
    PublishedRecordExistsError,
)

from test_real_pipeline import (
    FakeIndexClient,
    OfficialSourceCollector,
    OfficialSourceTarget,
    StaticOfficialClient,
    _config,
    _dual_sourced_registry,
    _request,
    _store,
)


def _collect(tmp_path, run_id="run-publish-001", close="3021.45"):
    store = _store(tmp_path)
    config = _config(tmp_path)
    result = collect_real_after_close(
        request=_request(run_id),
        config=config,
        store=store,
        registry=_dual_sourced_registry(tmp_path),
        market_clients=(
            MarketDataCollector(client=FakeIndexClient("sse-official", close)),
            MarketDataCollector(client=FakeIndexClient("vendor", close)),
        ),
        official_collector=OfficialSourceCollector(
            client=StaticOfficialClient(),
            targets=[
                OfficialSourceTarget(
                    module="policy_regulation",
                    source_name="合成交易所",
                    source_url="fixture://policy",
                    source_type=SourceType.EXCHANGE,
                )
            ],
        ),
    )
    return store, config, result


def _approve_pending_candidate(store: BriefingStore, run_id: str) -> str:
    with store.connection() as connection:
        candidate_id = connection.execute(
            "select candidate_id from evidence_candidates where run_id = ?",
            (run_id,),
        ).fetchone()["candidate_id"]
    store.review_candidate(
        candidate_id,
        CandidateReviewStatus.APPROVED,
        reviewer_id="owner",
        note="人工确认",
        approved_fact_id=f"fact-{run_id}-official-approved",
    )
    return candidate_id


def test_publish_real_rejects_when_dual_source_values_conflict(tmp_path):
    # 第二个提供方报不同收盘价：双源核对必须给出冲突错误码
    result = collect_real_after_close(
        request=_request("run-conflict"),
        config=_config(tmp_path),
        store=_store(tmp_path),
        registry=_dual_sourced_registry(tmp_path),
        market_clients=(
            MarketDataCollector(client=FakeIndexClient("sse-official", "3021.45")),
            MarketDataCollector(client=FakeIndexClient("vendor", "3099.99")),
        ),
        official_collector=None,
    )

    assert "core_index_source_conflict" in result.blocking_error_codes


def test_publish_real_blocks_when_reconciled_indices_missing(tmp_path):
    store, config, _ = _collect(tmp_path, run_id="run-no-reconciliation")
    _approve_pending_candidate(store, "run-no-reconciliation")
    with store.connection() as connection:
        connection.execute(
            "delete from source_snapshots where run_id = ? and module = ?",
            ("run-no-reconciliation", "market_indices"),
        )

    with pytest.raises(RuntimeError, match="核对"):
        publish_real_after_close(
            request=_request("run-no-reconciliation"),
            config=config,
            store=store,
        )


def test_publish_real_builds_report_after_candidate_approved(tmp_path):
    store, config, collect_result = _collect(tmp_path)
    assert collect_result.status == RunStatus.AWAITING_REVIEW
    _approve_pending_candidate(store, "run-publish-001")

    report = publish_real_after_close(
        request=_request("run-publish-001"),
        config=config,
        store=store,
    )

    assert store.get_run("run-publish-001").status == RunStatus.COMPLETED
    facts = store.list_facts("run-publish-001")
    # 三个核心指数 + 一条人工批准的官方事实
    index_facts = [fact for fact in facts if fact.module == "market_indices"]
    official_facts = [fact for fact in facts if fact.module == "policy_regulation"]
    assert len(index_facts) == 3
    assert len(official_facts) == 1
    assert all(
        fact.classification == FactClassification.FACT for fact in official_facts
    )
    assert {fact.fact_id for fact in index_facts} == {
        "fact-run-publish-001-index-000001.SH",
        "fact-run-publish-001-index-399001.SZ",
        "fact-run-publish-001-index-399006.SZ",
    }
    assert report.sections


def test_published_report_is_visible_and_integrity_checked(tmp_path):
    store, config, _ = _collect(tmp_path)
    _approve_pending_candidate(store, "run-publish-001")
    report = publish_real_after_close(
        request=_request("run-publish-001"),
        config=config,
        store=store,
    )

    published = store.get_published_report(report.report_id)

    assert published.report_id == report.report_id
    store.assert_report_integrity(report.report_id)
    assert Path(published.markdown_path).is_file()
    assert Path(published.html_path).is_file()
    assert Path(published.fact_ledger_path).is_file()


def test_publish_bundle_rejects_preexisting_facts_for_reviewing_run(tmp_path):
    """AWAITING_REVIEW 的 run 允许采集产物，但事实绝不能被预置。"""
    store = _store(tmp_path)
    store.create_run(
        Run.create(
            run_id="run-preloaded",
            report_date="2026-07-02",
            report_type=ReportType.AFTER_CLOSE,
            enabled_modules=["market_indices"],
        )
    )
    store.transition_run("run-preloaded", RunStatus.RUNNING)
    store.transition_run("run-preloaded", RunStatus.AWAITING_REVIEW)

    with pytest.raises((InvalidPublicationBundleError, PublishedRecordExistsError)):
        store.publish_run_bundle(
            snapshots=[],
            facts=[
                AtomicFact(
                    fact_id="fact-preloaded",
                    run_id="run-preloaded",
                    report_date="2026-07-02",
                    report_type=ReportType.AFTER_CLOSE,
                    module="market_indices",
                    claim="预置事实",
                    classification=FactClassification.FACT,
                    source_name="Fixture",
                    source_url="fixture://x",
                    source_type=SourceType.DATA_API,
                    published_at=None,
                    fetched_at=datetime(2026, 7, 2, 7, 0, tzinfo=timezone.utc),
                    confidence="high",
                    raw_snapshot_path=str(tmp_path / "raw" / "missing.json"),
                )
            ],
            report=_report_stub(tmp_path, "run-preloaded"),
            target_status=RunStatus.COMPLETED,
        )


def _report_stub(tmp_path, run_id):
    from market_briefing.domain import Report

    paths = {}
    for name in ("briefing.md", "briefing.html", "fact_ledger.json"):
        path = tmp_path / "reports" / "2026-07-02" / "after_close" / run_id / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("artifact", encoding="utf-8")
        paths[name] = str(path)
    return Report(
        report_id=f"report-{run_id}",
        run_id=run_id,
        report_date="2026-07-02",
        report_type=ReportType.AFTER_CLOSE,
        title="预置报告",
        sections=[],
        markdown_path=paths["briefing.md"],
        html_path=paths["briefing.html"],
        fact_ledger_path=paths["fact_ledger.json"],
    )


def test_publish_real_is_not_repeatable(tmp_path):
    store, config, _ = _collect(tmp_path)
    _approve_pending_candidate(store, "run-publish-001")
    publish_real_after_close(request=_request("run-publish-001"), config=config, store=store)

    with pytest.raises(PublishedRecordExistsError):
        publish_real_after_close(
            request=_request("run-publish-001"), config=config, store=store
        )
