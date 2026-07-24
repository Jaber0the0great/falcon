import os
import uuid
import base64
import logging
import unicodedata
from flask import Blueprint, request, jsonify, session, current_app, send_from_directory
from models.models import Message, User, Group, GroupMember, GroupInvite, GroupJoinRequest
from database.database import db
from utils.crypto import decrypt_text
from utils.api import success_response, error_response, ErrorCode
from utils.security import (
    validate_required_fields,
    validate_group_name,
    validate_username,
    validate_username_list,
    validate_string_length,
    sanitize_filename,
    ValidationError,
    login_required,
    rate_limit,
    user_key,
    ip_key,
    HISTORY_LIMIT,
    UPLOAD_LIMIT,
    DOWNLOAD_LIMIT,
    CALL_LOG_LIMIT,
    GROUP_CREATE_LIMIT,
    GROUP_LIST_LIMIT,
    GROUP_INVITE_LIMIT,
    GROUP_INVITE_RESPOND_LIMIT,
    GROUP_JOIN_REQUEST_LIMIT,
    GROUP_JOIN_REQUESTS_LIST_LIMIT,
    GROUP_JOIN_REQUESTS_RESPOND_LIMIT,
    GROUP_MEMBERS_LIMIT,
    GROUP_KICK_LIMIT,
    GROUP_LEAVE_LIMIT,
    GROUP_DELETE_LIMIT,
    USER_INFO_LIMIT,
    WEBRTC_CONFIG_LIMIT,
    MAX_GROUP_DESCRIPTION_LENGTH,
    MAX_UPLOAD_SIZE,
    MAX_FILE_NAME_LENGTH,
    ALLOWED_EXTENSIONS,
    DANGEROUS_FILENAME_CHARS,
    SUSPICIOUS_MIME_TYPES,
)

logger = logging.getLogger(__name__)

api_bp = Blueprint('api', __name__, url_prefix='/api')

@api_bp.route('/history', methods=['GET'])
@rate_limit(HISTORY_LIMIT, key_func=user_key)
def get_history():
    if 'user_id' not in session:
        return error_response(ErrorCode.AUTH_NOT_AUTHENTICATED[0], "Not authenticated", status_code=401)

    my_name = session['username']
    other_name = request.args.get('target', 'All')

    if len(other_name) > 80:
        return error_response(ErrorCode.VALIDATION_INVALID_TARGET[0], "Invalid target", status_code=400)

    limit = request.args.get('limit', 50, type=int)
    offset = request.args.get('offset', 0, type=int)
    limit = min(limit, 200)

    from models.models import MessageVisibility
    if other_name == "All":
        base = Message.query.outerjoin(
            MessageVisibility,
            (Message.msg_id == MessageVisibility.msg_id) & (MessageVisibility.username == my_name)
        ).filter(
            (Message.recipient == "All") &
            (MessageVisibility.id == None)
        )
        total = base.count()
        messages = base.order_by(Message.id.desc()).limit(limit).offset(offset).all()
        messages.reverse()
    else:
        group = Group.query.filter_by(name=other_name).first()
        if group:
            is_member = GroupMember.query.filter_by(group_name=other_name, username=my_name).first() is not None
            if not is_member:
                return error_response(ErrorCode.GROUP_NOT_MEMBER[0], "Unauthorized", status_code=403)

            base = Message.query.outerjoin(
                MessageVisibility,
                (Message.msg_id == MessageVisibility.msg_id) & (MessageVisibility.username == my_name)
            ).filter(
                (Message.recipient == other_name) &
                (MessageVisibility.id == None)
            )
            total = base.count()
            messages = base.order_by(Message.id.desc()).limit(limit).offset(offset).all()
            messages.reverse()
        else:
            base = Message.query.outerjoin(
                MessageVisibility,
                (Message.msg_id == MessageVisibility.msg_id) & (MessageVisibility.username == my_name)
            ).filter(
                (((Message.sender == my_name) & (Message.recipient == other_name)) |
                 ((Message.sender == other_name) & (Message.recipient == my_name))) &
                (MessageVisibility.id == None)
            )
            total = base.count()
            messages = base.order_by(Message.id.desc()).limit(limit).offset(offset).all()
            messages.reverse()

    result = []
    for msg in messages:
        result.append({
            "db_id": msg.id,
            "sender": msg.sender,
            "to": msg.recipient,
            "type": msg.msg_type,
            "content": decrypt_text(msg.content),
            "time": msg.time,
            "duration": msg.duration,
            "size": msg.duration,
            "name": msg.file_name,
            "data": None,
            "status": msg.status,
            "msg_id": msg.msg_id,
            "reactions": msg.reactions,
            "reply_to": msg.reply_to,
            "reply_content": decrypt_text(msg.reply_content)
        })
    return success_response({"messages": result, "total": total, "offset": offset, "limit": limit})

