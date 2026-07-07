import os
import sqlite3
import logging

logger = logging.getLogger(__name__)

EXPECTED_TABLES_V1 = {
    "user": ["id", "username", "password_hash", "status", "created_at", "last_seen", "is_banned", "is_admin"],
    "message": ["id", "sender", "recipient", "msg_type", "content", "time", "duration", "file_name", "raw_data", "status", "msg_id", "reactions", "reply_to", "reply_content", "deleted_by_sender", "deleted_by_recipient", "created_at"],
    "group": ["id", "name", "description", "owner_username", "created_at"],
    "group_member": ["id", "group_name", "username", "joined_at"],
    "group_invite": ["id", "group_name", "username", "status", "invited_by"],
    "group_join_request": ["id", "group_name", "username", "status"],
    "system_broadcast": ["id", "message", "created_at", "is_sent"],
}

LEGACY_MESSAGE_COLUMNS = ["sender", "recipient", "content", "time", "msg_type", "msg_id", "file_name", "raw_data", "status", "reactions", "reply_to", "reply_content", "duration"]


def scan(filepath):
    if not os.path.isfile(filepath):
        return {"error": f"File not found: {filepath}"}

    file_size = os.path.getsize(filepath)
    if file_size == 0:
        return {"error": "Database file is empty (0 bytes)"}

    if not _is_sqlite(filepath):
        return {"error": "Not a valid SQLite database (magic bytes mismatch)"}

    try:
        conn = sqlite3.connect(filepath)
        conn.execute("PRAGMA journal_mode=OFF")
    except sqlite3.Error as e:
        return {"error": f"Cannot open database: {e}"}

    try:
        integrity = _check_integrity(conn)
        if not integrity["passed"]:
            return {"error": f"Database integrity check failed: {integrity['message']}"}

        tables = _discover_tables(conn)
        version = detect_version(tables)

        result = {
            "file_path": os.path.abspath(filepath),
            "file_size_bytes": file_size,
            "format": "SQLite 3.x",
            "version_detected": version,
            "integrity": integrity,
            "tables": {},
        }

        for table_name, info in tables.items():
            columns = _get_columns(conn, table_name)
            row_count = _count_rows(conn, table_name)
            result["tables"][table_name] = {
                "records": row_count,
                "columns": columns,
            }

        if version == "legacy":
            result["extracted_users"] = extract_users_from_messages(conn)
            result["message_types"] = _count_message_types(conn)
            result["date_range"] = _get_date_range(conn)
        elif version in ("v1.0", "partial"):
            result["message_types"] = _count_message_types(conn) if "message" in tables else {}
            result["date_range"] = _get_date_range(conn) if "message" in tables else None
            if "user" in tables:
                result["admin_count"] = _count_admins(conn)
        else:
            result["message_types"] = _count_message_types(conn) if "message" in tables else {}

        return result

    except Exception as e:
        logger.exception("Scanner failed: %s", e)
        return {"error": f"Scan failed: {e}"}
    finally:
        conn.close()


def _is_sqlite(filepath):
    try:
        with open(filepath, "rb") as f:
            header = f.read(16)
        return header == b"SQLite format 3\x00"
    except OSError:
        return False


def _check_integrity(conn):
    try:
        cur = conn.execute("PRAGMA integrity_check")
        row = cur.fetchone()
        if row and row[0] == "ok":
            return {"passed": True, "message": "ok"}
        return {"passed": False, "message": row[0] if row else "integrity check returned no result"}
    except sqlite3.Error as e:
        return {"passed": False, "message": str(e)}


def _discover_tables(conn):
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = {}
    for row in cur.fetchall():
        name = row[0]
        if name.startswith("sqlite_"):
            continue
        tables[name] = {"name": name}
    return tables


def _get_columns(conn, table_name):
    cur = conn.execute(f"PRAGMA table_info(`{table_name}`)")
    return [{"name": row[1], "type": row[2], "notnull": bool(row[3]), "default": row[4], "pk": bool(row[5])} for row in cur.fetchall()]


def _count_rows(conn, table_name):
    try:
        cur = conn.execute(f"SELECT COUNT(*) FROM `{table_name}`")
        return cur.fetchone()[0]
    except sqlite3.Error:
        return -1


def _count_message_types(conn):
    try:
        cur = conn.execute("SELECT msg_type, COUNT(*) as cnt FROM message GROUP BY msg_type")
        return {row[0]: row[1] for row in cur.fetchall()}
    except sqlite3.Error:
        return {}


def _get_date_range(conn):
    try:
        cur = conn.execute("SELECT MIN(time), MAX(time) FROM message WHERE time IS NOT NULL")
        row = cur.fetchone()
        if row and row[0]:
            return {"earliest": row[0], "latest": row[1]}
        return None
    except sqlite3.Error:
        return None


def _count_admins(conn):
    try:
        cur = conn.execute("SELECT COUNT(*) FROM user WHERE is_admin = 1")
        return cur.fetchone()[0]
    except sqlite3.Error:
        return 0


def detect_version(tables):
    table_names = set(tables.keys())

    if EXPECTED_TABLES_V1.keys() <= table_names:
        return "v1.0"

    v1_without_optional = {"user", "message", "group"}
    if v1_without_optional <= table_names:
        return "v1.0"

    if "user" in table_names and "message" in table_names:
        return "v1.0"

    if "messages" in table_names or "message" in table_names:
        cols = _get_columns_for_detect(tables)
        if _is_likely_legacy(cols):
            return "legacy"

    if len(table_names) == 0:
        return "empty"

    return "unknown"


def _get_columns_for_detect(tables):
    return []


def _is_likely_legacy(cols):
    return True


EXCLUDED_NAMES = {"server", "all"}

def extract_users_from_messages(conn):
    users = set()
    try:
        table_name = "messages" if _table_exists(conn, "messages") else "message"
        cur = conn.execute(f"SELECT DISTINCT sender, recipient FROM `{table_name}`")
        for row in cur.fetchall():
            sender, recipient = row[0], row[1]
            if sender and sender.lower() not in EXCLUDED_NAMES:
                users.add(sender)
            if recipient and recipient.lower() not in EXCLUDED_NAMES:
                users.add(recipient)
    except sqlite3.Error as e:
        logger.warning("Could not extract users from messages: %s", e)
    return sorted(users)


def _table_exists(conn, table_name):
    cur = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
    return cur.fetchone()[0] > 0
