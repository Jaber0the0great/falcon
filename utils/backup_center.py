import os
import io
import json
import sqlite3
import zipfile
import logging
from datetime import datetime, timezone

from utils.backup import (
    create_backup,
    create_quick_backup,
    create_pre_import_backup,
    restore_backup,
    list_backups,
    search_backups,
    verify_backup_file,
    prune_backups,
    _sha256_file,
    _write_sha256_sidecar,
    QUICK_SUBDIR,
    FULL_SUBDIR,
    PRE_IMPORT_SUBDIR,
    BACKUP_DIR,
)

from utils.migration.printer import sha256_checksum

logger = logging.getLogger(__name__)

try:
    from version import __version__ as APP_VERSION
except ImportError:
    APP_VERSION = "0.0.0"


SCHEMA_TABLE_COUNT = 7
SCHEMA_TABLES = [
    "user", "message", "group", "group_member",
    "group_invite", "group_join_request", "system_broadcast",
]


def get_db_stats(db_path):
    if not os.path.isfile(db_path):
        return {}
    stats = {}
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        for table in SCHEMA_TABLES:
            try:
                c.execute(f"SELECT COUNT(*) FROM {table}")
                stats[f"total_{table}"] = c.fetchone()[0]
            except sqlite3.OperationalError:
                stats[f"total_{table}"] = -1
        stats["total_rows"] = sum(v for v in stats.values() if v > 0)
        conn.close()
    except Exception as e:
        logger.warning("Failed to read DB stats: %s", e)
    return stats


def get_schema_version(db_path):
    if not os.path.isfile(db_path):
        return 0
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in c.fetchall()}
        conn.close()
        known = {t for t in tables if t in SCHEMA_TABLES}
        return len(known)
    except Exception:
        return 0


def build_manifest(backup_type, db_path, uploads_dir=None):
    sha256_db = _sha256_file(db_path) or ""
    stats = get_db_stats(db_path)
    schema_ver = get_schema_version(db_path)
    manifest = {
        "backup_type": backup_type,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "application_version": APP_VERSION,
        "database_schema_version": schema_ver,
        "sha256": sha256_db,
        "contents": {
            "database": {
                "file": os.path.basename(db_path) if db_path else "falcon_web.db",
                "size_bytes": os.path.getsize(db_path) if db_path and os.path.isfile(db_path) else 0,
                "sha256": sha256_db,
            }
        },
        "database_statistics": stats,
    }
    if uploads_dir and os.path.isdir(uploads_dir):
        upload_files = []
        total_upload_size = 0
        for root, dirs, files in os.walk(uploads_dir):
            for fname in files:
                fpath = os.path.join(root, fname)
                try:
                    sz = os.path.getsize(fpath)
                    total_upload_size += sz
                    upload_files.append({
                        "path": os.path.relpath(fpath, uploads_dir),
                        "size": sz,
                    })
                except OSError:
                    pass
        manifest["contents"]["uploads"] = {
            "count": len(upload_files),
            "size_bytes": total_upload_size,
            "files": upload_files,
        }
    return manifest


def create_full_backup(db_path="database/falcon_web.db", uploads_dir=None, label=None, backup_dir=None):
    from utils.backup import _resolve_backup_dir
    target_dir = _resolve_backup_dir(backup_dir, FULL_SUBDIR)
    os.makedirs(target_dir, exist_ok=True)

    if not os.path.isfile(db_path):
        return {"success": False, "error": f"Database not found: {db_path}"}

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S%f")[:19]
    prefix = f"{label}_" if label else ""
    filename = f"{prefix}full_backup_{timestamp}.zip"
    dest = os.path.join(target_dir, filename)

    manifest = build_manifest("full", db_path, uploads_dir)

    try:
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest, indent=2))
            zf.write(db_path, arcname="falcon_web.db")
            if uploads_dir and os.path.isdir(uploads_dir):
                for entry in manifest["contents"]["uploads"]["files"]:
                    src = os.path.join(uploads_dir, entry["path"])
                    if os.path.isfile(src):
                        zf.write(src, arcname="uploads/" + entry["path"])
    except Exception as e:
        logger.exception("Full backup failed: %s", e)
        if os.path.isfile(dest):
            os.remove(dest)
        return {"success": False, "error": str(e)}

    file_size = os.path.getsize(dest)
    zip_sha256 = _sha256_file(dest)
    manifest["sha256"] = zip_sha256
    _write_sha256_sidecar(dest, zip_sha256)

    manifest_path = dest + ".manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    logger.info("Full backup created: %s (%d bytes, sha256=%s)", dest, file_size, zip_sha256)

    return {
        "success": True,
        "path": dest,
        "filename": filename,
        "size": file_size,
        "timestamp": timestamp,
        "sha256": zip_sha256,
        "type": "full",
        "manifest": manifest,
    }