@api_bp.route('/upload', methods=['POST'])
@rate_limit(UPLOAD_LIMIT, key_func=user_key)
def upload_file():
    if 'user_id' not in session:
        return error_response(ErrorCode.AUTH_NOT_AUTHENTICATED[0], "Not authenticated", status_code=401)

    if 'file' not in request.files:
        return error_response(ErrorCode.VALIDATION_MISSING_FIELD[0], "No file part", status_code=400)

    file = request.files['file']
    original_name = file.filename or ''
    if original_name == '':
        return error_response(ErrorCode.VALIDATION_MISSING_FIELD[0], "No selected file", status_code=400)

    # ── Layer 1: Filename validation ────────────────────────────────────

    # Reject filenames that exceed the configured maximum length
    if len(original_name) > MAX_FILE_NAME_LENGTH:
        return error_response(ErrorCode.VALIDATION_INVALID_INPUT[0], "Invalid filename", status_code=400)

    # Reject dangerous control characters (C0 controls, DEL, bidi overrides)
    if any(c in DANGEROUS_FILENAME_CHARS for c in original_name):
        return error_response(ErrorCode.VALIDATION_INVALID_INPUT[0], "Invalid filename", status_code=400)

    # Unicode NFC normalization (canonical composition)
    normalized_name = unicodedata.normalize('NFC', original_name)

    # Sanitize: strip path separators, restrict to safe character set
    safe_name = sanitize_filename(normalized_name)
    if not safe_name or safe_name == "untitled":
        return error_response(ErrorCode.VALIDATION_INVALID_INPUT[0], "Invalid filename", status_code=400)

    # ── Layer 2: Extension validation (allowlist) ───────────────────────

    # Reject files without a detectable extension
    last_ext = os.path.splitext(safe_name)[1].lower()
    if not last_ext:
        return error_response(ErrorCode.VALIDATION_INVALID_INPUT[0], "Invalid filename", status_code=400)

    # Check every extension segment against the allowlist.
    # This naturally catches double-extensions (e.g. image.png.exe)
    # because .exe is not in the allowlist.
    parts = safe_name.split('.')
    for i in range(1, len(parts)):
        ext = '.' + parts[i].lower()
        if ext not in ALLOWED_EXTENSIONS:
            return error_response(ErrorCode.FILE_INVALID_TYPE[0], "File type not allowed.", status_code=400)

    # ── Layer 3: File-size validation ───────────────────────────────────

    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size > MAX_UPLOAD_SIZE:
        return error_response(ErrorCode.FILE_TOO_LARGE[0], "File too large.", status_code=413)

    # ── Layer 4: Advisory MIME-type check ───────────────────────────────
    # Content-Type is user-controlled and MUST NOT be trusted for access
    # decisions.  This check is an advisory hint only; the actual file
    # type is governed by the extension allowlist (Layer 2) and future
    # magic-byte inspection (Layer 5).

    content_type = (file.content_type or '').lower()
    if content_type in SUSPICIOUS_MIME_TYPES:
        return error_response(ErrorCode.FILE_INVALID_TYPE[0], "File type not allowed.", status_code=400)

    # ── Layer 5: Magic-byte inspection ──────────────────────────────────
    # NOT IMPLEMENTED — see SECURITY_IMPLEMENTATION_ROADMAP_V2.md (FI-001).
    # Full magic-byte validation would require either the python-magic
    # library (which depends on libmagic, a native C library) or a
    # manually curated signature database covering hundreds of file
    # formats.  Both approaches add significant complexity for limited
    # incremental gain given that Layers 1-4 already prevent executable
    # uploads.  Deferred as a future hardening item.

    # ── Save ────────────────────────────────────────────────────────────

    filename = f"{uuid.uuid4().hex}_{safe_name}"
    filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)

    # Post-save size verification
    saved_size = os.path.getsize(filepath)
    if saved_size > MAX_UPLOAD_SIZE:
        os.remove(filepath)
        return error_response(ErrorCode.FILE_TOO_LARGE[0], "File too large.", status_code=413)

    return success_response({
        "filename": filename,
        "original_name": original_name,
        "size": saved_size
    })

@api_bp.route('/download/<filename>', methods=['GET'])
@login_required
@rate_limit(DOWNLOAD_LIMIT, key_func=ip_key)
def download_file(filename):
    """Serve an uploaded file.

    Security model
    --------------
    *Public endpoint* — no authentication required.

    Rationale:
      The stored filenames use the pattern ``<uuid_hex>_<safe_name>``, where
      ``uuid_hex`` is a 128-bit random value (32 hex chars).  This makes
      direct URL enumeration infeasible (2¹²⁸ search space).  Files can only
      be accessed by users who have been given the specific URL (typically
      via a chat message that contains the filename).

    Why this is acceptable today:
      1. UUID-based naming provides URL-level protection equivalent to a
         bearer token scoped to that single resource.
      2. Adding per-user download authorization would require tracking which
         users are entitled to which files (e.g. a ``FileAccess`` table or
         signed URLs).  That is a product-level feature, not a security
         regression, and is out of scope for the current hardening phase.

    Defences in place:
      - ``sanitize_filename()`` strips path separators and non-alphanumeric
        characters, preventing path-traversal attacks.
      - ``send_from_directory()`` (Flask) raises a 404 if the resolved path
        falls outside *UPLOAD_FOLDER*, providing defence in depth.
      - Filenames are validated at upload time (extension allowlist, length,
        character restrictions) so every file served has already passed
        multiple security layers.

    Future improvement:
      Signed (time-limited) URLs could be introduced if per-user access
      control is ever required.
    """
    safe_name = sanitize_filename(filename)
    if not safe_name:
        return error_response(ErrorCode.FILE_DOWNLOAD_FAILED[0], "Invalid filename", status_code=400)
    return send_from_directory(current_app.config['UPLOAD_FOLDER'], safe_name)

@api_bp.route('/user_info', methods=['GET'])
@rate_limit(USER_INFO_LIMIT, key_func=user_key)
def get_user_info():
    if 'user_id' not in session:
        return error_response(ErrorCode.AUTH_NOT_AUTHENTICATED[0], "Not authenticated", status_code=401)
    return success_response({"username": session['username']})
