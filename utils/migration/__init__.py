from utils.migration.scanner import scan, detect_version, extract_users_from_messages

try:
    from utils.migration.validator import validate_schema, check_integrity, check_column_compatibility
except ImportError:
    pass

try:
    from utils.migration.resolver import detect_conflicts, generate_preview, apply_resolutions
except ImportError:
    pass

try:
    from utils.migration.importer import run_import, cancel_import, get_import_status
except ImportError:
    pass

try:
    from utils.migration.printer import generate_report, save_report, format_human_readable
except ImportError:
    pass

IMPORT_ORDER = [
    "user",
    "group",
    "system_broadcast",
    "group_member",
    "group_invite",
    "group_join_request",
    "message",
]