def restore_backup_full(backup_path, target_db_path="database/falcon_web.db", uploads_dir=None):
    if not os.path.isfile(backup_path):
        return {"success": False, "error": f"Backup file not found: {backup_path}"}

    ext = os.path.splitext(backup_path)[1]
    if ext == ".zip":
        return _restore_zip_backup(backup_path, target_db_path, uploads_dir)
    else:
        return _restore_sqlite_backup(backup_path, target_db_path)


def _restore_sqlite_backup(backup_path, target_db_path):
    verify = verify_backup_file(backup_path)
    if not verify["valid"] and verify.get("sha256_stored"):
        return {
            "success": False,
            "error": "SHA256 mismatch — backup may be corrupted",
            "verification": verify,
        }

    pre_restore = create_backup(db_path=target_db_path, label="pre_restore", subdir=QUICK_SUBDIR)
    if not pre_restore.get("success"):
        logger.warning("Pre-restore backup failed: %s", pre_restore.get("error"))

    result = restore_backup(backup_path, target_db_path)
    if result["success"]:
        result["pre_restore_backup"] = pre_restore
        result["verification"] = verify_restore(target_db_path)
    return result


def _restore_zip_backup(backup_path, target_db_path, uploads_dir):
    verify = verify_backup_file(backup_path)
    if not verify["valid"] and verify.get("sha256_stored"):
        return {
            "success": False,
            "error": "SHA256 mismatch — backup may be corrupted",
            "verification": verify,
        }

    pre_restore = create_backup(db_path=target_db_path, label="pre_restore", subdir=QUICK_SUBDIR)

    try:
        with zipfile.ZipFile(backup_path, "r") as zf:
            if "manifest.json" not in zf.namelist():
                return {"success": False, "error": "Invalid backup: missing manifest.json"}
            manifest = json.loads(zf.read("manifest.json"))

            db_data = zf.read("falcon_web.db")
            with open(target_db_path, "wb") as f:
                f.write(db_data)

            if uploads_dir and "uploads" in manifest.get("contents", {}):
                os.makedirs(uploads_dir, exist_ok=True)
                for entry in manifest["contents"]["uploads"]["files"]:
                    arc_path = "uploads/" + entry["path"]
                    if arc_path in zf.namelist():
                        target_file = os.path.join(uploads_dir, entry["path"])
                        os.makedirs(os.path.dirname(target_file), exist_ok=True)
                        with zf.open(arc_path) as src, open(target_file, "wb") as dst:
                            dst.write(src.read())

    except Exception as e:
        logger.exception("Full restore failed: %s", e)
        if pre_restore.get("success") and os.path.isfile(pre_restore.get("path", "")):
            restore_backup(pre_restore["path"], target_db_path)
        return {"success": False, "error": str(e), "pre_restore_backup": pre_restore}

    verification = verify_restore(target_db_path, uploads_dir)
    return {
        "success": True,
        "path": target_db_path,
        "pre_restore_backup": pre_restore,
        "verification": verification,
        "manifest": manifest,
    }