@api_bp.route('/users/fcm_token', methods=['POST'])
@rate_limit(USER_INFO_LIMIT, key_func=user_key)
def save_fcm_token():
    if 'user_id' not in session:
        return error_response(ErrorCode.AUTH_NOT_AUTHENTICATED[0], "Not authenticated", status_code=401)
    
    data = request.get_json()
    if not data or 'token' not in data:
        return error_response(ErrorCode.PARAM_MISSING[0], "Token is required", status_code=400)
        
    token = data.get('token')
    user = User.query.get(session['user_id'])
    if not user:
        return error_response(ErrorCode.USER_NOT_FOUND[0], "User not found", status_code=404)
        
    user.fcm_token = token if token else None
    db.session.commit()
    return success_response()

@api_bp.route('/webrtc_config', methods=['GET'])
@rate_limit(WEBRTC_CONFIG_LIMIT, key_func=ip_key)
def get_webrtc_config():
    if 'user_id' not in session:
        return error_response(ErrorCode.AUTH_NOT_AUTHENTICATED[0], "Not authenticated", status_code=401)
        
    turn_url = current_app.config.get('TURN_SERVER', 'turn:openrelay.metered.ca:80')
    username = current_app.config.get('TURN_USERNAME', 'openrelayproject')
    credential = current_app.config.get('TURN_CREDENTIAL', 'openrelayproject')
    
    # Extract host:port from the config URL
    host_port = turn_url.split('turn:')[-1].split('?')[0]
    
    return success_response({"iceServers": [
            { "urls": "stun:stun.l.google.com:19302" },
            { "urls": "stun:stun1.l.google.com:19302" },
            { "urls": "stun:stun2.l.google.com:19302" },
            { "urls": "stun:stun3.l.google.com:19302" },
            { "urls": "stun:stun4.l.google.com:19302" },
            { "urls": f"stun:{host_port}" },
            {
                "urls": f"turn:{host_port}",
                "username": username,
                "credential": credential
            },
            {
                "urls": f"turn:{host_port.split(':')[0]}:443",
                "username": username,
                "credential": credential
            },
            {
                "urls": f"turn:{host_port.split(':')[0]}:443?transport=tcp",
                "username": username,
                "credential": credential
            }
        ]
    })


# --- GROUP CHAT ENDPOINTS ---

@api_bp.route('/groups/create', methods=['POST'])
@rate_limit(GROUP_CREATE_LIMIT, key_func=user_key)
def create_group():
    if 'user_id' not in session:
        return error_response(ErrorCode.AUTH_NOT_AUTHENTICATED[0], "Not authenticated", status_code=401)
    
    my_name = session['username']
    data = request.json or {}
    raw_name = (data.get('name') or '').strip()
    
    if not raw_name:
        return error_response(ErrorCode.VALIDATION_MISSING_FIELD[0], "Group name is required", status_code=400)
        
    if raw_name.lower() == 'all':
        return error_response(ErrorCode.VALIDATION_INVALID_GROUP_NAME[0], "Invalid group name", status_code=400)
        
    try:
        group_name = validate_group_name(raw_name)
    except ValidationError as e:
        return error_response(ErrorCode.VALIDATION_INVALID_GROUP_NAME[0], e.message, status_code=400)
    
    try:
        description = (data.get('description') or '').strip()
        if description:
            validate_string_length(description, 0, MAX_GROUP_DESCRIPTION_LENGTH, "Description")
    except ValidationError as e:
        return error_response(ErrorCode.VALIDATION_INVALID_INPUT[0], e.message, status_code=400)
    
    try:
        members = validate_username_list(data.get('members', []))
    except ValidationError as e:
        return error_response(ErrorCode.VALIDATION_INVALID_INPUT[0], e.message, status_code=400)
        
    # Check if a group or user with this name already exists (since they share the namespace in messages)
    existing_group = Group.query.filter_by(name=group_name).first()
    existing_user = User.query.filter(User.username.ilike(group_name)).first()
    if existing_group or existing_user:
        return error_response(ErrorCode.GROUP_CREATE_FAILED[0], "Name already taken", status_code=400)
        
    # Create the group
    group = Group(name=group_name, owner_username=my_name, description=description)
    db.session.add(group)
    
    # Automatically add owner as a member
    member = GroupMember(group_name=group_name, username=my_name)
    db.session.add(member)
    
    # Add selected members directly
    for u_name in members:
        if u_name.lower() != my_name.lower():
            user_exists = User.query.filter(User.username.ilike(u_name)).first()
            if user_exists and not user_exists.is_admin:
                mb = GroupMember(group_name=group_name, username=user_exists.username)
                db.session.add(mb)
                
    db.session.commit()
    
    # Broadcast to all users to reload their groups list
    try:
        socketio = current_app.extensions.get('socketio')
        if socketio:
            socketio.emit('group_list_updated', {
                "group_name": group_name,
                "created_by": my_name
            }, room='All')
    except Exception as e:
        logger.error("Error emitting group_list_updated socket event on create: %s", e)
        
    return success_response({"message": "Group created successfully"})

@api_bp.route('/groups', methods=['GET'])
@rate_limit(GROUP_LIST_LIMIT, key_func=user_key)
def get_groups():
    if 'user_id' not in session:
        return error_response(ErrorCode.AUTH_NOT_AUTHENTICATED[0], "Not authenticated", status_code=401)
        
    my_name = session['username']
    groups = Group.query.order_by(Group.name.asc()).all()
    
    result = []
    for g in groups:
        is_owner = (g.owner_username == my_name)
        is_member = GroupMember.query.filter_by(group_name=g.name, username=my_name).first() is not None
        has_invite = GroupInvite.query.filter_by(group_name=g.name, username=my_name, status='pending').first() is not None
        has_request = GroupJoinRequest.query.filter_by(group_name=g.name, username=my_name, status='pending').first() is not None
        
        result.append({
            "name": g.name,
            "description": g.description or "",
            "owner": g.owner_username,
            "is_owner": is_owner,
            "is_member": is_member,
            "has_invite": has_invite,
            "has_request": has_request
        })
        
    return success_response({"groups": result})

