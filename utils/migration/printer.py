import os
import json
import hashlib
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

DEFAULT_LOG_DIR = "logs/imports"


def sha256_checksum(filepath):
    if not os.path.isfile(filepath):
        return None
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def generate_report(progress_data, scan_result=None, validation_result=None, imported_db_path=None):
    report = {
        "import_id": progress_data.get("import_id", "unknown"),
        "status": progress_data.get("status", "unknown"),
        "progress_pct": progress_data.get("progress_pct", 0),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tables": {},
        "error": progress_data.get("error"),
    }

    for table_name, table_info in progress_data.get("tables", {}).items():
        report["tables"][table_name] = {
            "status": table_info.get("status", "unknown"),
            "current": table_info.get("current", 0),
            "total": table_info.get("total", 0),
            "error": table_info.get("error"),
        }

    results = progress_data.get("results", {})
    report["import_summary"] = {
        "total_imported": sum(r.get("imported", 0) for r in results.values()),
        "total_skipped": sum(r.get("skipped", 0) for r in results.values()),
        "total_replaced": sum(r.get("replaced", 0) for r in results.values()),
        "total_records": sum(r.get("total", 0) for r in results.values()),
    }

    if imported_db_path:
        report["sha256"] = sha256_checksum(imported_db_path)

    pre_import_backup = progress_data.get("pre_import_backup")
    if pre_import_backup and pre_import_backup.get("path"):
        report["pre_import_backup"] = {
            "path": pre_import_backup["path"],
            "sha256": sha256_checksum(pre_import_backup["path"]),
        }

    if scan_result:
        report["scan"] = _sanitize_scan(scan_result)
    if validation_result:
        report["validation"] = _sanitize_validation(validation_result)

    return report


def print_summary(progress_data, output=None):
    lines = []
    lines.append("=" * 60)
    lines.append("DATABASE IMPORT SUMMARY")
    lines.append("=" * 60)
    lines.append(f"Import ID: {progress_data.get('import_id', 'N/A')}")
    lines.append(f"Status: {progress_data.get('status', 'N/A')}")
    lines.append(f"Progress: {progress_data.get('progress_pct', 0)}%")

    error = progress_data.get("error")
    if error:
        lines.append(f"Error: {error}")

    sha256 = progress_data.get("sha256")
    if sha256:
        lines.append(f"SHA256: {sha256}")

    lines.append("")
    lines.append("Tables:")
    for table_name in ("user", "group", "system_broadcast", "group_member", "group_invite", "group_join_request", "message"):
        info = progress_data.get("tables", {}).get(table_name)
        if not info:
            continue
        status = info.get("status", "?")
        current = info.get("current", 0)
        total = info.get("total", 0)
        err = info.get("error")
        err_str = f" [ERROR: {err}]" if err else ""
        lines.append(f"  {table_name:20s} {status:12s} {current:4d}/{total:<4d}{err_str}")

    results = progress_data.get("results", {})
    if results:
        lines.append("")
        lines.append("Results:")
        for table_name in ("user", "group", "system_broadcast", "group_member", "group_invite", "group_join_request", "message"):
            r = results.get(table_name)
            if not r:
                continue
            imported = r.get("imported", 0)
            skipped = r.get("skipped", 0)
            replaced = r.get("replaced", 0)
            total = r.get("total", 0)
            lines.append(f"  {table_name:20s} imported={imported} skipped={skipped} replaced={replaced} total={total}")

    lines.append("=" * 60)

    output_text = "\n".join(lines)
    if output:
        output.write(output_text)
        output.write("\n")
    else:
        print(output_text)

    return output_text


def save_report(progress_data, log_dir=DEFAULT_LOG_DIR, scan_result=None, validation_result=None, imported_db_path=None):
    import_id = progress_data.get("import_id", "unknown")
    report_dir = os.path.join(log_dir, import_id)
    os.makedirs(report_dir, exist_ok=True)

    report = generate_report(progress_data, scan_result, validation_result, imported_db_path)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(report_dir, "report.json")
    summary_path = os.path.join(report_dir, "report.txt")

    report["report_files"] = {
        "json": os.path.relpath(report_path, log_dir),
        "text": os.path.relpath(summary_path, log_dir),
        "timestamp": timestamp,
    }

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    progress_data_for_summary = dict(progress_data)
    progress_data_for_summary["sha256"] = report.get("sha256")
    with open(summary_path, "w", encoding="utf-8") as f:
        print_summary(progress_data_for_summary, output=f)

    return {"report_path": report_path, "summary_path": summary_path, "report_dir": report_dir}


def _sanitize_scan(scan_result):
    if isinstance(scan_result, dict):
        return {k: str(v) if not isinstance(v, (str, int, float, bool, list, type(None))) else v for k, v in scan_result.items()}
    return str(scan_result)


def _sanitize_validation(validation_result):
    if isinstance(validation_result, dict):
        return {k: str(v) if not isinstance(v, (str, int, float, bool, list, type(None))) else v for k, v in validation_result.items()}
    return str(validation_result)


format_human_readable = print_summary
