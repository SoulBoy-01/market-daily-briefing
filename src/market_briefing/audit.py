from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path
import re


SAFE_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class UnsafeAuditPathError(ValueError):
    pass


@dataclass(frozen=True)
class SnapshotFile:
    path: Path
    content_sha256: str


def run_directory(root: Path, report_date: str, run_id: str) -> Path:
    try:
        parsed_date = date.fromisoformat(report_date)
    except ValueError as exc:
        raise UnsafeAuditPathError(f"invalid report date: {report_date}") from exc
    if parsed_date.isoformat() != report_date or not SAFE_RUN_ID_RE.fullmatch(run_id):
        raise UnsafeAuditPathError(f"unsafe run path: {report_date}/{run_id}")

    resolved_root = root.resolve()
    resolved_path = (resolved_root / report_date / run_id).resolve()
    if not resolved_path.is_relative_to(resolved_root):
        raise UnsafeAuditPathError(f"run path escapes root: {resolved_path}")
    return resolved_path


def write_snapshot_text(path: Path, content: str) -> SnapshotFile:
    encoded = content.encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)
    return SnapshotFile(path=path, content_sha256=sha256(encoded).hexdigest())


def verify_snapshot_hash(path: Path, expected_sha256: str) -> bool:
    if not expected_sha256 or not path.is_file():
        return False
    return sha256(path.read_bytes()).hexdigest() == expected_sha256


def move_run_directory(
    source_root: Path,
    destination_root: Path,
    report_date: str,
    run_id: str,
) -> tuple[Path, Path] | None:
    source = run_directory(source_root, report_date, run_id)
    destination = run_directory(destination_root, report_date, run_id)
    if not source.exists():
        return None
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    source.rename(destination)
    return source, destination


def rebase_audit_path(path: str, source_run_dir: Path, destination_run_dir: Path) -> str:
    resolved_path = Path(path).resolve()
    resolved_source = source_run_dir.resolve()
    try:
        relative_path = resolved_path.relative_to(resolved_source)
    except ValueError as exc:
        raise UnsafeAuditPathError(f"snapshot path is outside run directory: {path}") from exc
    return str(destination_run_dir.resolve() / relative_path)
