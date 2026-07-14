import pytest

from market_briefing.audit import (
    UnsafeAuditPathError,
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
