import pytest

from market_briefing.audit import (
    UnsafeAuditPathError,
    recover_orphaned_publication_directories,
    run_directory,
    verify_snapshot_hash,
    write_snapshot_text,
)


def test_snapshot_hash_detects_file_tampering(tmp_path):
    snapshot_file = write_snapshot_text(tmp_path / "snapshot.json", '{"value": 1}')

    assert len(snapshot_file.content_sha256) == 64
    assert verify_snapshot_hash(snapshot_file.path, snapshot_file.content_sha256)

    snapshot_file.path.write_text('{"value": 2}', encoding="utf-8")

    assert not verify_snapshot_hash(snapshot_file.path, snapshot_file.content_sha256)


@pytest.mark.parametrize("unsafe_run_id", ["../escape", "..\\escape", ".", "C:escape"])
def test_run_directory_rejects_untrusted_path_components(tmp_path, unsafe_run_id):
    with pytest.raises(UnsafeAuditPathError):
        run_directory(tmp_path / "root", "2026-07-02", unsafe_run_id)


def test_run_directory_rejects_invalid_report_date(tmp_path):
    with pytest.raises(UnsafeAuditPathError):
        run_directory(tmp_path / "root", "2026-02-30", "safe-run")


def test_run_directory_stays_under_resolved_root(tmp_path):
    root = tmp_path / "root"

    path = run_directory(root, "2026-07-02", "safe-run")

    assert path == root.resolve() / "2026-07-02" / "safe-run"


def test_recovery_moves_unreferenced_final_directories_to_diagnostics(tmp_path):
    raw_dir = tmp_path / "raw"
    reports_dir = tmp_path / "reports"
    diagnostics_dir = tmp_path / "diagnostics"
    raw_run = raw_dir / "2026-07-02" / "orphan-run"
    report_run = reports_dir / "2026-07-02" / "after_close" / "orphan-run"
    raw_run.mkdir(parents=True)
    report_run.mkdir(parents=True)
    (raw_run / "snapshot.json").write_text("{}", encoding="utf-8")
    (report_run / "briefing.md").write_text("orphan", encoding="utf-8")

    recovered = recover_orphaned_publication_directories(
        raw_dir=raw_dir,
        reports_dir=reports_dir,
        diagnostics_dir=diagnostics_dir,
        published_run_locations=set(),
    )

    assert recovered == {"orphan-run"}
    assert not raw_run.exists()
    assert not report_run.exists()
    assert (
        diagnostics_dir / "2026-07-02" / "orphan-run" / "orphan-raw" / "snapshot.json"
    ).is_file()
    assert (
        diagnostics_dir
        / "2026-07-02"
        / "orphan-run"
        / "orphan-report-after_close"
        / "briefing.md"
    ).is_file()


def test_recovery_preserves_directories_referenced_by_published_run(tmp_path):
    raw_run = tmp_path / "raw" / "2026-07-02" / "published-run"
    report_run = tmp_path / "reports" / "2026-07-02" / "after_close" / "published-run"
    raw_run.mkdir(parents=True)
    report_run.mkdir(parents=True)

    recovered = recover_orphaned_publication_directories(
        raw_dir=tmp_path / "raw",
        reports_dir=tmp_path / "reports",
        diagnostics_dir=tmp_path / "diagnostics",
        published_run_locations={
            ("2026-07-02", "after_close", "published-run"),
        },
    )

    assert recovered == set()
    assert raw_run.is_dir()
    assert report_run.is_dir()


def test_recovery_moves_published_run_id_from_unreferenced_locations(tmp_path):
    raw_dir = tmp_path / "raw"
    reports_dir = tmp_path / "reports"
    diagnostics_dir = tmp_path / "diagnostics"
    correct_raw = raw_dir / "2026-07-02" / "published-run"
    misplaced_raw = raw_dir / "2026-07-03" / "published-run"
    correct_report = reports_dir / "2026-07-02" / "after_close" / "published-run"
    misplaced_report = reports_dir / "2026-07-02" / "pre_open_update" / "published-run"
    for directory in (correct_raw, misplaced_raw, correct_report, misplaced_report):
        directory.mkdir(parents=True)

    recovered = recover_orphaned_publication_directories(
        raw_dir=raw_dir,
        reports_dir=reports_dir,
        diagnostics_dir=diagnostics_dir,
        published_run_locations={
            ("2026-07-02", "after_close", "published-run"),
        },
    )

    assert recovered == {"published-run"}
    assert correct_raw.is_dir()
    assert correct_report.is_dir()
    assert not misplaced_raw.exists()
    assert not misplaced_report.exists()
    assert (
        diagnostics_dir / "2026-07-03" / "published-run" / "orphan-raw"
    ).is_dir()
    assert (
        diagnostics_dir
        / "2026-07-02"
        / "published-run"
        / "orphan-report-pre_open_update"
    ).is_dir()