@api_bp.route('/calls/log', methods=['POST'])
@rate_limit(CALL_LOG_LIMIT, key_func=user_key)
def save_call_log():
    if 'user_id' not in session:
        return error_response(ErrorCode.AUTH_NOT_AUTHENTICATED[0], "Not authenticated", status_code=401)
        
    my_name = session['username']
    data = request.json or {}

    try:
        validate_required_fields(data, 'recipient', 'status')
    except ValidationError:
        return error_response(ErrorCode.VALIDATION_MISSING_FIELD[0], "Missing parameters", status_code=400)

    recipient = data.get('recipient')
    status = data.get('status')
    duration = int(data.get('duration', 0))
        
    recip_user = User.query.filter_by(username=recipient).first()
    if not recip_user:
        return error_response(ErrorCode.MESSAGE_RECIPIENT_NOT_FOUND[0], "Recipient not found", status_code=404)
        
    import uuid
    import datetime as dt
    msg_id = str(uuid.uuid4())
    time_str = dt.datetime.now().strftime("%H:%M")
    
    # Save call log message to DB
    msg = Message(
        sender=my_name,
        recipient=recipient,
        msg_type='call_log',
        content=status,
        duration=duration,
        time=time_str,
        msg_id=msg_id,
        status='delivered' if recip_user.status != 'Offline' else 'sent'
    )
    db.session.add(msg)
    db.session.commit()
    
    # Broadcast via sockets
    try:
        socketio = current_app.extensions.get('socketio')
        payload = {
            "type": "call_log",
            "sender": my_name,
            "to": recipient,
            "content": status,
            "duration": duration,
            "time": time_str,
            "msg_id": msg_id,
            "status": msg.status
        }
        socketio.emit('new_message', payload, room=recipient)
        socketio.emit('new_message', payload, room=my_name)
    except Exception as e:
        logger.error("Error emitting call log socket event: %s", e)
        
    return success_response({"message": "Call log saved successfully"})

@api_bp.route('/calls/history', methods=['GET'])
@rate_limit(USER_INFO_LIMIT, key_func=user_key)
def get_call_history():
    if 'user_id' not in session:
        return error_response(ErrorCode.AUTH_NOT_AUTHENTICATED[0], "Not authenticated", status_code=401)
        
    my_name = session['username']
    
    from models.models import MessageVisibility
    calls = Message.query.outerjoin(
        MessageVisibility,
        (Message.msg_id == MessageVisibility.msg_id) & (MessageVisibility.username == my_name)
    ).filter(
        Message.msg_type == 'call_log',
        ((Message.sender == my_name) | (Message.recipient == my_name)),
        MessageVisibility.id == None
    ).order_by(Message.id.desc()).all()
    
    result = []
    for c in calls:
        result.append({
            "msg_id": c.msg_id,
            "sender": c.sender,
            "recipient": c.recipient,
            "status": c.content,
            "duration": c.duration or 0,
            "time": c.time,
            "created_at": c.created_at.isoformat() + "Z" if c.created_at else None
        })
    return success_response({"calls": result})

@api_bp.route('/groups/invite', methods=['POST'])
@rate_limit(GROUP_INVITE_LIMIT, key_func=user_key)
def invite_to_group():
    if 'user_id' not in session:
        return error_response(ErrorCode.AUTH_NOT_AUTHENTICATED[0], "Not authenticated", status_code=401)
        
    my_name = session['username']
    data = request.json or {}
    group_name_raw = data.get('group_name')
    
    # Support both single username and batch usernames
    target_usernames = data.get('usernames', [])
    if not target_usernames and data.get('username'):
        target_usernames = [data.get('username')]
        
    if not group_name_raw or not target_usernames:
        return error_response(ErrorCode.VALIDATION_MISSING_FIELD[0], "Missing parameters", status_code=400)
    
    try:
        group_name = validate_group_name(group_name_raw)
    except ValidationError:
        return error_response(ErrorCode.VALIDATION_INVALID_GROUP_NAME[0], "Missing parameters", status_code=400)
    
    try:
        target_usernames = validate_username_list(target_usernames)
    except ValidationError:
        return error_response(ErrorCode.VALIDATION_INVALID_INPUT[0], "Missing parameters", status_code=400)
        
    group = Group.query.filter_by(name=group_name).first()
    if not group:
        return error_response(ErrorCode.GROUP_NOT_FOUND[0], "Group not found", status_code=404)
        
    if group.owner_username != my_name:
        return error_response(ErrorCode.GROUP_INVITE_FAILED[0], "Only the group owner can invite users", status_code=403)
        
    invited_count = 0
    errors = []
    
    for target_username in target_usernames:
        target_username = target_username.strip()
        if not target_username:
            continue
            
        target_user = User.query.filter(User.username.ilike(target_username)).first()
        if not target_user or target_user.is_admin:
            continue
            
        # Check if already a member
        if GroupMember.query.filter_by(group_name=group_name, username=target_user.username).first():
            continue
            
        # Check if already invited
        existing_invite = GroupInvite.query.filter_by(group_name=group_name, username=target_user.username, status='pending').first()
        if existing_invite:
            continue
            
        # Create invite
        invite = GroupInvite(group_name=group_name, username=target_user.username, invited_by=my_name)
        db.session.add(invite)
        invited_count += 1
        
        # Send socket notification if invitee is online
        try:
            socketio = current_app.extensions.get('socketio')
            if socketio:
                socketio.emit('group_invite_received', {
                    "group_name": group_name,
                    "invited_by": my_name
                }, room=target_user.username)
        except Exception as e:
            logger.error("Error emitting group_invite_received socket event: %s", e)
            
    if invited_count > 0:
        db.session.commit()
        
    return success_response({"message": f"Successfully sent {invited_count} invitation(s)", "errors": errors})

