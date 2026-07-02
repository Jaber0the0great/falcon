import os
import uuid
import base64
from flask import Blueprint, request, jsonify, session, current_app, send_from_directory
from models.models import Message, User, Group, GroupMember, GroupInvite, GroupJoinRequest
from database.database import db

api_bp = Blueprint('api', __name__, url_prefix='/api')

@api_bp.route('/history', methods=['GET'])
def get_history():
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
        
    my_name = session['username']
    other_name = request.args.get('target', 'All')
    
    if other_name == "All":
        messages = Message.query.filter(
            (Message.recipient == "All") &
            ~((Message.sender == my_name) & (Message.deleted_by_sender == True))
        ).order_by(Message.id.asc()).all()
    else:
        # Check if the target is a group
        group = Group.query.filter_by(name=other_name).first()
        if group:
            # Verify the current user is a member of the group
            is_member = GroupMember.query.filter_by(group_name=other_name, username=my_name).first() is not None
            if not is_member:
                return jsonify({"success": False, "error": "Unauthorized"}), 403
            
            messages = Message.query.filter(
                (Message.recipient == other_name) &
                ~((Message.sender == my_name) & (Message.deleted_by_sender == True))
            ).order_by(Message.id.asc()).all()
        else:
            messages = Message.query.filter(
                (((Message.sender == my_name) & (Message.recipient == other_name)) |
                 ((Message.sender == other_name) & (Message.recipient == my_name))) &
                ~((Message.sender == my_name) & (Message.deleted_by_sender == True)) &
                ~((Message.recipient == my_name) & (Message.deleted_by_recipient == True))
            ).order_by(Message.id.asc()).all()
        
    result = []
    for msg in messages:
        result.append({
            "db_id": msg.id,
            "sender": msg.sender,
            "to": msg.recipient,
            "type": msg.msg_type,
            "content": msg.content,
            "time": msg.time,
            "duration": msg.duration,
            "size": msg.duration,
            "name": msg.file_name,
            "data": msg.raw_data,
            "status": msg.status,
            "msg_id": msg.msg_id,
            "reactions": msg.reactions,
            "reply_to": msg.reply_to,
            "reply_content": msg.reply_content
        })
    return jsonify({"success": True, "messages": result})

