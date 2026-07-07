import os
import uuid
import json
import tempfile
import logging
from flask import Blueprint, render_template, request, jsonify, session, redirect
from utils.api import success_response, error_response, ErrorCode
from utils.security import rate_limit, admin_key

logger = logging.getLogger(__name__)

migration_bp = Blueprint('migration', __name__, url_prefix='/admin')


@migration_bp.before_request
def check_admin_session():
    if not session.get('admin_logged_in'):
        return redirect('/login')


# Rate limit constant (conservative — admin-only, data-sensitive operations)
MIGRATION_LIMIT = 10


@migration_bp.route('/db-import')
def db_import_page():
    return render_template('admin/admin_db_import.html')


@migration_bp.route('/api/db-import/scan', methods=['POST'])
@rate_limit(MIGRATION_LIMIT, key_func=admin_key)
def scan_uploaded_db():
    try:
        if 'file' not in request.files:
            return error_response(ErrorCode.VALIDATION_MISSING_FIELD[0], "No file provided", status_code=400)
        f = request.files['file']
        if not f.filename:
            return error_response(ErrorCode.VALIDATION_MISSING_FIELD[0], "No file selected", status_code=400)
        if not f.filename.endswith('.db'):
            return error_response(ErrorCode.VALIDATION_INVALID_INPUT[0], "Only .db files are accepted", status_code=400)

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        f.save(tmp.name)
        tmp.close()

        from utils.migration.scanner import scan, detect_version
        scan_result = scan(tmp.name)
        if "error" in scan_result:
            return error_response(ErrorCode.SERVER_INTERNAL_ERROR[0], scan_result["error"], status_code=500)

        tables_info = scan_result.get("tables", {})
        version_detected = detect_version(tables_info)

        from utils.migration.validator import validate_schema
        validation_issues = validate_schema(tables_info, version_detected)

        from utils.migration.resolver import detect_conflicts
        from database.database import db as flask_db

        import sqlite3
        source_conn = sqlite3.connect(tmp.name)
        from models.models import User, Message, Group, GroupMember, GroupInvite, GroupJoinRequest, SystemBroadcast
        from utils.migration.constants import ModelKeys
        target_models = {
            ModelKeys.USER: User,
            ModelKeys.MESSAGE: Message,
            ModelKeys.GROUP: Group,
            ModelKeys.GROUP_MEMBER: GroupMember,
            ModelKeys.GROUP_INVITE: GroupInvite,
            ModelKeys.GROUP_JOIN_REQUEST: GroupJoinRequest,
            ModelKeys.SYSTEM_BROADCAST: SystemBroadcast,
        }
        enabled = {"user": True, "message": True, "group": True, "group_member": True, "group_invite": True, "group_join_request": True, "system_broadcast": True}
        conflict_report = detect_conflicts(source_conn, flask_db.session, target_models, enabled)
        source_conn.close()

        preview = {}
        if conflict_report:
            for entity in ('user', 'message', 'group'):
                entity_info = conflict_report.entities.get(entity, {})
                entity_conflicts = entity_info.get("conflicts", [])
                preview[entity] = {
                    "total_conflicts": len(entity_conflicts),
                    "conflict_keys": [str(c) for c in entity_conflicts[:20]],
                    "total_source": entity_info.get("total_in_source", 0),
                    "total_existing": 0,
                }

        upload_id = str(uuid.uuid4())
        _uploaded_files[upload_id] = tmp.name

        validation_issues_data = [
            {"severity": i.severity, "message": i.message}
            for i in validation_issues
        ]
        total_rows = sum(
            info.get("records", 0) for info in tables_info.values()
        )

        return success_response({
            "upload_id": upload_id,
            "scan": {
                "version": version_detected,
                "tables": len(tables_info),
                "total_rows": total_rows,
            },
            "validation": {
                "issues": validation_issues_data,
                "valid": all(i.severity != "error" for i in validation_issues),
            },
            "conflicts": preview,
            "message_types": list(scan_result.get("message_types", {})),
        })
    except Exception as e:
        logger.exception("Scan failed")
        return error_response(ErrorCode.SERVER_INTERNAL_ERROR[0], str(e), status_code=500)


