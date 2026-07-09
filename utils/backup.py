import os
import sqlite3
import hashlib
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

BACKUP_DIR = "backups"
PRE_IMPORT_PREFIX = "pre_import_"
QUICK_SUBDIR = "quick"
FULL_SUBDIR = "full"
PRE_IMPORT_SUBDIR = "pre_import"

DEFAULT_RETENTION = {
    QUICK_SUBDIR: 10,
    FULL_SUBDIR: 5,
    PRE_IMPORT_SUBDIR: 20,
}


def _sha256_file(filepath):
    if not os.path.isfile(filepath):
        return None
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_sha256_sidecar(filepath, digest):
    sha_path = filepath + ".sha256"
    filename = os.path.basename(filepath)
    with open(sha_path, "w") as f:
        f.write(f"{digest}  {filename}\n")
    return sha_path


def _resolve_backup_dir(backup_dir, subdir=None):
    if backup_dir:
        base = backup_dir
    else:
        base = BACKUP_DIR
    if subdir:
        return os.path.join(base, subdir)
    return base


def create_backup(db_path="database/falcon_web.db", label=None, backup_dir=None, subdir=None):
    target_dir = _resolve_backup_dir(backup_dir, subdir)
    os.makedirs(target_dir, exist_ok=True)

    if not os.path.isfile(db_path):
        logger.error("Database not found: %s", db_path)
        return {"success": False, "error": f"Database not found: {db_path}"}

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    prefix = f"{label}_" if label else ""
    filename = f"{prefix}Falcon_Backup_{timestamp}.db"
    dest = os.path.join(target_dir, filename)
    
    counter = 1
    while os.path.exists(dest):
        filename = f"{prefix}Falcon_Backup_{timestamp}_{counter}.db"
        dest = os.path.join(target_dir, filename)
        counter += 1

    try:
        source_conn = sqlite3.connect(db_path)
        dest_conn = sqlite3.connect(dest)
        with dest_conn:
            source_conn.backup(dest_conn, pages=50)
        source_conn.close()
        dest_conn.close()
    except Exception as e:
        logger.exception("Backup failed: %s", e)
        return {"success": False, "error": str(e)}

    file_size = os.path.getsize(dest)
    sha256_digest = _sha256_file(dest)
    _write_sha256_sidecar(dest, sha256_digest)

    logger.info("Backup created: %s (%d bytes, sha256=%s)", dest, file_size, sha256_digest)

    return {
        "success": True,
        "path": dest,
        "filename": filename,
        "size": file_size,
        "timestamp": timestamp,
        "sha256": sha256_digest,
        "type": subdir or "unknown",
    }


def create_quick_backup(db_path="database/falcon_web.db", backup_dir=None):
    return create_backup(db_path=db_path, subdir=QUICK_SUBDIR, backup_dir=backup_dir)


def create_pre_import_backup(import_id, db_path="database/falcon_web.db", backup_dir=None):
    label = f"{PRE_IMPORT_PREFIX}{import_id}"
    return create_backup(db_path=db_path, label=label, subdir=PRE_IMPORT_SUBDIR, backup_dir=backup_dir)


def _scan_directory(backup_dir, subdir=None):
    target_dir = _resolve_backup_dir(backup_dir, subdir)
    if not os.path.isdir(target_dir):
        return []
    entries = []
    for fname in sorted(os.listdir(target_dir), reverse=True):
        fpath = os.path.join(target_dir, fname)
        if not os.path.isfile(fpath) or fname.endswith(".sha256"):
            continue
        stat = os.stat(fpath)
        sha256_digest = None
        sha_path = fpath + ".sha256"
        if os.path.isfile(sha_path):
            try:
                with open(sha_path) as f:
                    sha256_digest = f.read().strip().split()[0]
            except (IndexError, OSError):
                pass
        entries.append({
            "filename": fname,
            "path": fpath,
            "size": stat.st_size,
            "mtime": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            "sha256": sha256_digest,
            "is_pre_import": fname.startswith(PRE_IMPORT_PREFIX),
            "type": subdir or "unknown",
        })
    return entries


def list_backups(backup_dir=None, backup_type=None, subdir=None):
    if subdir:
        return _scan_directory(backup_dir, subdir)
    if backup_type:
        return _scan_directory(backup_dir, backup_type)
    all_entries = []
    for sd in (QUICK_SUBDIR, FULL_SUBDIR, PRE_IMPORT_SUBDIR):
        all_entries.extend(_scan_directory(backup_dir, sd))
    all_entries.extend(_scan_directory(backup_dir, None))
    all_entries.sort(key=lambda e: e["mtime"], reverse=True)
    return all_entries


def search_backups(query, backup_dir=None):
    q = query.lower()
    results = []
    for entry in list_backups(backup_dir=backup_dir):
        if q in entry["filename"].lower() or q in entry.get("type", "").lower():
            results.append(entry)
    return results


def restore_backup(backup_path, target_path="database/falcon_web.db"):
    if not os.path.isfile(backup_path):
        return {"success": False, "error": f"Backup file not found: {backup_path}"}

    try:
        backup_conn = sqlite3.connect(backup_path)
        target_conn = sqlite3.connect(target_path)
        with target_conn:
            backup_conn.backup(target_conn, pages=50)
        backup_conn.close()
        target_conn.close()
    except Exception as e:
        logger.exception("Restore failed: %s", e)
        return {"success": False, "error": str(e)}

    logger.info("Database restored from: %s", backup_path)
    return {"success": True, "path": target_path}


def verify_backup_file(backup_path):
    if not os.path.isfile(backup_path):
        return {"valid": False, "error": "File not found"}
    sha_path = backup_path + ".sha256"
    actual = _sha256_file(backup_path)
    stored = None
    if os.path.isfile(sha_path):
        try:
            with open(sha_path) as f:
                stored = f.read().strip().split()[0]
        except (IndexError, OSError):
            pass
    match = stored is None or actual == stored
    return {
        "valid": match,
        "sha256_actual": actual,
        "sha256_stored": stored,
        "match": match,
        "has_sidecar": stored is not None,
    }


def prune_backups(retain_count=None, backup_dir=None, backup_type=None):
    if backup_type:
        result = _prune_single(retain_count, backup_dir, backup_type)
        result["success"] = True
        return result

    total_deleted = []
    for btype, default_retain in DEFAULT_RETENTION.items():
        rc = retain_count if retain_count is not None else default_retain
        sub_result = _prune_single(rc, backup_dir, btype)
        total_deleted.extend(sub_result.get("deleted", []))
    flat_result = _prune_single(retain_count or 10, backup_dir, None)
    total_deleted.extend(flat_result.get("deleted", []))
    return {"success": True, "deleted": total_deleted}


def _prune_single(retain_count, backup_dir, subdir):
    target_dir = _resolve_backup_dir(backup_dir, subdir)
    if not os.path.isdir(target_dir):
        return {"deleted": []}

    all_backups = _scan_directory(backup_dir, subdir)
    actual_retain = retain_count if retain_count is not None else DEFAULT_RETENTION.get(subdir, 10)
    if len(all_backups) <= actual_retain:
        return {"deleted": []}

    to_delete = all_backups[actual_retain:]
    deleted = []
    for b in to_delete:
        try:
            sha_path = b["path"] + ".sha256"
            if os.path.isfile(sha_path):
                os.remove(sha_path)
            os.remove(b["path"])
            deleted.append(b["filename"])
            logger.info("Pruned backup: %s", b["filename"])
        except OSError as e:
            logger.warning("Failed to prune backup %s: %s", b["filename"], e)

    return {"deleted": deleted}
