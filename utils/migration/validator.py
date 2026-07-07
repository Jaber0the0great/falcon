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

LEGACY_MESSAGE_COLUMNS = {"sender", "recipient", "content", "time", "msg_type", "msg_id", "file_name", "raw_data", "status", "reactions", "reply_to", "reply_content", "duration"}

EXPECTED_TABLES_LEGACY = {
    "messages": LEGACY_MESSAGE_COLUMNS,
}

CRITICAL_MESSAGE_COLUMNS = {"sender", "recipient", "msg_type", "msg_id"}
CRITICAL_USER_COLUMNS = {"username", "password_hash"}
CRITICAL_GROUP_COLUMNS = {"name", "owner_username"}


class ValidationIssue:
    def __init__(self, severity, code, message, table=None, column=None):
        self.severity = severity
        self.code = code
        self.message = message
        self.table = table
        self.column = column

    def to_dict(self):
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "table": self.table,
            "column": self.column,
        }

    def __repr__(self):
        return f"[{self.severity.upper()}] {self.code}: {self.message}"


def validate_schema(schema_info, version_detected):
    issues = []

    if version_detected == "v1.0":
        _validate_v1(schema_info, issues)
    elif version_detected == "legacy":
        _validate_legacy(schema_info, issues)
    elif version_detected == "unknown":
        _validate_unknown(schema_info, issues)
    else:
        issues.append(ValidationIssue("error", "UNKNOWN_VERSION", f"Unrecognized version: {version_detected}"))

    return issues


def _validate_v1(schema_info, issues):
    source_tables = {name: info for name, info in schema_info.items()}

    for expected_name, expected_cols in EXPECTED_TABLES_V1.items():
        if expected_name not in source_tables:
            if expected_name in ("group_member", "group_invite", "group_join_request"):
                issues.append(ValidationIssue("warning", "MISSING_TABLE", f"Optional table '{expected_name}' not found", table=expected_name))
            else:
                issues.append(ValidationIssue("error", "MISSING_TABLE", f"Required table '{expected_name}' not found", table=expected_name))
            continue

        source_cols = {c["name"] for c in source_tables[expected_name].get("columns", [])}
        missing = [c for c in expected_cols if c not in source_cols]
        extra = [c for c in sorted(source_cols) if c not in expected_cols]

        for col in missing:
            if col in _get_critical_columns(expected_name):
                issues.append(ValidationIssue("error", "MISSING_CRITICAL_COLUMN", f"Required column '{expected_name}.{col}' not found", table=expected_name, column=col))
            else:
                issues.append(ValidationIssue("warning", "MISSING_COLUMN", f"Optional column '{expected_name}.{col}' not found — will use default", table=expected_name, column=col))

        for col in extra:
            issues.append(ValidationIssue("info", "EXTRA_COLUMN", f"Extra column '{expected_name}.{col}' found — will be ignored during import", table=expected_name, column=col))


def _get_critical_columns(table_name):
    if table_name == "user":
        return CRITICAL_USER_COLUMNS
    elif table_name == "message":
        return CRITICAL_MESSAGE_COLUMNS
    elif table_name == "group":
        return CRITICAL_GROUP_COLUMNS
    return set()


def _validate_legacy(schema_info, issues):
    table_name = "messages" if "messages" in schema_info else "message"
    if table_name not in schema_info:
        issues.append(ValidationIssue("error", "MISSING_TABLE", "No 'messages' or 'message' table found in legacy database"))
        return

    source_cols = {c["name"] for c in schema_info[table_name].get("columns", [])}
    missing = LEGACY_MESSAGE_COLUMNS - source_cols

    for col in sorted(missing):
        if col in CRITICAL_MESSAGE_COLUMNS:
            issues.append(ValidationIssue("warning", "MISSING_CRITICAL_COLUMN", f"Critical column '{col}' not found — will generate default values", table=table_name, column=col))
        else:
            issues.append(ValidationIssue("info", "MISSING_COLUMN", f"Column '{col}' not found — will use default", table=table_name, column=col))


def _validate_unknown(schema_info, issues):
    if not schema_info:
        issues.append(ValidationIssue("error", "NO_TABLES", "Database contains no tables"))
        return

    issues.append(ValidationIssue("warning", "UNKNOWN_SCHEMA", "Could not determine database version — will attempt best-effort import"))

    for table_name, info in schema_info.items():
        if table_name in EXPECTED_TABLES_V1:
            issues.append(ValidationIssue("info", "RECOGNIZED_TABLE", f"Table '{table_name}' matches expected schema", table=table_name))
        else:
            issues.append(ValidationIssue("warning", "UNRECOGNIZED_TABLE", f"Table '{table_name}' is not recognized — will be skipped", table=table_name))


def check_integrity(conn):
    try:
        cur = conn.execute("PRAGMA integrity_check")
        row = cur.fetchone()
        if row and row[0] == "ok":
            return {"passed": True, "message": "ok"}
        return {"passed": False, "message": row[0] if row else "integrity check returned no result"}
    except Exception as e:
        return {"passed": False, "message": str(e)}


def check_column_compatibility(source_columns, expected_columns):
    source_names = {c["name"] for c in source_columns}
    expected_names = set(expected_columns)

    missing = sorted(expected_names - source_names)
    extra = sorted(source_names - expected_names)
    common = sorted(source_names & expected_names)

    return {
        "missing": missing,
        "extra": extra,
        "common": common,
        "compatible": len(missing) == 0,
    }
