import os
import sqlite3
import uuid
import threading
import logging
from datetime import datetime
from sqlalchemy import DateTime
from sqlalchemy.exc import IntegrityError

from utils.migration import IMPORT_ORDER

logger = logging.getLogger(__name__)

import_progress = {}

BATCH_SIZE = 500

TABLE_MODEL_MAP = {
    "user": "User",
    "group": "Group",
    "system_broadcast": "SystemBroadcast",
    "group_member": "GroupMember",
    "group_invite": "GroupInvite",
    "group_join_request": "GroupJoinRequest",
    "message": "Message",
}

SOURCE_TABLE_MAP = {
    "user": "user",
    "group": "group",
    "system_broadcast": "system_broadcast",
    "group_member": "group_member",
    "group_invite": "group_invite",
    "group_join_request": "group_join_request",
    "message": "message",
}


class ImportBatchError(Exception):
    def __init__(self, table, batch_index, message):
        self.table = table
        self.batch_index = batch_index
        super().__init__(f"Import failed for {table} batch #{batch_index}: {message}")


def run_import(source_path, config, app):
    import_id = _generate_import_id()
    password = config.get("default_password", "password123")
    policies = config.get("policies", {})
    enabled = config.get("enabled", {})

    progress = {
        "status": "pending",
        "progress_pct": 0,
        "tables": {t: {"status": "pending", "current": 0, "total": 0, "error": None} for t in IMPORT_ORDER},
        "cancel": False,
        "error": None,
        "import_id": import_id,
        "results": {},
    }
    import_progress[import_id] = progress

    def _worker():
        progress["status"] = "in_progress"
        try:
            with app.app_context():
                from database.database import db
                _do_import(source_path, config, progress, db, password)
        except Exception as e:
            logger.exception("Import %s failed unexpectedly", import_id)
            progress["status"] = "failed"
            progress["error"] = str(e)

    thread = threading.Thread(target=_worker, name=f"import-{import_id}", daemon=True)
    thread.start()
    return import_id


def _do_import(source_path, config, progress, db, password):
    if not os.path.isfile(source_path):
        progress["status"] = "failed"
        progress["error"] = f"Source file not found: {source_path}"
        return

    backup_result = _create_import_backup(progress.get("import_id", "unknown"))
    progress["pre_import_backup"] = backup_result
    if not backup_result.get("success"):
        progress["status"] = "failed"
        progress["error"] = f"Pre-import backup failed: {backup_result.get('error', 'Unknown error')}"
        return

    source_conn = sqlite3.connect(source_path)
    source_conn.row_factory = sqlite3.Row

    try:
        _detect_source_tables(source_conn, config)

        total_tables = len(IMPORT_ORDER)
        for idx, table in enumerate(IMPORT_ORDER):
            if progress.get("cancel"):
                progress["status"] = "cancelled"
                return

            if not config.get("enabled", {}).get(table, True):
                progress["tables"][table]["status"] = "skipped"
                _update_overall_progress(progress, idx + 1, total_tables)
                continue

            _import_table(source_conn, table, config, progress, db, password)
            _update_overall_progress(progress, idx + 1, total_tables)

        if not progress.get("cancel"):
            progress["status"] = "completed"
            progress["progress_pct"] = 100

    except ImportBatchError as e:
        progress["status"] = "failed"
        progress["error"] = str(e)
        if e.table in progress["tables"]:
            progress["tables"][e.table]["error"] = str(e)
    except Exception as e:
        logger.exception("Import failed")
        progress["status"] = "failed"
        progress["error"] = str(e)
    finally:
        source_conn.close()


def _import_table(source_conn, table_name, config, progress, db, password):
    table_progress = progress["tables"][table_name]
    table_progress["status"] = "in_progress"

    from models.models import User, Message, Group, GroupMember, GroupInvite, GroupJoinRequest, SystemBroadcast

    model_map = {
        "user": User,
        "message": Message,
        "group": Group,
        "group_member": GroupMember,
        "group_invite": GroupInvite,
        "group_join_request": GroupJoinRequest,
        "system_broadcast": SystemBroadcast,
    }

    Model = model_map.get(table_name)
    if not Model:
        table_progress["status"] = "skipped"
        return

    source_table = config.get("source_table_map", {}).get(table_name, table_name)
    if not _source_table_exists(source_conn, source_table):
        table_progress["status"] = "skipped"
        table_progress["total"] = 0
        return

    rows = _read_source_rows(source_conn, source_table, table_name)
    table_progress["total"] = len(rows)

    if len(rows) == 0:
        table_progress["status"] = "completed"
        table_progress["current"] = 0
        progress["results"][table_name] = {"imported": 0, "skipped": 0, "replaced": 0, "total": 0}
        return

    existing = _get_existing_lookup(Model, table_name)

    imported = 0
    skipped = 0
    replaced = 0

    for i in range(0, len(rows), BATCH_SIZE):
        if progress.get("cancel"):
            return

        batch = rows[i:i + BATCH_SIZE]
        resolved = _resolve_batch(batch, table_name, config, existing)

        to_import = [r for action, r in resolved if action == "import"]
        to_skip = [r for action, r in resolved if action == "skip"]
        to_replace = [r for action, r in resolved if action == "replace"]

        skipped += len(to_skip)
        replaced += len(to_replace)

        if to_replace:
            _do_replace(to_replace, table_name, Model, db)

        if to_import:
            _do_insert(to_import, table_name, Model, db, password, table_progress, i)

        imported += len(to_import)
        table_progress["current"] = min(i + BATCH_SIZE, len(rows))

    table_progress["status"] = "completed"
    progress["results"][table_name] = {
        "imported": imported,
        "skipped": skipped,
        "replaced": replaced,
        "total": len(rows),
    }