@migration_bp.route('/api/db-import/preview', methods=['POST'])
@rate_limit(MIGRATION_LIMIT, key_func=admin_key)
def import_preview():
    try:
        data = request.json or {}
        upload_id = data.get("upload_id")
        if not upload_id or upload_id not in _uploaded_files:
            return error_response(ErrorCode.VALIDATION_MISSING_FIELD[0], "Invalid upload ID", status_code=400)

        source_path = _uploaded_files[upload_id]
        from utils.migration.resolver import detect_conflicts, generate_preview
        from database.database import db as flask_db

        import sqlite3
        source_conn = sqlite3.connect(source_path)
        from models.models import User, Message, Group, GroupMember, GroupInvite, GroupJoinRequest, SystemBroadcast
        from utils.migration.constants import ModelKeys
        target_models = {
            ModelKeys.USER: User,
            ModelKeys.MESSAGE: Message,
            ModelKeys.GROUP: Group,
            ModelKeys.GROUP_MEMBER: GroupMember,
            ModelKeys.GROUP_INVITE: GroupInvite,
            ModelKeys.GROUP_JOIN_REQUEST: GroupJoinRequest,
            ModelKeys.SYSTEM_BROADCAST: SystemBroadcast,
        }

        policies = data.get("policies", {})
        enabled = {"user": True, "message": True, "group": True, "group_member": True, "group_invite": True, "group_join_request": True, "system_broadcast": True}
        conflict_report = detect_conflicts(source_conn, flask_db.session, target_models, enabled)

        config = {"policies": policies, "enabled": enabled}
        preview_report = generate_preview(source_conn, flask_db.session, target_models, config)
        source_conn.close()

        return success_response({
            "preview": preview_report.to_dict() if preview_report else {},
            "conflicts": {
                e: v["conflict_count"] for e, v in conflict_report.entities.items()
            } if conflict_report else {},
            "total_conflicts": sum(e["conflict_count"] for e in conflict_report.entities.values()) if conflict_report else 0,
        })
    except Exception as e:
        logger.exception("Preview failed")
        return error_response(ErrorCode.SERVER_INTERNAL_ERROR[0], str(e), status_code=500)


@migration_bp.route('/api/db-import/start', methods=['POST'])
@rate_limit(MIGRATION_LIMIT, key_func=admin_key)
def start_import():
    try:
        data = request.json or {}
        upload_id = data.get("upload_id")
        if not upload_id or upload_id not in _uploaded_files:
            return error_response(ErrorCode.VALIDATION_MISSING_FIELD[0], "Invalid upload ID", status_code=400)

        source_path = _uploaded_files[upload_id]
        policies = data.get("policies", {})
        enabled = data.get("enabled", {})
        default_password = data.get("default_password", "password123")

        config = {
            "policies": policies,
            "enabled": enabled,
            "default_password": default_password,
        }

        from app import create_app
        from config import Config
        app = create_app(Config)

        from utils.migration.importer import run_import
        import_id = run_import(source_path, config, app)

        return success_response({
            "import_id": import_id,
        })
    except Exception as e:
        logger.exception("Import start failed")
        return error_response(ErrorCode.SERVER_INTERNAL_ERROR[0], str(e), status_code=500)


@migration_bp.route('/api/db-import/status/<import_id>')
@rate_limit(MIGRATION_LIMIT * 2, key_func=admin_key)
def import_status(import_id):
    from utils.migration.importer import get_import_status
    status = get_import_status(import_id)
    if status is None:
        return error_response(ErrorCode.VALIDATION_MISSING_FIELD[0], "Import not found", status_code=404)
    return success_response(status)


@migration_bp.route('/api/db-import/cancel/<import_id>', methods=['POST'])
@rate_limit(MIGRATION_LIMIT, key_func=admin_key)
def cancel_import_route(import_id):
    from utils.migration.importer import cancel_import
    result = cancel_import(import_id)
    return success_response(result)


@migration_bp.route('/api/db-import/result/<import_id>')
@rate_limit(MIGRATION_LIMIT, key_func=admin_key)
def import_result(import_id):
    from utils.migration.importer import get_import_status
    status = get_import_status(import_id)
    if status is None:
        return error_response(ErrorCode.VALIDATION_MISSING_FIELD[0], "Import not found", status_code=404)

    from utils.migration.printer import generate_report
    from config import Config
    db_uri = Config.SQLALCHEMY_DATABASE_URI
    db_path = db_uri.replace("sqlite:///", "") if db_uri.startswith("sqlite:///") else None
    report = generate_report(status, imported_db_path=db_path)

    return success_response(report)


_uploaded_files = {}
