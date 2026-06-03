import os
import datetime
import uuid
from flask import Blueprint, render_template, request, jsonify, session, redirect, current_app
from database.database import db
from models.models import User, Message, Group, GroupMember, GroupInvite, GroupJoinRequest, SystemBroadcast
from werkzeug.security import generate_password_hash
from utils.crypto import decrypt_text
from sqlalchemy import or_, and_, func

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

@admin_bp.before_request
def check_admin_session():
    # Enforce admin authentication check for all admin routes
    if not session.get('admin_logged_in'):
        if request.path.startswith('/admin/api/'):
            return jsonify({"success": False, "error": "Unauthorized admin access."}), 401
        return redirect('/login')

@admin_bp.route('/')
@admin_bp.route('/dashboard')
def dashboard():
    return render_template('admin/admin_dashboard.html')

@admin_bp.route('/logout')
def logout():
    session.pop('admin_logged_in', None)
    return redirect('/login')

# --- Statistics API ---
@admin_bp.route('/api/stats', methods=['GET'])
def get_stats():
    try:
        db_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', 'sqlite:///falcon_web.db')
        db_path = db_uri.replace('sqlite:///', '')
        
        # Calculate file size
        size_bytes = 0
        if os.path.exists(db_path):
            size_bytes = os.path.getsize(db_path)
        size_mb = size_bytes / (1024 * 1024)
        
        total_users = User.query.count()
        total_messages = Message.query.count()
        
        text_messages = Message.query.filter_by(msg_type='text').count()
        file_messages = Message.query.filter_by(msg_type='file').count()
        voice_messages = Message.query.filter_by(msg_type='voice').count()
        
        # User status distribution
        status_counts = db.session.query(User.status, func.count(User.id)).group_by(User.status).all()
        status_dist = {status: count for status, count in status_counts}
        
        return jsonify({
            "success": True,
            "db_path": os.path.abspath(db_path),
            "db_size": f"{size_mb:.2f} MB ({size_bytes:,} bytes)",
            "total_users": total_users,
            "total_messages": total_messages,
            "text_messages": text_messages,
            "file_messages": file_messages,
            "voice_messages": voice_messages,
            "status_distribution": status_dist
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# --- User Management API ---
@admin_bp.route('/api/users', methods=['GET'])
def list_users():
    try:
        users = User.query.all()
        user_list = []
        for u in users:
            # count sent messages
            sent_count = Message.query.filter_by(sender=u.username).count()
            user_list.append({
                "id": u.id,
                "username": u.username,
                "status": u.status,
                "created_at": u.created_at.strftime("%Y-%m-%d %H:%M:%S") if u.created_at else "N/A",
                "last_seen": u.last_seen.strftime("%Y-%m-%d %H:%M:%S") if u.last_seen else "N/A",
                "is_banned": u.is_banned,
                "sent_count": sent_count
            })
        return jsonify({"success": True, "users": user_list})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@admin_bp.route('/api/users/add', methods=['POST'])
def add_user():
    try:
        data = request.json or {}
        username = data.get('username', '').strip()
        password = data.get('password', '')
        
        if not username or not password:
            return jsonify({"success": False, "error": "Username and password are required."}), 400
            
        # Check if user exists
        existing = User.query.filter(func.lower(User.username) == func.lower(username)).first()
        if existing:
            return jsonify({"success": False, "error": f"User '{username}' already exists."}), 409
            
        u = User(username=username, status="Offline")
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        return jsonify({"success": True, "message": f"User '{username}' created successfully."})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

@admin_bp.route('/api/users/edit/<int:user_id>', methods=['POST'])
def edit_user(user_id):
    try:
        u = User.query.get_or_404(user_id)
        data = request.json or {}
        new_username = data.get('username', '').strip()
        new_status = data.get('status', 'Offline')
        new_password = data.get('password', '')
        
        if not new_username:
            return jsonify({"success": False, "error": "Username cannot be empty."}), 400
            
        old_username = u.username
        
        # Check if renaming username conflicts
        if new_username.lower() != old_username.lower():
            conflict = User.query.filter(func.lower(User.username) == func.lower(new_username)).first()
            if conflict:
                return jsonify({"success": False, "error": f"Username '{new_username}' already exists."}), 409
        
        # Update user
        u.username = new_username
        u.status = new_status
        if new_password:
            u.set_password(new_password)
            
        # Propagate username changes to other tables if updated
        if new_username != old_username:
            # Update messages
            Message.query.filter_by(sender=old_username).update({Message.sender: new_username})
            Message.query.filter_by(recipient=old_username).update({Message.recipient: new_username})
            # Update groups ownership
            Group.query.filter_by(owner_username=old_username).update({Group.owner_username: new_username})
            # Update group members
            GroupMember.query.filter_by(username=old_username).update({GroupMember.username: new_username})
            # Update invites
            GroupInvite.query.filter_by(username=old_username).update({GroupInvite.username: new_username})
            GroupInvite.query.filter_by(invited_by=old_username).update({GroupInvite.invited_by: new_username})
            # Update requests
            GroupJoinRequest.query.filter_by(username=old_username).update({GroupJoinRequest.username: new_username})
            
        db.session.commit()
        return jsonify({"success": True, "message": "User updated successfully."})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

@admin_bp.route('/api/users/toggle_ban/<int:user_id>', methods=['POST'])
def toggle_ban(user_id):
    try:
        u = User.query.get_or_404(user_id)
        u.is_banned = not u.is_banned
        db.session.commit()
        status_txt = "banned" if u.is_banned else "unbanned"
        return jsonify({"success": True, "message": f"User {u.username} has been {status_txt}."})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

@admin_bp.route('/api/users/delete/<int:user_id>', methods=['POST'])
def delete_user(user_id):
    try:
        u = User.query.get_or_404(user_id)
        username = u.username
        
        # Cascade deletes
        db.session.delete(u)
        Message.query.filter(or_(Message.sender == username, Message.recipient == username)).delete()
        GroupMember.query.filter_by(username=username).delete()
        GroupInvite.query.filter_by(username=username).delete()
        GroupInvite.query.filter_by(invited_by=username).delete()
        GroupJoinRequest.query.filter_by(username=username).delete()
        
        # If user owns a group, delete the group cascade style
        owned_groups = Group.query.filter_by(owner_username=username).all()
        for g in owned_groups:
            GroupMember.query.filter_by(group_name=g.name).delete()
            GroupInvite.query.filter_by(group_name=g.name).delete()
            GroupJoinRequest.query.filter_by(group_name=g.name).delete()
            Message.query.filter_by(recipient=g.name).delete()
            db.session.delete(g)
            
        db.session.commit()
        return jsonify({"success": True, "message": f"User '{username}' and all their data/messages deleted successfully."})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

# --- Group Management API ---
@admin_bp.route('/api/groups', methods=['GET'])
def list_groups():
    try:
        groups = Group.query.all()
        group_list = []
        for g in groups:
            member_count = GroupMember.query.filter_by(group_name=g.name).count()
            group_list.append({
                "id": g.id,
                "name": g.name,
                "owner_username": g.owner_username,
                "description": g.description or "",
                "created_at": g.created_at.strftime("%Y-%m-%d %H:%M:%S") if g.created_at else "N/A",
                "member_count": member_count
            })
        return jsonify({"success": True, "groups": group_list})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@admin_bp.route('/api/groups/<string:group_name>/members', methods=['GET'])
def list_group_members(group_name):
    try:
        members = GroupMember.query.filter_by(group_name=group_name).all()
        mem_list = [{
            "id": m.id,
            "username": m.username,
            "joined_at": m.joined_at.strftime("%Y-%m-%d %H:%M:%S") if m.joined_at else "N/A"
        } for m in members]
        return jsonify({"success": True, "members": mem_list})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@admin_bp.route('/api/groups/rename', methods=['POST'])
def rename_group():
    try:
        data = request.json or {}
        old_name = data.get('old_name', '').strip()
        new_name = data.get('new_name', '').strip()
        
        if not old_name or not new_name:
            return jsonify({"success": False, "error": "Old and new group names are required."}), 400
            
        g = Group.query.filter_by(name=old_name).first_or_404()
        
        # Check conflict
        if new_name.lower() != old_name.lower():
            conflict = Group.query.filter(func.lower(Group.name) == func.lower(new_name)).first()
            if conflict:
                return jsonify({"success": False, "error": f"Group name '{new_name}' already exists."}), 409
                
        g.name = new_name
        
        # Propagate group name changes
        GroupMember.query.filter_by(group_name=old_name).update({GroupMember.group_name: new_name})
        GroupInvite.query.filter_by(group_name=old_name).update({GroupInvite.group_name: new_name})
        GroupJoinRequest.query.filter_by(group_name=old_name).update({GroupJoinRequest.group_name: new_name})
        Message.query.filter_by(recipient=old_name).update({Message.recipient: new_name})
        
        db.session.commit()
        return jsonify({"success": True, "message": f"Group renamed from '{old_name}' to '{new_name}' successfully."})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

@admin_bp.route('/api/groups/kick', methods=['POST'])
def kick_group_member():
    try:
        data = request.json or {}
        group_name = data.get('group_name', '').strip()
        username = data.get('username', '').strip()
        
        if not group_name or not username:
            return jsonify({"success": False, "error": "Group name and username are required."}), 400
            
        member = GroupMember.query.filter_by(group_name=group_name, username=username).first()
        if not member:
            return jsonify({"success": False, "error": f"User '{username}' is not a member of '{group_name}'."}), 404
            
        db.session.delete(member)
        db.session.commit()
        return jsonify({"success": True, "message": f"Kicked '{username}' from group '{group_name}'."})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

@admin_bp.route('/api/groups/delete', methods=['POST'])
def delete_group():
    try:
        data = request.json or {}
        group_name = data.get('group_name', '').strip()
        
        if not group_name:
            return jsonify({"success": False, "error": "Group name is required."}), 400
            
        g = Group.query.filter_by(name=group_name).first_or_404()
        
        # Cascade deletes
        db.session.delete(g)
        GroupMember.query.filter_by(group_name=group_name).delete()
        GroupInvite.query.filter_by(group_name=group_name).delete()
        GroupJoinRequest.query.filter_by(group_name=group_name).delete()
        Message.query.filter_by(recipient=group_name).delete()
        
        db.session.commit()
        return jsonify({"success": True, "message": f"Group '{group_name}' and all its messages/members deleted successfully."})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

# --- Chat Viewer API ---
@admin_bp.route('/api/chats/users', methods=['GET'])
def get_chat_users():
    try:
        users = User.query.order_by(User.username.asc()).all()
        # also get list of groups to allow admins to inspect group chats!
        groups = Group.query.order_by(Group.name.asc()).all()
        
        u_list = [{"username": u.username, "type": "user"} for u in users]
        g_list = [{"username": g.name, "type": "group"} for g in groups]
        
        return jsonify({"success": True, "users": u_list, "groups": g_list})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@admin_bp.route('/api/chats/history', methods=['GET'])
def get_chat_history():
    try:
        user_a = request.args.get('user_a', '').strip()
        user_b = request.args.get('user_b', '').strip()
        chat_type = request.args.get('type', 'direct') # direct or group
        
        if not user_a:
            return jsonify({"success": False, "error": "User A is required."}), 400
            
        if chat_type == 'group':
            # load group messages
            messages = Message.query.filter_by(recipient=user_a).order_by(Message.id.asc()).all()
        else:
            if not user_b:
                return jsonify({"success": False, "error": "User B is required for direct chat history."}), 400
            # load direct messages between A and B
            messages = Message.query.filter(
                or_(
                    and_(Message.sender == user_a, Message.recipient == user_b),
                    and_(Message.sender == user_b, Message.recipient == user_a)
                )
            ).order_by(Message.id.asc()).all()
            
        msg_list = []
        for m in messages:
            content = m.content
            if m.msg_type == 'text':
                content = decrypt_text(m.content)
                
            msg_list.append({
                "id": m.id,
                "sender": m.sender,
                "recipient": m.recipient,
                "msg_type": m.msg_type,
                "content": content,
                "time": m.time,
                "duration": m.duration,
                "file_name": m.file_name,
                "status": m.status,
                "msg_id": m.msg_id
            })
            
        return jsonify({"success": True, "messages": msg_list})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@admin_bp.route('/api/chats/delete/<int:msg_id>', methods=['POST'])
def delete_message(msg_id):
    try:
        m = Message.query.get_or_404(msg_id)
        db.session.delete(m)
        db.session.commit()
        return jsonify({"success": True, "message": "Message deleted permanently."})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

# --- Media Manager API ---
@admin_bp.route('/api/media', methods=['GET'])
def list_media():
    try:
        upload_dir = current_app.config.get('UPLOAD_FOLDER', 'static/uploads')
        media_files = []
        if os.path.exists(upload_dir):
            for f in os.listdir(upload_dir):
                fpath = os.path.join(upload_dir, f)
                if os.path.isfile(fpath):
                    size_mb = os.path.getsize(fpath) / (1024 * 1024)
                    mtime = datetime.datetime.fromtimestamp(os.path.getmtime(fpath)).strftime('%Y-%m-%d %H:%M')
                    ext = f.split('.')[-1].upper() if '.' in f else 'N/A'
                    media_files.append({
                        "filename": f,
                        "size": f"{size_mb:.2f}",
                        "mtime": mtime,
                        "type": ext
                    })
        return jsonify({"success": True, "media": media_files})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@admin_bp.route('/api/media/delete', methods=['POST'])
def delete_media_file():
    try:
        data = request.json or {}
        filename = data.get('filename', '').strip()
        if not filename:
            return jsonify({"success": False, "error": "Filename is required."}), 400
            
        # Prevent path traversal attacks
        filename = os.path.basename(filename)
        upload_dir = current_app.config.get('UPLOAD_FOLDER', 'static/uploads')
        fpath = os.path.join(upload_dir, filename)
        
        if os.path.exists(fpath) and os.path.isfile(fpath):
            os.remove(fpath)
            return jsonify({"success": True, "message": f"File '{filename}' deleted successfully."})
        else:
            return jsonify({"success": False, "error": f"File '{filename}' not found."}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# --- Broadcast API ---
@admin_bp.route('/api/broadcast', methods=['POST'])
def send_broadcast():
    try:
        data = request.json or {}
        message = data.get('message', '').strip()
        
        if not message:
            return jsonify({"success": False, "error": "Broadcast message cannot be empty."}), 400
            
        b = SystemBroadcast(message=message, is_sent=False)
        db.session.add(b)
        db.session.commit()
        return jsonify({"success": True, "message": "Broadcast message queued successfully."})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