def _do_insert(rows, table_name, Model, db, password, table_progress, batch_index):
    try:
        objects = [_row_to_model(row, table_name, Model, db, password) for row in rows]
        db.session.bulk_save_objects(objects)
        db.session.commit()
    except IntegrityError as e:
        db.session.rollback()
        logger.error("Batch %d for %s failed: %s", batch_index, table_name, e)
        raise ImportBatchError(table_name, batch_index, str(e))
    except Exception as e:
        db.session.rollback()
        logger.error("Unexpected error in batch %d for %s: %s", batch_index, table_name, e)
        raise ImportBatchError(table_name, batch_index, str(e))


def _do_replace(rows, table_name, Model, db):
    try:
        for row in rows:
            if table_name == "message":
                existing = Model.query.filter_by(msg_id=row.get("msg_id")).first()
            elif table_name == "user":
                existing = Model.query.filter_by(username=row.get("username")).first()
            else:
                continue

            if existing:
                db.session.delete(existing)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.warning("Replace failed for %s batch: %s", table_name, e)

def _parse_datetime(val):
    if not val:
        return None
    if isinstance(val, datetime):
        return val
    # Try common formats found in SQLite dumps
    for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S'):
        try:
            return datetime.strptime(val, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(val)
    except ValueError:
        return None


def _row_to_model(row, table_name, Model, db, password):
    data = dict(row)
    data.pop("id", None)

    # Convert SQLite string timestamps to Python datetime objects for mapped DateTime columns
    datetime_cols = {c.name for c in Model.__table__.columns if isinstance(c.type, DateTime)}
    for col_name in datetime_cols:
        if col_name in data and isinstance(data[col_name], str):
            data[col_name] = _parse_datetime(data[col_name])

    if table_name == "user":
        username = data.get("username", str(uuid.uuid4()))
        password_hash = data.get("password_hash", "")
        user = Model(username=username)
        if password_hash:
            user.password_hash = password_hash
        else:
            user.set_password(password)
        user.status = data.get("status", "Available")
        user.is_banned = data.get("is_banned", False)
        user.is_admin = data.get("is_admin", False)
        return user

    if table_name == "message":
        if "msg_id" not in data or not data.get("msg_id"):
            data["msg_id"] = str(uuid.uuid4())

    return Model(**{k: v for k, v in data.items() if hasattr(Model, k)})


def _read_source_rows(conn, source_table, table_name):
    try:
        cur = conn.execute(f"SELECT * FROM `{source_table}`")
        return [dict(row) for row in cur.fetchall()]
    except sqlite3.Error as e:
        logger.warning("Could not read from source table %s: %s", source_table, e)
        return []


def _resolve_batch(rows, table_name, config, existing):
    policy = config.get("policies", {}).get(table_name, "skip")
    resolutions = {}

    if table_name == "user":
        resolutions["existing_usernames"] = existing
    elif table_name == "message":
        resolutions["existing_msg_ids"] = existing
    elif table_name == "group":
        resolutions["existing_names"] = existing
    elif table_name == "group_member":
        resolutions = {}
    elif table_name == "group_invite":
        resolutions = {}
    elif table_name == "group_join_request":
        resolutions = {}
    elif table_name == "system_broadcast":
        resolutions = {}

    from utils.migration.resolver import apply_resolutions
    return apply_resolutions(rows, table_name, policy, resolutions)


def _get_existing_lookup(Model, table_name):
    try:
        if table_name == "user":
            return {u.username.lower() for u in Model.query.with_entities(Model.username).all()}
        elif table_name == "message":
            return {m.msg_id for m in Model.query.with_entities(Model.msg_id).all() if m.msg_id}
        elif table_name == "group":
            return {g.name.lower() for g in Model.query.with_entities(Model.name).all()}
        else:
            return set()
    except Exception:
        return set()


def _source_table_exists(conn, table_name):
    try:
        cur = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
        return cur.fetchone()[0] > 0
    except sqlite3.Error:
        return False


def _detect_source_tables(conn, config):
    source_map = {}
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    existing = {row[0] for row in cur.fetchall()}

    for target_table, source_table in SOURCE_TABLE_MAP.items():
        if source_table in existing:
            source_map[target_table] = source_table
        elif target_table == "message" and "messages" in existing:
            source_map[target_table] = "messages"
        elif target_table == "group" and "group" in existing:
            source_map[target_table] = "group"
        else:
            source_map[target_table] = source_table

    config["source_table_map"] = source_map


def _create_import_backup(import_id):
    try:
        from utils.backup import create_pre_import_backup
        return create_pre_import_backup(import_id)
    except Exception as e:
        logger.warning("Backup creation failed (non-fatal if app context unavailable): %s", e)
        return {"success": True, "skipped": True, "message": "Backup skipped (non-fatal)"}


def _update_overall_progress(progress, completed, total):
    progress["progress_pct"] = int((completed / total) * 100)


def _generate_import_id():
    return str(uuid.uuid4())


def cancel_import(import_id):
    prog = import_progress.get(import_id)
    if not prog:
        return {"found": False, "message": "Import not found"}
    if prog["status"] != "in_progress":
        return {"found": True, "message": f"Import is not in progress (status: {prog['status']})"}
    prog["cancel"] = True
    return {"found": True, "message": "Cancellation requested. Finishing current batch..."}


def get_import_status(import_id):
    prog = import_progress.get(import_id)
    if not prog:
        return None

    return {
        "import_id": prog["import_id"],
        "status": prog["status"],
        "progress_pct": prog["progress_pct"],
        "tables": prog["tables"],
        "error": prog["error"],
        "results": prog.get("results", {}),
    }