def check_compatibility(backup_path, current_db_path="database/falcon_web.db"):
    issues = []
    ext = os.path.splitext(backup_path)[1]

    if ext == ".zip":
        try:
            with zipfile.ZipFile(backup_path, "r") as zf:
                if "manifest.json" not in zf.namelist():
                    return {"compatible": False, "issues": ["Missing manifest.json"]}
                manifest = json.loads(zf.read("manifest.json"))
        except Exception as e:
            return {"compatible": False, "issues": [f"Cannot read backup: {e}"]}
    else:
        manifest = None

    current_schema = get_schema_version(current_db_path)
    if manifest:
        backup_schema = manifest.get("database_schema_version", 0)
        if backup_schema == 0:
            issues.append("Backup has unknown schema version — proceed with caution")
        elif backup_schema < current_schema:
            issues.append(f"Backup schema ({backup_schema}) is older than current ({current_schema}) — data may be missing")
    else:
        backup_schema = get_schema_version(backup_path)
        if backup_schema == 0:
            issues.append("Backup file does not contain a recognizable database")
            return {"compatible": False, "issues": issues}

    backup_verify = verify_backup_file(backup_path)
    if not backup_verify["valid"] and backup_verify.get("sha256_stored"):
        issues.append("SHA256 checksum mismatch — backup may be corrupted")

    compatible = len(issues) == 0 or all("caution" in i for i in issues)
    return {
        "compatible": compatible,
        "issues": issues,
        "backup_schema": backup_schema if not manifest else manifest.get("database_schema_version"),
        "current_schema": current_schema,
        "manifest": manifest,
    }


def verify_restore(db_path, uploads_dir=None):
    results = {}
    integrity = _check_db_integrity(db_path)
    results["integrity"] = integrity
    results["users"] = _verify_entity(db_path, "user")
    results["messages"] = _verify_entity(db_path, "message")
    results["groups"] = _verify_entity(db_path, "group")

    if uploads_dir and os.path.isdir(uploads_dir):
        results["uploads"] = {
            "count": len([f for f in os.listdir(uploads_dir) if os.path.isfile(os.path.join(uploads_dir, f))]),
            "directory_exists": True,
        }
    else:
        results["uploads"] = {"count": 0, "directory_exists": False}

    all_checks = [
        integrity.get("ok", False),
    ]
    for key in ("users", "messages", "groups"):
        ent = results.get(key, {})
        if not ent.get("note") == "table not present":
            all_checks.append(ent.get("ok", False))
    results["all_ok"] = all(all_checks)
    return results


def _check_db_integrity(db_path):
    if not os.path.isfile(db_path):
        return {"ok": False, "error": "Database file not found"}
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("PRAGMA integrity_check")
        result = c.fetchone()[0]
        if result == "ok":
            return {"ok": True}
        return {"ok": False, "error": result}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        if conn:
            conn.close()


def _verify_entity(db_path, table):
    if not os.path.isfile(db_path):
        return {"ok": False, "error": "Database not found", "count": -1}
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute(f"SELECT COUNT(*) FROM {table}")
        count = c.fetchone()[0]
        return {"ok": count > 0 if table in ("user", "message") else True, "count": count}
    except sqlite3.OperationalError:
        return {"ok": True, "count": 0, "note": "table not present"}
    except Exception as e:
        return {"ok": False, "error": str(e), "count": -1}
    finally:
        if conn:
            conn.close()


def apply_retention(backup_dir=None, config=None):
    if config:
        for btype, retain_count in config.items():
            prune_backups(retain_count=retain_count, backup_dir=backup_dir, backup_type=btype)
    else:
        prune_backups(backup_dir=backup_dir)
    return {"success": True}


def get_backup_summary(backup_dir=None):
    all_backups = list_backups(backup_dir=backup_dir)
    summary = {
        "total": len(all_backups),
        "by_type": {},
        "total_size_bytes": 0,
    }
    for b in all_backups:
        bt = b.get("type", "unknown")
        summary["by_type"].setdefault(bt, {"count": 0, "size_bytes": 0})
        summary["by_type"][bt]["count"] += 1
        summary["by_type"][bt]["size_bytes"] += b.get("size", 0)
        summary["total_size_bytes"] += b.get("size", 0)

    for bt in summary["by_type"]:
        summary["by_type"][bt]["size_mb"] = round(summary["by_type"][bt]["size_bytes"] / (1024 * 1024), 2)
    summary["total_size_mb"] = round(summary["total_size_bytes"] / (1024 * 1024), 2)
    return summary