@api_bp.route('/upload', methods=['POST'])
def upload_file():
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
        
    if 'file' not in request.files:
        return jsonify({"success": False, "error": "No file part"}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({"success": False, "error": "No selected file"}), 400
        
    if file:
        filename = f"{uuid.uuid4().hex}_{file.filename}"
        filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        size = os.path.getsize(filepath)
        return jsonify({
            "success": True, 
            "filename": filename,
            "original_name": file.filename,
            "size": size
        })

@api_bp.route('/download/<filename>', methods=['GET'])
def download_file(filename):
    return send_from_directory(current_app.config['UPLOAD_FOLDER'], filename)

@api_bp.route('/user_info', methods=['GET'])
def get_user_info():
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
    return jsonify({"success": True, "username": session['username']})

@api_bp.route('/webrtc_config', methods=['GET'])
def get_webrtc_config():
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
        
    turn_url = current_app.config.get('TURN_SERVER', 'turn:openrelay.metered.ca:80')
    username = current_app.config.get('TURN_USERNAME', 'openrelayproject')
    credential = current_app.config.get('TURN_CREDENTIAL', 'openrelayproject')
    
    # Extract host:port from the config URL
    host_port = turn_url.split('turn:')[-1].split('?')[0]
    
    return jsonify({
        "success": True,
        "iceServers": [
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
def create_group():
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
    
    my_name = session['username']
    data = request.json or {}
    group_name = data.get('name', '').strip()
    description = data.get('description', '').strip()
    
    if not group_name:
        return jsonify({"success": False, "error": "Group name is required"}), 400
        
    if group_name == 'All' or group_name.lower() == 'all':
        return jsonify({"success": False, "error": "Invalid group name"}), 400
        
    # Check if a group or user with this name already exists (since they share the namespace in messages)
    existing_group = Group.query.filter_by(name=group_name).first()
    existing_user = User.query.filter(User.username.ilike(group_name)).first()
    if existing_group or existing_user:
        return jsonify({"success": False, "error": "Name already taken"}), 400
        
    # Create the group
    group = Group(name=group_name, owner_username=my_name, description=description)
    db.session.add(group)
    
    # Automatically add owner as a member
    member = GroupMember(group_name=group_name, username=my_name)
    db.session.add(member)
    
    # Add selected members directly
    selected_members = data.get('members', [])
    for u_name in selected_members:
        u_name = u_name.strip()
        if u_name and u_name != my_name:
            user_exists = User.query.filter(User.username.ilike(u_name)).first()
            if user_exists:
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
        print("Error emitting group_list_updated socket event on create:", e)
        
    return jsonify({"success": True, "message": "Group created successfully"})

@api_bp.route('/groups', methods=['GET'])
def get_groups():
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
        
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
        
    return jsonify({"success": True, "groups": result})

@api_bp.route('/calls/log', methods=['POST'])
def save_call_log():
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
        
    my_name = session['username']
    data = request.json or {}
    recipient = data.get('recipient')
    status = data.get('status')  # 'completed', 'missed', 'rejected', 'busy'
    duration = int(data.get('duration', 0))
    
    if not recipient or not status:
        return jsonify({"success": False, "error": "Missing parameters"}), 400
        
    recip_user = User.query.filter_by(username=recipient).first()
    if not recip_user:
        return jsonify({"success": False, "error": "Recipient not found"}), 404
        
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
        print("Error emitting call log socket event:", e)
        
    return jsonify({"success": True, "message": "Call log saved successfully"})

@api_bp.route('/groups/invite', methods=['POST'])
def invite_to_group():
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
        
    my_name = session['username']
    data = request.json or {}
    group_name = data.get('group_name')
    
    # Support both single username and batch usernames
    target_usernames = data.get('usernames', [])
    if not target_usernames and data.get('username'):
        target_usernames = [data.get('username')]
        
    if not group_name or not target_usernames:
        return jsonify({"success": False, "error": "Missing parameters"}), 400
        
    group = Group.query.filter_by(name=group_name).first()
    if not group:
        return jsonify({"success": False, "error": "Group not found"}), 404
        
    if group.owner_username != my_name:
        return jsonify({"success": False, "error": "Only the group owner can invite users"}), 403
        
    invited_count = 0
    errors = []
    
    for target_username in target_usernames:
        target_username = target_username.strip()
        if not target_username:
            continue
            
        target_user = User.query.filter(User.username.ilike(target_username)).first()
        if not target_user:
            errors.append(f"User {target_username} not found")
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
            print("Error emitting group_invite_received socket event:", e)
            
    if invited_count > 0:
        db.session.commit()
        
    return jsonify({"success": True, "message": f"Successfully sent {invited_count} invitation(s)", "errors": errors})

@api_bp.route('/groups/invite/respond', methods=['POST'])
def respond_to_invite():
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
        
    my_name = session['username']
    data = request.json or {}
    group_name = data.get('group_name')
    action = data.get('action') # 'accept' or 'reject'
    
    if not group_name or action not in ('accept', 'reject'):
        return jsonify({"success": False, "error": "Invalid parameters"}), 400
        
    invite = GroupInvite.query.filter_by(group_name=group_name, username=my_name, status='pending').first()
    if not invite:
        return jsonify({"success": False, "error": "Invitation not found"}), 404
        
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
                print("Error emitting join group room:", e)
    else:
        invite.status = 'rejected'
        
    db.session.commit()
    return jsonify({"success": True, "message": f"Invitation {action}ed successfully"})

@api_bp.route('/groups/request_join', methods=['POST'])
def request_join():
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
        
    my_name = session['username']
    data = request.json or {}
    group_name = data.get('group_name')
    
    if not group_name:
        return jsonify({"success": False, "error": "Group name is required"}), 400
        
    group = Group.query.filter_by(name=group_name).first()
    if not group:
        return jsonify({"success": False, "error": "Group not found"}), 404
        
    # Check if already member
    if GroupMember.query.filter_by(group_name=group_name, username=my_name).first():
        return jsonify({"success": False, "error": "Already a member"}), 400
        
    # Check if already requested
    existing_req = GroupJoinRequest.query.filter_by(group_name=group_name, username=my_name, status='pending').first()
    if existing_req:
        return jsonify({"success": False, "error": "Request already pending"}), 400
        
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
        print("Error emitting request join socket:", e)
        
    return jsonify({"success": True, "message": "Join request submitted successfully"})

@api_bp.route('/groups/requests', methods=['GET'])
def get_join_requests():
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
        
    my_name = session['username']
    group_name = request.args.get('group_name')
    
    if not group_name:
        return jsonify({"success": False, "error": "Group name is required"}), 400
        
    group = Group.query.filter_by(name=group_name).first()
    if not group:
        return jsonify({"success": False, "error": "Group not found"}), 404
        
    if group.owner_username != my_name:
        return jsonify({"success": False, "error": "Unauthorized"}), 403
        
    reqs = GroupJoinRequest.query.filter_by(group_name=group_name, status='pending').all()
    result = [r.username for r in reqs]
    return jsonify({"success": True, "requests": result})

@api_bp.route('/groups/requests/respond', methods=['POST'])
def respond_to_request():
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
        
    my_name = session['username']
    data = request.json or {}
    group_name = data.get('group_name')
    target_username = data.get('username')
    action = data.get('action') # 'accept' or 'reject'
    
    if not group_name or not target_username or action not in ('accept', 'reject'):
        return jsonify({"success": False, "error": "Invalid parameters"}), 400
        
    group = Group.query.filter_by(name=group_name).first()
    if not group:
        return jsonify({"success": False, "error": "Group not found"}), 404
        
    if group.owner_username != my_name:
        return jsonify({"success": False, "error": "Unauthorized"}), 403
        
    req_join = GroupJoinRequest.query.filter_by(group_name=group_name, username=target_username, status='pending').first()
    if not req_join:
        return jsonify({"success": False, "error": "Request not found"}), 404
        
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
                print("Error emitting join group room:", e)
    else:
        req_join.status = 'rejected'
        
    db.session.commit()
    return jsonify({"success": True, "message": f"Join request {action}ed successfully"})

@api_bp.route('/groups/members', methods=['GET'])
def get_group_members():
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
        
    group_name = request.args.get('group_name')
    if not group_name:
        return jsonify({"success": False, "error": "Group name is required"}), 400
        
    # Verify is member
    my_name = session['username']
    if not GroupMember.query.filter_by(group_name=group_name, username=my_name).first():
        return jsonify({"success": False, "error": "Unauthorized"}), 403
        
    members = GroupMember.query.filter_by(group_name=group_name).all()
    result = [m.username for m in members]
    return jsonify({"success": True, "members": result})

@api_bp.route('/groups/kick', methods=['POST'])
def kick_member():
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
        
    my_name = session['username']
    data = request.json or {}
    group_name = data.get('group_name')
    target_username = data.get('username')
    
    if not group_name or not target_username:
        return jsonify({"success": False, "error": "Missing parameters"}), 400
        
    group = Group.query.filter_by(name=group_name).first()
    if not group:
        return jsonify({"success": False, "error": "Group not found"}), 404
        
    if group.owner_username != my_name:
        return jsonify({"success": False, "error": "Unauthorized"}), 403
        
    if target_username == my_name:
        return jsonify({"success": False, "error": "Cannot kick yourself"}), 400
        
    member = GroupMember.query.filter_by(group_name=group_name, username=target_username).first()
    if not member:
        return jsonify({"success": False, "error": "Member not found"}), 404
        
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
        print("Error emitting kick/leave room:", e)
        
    db.session.commit()
    return jsonify({"success": True, "message": "Member kicked successfully"})

@api_bp.route('/groups/leave', methods=['POST'])
def leave_group():
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
        
    my_name = session['username']
    data = request.json or {}
    group_name = data.get('group_name')
    
    if not group_name:
        return jsonify({"success": False, "error": "Group name is required"}), 400
        
    group = Group.query.filter_by(name=group_name).first()
    if not group:
        return jsonify({"success": False, "error": "Group not found"}), 404
        
    if group.owner_username == my_name:
        return jsonify({"success": False, "error": "Owner cannot leave, delete the group instead"}), 400
        
    member = GroupMember.query.filter_by(group_name=group_name, username=my_name).first()
    if not member:
        return jsonify({"success": False, "error": "Not a member"}), 400
        
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
        print("Error emitting leave room:", e)
        
    db.session.commit()
    return jsonify({"success": True, "message": "Left group successfully"})

@api_bp.route('/groups/delete', methods=['POST'])
def delete_group():
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Not authenticated"}), 401
        
    my_name = session['username']
    data = request.json or {}
    group_name = data.get('group_name')
    
    if not group_name:
        return jsonify({"success": False, "error": "Group name is required"}), 400
        
    group = Group.query.filter_by(name=group_name).first()
    if not group:
        return jsonify({"success": False, "error": "Group not found"}), 404
        
    if group.owner_username != my_name:
        return jsonify({"success": False, "error": "Unauthorized"}), 403
        
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
        print("Error emitting group deleted socket:", e)
        
    db.session.commit()
    return jsonify({"success": True, "message": "Group deleted successfully"})



