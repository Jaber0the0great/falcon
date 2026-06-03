import json
from datetime import datetime
from flask import request, session
from flask_socketio import emit, join_room, leave_room
from database.database import db
from models.models import User, Message, GroupMember

def register_events(socketio):
    
    @socketio.on('connect')
    def handle_connect(*args, **kwargs):
        if 'user_id' not in session:
            return False
        
        user_id = session['user_id']
        user = User.query.get(user_id)
        if not user or user.is_banned:
            return False
        
        username = user.username
        user.status = "Available"
        user.last_seen = datetime.utcnow()
        db.session.commit()
            
        join_room(username)
        join_room('All')
        
        # Join custom group rooms
        try:
            my_memberships = GroupMember.query.filter_by(username=username).all()
            for member in my_memberships:
                join_room(member.group_name)
        except Exception as e:
            print("Error joining custom group rooms on connection:", e)

        
        # Mark pending offline messages sent to this user as 'delivered'
        undelivered = Message.query.filter_by(recipient=username, status='sent').all()
        if undelivered:
            for m in undelivered:
                m.status = 'delivered'
            db.session.commit()
            for m in undelivered:
                emit('message_status', {'msg_id': m.msg_id, 'status': 'delivered'}, room=m.sender)
        
        emit('system', {'type': 'system', 'content': f"🔵 {username} joined."}, room='All')
        broadcast_user_list()
        
    @socketio.on('disconnect')
    def handle_disconnect(*args, **kwargs):
        if 'user_id' in session:
            user = User.query.get(session['user_id'])
            if user:
                username = user.username
                user.status = "Offline"
                user.last_seen = datetime.utcnow()
                db.session.commit()
                
                leave_room(username)
                leave_room('All')
                
                emit('system', {'type': 'system', 'content': f"🔴 {username} left."}, room='All')
                broadcast_user_list()

    def broadcast_user_list():
        all_users = User.query.all()
        online_users = User.query.filter(User.status != 'Offline').all()
        
        for recipient in online_users:
            users_info = []
            for u in all_users:
                if u.username == recipient.username:
                    continue
                # count unread messages from u.username to recipient.username
                unread_count = Message.query.filter_by(
                    sender=u.username,
                    recipient=recipient.username
                ).filter(Message.status != 'read').count()
                
                users_info.append({
                    "name": u.username,
                    "status": u.status,
                    "last_seen": (u.last_seen.isoformat() + "Z") if u.last_seen else None,
                    "unread_count": unread_count
                })
            
            socketio.emit('user_list', {'type': 'user_list', 'users': users_info}, room=recipient.username)

    @socketio.on('send_message')
    def handle_message(data):
        if 'user_id' not in session: return
        user = User.query.get(session['user_id'])
        if not user: return
        
        sender = user.username
        target = data.get('to', 'All')
        
        # Override sender to prevent spoofing
        data['sender'] = sender
        
        ptype = data.get('type')
        
        # Save to DB if not transient
        if ptype not in ('typing', 'ack', 'read', 'reaction', 'system', 'webrtc_signaling'):
            if target != 'All':
                recipient_user = User.query.filter_by(username=target).first()
                if recipient_user and recipient_user.status != 'Offline':
                    msg_status = 'delivered'
                else:
                    msg_status = 'sent'
            else:
                msg_status = 'sent'
                
            data['status'] = msg_status
            
            msg = Message(
                sender=sender,
                recipient=target,
                msg_type=ptype,
                content=data.get('content'),
                time=data.get('time'),
                duration=data.get('duration') or data.get('size'),
                file_name=data.get('name'),
                raw_data=data.get('data'),
                status=msg_status,
                msg_id=data.get('msg_id'),
                reply_to=data.get('reply_to'),
                reply_content=data.get('reply_content')
            )
            db.session.add(msg)
            db.session.commit()

        if target == 'All':
            emit('new_message', data, room='All')
        else:
            emit('new_message', data, room=target)
            if sender != target:
                emit('new_message', data, room=sender)
                
            if ptype not in ('typing', 'ack', 'read', 'system', 'reaction'):
                ack_data = {"type": "ack", "sender": "Server", "to": sender, "msg_id": data.get('msg_id'), "status": data.get('status')}
                emit('new_message', ack_data, room=sender)
                
                # Update user list to reflect new unread count badge
                broadcast_user_list()

    @socketio.on('message_read')
    def handle_message_read(data):
        if 'user_id' not in session: return
        msg_id = data.get('msg_id')
        msg = Message.query.filter_by(msg_id=msg_id).first()
        if msg and msg.status != 'read':
            msg.status = 'read'
            db.session.commit()
            emit('message_status', {'msg_id': msg_id, 'status': 'read'}, room=msg.sender)
            broadcast_user_list()

    @socketio.on('mark_all_read')
    def handle_mark_all_read(data):
        if 'user_id' not in session: return
        user = User.query.get(session['user_id'])
        if not user: return
        
        my_username = user.username
        sender_username = data.get('sender')
        if not sender_username: return
        
        unread_messages = Message.query.filter_by(
            sender=sender_username,
            recipient=my_username
        ).filter(Message.status != 'read').all()
        
        if unread_messages:
            for m in unread_messages:
                m.status = 'read'
            db.session.commit()
            
            for m in unread_messages:
                emit('message_status', {'msg_id': m.msg_id, 'status': 'read'}, room=sender_username)
            
            broadcast_user_list()

    @socketio.on('reaction')
    def handle_reaction(data):
        if 'user_id' not in session: return
        user = User.query.get(session['user_id'])
        if not user: return

        my_username = user.username
        msg_id = data.get('msg_id')
        emoji  = data.get('emoji')
        target = data.get('to', 'All')

        if not msg_id or not emoji:
            return

        msg = Message.query.filter_by(msg_id=msg_id).first()
        if not msg:
            return

        import json as _json
        try:
            reactions = _json.loads(msg.reactions or '{}')
        except Exception:
            reactions = {}

        # Toggle: remove if already reacted, add otherwise
        users_list = reactions.get(emoji, [])
        if my_username in users_list:
            users_list.remove(my_username)
        else:
            users_list.append(my_username)

        if users_list:
            reactions[emoji] = users_list
        else:
            reactions.pop(emoji, None)

        reactions_json = _json.dumps(reactions, ensure_ascii=False)
        msg.reactions = reactions_json
        db.session.commit()

        update_payload = {'msg_id': msg_id, 'reactions': reactions_json}

        # For group rooms and broadcast, all members (including sender) are already in
        # the room, so one emit suffices. For private, emit to both sides.
        from models.models import Group as _Group
        is_shared_room = (target == 'All') or bool(_Group.query.filter_by(name=target).first())

        if is_shared_room:
            emit('reaction_update', update_payload, room=target)
        else:
            emit('reaction_update', update_payload, room=target)
            if my_username != target:
                emit('reaction_update', update_payload, room=my_username)

    @socketio.on('delete_message')
    def handle_delete_message(data):
        if 'user_id' not in session: return
        user = User.query.get(session['user_id'])
        if not user: return
        
        username = user.username
        msg_id = data.get('msg_id')
        delete_type = data.get('delete_type', 'everyone') # 'me' or 'everyone'
        
        msg = Message.query.filter_by(msg_id=msg_id).first()
        if not msg: return
        
        is_sender = (msg.sender == username)
        
        if delete_type == 'everyone' and is_sender:
            db.session.delete(msg)
            db.session.commit()
            
            target = data.get('to', 'All')
            emit('message_deleted', {'msg_id': msg_id, 'to': target}, room=target)
            if target != 'All' and username != target:
                emit('message_deleted', {'msg_id': msg_id, 'to': target}, room=username)
        elif delete_type == 'me':
            if is_sender:
                msg.deleted_by_sender = True
            else:
                msg.deleted_by_recipient = True
                
            if msg.deleted_by_sender and (msg.deleted_by_recipient or msg.recipient == 'All'):
                db.session.delete(msg)
            db.session.commit()
            
            # Emit deletion to the deleting user only
            emit('message_deleted', {'msg_id': msg_id, 'to': username}, room=username)

    @socketio.on('webrtc_signaling')
    def handle_webrtc(data):
        if 'user_id' not in session: return
        target = data.get('to')
        if target:
            emit('webrtc_signaling', data, room=target)
            
    @socketio.on('status_update')
    def handle_status(data):
        if 'user_id' not in session: return
        user = User.query.get(session['user_id'])
        if user:
            user.status = data.get('status', 'Available')
            db.session.commit()
            broadcast_user_list()

    @socketio.on('join_room_request')
    def handle_join_room_request(data):
        if 'user_id' not in session: return
        group_name = data.get('group_name')
        if group_name:
            user = User.query.get(session['user_id'])
            if user and GroupMember.query.filter_by(group_name=group_name, username=user.username).first():
                join_room(group_name)

    @socketio.on('leave_room_request')
    def handle_leave_room_request(data):
        if 'user_id' not in session: return
        group_name = data.get('group_name')
        if group_name:
            leave_room(group_name)

    @socketio.on('group_call_start')
    def handle_group_call_start(data):
        if 'user_id' not in session: return
        user = User.query.get(session['user_id'])
        if not user: return
        group_name = data.get('group_name')
        if group_name:
            if GroupMember.query.filter_by(group_name=group_name, username=user.username).first():
                emit('group_call_incoming', {
                    "group_name": group_name,
                    "caller": user.username
                }, room=group_name, include_self=False)

    @socketio.on('group_call_join')
    def handle_group_call_join(data):
        if 'user_id' not in session: return
        user = User.query.get(session['user_id'])
        if not user: return
        group_name = data.get('group_name')
        if group_name:
            if GroupMember.query.filter_by(group_name=group_name, username=user.username).first():
                call_room = f"call_{group_name}"
                join_room(call_room)
                emit('user_joined_group_call', {
                    "username": user.username,
                    "group_name": group_name
                }, room=call_room, include_self=False)

    @socketio.on('group_call_signaling')
    def handle_group_call_signaling(data):
        if 'user_id' not in session: return
        user = User.query.get(session['user_id'])
        if not user: return
        target = data.get('to')
        if target:
            data['from'] = user.username
            emit('group_call_signaling', data, room=target)

    @socketio.on('group_call_leave')
    def handle_group_call_leave(data):
        if 'user_id' not in session: return
        user = User.query.get(session['user_id'])
        if not user: return
        group_name = data.get('group_name')
        if group_name:
            call_room = f"call_{group_name}"
            leave_room(call_room)
            emit('user_left_group_call', {
                "username": user.username,
                "group_name": group_name
            }, room=call_room, include_self=False)

