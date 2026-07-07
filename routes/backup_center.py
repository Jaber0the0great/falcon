import os
import json
import logging
from flask import Blueprint, render_template, request, jsonify, session, redirect, send_file
from utils.api import success_response, error_response, ErrorCode
from utils.security import rate_limit, admin_key

logger = logging.getLogger(__name__)

backup_center_bp = Blueprint('backup_center', __name__, url_prefix='/admin')

BACKUP_LIMIT = 10


@backup_center_bp.before_request
def check_admin_session():
    if not session.get('admin_logged_in'):
        return redirect('/login')


@backup_center_bp.route('/backup-center')
def backup_center_page():
    return render_template('admin/admin_backup_center.html')


@backup_center_bp.route('/api/backup-center/summary')
@rate_limit(BACKUP_LIMIT, key_func=admin_key)
def api_summary():
    from utils.backup_center import get_backup_summary
    summary = get_backup_summary()
    return success_response(summary)


@backup_center_bp.route('/api/backup-center/create-quick', methods=['POST'])
@rate_limit(BACKUP_LIMIT, key_func=admin_key)
def api_create_quick():
    from flask import current_app
    db_uri = current_app.config['SQLALCHEMY_DATABASE_URI']
    db_path = db_uri.replace('sqlite:///', '')
    from utils.backup import create_quick_backup
    result = create_quick_backup(db_path=db_path)
    if not result.get("success"):
        return error_response(ErrorCode.SERVER_INTERNAL_ERROR[0], result.get("error", "Backup failed"), status_code=500)
    return success_response(result)


@backup_center_bp.route('/api/backup-center/create-full', methods=['POST'])
@rate_limit(BACKUP_LIMIT, key_func=admin_key)
def api_create_full():
    from flask import current_app
    db_uri = current_app.config['SQLALCHEMY_DATABASE_URI']
    db_path = db_uri.replace('sqlite:///', '')
    uploads_dir = current_app.config.get('UPLOAD_FOLDER', 'static/uploads')
    from utils.backup_center import create_full_backup
    result = create_full_backup(db_path=db_path, uploads_dir=uploads_dir)
    if not result.get("success"):
        return error_response(ErrorCode.SERVER_INTERNAL_ERROR[0], result.get("error", "Full backup failed"), status_code=500)
    return success_response(result)


@backup_center_bp.route('/api/backup-center/list')
@rate_limit(BACKUP_LIMIT * 2, key_func=admin_key)
def api_list():
    backup_type = request.args.get('type')
    from utils.backup import list_backups
    backups = list_backups(backup_type=backup_type)
    return success_response({"backups": backups, "count": len(backups)})


@backup_center_bp.route('/api/backup-center/search')
@rate_limit(BACKUP_LIMIT * 2, key_func=admin_key)
def api_search():
    query = request.args.get('q', '')
    if not query:
        return error_response(ErrorCode.VALIDATION_MISSING_FIELD[0], "Search query required", status_code=400)
    from utils.backup import search_backups
    results = search_backups(query)
    return success_response({"results": results, "count": len(results)})


@backup_center_bp.route('/api/backup-center/download', methods=['GET'])
@rate_limit(BACKUP_LIMIT * 2, key_func=admin_key)
def api_download():
    filename = request.args.get('filename')
    if not filename:
        return error_response(ErrorCode.VALIDATION_MISSING_FIELD[0], "Filename required", status_code=400)

    from utils.backup import list_backups, BACKUP_DIR
    all_backups = list_backups()
    for b in all_backups:
        if b["filename"] == filename:
            if not os.path.isfile(b["path"]):
                return error_response(ErrorCode.VALIDATION_MISSING_FIELD[0], "File not found on disk", status_code=404)
            return send_file(b["path"], as_attachment=True, download_name=filename)

    return error_response(ErrorCode.VALIDATION_MISSING_FIELD[0], "Backup not found", status_code=404)


@backup_center_bp.route('/api/backup-center/verify', methods=['GET'])
@rate_limit(BACKUP_LIMIT, key_func=admin_key)
def api_verify():
    filename = request.args.get('filename')
    if not filename:
        return error_response(ErrorCode.VALIDATION_MISSING_FIELD[0], "Filename required", status_code=400)

    from utils.backup import list_backups, verify_backup_file
    all_backups = list_backups()
    for b in all_backups:
        if b["filename"] == filename:
            verification = verify_backup_file(b["path"])
            return success_response(verification)

    return error_response(ErrorCode.VALIDATION_MISSING_FIELD[0], "Backup not found", status_code=404)