@api_bp.route('/groups/invite/respond', methods=['POST'])
@rate_limit(GROUP_INVITE_RESPOND_LIMIT, key_func=user_key)
def respond_to_invite():
    if 'user_id' not in session:
        return error_response(ErrorCode.AUTH_NOT_AUTHENTICATED[0], "Not authenticated", status_code=401)
        
    my_name = session['username']
    data = request.json or {}
    group_name_raw = data.get('group_name')
    action = data.get('action') # 'accept' or 'reject'
    
    if not group_name_raw or action not in ('accept', 'reject'):
        return error_response(ErrorCode.VALIDATION_MISSING_FIELD[0], "Invalid parameters", status_code=400)
    
    try:
        group_name = validate_group_name(group_name_raw)
    except ValidationError:
        return error_response(ErrorCode.VALIDATION_INVALID_GROUP_NAME[0], "Invalid parameters", status_code=400)
        
    invite = GroupInvite.query.filter_by(group_name=group_name, username=my_name, status='pending').first()
    if not invite:
        return error_response(ErrorCode.GROUP_INVITE_FAILED[0], "Invitation not found", status_code=404)
        
    if action == 'accept':
        invite.status = 'accepted'
        # Add to members
        if not GroupMember.query.filter_by(group_name=group_name, username=my_name).first():
            member = GroupMember(group_name=group_name, username=my_name)
            db.session.add(member)
            
            # Send message to group
            msg_id = str(uuid.uuid4())
            import datetime as dt
            sys_msg = Message(
                sender='System',
                recipient=group_name,
                msg_type='system',
                content=f"🔵 {my_name} joined the group.",
                time=dt.datetime.now().strftime("%H:%M"),
                msg_id=msg_id
            )
            db.session.add(sys_msg)
            
            try:
                socketio = current_app.extensions.get('socketio')
                if socketio:
                    socketio.emit('join_group_room', {"group_name": group_name}, room=my_name)
                    # Emit system message to group room
                    socketio.emit('new_message', {
                        "type": "system",
                        "sender": "System",
                        "to": group_name,
                        "content": f"🔵 {my_name} joined the group.",
                        "time": dt.datetime.now().strftime("%H:%M"),
                        "msg_id": msg_id
                    }, room=group_name)
            except Exception as e:
                logger.error("Error emitting join group room: %s", e)
    else:
        invite.status = 'rejected'
        
    db.session.commit()
    return success_response({"message": f"Invitation {action}ed successfully"})

@api_bp.route('/groups/request_join', methods=['POST'])
@rate_limit(GROUP_JOIN_REQUEST_LIMIT, key_func=user_key)
def request_join():
    if 'user_id' not in session:
        return error_response(ErrorCode.AUTH_NOT_AUTHENTICATED[0], "Not authenticated", status_code=401)
        
    my_name = session['username']
    data = request.json or {}
    group_name_raw = data.get('group_name')
    
    if not group_name_raw:
        return error_response(ErrorCode.VALIDATION_MISSING_FIELD[0], "Group name is required", status_code=400)
    
    try:
        group_name = validate_group_name(group_name_raw)
    except ValidationError as e:
        return error_response(ErrorCode.VALIDATION_INVALID_GROUP_NAME[0], e.message, status_code=400)
        
    group = Group.query.filter_by(name=group_name).first()
    if not group:
        return error_response(ErrorCode.GROUP_NOT_FOUND[0], "Group not found", status_code=404)
        
    # Check if already member
    if GroupMember.query.filter_by(group_name=group_name, username=my_name).first():
        return error_response(ErrorCode.GROUP_ALREADY_MEMBER[0], "Already a member", status_code=400)
        
    # Check if already requested
    existing_req = GroupJoinRequest.query.filter_by(group_name=group_name, username=my_name, status='pending').first()
    if existing_req:
        return error_response(ErrorCode.GROUP_JOIN_REQUEST_FAILED[0], "Request already pending", status_code=400)
        
    # Create request
    req_join = GroupJoinRequest(group_name=group_name, username=my_name)
    db.session.add(req_join)
    db.session.commit()
    
    # Notify owner in real-time
    try:
        socketio = current_app.extensions.get('socketio')
        if socketio:
            socketio.emit('group_request_received', {
                "group_name": group_name,
                "username": my_name
            }, room=group.owner_username)
    except Exception as e:
        logger.error("Error emitting request join socket: %s", e)
        
    return success_response({"message": "Join request submitted successfully"})

@api_bp.route('/groups/requests', methods=['GET'])
@rate_limit(GROUP_JOIN_REQUESTS_LIST_LIMIT, key_func=user_key)
def get_join_requests():
    if 'user_id' not in session:
        return error_response(ErrorCode.AUTH_NOT_AUTHENTICATED[0], "Not authenticated", status_code=401)
        
    my_name = session['username']
    group_name_raw = request.args.get('group_name')
    
    if not group_name_raw:
        return error_response(ErrorCode.VALIDATION_MISSING_FIELD[0], "Group name is required", status_code=400)
    
    try:
        group_name = validate_group_name(group_name_raw)
    except ValidationError as e:
        return error_response(ErrorCode.VALIDATION_INVALID_GROUP_NAME[0], e.message, status_code=400)
        
    group = Group.query.filter_by(name=group_name).first()
    if not group:
        return error_response(ErrorCode.GROUP_NOT_FOUND[0], "Group not found", status_code=404)
        
    if group.owner_username != my_name:
        return error_response(ErrorCode.GROUP_NOT_MEMBER[0], "Unauthorized", status_code=403)
        
    reqs = GroupJoinRequest.query.filter_by(group_name=group_name, status='pending').all()
    admin_usernames = {u.username for u in User.query.filter(User.is_admin == True).all()}
    result = [r.username for r in reqs if r.username not in admin_usernames]
    return success_response({"requests": result})

