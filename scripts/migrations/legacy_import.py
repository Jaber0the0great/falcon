#!/usr/bin/env python
"""
Legacy database import tool.

Usage:
    python -m scripts.migrations.legacy_import <source.db> [options]

Runs the full import pipeline: scan -> validate -> resolve -> import.
"""

import argparse
import sys
import json
import os
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

IMPORT_ORDER = ["user", "group", "system_broadcast", "group_member", "group_invite", "group_join_request", "message"]


def main():
    parser = argparse.ArgumentParser(description="Import a legacy SQLite database into Falcon Web App.")
    parser.add_argument("source", help="Path to the source SQLite database file")
    parser.add_argument("--db-uri", default=None, help="SQLAlchemy database URI for the target database")
    parser.add_argument("--config", help="Path to a JSON config file with policies and settings")
    parser.add_argument("--default-password", default="password123", help="Default password for imported users")
    parser.add_argument("--no-import", action="store_true", help="Run scan/validate/resolve only, skip import")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompts")
    parser.add_argument("--log-dir", default="logs/imports", help="Directory for import logs and reports")
    args = parser.parse_args()

    source_path = os.path.abspath(args.source)
    if not os.path.isfile(source_path):
        logger.error("Source file not found: %s", source_path)
        sys.exit(1)

    logger.info("Source database: %s", source_path)

    config = _load_config(args)
    if config is None:
        sys.exit(1)

    config["default_password"] = args.default_password

    _run_pipeline(source_path, config, args)


def _load_config(args):
    if args.config:
        try:
            with open(args.config, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error("Failed to load config file: %s", e)
            return None

    return {
        "policies": {
            "user": "skip",
            "message": "skip_duplicates",
            "group": "skip",
            "group_member": "import_all",
            "group_invite": "import_all",
            "group_join_request": "import_all",
            "system_broadcast": "import_all",
        },
        "enabled": {t: True for t in IMPORT_ORDER},
    }


def _run_pipeline(source_path, config, args):
    from app import create_app
    from config import Config

    class ImportConfig(Config):
        TESTING = False
        SQLALCHEMY_DATABASE_URI = args.db_uri or Config.SQLALCHEMY_DATABASE_URI

    app = create_app(ImportConfig)

    logger.info("Step 1: Scanning source database...")
    from utils.migration.scanner import scan, detect_version
    try:
        scan_result = scan(source_path)
        version_info = detect_version(source_path)
        logger.info("  Detected version: %s", version_info.get("version", "unknown"))
        logger.info("  Tables found: %d", len(scan_result.get("tables", {})))
        logger.info("  Total rows: %d", scan_result.get("total_rows", 0))
    except Exception as e:
        logger.error("Scan failed: %s", e)
        sys.exit(1)

    logger.info("Step 2: Validating schema...")
    from utils.migration.validator import validate_schema, check_integrity
    try:
        validation = validate_schema(source_path)
        issues = validation.get("issues", [])
        logger.info("  Validation issues: %d", len(issues))
        for issue in issues:
            logger.info("    [%s] %s: %s", issue.get("severity", "?"), issue.get("field", "?"), issue.get("message", ""))
    except Exception as e:
        logger.error("Validation failed: %s", e)
        sys.exit(1)

    logger.info("Step 3: Detecting conflicts...")
    from utils.migration.resolver import detect_conflicts, generate_preview

    with app.app_context():
        from database.database import db
        try:
            conflict_report = detect_conflicts(source_path)
            preview = generate_preview(conflict_report, config.get("policies", {}))
            logger.info("  Total conflicts: %d", conflict_report.total_conflicts)
            if preview:
                for entity, info in preview.items():
                    logger.info("  %s: %d to import, %d to skip", entity, info.get("to_import", 0), info.get("to_skip", 0))
        except Exception as e:
            logger.error("Conflict detection failed: %s", e)
            sys.exit(1)

    if not args.yes:
        response = input("Proceed with import? [y/N]: ").strip().lower()
        if response != "y":
            logger.info("Import cancelled by user.")
            sys.exit(0)

    if args.no_import:
        logger.info("Skipping import (--no-import specified).")
        logger.info("Scan, validation, and conflict resolution complete.")
        sys.exit(0)

    logger.info("Step 4: Importing data (this may take a while)...")
    from utils.migration.importer import run_import, get_import_status, cancel_import, import_progress

    import_id = run_import(source_path, config, app)
    logger.info("  Import ID: %s", import_id)

    try:
        _monitor_import(import_id, args)
    except KeyboardInterrupt:
        logger.warning("Interrupted! Requesting cancellation...")
        cancel_import(import_id)
        logger.info("Waiting for graceful shutdown...")
        for _ in range(30):
            status = get_import_status(import_id)
            if status and status["status"] in ("completed", "failed", "cancelled"):
                break
            import time
            time.sleep(1)
        logger.info("Import %s.", get_import_status(import_id).get("status", "unknown"))
        sys.exit(130)

    final_status = get_import_status(import_id)
    if not final_status:
        logger.error("Could not retrieve final import status.")
        sys.exit(1)

    logger.info("Step 5: Generating report...")
    from utils.migration.printer import print_summary, save_report

    print()
    print_summary(final_status)

    from config import Config
    db_path = args.db_uri or Config.SQLALCHEMY_DATABASE_URI
    if db_path and db_path.startswith("sqlite:///"):
        imported_db_path = db_path[len("sqlite:///"):]
    else:
        imported_db_path = "database/falcon_web.db"

    try:
        paths = save_report(final_status, log_dir=args.log_dir, scan_result=scan_result, validation_result=validation, imported_db_path=imported_db_path)
        logger.info("Report saved: %s", paths["report_path"])
        logger.info("Summary saved: %s", paths["summary_path"])
    except Exception as e:
        logger.warning("Could not save report: %s", e)

    if final_status["status"] == "failed":
        logger.error("Import failed: %s", final_status.get("error", "Unknown error"))
        sys.exit(1)

    logger.info("Import completed successfully.")


def _monitor_import(import_id, args):
    import time
    from utils.migration.importer import get_import_status

    while True:
        status = get_import_status(import_id)
        if not status:
            break

        if status["status"] in ("completed", "failed", "cancelled"):
            break

        pct = status.get("progress_pct", 0)
        print(f"\r  Progress: {pct}%", end="", flush=True)
        time.sleep(1)

    print()


if __name__ == "__main__":
    main()
