"""Backup/migration helper CLI for CyberMind.

Goal: make it easy to move your data (including notes) between machines.

This tool produces a compressed archive that contains a consistent SQLite DB
snapshot plus your per-map backups.

Usage:
  cybermind-migrate export --out cybermind-backup.tar.gz
  cybermind-migrate import --archive cybermind-backup.tar.gz

You can bypass Fedora/GNOME runtime checks for this tool via
CYBERMIND_SKIP_PREFLIGHT=1 if needed.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sqlite3
import sys
import tarfile
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from cybermind.database import get_data_dir


@dataclass(frozen=True)
class Manifest:
    created_at: str
    hostname: str
    platform: str
    python: str
    data_dir: str


def _iter_backup_dbs(backups_dir: Path) -> Iterable[Path]:
    if not backups_dir.exists():
        return []
    return sorted(backups_dir.glob("*.db"))


def _sqlite_consistent_copy(src_db: Path, dst_db: Path) -> None:
    """Create a consistent single-file copy of an SQLite database.

    Uses sqlite3 backup API. This avoids needing to also copy -wal/-shm files.
    """
    if not src_db.exists():
        raise FileNotFoundError(str(src_db))

    dst_db.parent.mkdir(parents=True, exist_ok=True)

    # Open source. Best-effort read-only.
    src_uri = f"file:{src_db.as_posix()}?mode=ro"
    src = sqlite3.connect(src_uri, uri=True)
    try:
        dst = sqlite3.connect(dst_db.as_posix())
        try:
            src.backup(dst)
            dst.commit()
        finally:
            dst.close()
    finally:
        src.close()


def _sqlite_open_ro(db_path: Path) -> sqlite3.Connection:
    uri = f"file:{db_path.as_posix()}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _sqlite_integrity_ok(conn: sqlite3.Connection) -> bool:
    cur = conn.cursor()
    cur.execute("PRAGMA integrity_check")
    row = cur.fetchone()
    return bool(row) and str(row[0]).lower() == "ok"


def _db_counts(conn: sqlite3.Connection) -> dict:
    cur = conn.cursor()
    out: dict[str, int] = {}
    for table in ("maps", "nodes", "notes", "relationships", "settings"):
        try:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            out[table] = int(cur.fetchone()[0])
        except sqlite3.Error:
            out[table] = -1

    try:
        cur.execute("SELECT COUNT(*) FROM notes WHERE content IS NOT NULL AND TRIM(content) != ''")
        out["notes_nonempty"] = int(cur.fetchone()[0])
    except sqlite3.Error:
        out["notes_nonempty"] = -1

    return out


def verify_local() -> int:
    """Verify the local CyberMind data directory."""
    data_dir = get_data_dir()
    db_path = data_dir / "cybermind.db"
    backups_dir = data_dir / "backups"

    if not db_path.exists():
        print(f"No DB found at {db_path}")
        return 2

    with _sqlite_open_ro(db_path) as conn:
        ok = _sqlite_integrity_ok(conn)
        counts = _db_counts(conn)

    backups = list(_iter_backup_dbs(backups_dir))

    print("Local CyberMind data verification")
    print(f"  Data dir: {data_dir}")
    print(f"  DB: {db_path}")
    print(f"  SQLite integrity_check: {'OK' if ok else 'FAILED'}")
    print(f"  Counts: maps={counts.get('maps')} nodes={counts.get('nodes')} notes={counts.get('notes')} nonempty_notes={counts.get('notes_nonempty')}")
    print(f"  Backups: {len(backups)} file(s)")

    return 0 if ok else 2


def verify_archive(archive_path: Path) -> int:
    """Verify a migration archive without importing it."""
    archive_path = archive_path.expanduser().resolve()
    if not archive_path.exists():
        print(f"Archive not found: {archive_path}")
        return 2

    with tempfile.TemporaryDirectory(prefix="cybermind-verify-") as td:
        td_path = Path(td)
        with tarfile.open(archive_path, "r:gz") as tf:
            tf.extractall(td_path)

        manifest_path = td_path / "manifest.json"
        db_path = td_path / "data" / "cybermind.db"
        backups_dir = td_path / "data" / "backups"

        if not db_path.exists():
            print("Archive is missing data/cybermind.db")
            return 2

        manifest = None
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                manifest = None

        with _sqlite_open_ro(db_path) as conn:
            ok = _sqlite_integrity_ok(conn)
            counts = _db_counts(conn)

        backups = list(_iter_backup_dbs(backups_dir))

        print("CyberMind archive verification")
        print(f"  Archive: {archive_path}")
        if manifest:
            print(f"  Created: {manifest.get('created_at', 'unknown')}")
            print(f"  Source host: {manifest.get('hostname', 'unknown')}")
        print(f"  SQLite integrity_check: {'OK' if ok else 'FAILED'}")
        print(f"  Counts: maps={counts.get('maps')} nodes={counts.get('nodes')} notes={counts.get('notes')} nonempty_notes={counts.get('notes_nonempty')}")
        print(f"  Backups in archive: {len(backups)} file(s)")

        return 0 if ok else 2


def export_archive(out_path: Path, include_exports: bool = False) -> None:
    data_dir = get_data_dir()
    main_db = data_dir / "cybermind.db"
    backups_dir = data_dir / "backups"
    exports_dir = data_dir / "exports"

    if not main_db.exists():
        raise SystemExit(f"No database found at {main_db}")

    out_path = out_path.expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="cybermind-migrate-") as td:
        staging = Path(td)

        # Manifest
        manifest = Manifest(
            created_at=datetime.now().isoformat(timespec="seconds"),
            hostname=platform.node(),
            platform=platform.platform(),
            python=sys.version.replace("\n", " "),
            data_dir=str(data_dir),
        )
        (staging / "manifest.json").write_text(
            json.dumps(asdict(manifest), indent=2, sort_keys=True),
            encoding="utf-8",
        )

        # Main DB snapshot
        (staging / "data").mkdir(parents=True, exist_ok=True)
        _sqlite_consistent_copy(main_db, staging / "data" / "cybermind.db")

        # Per-map backups snapshot
        (staging / "data" / "backups").mkdir(parents=True, exist_ok=True)
        for bdb in _iter_backup_dbs(backups_dir):
            _sqlite_consistent_copy(bdb, staging / "data" / "backups" / bdb.name)

        # Optional exports folder (images/markdown/pdf you’ve generated)
        if include_exports and exports_dir.exists():
            dst_exports = staging / "data" / "exports"
            shutil.copytree(exports_dir, dst_exports, dirs_exist_ok=True)

        # Build tar.gz
        with tarfile.open(out_path, "w:gz") as tf:
            tf.add(staging / "manifest.json", arcname="manifest.json")
            tf.add(staging / "data", arcname="data")


def import_archive(archive_path: Path, *, overwrite: bool = False) -> None:
    archive_path = archive_path.expanduser().resolve()
    if not archive_path.exists():
        raise SystemExit(f"Archive not found: {archive_path}")

    data_dir = get_data_dir()
    target_db = data_dir / "cybermind.db"

    # Extract into a temp dir first.
    with tempfile.TemporaryDirectory(prefix="cybermind-import-") as td:
        td_path = Path(td)
        with tarfile.open(archive_path, "r:gz") as tf:
            tf.extractall(td_path)

        extracted_db = td_path / "data" / "cybermind.db"
        extracted_backups = td_path / "data" / "backups"
        extracted_exports = td_path / "data" / "exports"

        if not extracted_db.exists():
            raise SystemExit("Archive is missing data/cybermind.db")

        # If target exists, back it up unless user explicitly allows overwrite.
        if target_db.exists():
            if not overwrite:
                raise SystemExit(
                    f"Target DB already exists at {target_db}. "
                    "Re-run with --overwrite to replace it (a safety backup will be kept)."
                )

            migrate_backup_root = data_dir / "migrate-backups" / datetime.now().strftime("%Y%m%d_%H%M%S")
            migrate_backup_root.mkdir(parents=True, exist_ok=True)
            shutil.move(str(target_db), str(migrate_backup_root / "cybermind.db"))

        # Install DB
        shutil.copy2(extracted_db, target_db)

        # Install per-map backups (merge by filename, overwriting duplicates)
        if extracted_backups.exists():
            (data_dir / "backups").mkdir(parents=True, exist_ok=True)
            for item in extracted_backups.glob("*.db"):
                shutil.copy2(item, data_dir / "backups" / item.name)

        # Install exports (optional; archive may not contain)
        if extracted_exports.exists():
            (data_dir / "exports").mkdir(parents=True, exist_ok=True)
            shutil.copytree(extracted_exports, data_dir / "exports", dirs_exist_ok=True)


def _cmd_export(args: argparse.Namespace) -> int:
    export_archive(Path(args.out), include_exports=bool(args.include_exports))
    print(f"Wrote archive: {Path(args.out).expanduser().resolve()}")
    return 0


def _cmd_import(args: argparse.Namespace) -> int:
    import_archive(Path(args.archive), overwrite=bool(args.overwrite))
    print("Import complete")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    if args.archive:
        return int(verify_archive(Path(args.archive)))
    return int(verify_local())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cybermind-migrate")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_exp = sub.add_parser("export", help="Export data archive")
    p_exp.add_argument("--out", required=True, help="Output .tar.gz path")
    p_exp.add_argument(
        "--include-exports",
        action="store_true",
        help="Also include the exports folder (PNG/PDF/MD you generated)",
    )
    p_exp.set_defaults(func=_cmd_export)

    p_imp = sub.add_parser("import", help="Import data archive")
    p_imp.add_argument("--archive", required=True, help="Input .tar.gz path")
    p_imp.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing cybermind.db (a safety copy will be saved)",
    )
    p_imp.set_defaults(func=_cmd_import)

    p_ver = sub.add_parser("verify", help="Verify an archive or local DB")
    p_ver.add_argument(
        "--archive",
        help="Path to a .tar.gz archive to verify (if omitted, verifies local ~/.local/share/cybermind)",
    )
    p_ver.set_defaults(func=_cmd_verify)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