@api_bp.route('/groups/requests/respond', methods=['POST'])
@rate_limit(GROUP_JOIN_REQUESTS_RESPOND_LIMIT, key_func=user_key)
def respond_to_request():
    if 'user_id' not in session:
        return error_response(ErrorCode.AUTH_NOT_AUTHENTICATED[0], "Not authenticated", status_code=401)
        
    my_name = session['username']
    data = request.json or {}
    group_name_raw = data.get('group_name')
    target_username_raw = data.get('username')
    action = data.get('action') # 'accept' or 'reject'
    
    if not group_name_raw or not target_username_raw or action not in ('accept', 'reject'):
        return error_response(ErrorCode.VALIDATION_MISSING_FIELD[0], "Invalid parameters", status_code=400)
    
    try:
        group_name = validate_group_name(group_name_raw)
        target_username = validate_username(target_username_raw)
    except ValidationError:
        return error_response(ErrorCode.VALIDATION_INVALID_INPUT[0], "Invalid parameters", status_code=400)
        
    group = Group.query.filter_by(name=group_name).first()
    if not group:
        return error_response(ErrorCode.GROUP_NOT_FOUND[0], "Group not found", status_code=404)
        
    if group.owner_username != my_name:
        return error_response(ErrorCode.GROUP_NOT_MEMBER[0], "Unauthorized", status_code=403)
        
    req_join = GroupJoinRequest.query.filter_by(group_name=group_name, username=target_username, status='pending').first()
    if not req_join:
        return error_response(ErrorCode.GROUP_NOT_FOUND[0], "Request not found", status_code=404)
        
    if action == 'accept':
        req_join.status = 'accepted'
        if not GroupMember.query.filter_by(group_name=group_name, username=target_username).first():
            member = GroupMember(group_name=group_name, username=target_username)
            db.session.add(member)
            
            # Send message to group
            msg_id = str(uuid.uuid4())
            import datetime as dt
            sys_msg = Message(
                sender='System',
                recipient=group_name,
                msg_type='system',
                content=f"🔵 {target_username} joined the group.",
                time=dt.datetime.now().strftime("%H:%M"),
                msg_id=msg_id
            )
            db.session.add(sys_msg)
            
            try:
                socketio = current_app.extensions.get('socketio')
                if socketio:
                    socketio.emit('join_group_room', {"group_name": group_name}, room=target_username)
                    socketio.emit('new_message', {
                        "type": "system",
                        "sender": "System",
                        "to": group_name,
                        "content": f"🔵 {target_username} joined the group.",
                        "time": dt.datetime.now().strftime("%H:%M"),
                        "msg_id": msg_id
                    }, room=group_name)
            except Exception as e:
                logger.error("Error emitting join group room: %s", e)
    else:
        req_join.status = 'rejected'
        
    db.session.commit()
    return success_response({"message": f"Join request {action}ed successfully"})

@api_bp.route('/groups/members', methods=['GET'])
@rate_limit(GROUP_MEMBERS_LIMIT, key_func=user_key)
def get_group_members():
    if 'user_id' not in session:
        return error_response(ErrorCode.AUTH_NOT_AUTHENTICATED[0], "Not authenticated", status_code=401)
        
    group_name_raw = request.args.get('group_name')
    if not group_name_raw:
        return error_response(ErrorCode.VALIDATION_MISSING_FIELD[0], "Group name is required", status_code=400)
    
    try:
        group_name = validate_group_name(group_name_raw)
    except ValidationError as e:
        return error_response(ErrorCode.VALIDATION_INVALID_GROUP_NAME[0], e.message, status_code=400)
        
    # Verify is member
    my_name = session['username']
    if not GroupMember.query.filter_by(group_name=group_name, username=my_name).first():
        return error_response(ErrorCode.GROUP_NOT_MEMBER[0], "Unauthorized", status_code=403)
        
    members = GroupMember.query.filter_by(group_name=group_name).all()
    admin_usernames = {u.username for u in User.query.filter(User.is_admin == True).all()}
    result = [m.username for m in members if m.username not in admin_usernames]
    return success_response({"members": result})