@backup_center_bp.route('/api/backup-center/restore', methods=['POST'])
@rate_limit(BACKUP_LIMIT, key_func=admin_key)
def api_restore():
    data = request.json or {}
    filename = data.get("filename")
    if not filename:
        return error_response(ErrorCode.VALIDATION_MISSING_FIELD[0], "Filename required", status_code=400)

    from flask import current_app
    db_uri = current_app.config['SQLALCHEMY_DATABASE_URI']
    db_path = db_uri.replace('sqlite:///', '')
    uploads_dir = current_app.config.get('UPLOAD_FOLDER', 'static/uploads')

    from utils.backup import list_backups
    from utils.backup_center import check_compatibility, restore_backup_full

    all_backups = list_backups()
    backup_entry = None
    for b in all_backups:
        if b["filename"] == filename:
            backup_entry = b
            break

    if not backup_entry:
        return error_response(ErrorCode.VALIDATION_MISSING_FIELD[0], "Backup not found", status_code=404)

    compatibility = check_compatibility(backup_entry["path"], current_db_path=db_path)
    if not compatibility.get("compatible"):
        return error_response(
            ErrorCode.VALIDATION_INVALID_INPUT[0],
            f"Backup incompatible: {'; '.join(compatibility.get('issues', []))}",
            status_code=400,
            extra={"compatibility": compatibility},
        )

    result = restore_backup_full(backup_entry["path"], target_db_path=db_path, uploads_dir=uploads_dir)
    if not result.get("success"):
        return error_response(ErrorCode.SERVER_INTERNAL_ERROR[0], result.get("error", "Restore failed"), status_code=500)

    return success_response(result)


@backup_center_bp.route('/api/backup-center/delete', methods=['DELETE'])
@rate_limit(BACKUP_LIMIT, key_func=admin_key)
def api_delete():
    data = request.json or {}
    filename = data.get("filename")
    if not filename:
        return error_response(ErrorCode.VALIDATION_MISSING_FIELD[0], "Filename required", status_code=400)

    from utils.backup import list_backups
    all_backups = list_backups()
    for b in all_backups:
        if b["filename"] == filename:
            try:
                sha_path = b["path"] + ".sha256"
                if os.path.isfile(sha_path):
                    os.remove(sha_path)
                manifest_path = b["path"] + ".manifest.json"
                if os.path.isfile(manifest_path):
                    os.remove(manifest_path)
                os.remove(b["path"])
                return success_response({"deleted": filename})
            except OSError as e:
                return error_response(ErrorCode.SERVER_INTERNAL_ERROR[0], str(e), status_code=500)

    return error_response(ErrorCode.VALIDATION_MISSING_FIELD[0], "Backup not found", status_code=404)


@backup_center_bp.route('/api/backup-center/prune', methods=['POST'])
@rate_limit(BACKUP_LIMIT, key_func=admin_key)
def api_prune():
    from utils.backup import prune_backups
    result = prune_backups()
    return success_response(result)


@backup_center_bp.route('/api/backup-center/import-history')
@rate_limit(BACKUP_LIMIT, key_func=admin_key)
def api_import_history():
    from utils.migration.printer import DEFAULT_LOG_DIR
    log_dir = DEFAULT_LOG_DIR
    if not os.path.isdir(log_dir):
        return success_response({"imports": [], "count": 0})

    imports = []
    for entry in sorted(os.listdir(log_dir), reverse=True):
        report_path = os.path.join(log_dir, entry, "report.json")
        if os.path.isfile(report_path):
            try:
                with open(report_path) as f:
                    report = json.load(f)
                imports.append({
                    "import_id": entry,
                    "status": report.get("status"),
                    "timestamp": report.get("timestamp"),
                    "summary": report.get("import_summary", {}),
                    "error": report.get("error"),
                })
            except (json.JSONDecodeError, OSError):
                imports.append({"import_id": entry, "status": "unknown", "error": "Could not read report"})

    return success_response({"imports": imports, "count": len(imports)})


@backup_center_bp.route('/api/backup-center/import-history/<import_id>')
@rate_limit(BACKUP_LIMIT, key_func=admin_key)
def api_import_detail(import_id):
    from utils.migration.printer import DEFAULT_LOG_DIR
    report_path = os.path.join(DEFAULT_LOG_DIR, import_id, "report.json")
    if not os.path.isfile(report_path):
        return error_response(ErrorCode.VALIDATION_MISSING_FIELD[0], "Import not found", status_code=404)

    try:
        with open(report_path) as f:
            report = json.load(f)
        return success_response(report)
    except (json.JSONDecodeError, OSError) as e:
        return error_response(ErrorCode.SERVER_INTERNAL_ERROR[0], str(e), status_code=500)