@api_bp.route('/groups/kick', methods=['POST'])
@rate_limit(GROUP_KICK_LIMIT, key_func=user_key)
def kick_member():
    if 'user_id' not in session:
        return error_response(ErrorCode.AUTH_NOT_AUTHENTICATED[0], "Not authenticated", status_code=401)
        
    my_name = session['username']
    data = request.json or {}
    group_name_raw = data.get('group_name')
    target_username_raw = data.get('username')
    
    if not group_name_raw or not target_username_raw:
        return error_response(ErrorCode.VALIDATION_MISSING_FIELD[0], "Missing parameters", status_code=400)
    
    try:
        group_name = validate_group_name(group_name_raw)
        target_username = validate_username(target_username_raw)
    except ValidationError:
        return error_response(ErrorCode.VALIDATION_INVALID_INPUT[0], "Missing parameters", status_code=400)
        
    group = Group.query.filter_by(name=group_name).first()
    if not group:
        return error_response(ErrorCode.GROUP_NOT_FOUND[0], "Group not found", status_code=404)
        
    if group.owner_username != my_name:
        return error_response(ErrorCode.GROUP_NOT_MEMBER[0], "Unauthorized", status_code=403)
        
    if target_username == my_name:
        return error_response(ErrorCode.GROUP_KICK_FAILED[0], "Cannot kick yourself", status_code=400)
        
    member = GroupMember.query.filter_by(group_name=group_name, username=target_username).first()
    if not member:
        return error_response(ErrorCode.GROUP_NOT_FOUND[0], "Member not found", status_code=404)
        
    db.session.delete(member)
    
    # Delete invites or requests associated
    GroupInvite.query.filter_by(group_name=group_name, username=target_username).delete()
    GroupJoinRequest.query.filter_by(group_name=group_name, username=target_username).delete()
    
    # Send system message
    msg_id = str(uuid.uuid4())
    import datetime as dt
    sys_msg = Message(
        sender='System',
        recipient=group_name,
        msg_type='system',
        content=f"🔴 {target_username} was kicked from the group.",
        time=dt.datetime.now().strftime("%H:%M"),
        msg_id=msg_id
    )
    db.session.add(sys_msg)
    
    try:
        socketio = current_app.extensions.get('socketio')
        if socketio:
            socketio.emit('leave_group_room', {"group_name": group_name}, room=target_username)
            socketio.emit('new_message', {
                "type": "system",
                "sender": "System",
                "to": group_name,
                "content": f"🔴 {target_username} was kicked from the group.",
                "time": dt.datetime.now().strftime("%H:%M"),
                "msg_id": msg_id
            }, room=group_name)
    except Exception as e:
        logger.error("Error emitting kick/leave room: %s", e)
        
    db.session.commit()
    return success_response({"message": "Member kicked successfully"})

@api_bp.route('/groups/leave', methods=['POST'])
@rate_limit(GROUP_LEAVE_LIMIT, key_func=user_key)
def leave_group():
    if 'user_id' not in session:
        return error_response(ErrorCode.AUTH_NOT_AUTHENTICATED[0], "Not authenticated", status_code=401)
        
    my_name = session['username']
    data = request.json or {}
    group_name_raw = data.get('group_name')
    
    if not group_name_raw:
        return error_response(ErrorCode.VALIDATION_MISSING_FIELD[0], "Group name is required", status_code=400)
    
    try:
        group_name = validate_group_name(group_name_raw)
    except ValidationError as e:
        return error_response(ErrorCode.VALIDATION_INVALID_GROUP_NAME[0], e.message, status_code=400)
        
    group = Group.query.filter_by(name=group_name).first()
    if not group:
        return error_response(ErrorCode.GROUP_NOT_FOUND[0], "Group not found", status_code=404)
        
    if group.owner_username == my_name:
        return error_response(ErrorCode.GROUP_LEAVE_FAILED[0], "Owner cannot leave, delete the group instead", status_code=400)
        
    member = GroupMember.query.filter_by(group_name=group_name, username=my_name).first()
    if not member:
        return error_response(ErrorCode.GROUP_NOT_MEMBER[0], "Not a member", status_code=400)
        
    db.session.delete(member)
    
    # Delete invites or requests associated
    GroupInvite.query.filter_by(group_name=group_name, username=my_name).delete()
    GroupJoinRequest.query.filter_by(group_name=group_name, username=my_name).delete()
    
    # Send system message
    msg_id = str(uuid.uuid4())
    import datetime as dt
    sys_msg = Message(
        sender='System',
        recipient=group_name,
        msg_type='system',
        content=f"🔴 {my_name} left the group.",
        time=dt.datetime.now().strftime("%H:%M"),
        msg_id=msg_id
    )
    db.session.add(sys_msg)
    
    try:
        socketio = current_app.extensions.get('socketio')
        if socketio:
            socketio.emit('leave_group_room', {"group_name": group_name}, room=my_name)
            socketio.emit('new_message', {
                "type": "system",
                "sender": "System",
                "to": group_name,
                "content": f"🔴 {my_name} left the group.",
                "time": dt.datetime.now().strftime("%H:%M"),
                "msg_id": msg_id
            }, room=group_name)
    except Exception as e:
        logger.error("Error emitting leave room: %s", e)
        
    db.session.commit()
    return success_response({"message": "Left group successfully"})

@api_bp.route('/groups/delete', methods=['POST'])
@rate_limit(GROUP_DELETE_LIMIT, key_func=user_key)
def delete_group():
    if 'user_id' not in session:
        return error_response(ErrorCode.AUTH_NOT_AUTHENTICATED[0], "Not authenticated", status_code=401)
        
    my_name = session['username']
    data = request.json or {}
    group_name_raw = data.get('group_name')
    
    if not group_name_raw:
        return error_response(ErrorCode.VALIDATION_MISSING_FIELD[0], "Group name is required", status_code=400)
    
    try:
        group_name = validate_group_name(group_name_raw)
    except ValidationError as e:
        return error_response(ErrorCode.VALIDATION_INVALID_GROUP_NAME[0], e.message, status_code=400)
        
    group = Group.query.filter_by(name=group_name).first()
    if not group:
        return error_response(ErrorCode.GROUP_NOT_FOUND[0], "Group not found", status_code=404)
        
    if group.owner_username != my_name:
        return error_response(ErrorCode.GROUP_DELETE_FAILED[0], "Unauthorized", status_code=403)
        
    # Delete group, members, invites, requests, and group messages
    Group.query.filter_by(name=group_name).delete()
    GroupMember.query.filter_by(group_name=group_name).delete()
    GroupInvite.query.filter_by(group_name=group_name).delete()
    GroupJoinRequest.query.filter_by(group_name=group_name).delete()
    Message.query.filter_by(recipient=group_name).delete()
    
    try:
        socketio = current_app.extensions.get('socketio')
        if socketio:
            socketio.emit('group_deleted', {"group_name": group_name}, room=group_name)
            socketio.emit('group_list_updated', {"group_name": group_name}, room='All')
    except Exception as e:
        logger.error("Error emitting group deleted socket: %s", e)
        
    db.session.commit()
    return success_response({"message": "Group deleted successfully"})

@api_bp.route('/users', methods=['GET'])
@rate_limit(USER_INFO_LIMIT, key_func=user_key)
def get_users_list():
    if 'user_id' not in session:
        return error_response(ErrorCode.AUTH_NOT_AUTHENTICATED[0], "Not authenticated", status_code=401)
        
    from sqlalchemy import or_
    my_name = session['username']
    all_users = User.query.filter(or_(User.is_admin == False, User.is_admin == None), User.username != my_name).all()
    
    result = []
    for u in all_users:
        unread_count = Message.query.filter(
            Message.sender == u.username,
            Message.recipient == my_name,
            Message.status != 'read'
        ).count()
        
        last_msg = Message.query.filter(
            ((Message.sender == my_name) & (Message.recipient == u.username)) |
            ((Message.sender == u.username) & (Message.recipient == my_name))
        ).order_by(Message.id.desc()).first()

        last_msg_iso = None
        sort_time = 0.0
        if last_msg:
            if hasattr(last_msg, 'created_at') and last_msg.created_at:
                last_msg_iso = last_msg.created_at.isoformat() + "Z"
                try:
                    sort_time = last_msg.created_at.timestamp()
                except Exception:
                    sort_time = 0.0

        result.append({
            "name": u.username,
            "status": u.status,
            "last_seen": (u.last_seen.isoformat() + "Z") if u.last_seen else None,
            "unread_count": unread_count,
            "last_message_time": last_msg_iso,
            "_sort_time": sort_time
        })
        
    result.sort(key=lambda x: (x["_sort_time"], x["unread_count"]), reverse=True)
    
    for r in result:
        r.pop("_sort_time", None)
        
    return success_response({"users": result})

@api_bp.route('/log_android_error', methods=['POST'])
def log_android_error():
    try:
        data = request.get_json() or {}
        username = data.get('username', 'Anonymous')
        action = data.get('action', 'Unknown action')
        error = data.get('error', 'No error message')
        details = data.get('details', '')
        client_time = data.get('timestamp', datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
        
        log_dir = os.path.join(current_app.root_path, 'logs')
        if not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
            
        log_file = os.path.join(log_dir, 'android_errors.log')
        log_entry = f"[{client_time}] [User: {username}] [Action: {action}] ERROR: {error} | Details: {details}\n"
        
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(log_entry)
            
        logger.error(f"[AndroidClientError] User: {username} | Action: {action} | Error: {error}")
        return success_response({"message": "Error logged successfully"})
    except Exception as e:
        logger.error("Failed to write android error log: %s", e)
        return error_response(500, f"Failed to log error: {str(e)}", status_code=500)

@api_bp.route('/update_profile', methods=['POST'])
@rate_limit(USER_INFO_LIMIT, key_func=user_key)
def update_profile():
    if 'user_id' not in session:
        return error_response(ErrorCode.AUTH_NOT_AUTHENTICATED[0], "Not authenticated", status_code=401)

    user = User.query.get(session['user_id'])
    if not user:
        return error_response(ErrorCode.AUTH_NOT_AUTHENTICATED[0], "User not found", status_code=404)

    data = request.get_json() or {}
    new_username = (data.get('new_username') or '').strip()
    new_password = (data.get('new_password') or data.get('new_pwd') or '').strip()

    if not new_username and not new_password:
        return error_response(ErrorCode.VALIDATION_INVALID_INPUT[0], "No changes provided", status_code=400)

    if new_username and new_username.lower() != user.username.lower():
        if len(new_username) < 3 or len(new_username) > 30:
            return error_response(ErrorCode.VALIDATION_INVALID_INPUT[0], "Username must be between 3 and 30 characters", status_code=400)
            
        existing = User.query.filter(User.username.ilike(new_username), User.id != user.id).first()
        if existing:
            return error_response(ErrorCode.AUTH_USER_ALREADY_EXISTS[0], "Username already taken. Please choose a different name.", status_code=409)

        old_username = user.username
        user.username = new_username

        try:
            Message.query.filter_by(sender=old_username).update({Message.sender: new_username}, synchronize_session=False)
            Message.query.filter_by(recipient=old_username).update({Message.recipient: new_username}, synchronize_session=False)
            GroupMember.query.filter_by(username=old_username).update({GroupMember.username: new_username}, synchronize_session=False)
            GroupInvite.query.filter_by(username=old_username).update({GroupInvite.username: new_username}, synchronize_session=False)
            GroupInvite.query.filter_by(invited_by=old_username).update({GroupInvite.invited_by: new_username}, synchronize_session=False)
            GroupJoinRequest.query.filter_by(username=old_username).update({GroupJoinRequest.username: new_username}, synchronize_session=False)
            Group.query.filter_by(owner_username=old_username).update({Group.owner_username: new_username}, synchronize_session=False)
        except Exception as e:
            logger.error("Error cascading username update: %s", e)

        session['username'] = new_username
        
        try:
            from app_socket import socketio
            if socketio:
                socketio.emit('user_update', {"type": "rename", "old_username": old_username, "new_username": new_username}, room='All')
        except Exception as se:
            logger.error("Error emitting user_update socket event: %s", se)

    if new_password:
        if len(new_password) < 6:
            return error_response(ErrorCode.VALIDATION_INVALID_INPUT[0], "Password must be at least 6 characters long.", status_code=400)
        user.set_password(new_password)

    db.session.commit()
    return success_response({"message": "Profile updated successfully", "username": user.username})




