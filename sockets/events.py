import json
import logging
import time
from collections import deque
from datetime import datetime, timedelta
from flask import request, session
from flask_socketio import emit, join_room, leave_room
from database.database import db
from models.models import User, Message, GroupMember, Group
from utils.presence import registry
from utils.typing import typing_tracker
from utils.security.constants import (
    MAX_MESSAGE_CONTENT_LENGTH,
    SOCKET_IO_RATE_LIMITS,
    VALID_STATUS_VALUES,
    AWAY_TIMEOUT_SECONDS,
    PRESENCE_DEBOUNCE_MS,
)
from utils.crypto import encrypt_text
from utils.security.sanitizers import sanitize_html

logger = logging.getLogger(__name__)

# Per-user per-event rate limit state: (user_id, event) -> deque of timestamps
_rate_history = {}

# Will be bound in register_events
check_away_users = None

def _check_rate_limit(event, user_id):
    """Return True if this event is within the configured rate limit."""
    max_per_second = SOCKET_IO_RATE_LIMITS.get(event, 0)
    if max_per_second <= 0:
        return True
    now = time.time()
    key = (user_id, event)
    if key not in _rate_history:
        _rate_history[key] = deque()
    bucket = _rate_history[key]
    while bucket and bucket[0] <= now - 1.0:
        bucket.popleft()
    if len(bucket) >= max_per_second:
        return False
    bucket.append(now)
    return True

def register_events(socketio):

    def _can_send_to_target(target, username):
        """Check if username is allowed to send messages to the given target room."""
        if target == 'All' or target == username:
            return True
        group = Group.query.filter_by(name=target).first()
        if group:
            return GroupMember.query.filter_by(group_name=target, username=username).first() is not None
        return True
    
    @socketio.on('connect')
    def handle_connect(*args, **kwargs):
        if 'user_id' not in session:
            return False
        
        user_id = session['user_id']
        user = User.query.get(user_id)
        if not user or user.is_banned:
            return False
        
        username = user.username
        
        # Administrators are not chat participants — connect silently, no broadcast
        if user.is_admin:
            join_room(username)
            join_room('All')
            try:
                my_memberships = GroupMember.query.filter_by(username=username).all()
                for member in my_memberships:
                    join_room(member.group_name)
            except Exception as e:
                logger.error("Error joining custom group rooms on connection: %s", e)
            registry.add_connection(username, request.sid)
            registry.update_heartbeat(username)
            return
        
        prev_online = registry.is_online(username)
        count = registry.add_connection(username, request.sid)
        registry.update_heartbeat(username)
        
        join_room(username)
        join_room('All')
        
        # Join custom group rooms
        try:
            my_memberships = GroupMember.query.filter_by(username=username).all()
            for member in my_memberships:
                join_room(member.group_name)
        except Exception as e:
            logger.error("Error joining custom group rooms on connection: %s", e)
        
        if count == 1 and not prev_online:
            # First connection — transition to Available
            registry.set_status(username, 'Available', reason='active')
            user.status = "Available"
            user.last_seen = datetime.utcnow()
            db.session.commit()
            emit('system', {'type': 'system', 'content': f"🔵 {username} joined."}, room='All')
            debounced_broadcast()
        else:
            # Additional tab — just refresh last_seen
            user.last_seen = datetime.utcnow()
            db.session.commit()
        
        # Mark pending offline messages sent to this user as 'delivered'
        undelivered = Message.query.filter_by(recipient=username, status='sent').all()
        if undelivered:
            for m in undelivered:
                m.status = 'delivered'
            db.session.commit()
            for m in undelivered:
                emit('message_status', {'msg_id': m.msg_id, 'status': 'delivered'}, room=m.sender)
        
        broadcast_user_list()
        
    @socketio.on('disconnect')
    def handle_disconnect(*args, **kwargs):
        if 'user_id' in session:
            user = User.query.get(session['user_id'])
            if user:
                username = user.username
                
                # Administrators disconnect silently — no broadcast
                if user.is_admin:
                    registry.remove_connection(username, request.sid)
                    leave_room(username)
                    leave_room('All')
                    return
                
                count = registry.remove_connection(username, request.sid)
                if count == 0:
                    # Last connection gone
                    registry.set_status(username, 'Offline', reason='disconnected')
                    user.status = "Offline"
                    user.last_seen = datetime.utcnow()
                    db.session.commit()
                    # Clear typing state for disconnected user
                    for room_name, type_ in typing_tracker.clear_user(username):
                        if type_ == 'private':
                            emit('user_typing_stop', {
                                'username': username,
                                'conversation': username,
                                'type': 'private',
                            }, room=room_name)
                        else:
                            emit('user_typing_stop', {
                                'username': username,
                                'conversation': room_name,
                                'type': 'group',
                            }, room=room_name, include_self=False)
                
                leave_room(username)
                leave_room('All')
                
                if count == 0:
                    emit('system', {'type': 'system', 'content': f"🔴 {username} left."}, room='All')
                    debounced_broadcast()

    def broadcast_user_list():
        from sqlalchemy import or_, and_, func
        all_users = User.query.filter(User.is_admin != True).all()
        online_users = User.query.filter(User.status != 'Offline', User.is_admin != True).all()
        
        # Batch all unread counts into a single GROUP BY query
        online_usernames = [u.username for u in online_users]
        unread_rows = db.session.query(
            Message.sender,
            Message.recipient,
            func.count(Message.id).label('cnt')
        ).filter(
            Message.recipient.in_(online_usernames),
            Message.status != 'read'
        ).group_by(Message.sender, Message.recipient).all()
        unread_lookup = {(r.sender, r.recipient): r.cnt for r in unread_rows}
        
        # Batch last-message retrieval: max message id per conversation pair
        from sqlalchemy import case
        all_usernames = [u.username for u in all_users]
        subq = db.session.query(
            func.max(Message.id).label('max_id'),
        ).select_from(Message).filter(
            Message.sender.in_(all_usernames),
            Message.recipient.in_(all_usernames)
        ).group_by(
            case((Message.sender <= Message.recipient, Message.sender), else_=Message.recipient),
            case((Message.sender <= Message.recipient, Message.recipient), else_=Message.sender),
        ).subquery()
        
        last_msg_rows = db.session.query(Message).join(
            subq, Message.id == subq.c.max_id
        ).all()
        
        last_msg_lookup = {}
        for msg in last_msg_rows:
            key = (msg.sender, msg.recipient) if msg.sender <= msg.recipient else (msg.recipient, msg.sender)
            last_msg_lookup[key] = msg
        
        epoch = datetime(1970, 1, 1)
        
        for recipient in online_users:
            users_info = []
            for u in all_users:
                if u.username == recipient.username:
                    continue
                unread_count = unread_lookup.get((u.username, recipient.username), 0)
                
                # Look up last message from batch
                key = (u.username, recipient.username) if u.username <= recipient.username else (recipient.username, u.username)
                last_msg = last_msg_lookup.get(key)
                last_msg_time = int((last_msg.created_at - epoch).total_seconds() * 1000) if (last_msg and last_msg.created_at) else 0
                
                users_info.append({
                    "name": u.username,
                    "status": u.status,
                    "last_seen": (u.last_seen.isoformat() + "Z") if u.last_seen else None,
                    "unread_count": unread_count,
                    "last_message_time": last_msg_time
                })
            
            socketio.emit('user_list', {'type': 'user_list', 'users': users_info}, room=recipient.username)

    # ── Debounced presence broadcast ─────────────────────────────────
    _last_broadcast: float = 0

    def debounced_broadcast():
        nonlocal _last_broadcast
        now = time.time() * 1000
        if now - _last_broadcast < PRESENCE_DEBOUNCE_MS:
            return
        _last_broadcast = now
        _send_user_updates()

    def _send_user_updates():
        """Emit user_update for all users."""
        online = registry.online_users()
        all_users = User.query.filter(User.is_admin != True).all()
        for user in all_users:
            reg_status = registry.get_status(user.username)
            data = {
                "name": user.username,
                "status": reg_status or user.status,
                "last_seen": user.last_seen.isoformat() + "Z" if user.last_seen else None,
                "is_online": user.username in online,
            }
            socketio.emit('user_update', data)

    # ── Heartbeat ─────────────────────────────────────────────────────

    @socketio.on('heartbeat')
    def handle_heartbeat(data=None):
        if 'user_id' not in session:
            return
        user = User.query.get(session['user_id'])
        if not user:
            return
        username = user.username
        registry.update_heartbeat(username)
        resumed = False
        reg_status = registry.get_status(username)
        if reg_status == 'Away':
            registry.set_status(username, 'Available', reason='active')
            user.status = 'Available'
            resumed = True
        user.last_seen = datetime.utcnow()
        db.session.commit()
        if resumed:
            debounced_broadcast()

    # ── Away detection (called from background scheduler) ─────────────
    global check_away_users

    def _check_away_users():
        """Mark users as Away if no heartbeat for AWAY_TIMEOUT_SECONDS."""
        threshold = datetime.utcnow() - timedelta(seconds=AWAY_TIMEOUT_SECONDS)
        changed = []
        for username in registry.online_users():
            last_hb = registry.get_last_heartbeat(username)
            if last_hb is None or last_hb > threshold:
                continue
            reg_status = registry.get_status(username)
            if reg_status in ('Available', 'Busy'):
                registry.set_status(username, 'Away', reason='idle_timeout')
                user = User.query.filter_by(username=username).first()
                if user:
                    user.status = 'Away'
                    changed.append(user)
        if changed:
            db.session.commit()
            debounced_broadcast()

    check_away_users = _check_away_users

    # ── Auto-busy on WebRTC call ──────────────────────────────────────

    @socketio.on('call_start')
    def handle_call_start(data):
        if 'user_id' not in session:
            return
        user = User.query.get(session['user_id'])
        if not user:
            return
        username = user.username
        reg_status = registry.get_status(username)
        if reg_status and reg_status not in ('Busy', 'Away', 'Offline'):
            registry.save_previous_status(username)
            registry.set_status(username, 'Busy', reason='in_call')
            user.status = 'Busy'
            db.session.commit()
            debounced_broadcast()

    @socketio.on('call_end')
    def handle_call_end(data):
        if 'user_id' not in session:
            return
        user = User.query.get(session['user_id'])
        if not user:
            return
        username = user.username
        reg_status = registry.get_status(username)
        if reg_status == 'Busy':
            reg_reason = registry.get_reason(username)
            if reg_reason == 'in_call':
                prev_status = registry.pop_previous_status(username) or 'Available'
                registry.set_status(username, prev_status, reason='active')
                user.status = prev_status
                db.session.commit()
                debounced_broadcast()

    # ── Typing Indicators ────────────────────────────────────────────

    @socketio.on('typing_start')
    def handle_typing_start(data):
        if 'user_id' not in session:
            return
        user = User.query.get(session['user_id'])
        if not user:
            return
        username = user.username
        to = data.get('to', '')
        if not to:
            return
        type_ = data.get('type', 'private')

        room = typing_tracker.start(username, to, type_)
        if room is None:
            return  # already typing — no duplicate broadcast

        if type_ == 'private':
            emit('user_typing', {
                'username': username,
                'conversation': username,
                'type': 'private',
            }, room=to)
        else:
            emit('user_typing', {
                'username': username,
                'conversation': to,
                'type': 'group',
            }, room=to, include_self=False)

    @socketio.on('typing_stop')
    def handle_typing_stop(data):
        if 'user_id' not in session:
            return
        user = User.query.get(session['user_id'])
        if not user:
            return
        username = user.username
        to = data.get('to', '')
        if not to:
            return
        type_ = data.get('type', 'private')

        room = typing_tracker.stop(username, to, type_)
        if room is None:
            return  # wasn't typing

        if type_ == 'private':
            emit('user_typing_stop', {
                'username': username,
                'conversation': username,
                'type': 'private',
            }, room=to)
        else:
            emit('user_typing_stop', {
                'username': username,
                'conversation': to,
                'type': 'group',
            }, room=to, include_self=False)

    @socketio.on('send_message')
    def handle_message(data):
        if 'user_id' not in session: return
        user = User.query.get(session['user_id'])
        if not user: return
        if not _check_rate_limit('send_message', user.id):
            return
        
        sender = user.username
        target = data.get('to', 'All')
        
        # Override sender to prevent spoofing
        data['sender'] = sender
        
        if not _can_send_to_target(target, sender):
            return
        
        # Reject oversized messages before any processing
        content = data.get('content', '') or ''
        if len(content) > MAX_MESSAGE_CONTENT_LENGTH:
            return
        
        # Strip HTML tags from message content (server-side XSS sanitization)
        data['content'] = sanitize_html(content)
        
        ptype = data.get('type')
        
        # Save to DB if not transient
        if ptype not in ('typing', 'ack', 'read', 'reaction', 'system', 'webrtc_signaling'):
            if target != 'All':
                recipient_user = User.query.filter_by(username=target).first()
                recipient_is_online = registry.is_online(target)
                if recipient_user and (recipient_user.status != 'Offline' or recipient_is_online):
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
                content=encrypt_text(data.get('content')),
                time=data.get('time'),
                duration=data.get('duration') or data.get('size'),
                file_name=data.get('name'),
                raw_data=data.get('data'),
                status=msg_status,
                msg_id=data.get('msg_id'),
                reply_to=data.get('reply_to'),
                reply_content=encrypt_text(data.get('reply_content'))
            )
            try:
                db.session.add(msg)
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                logger.exception("Database error occurred while persisting message: %s", e)
                error_ack = {
                    "type": "ack",
                    "sender": "Server",
                    "to": sender,
                    "msg_id": data.get('msg_id'),
                    "status": "failed"
                }
                emit('new_message', error_ack, room=sender)
                return

        # Auto-stop typing for this conversation after sending
        if sender != 'Server':
            stype = 'group' if Group.query.filter_by(name=target).first() else 'private'
            room = typing_tracker.stop(sender, target, stype)
            if room and stype == 'private':
                emit('user_typing_stop', {
                    'username': sender,
                    'conversation': sender,
                    'type': 'private',
                }, room=target)
            elif room:
                emit('user_typing_stop', {
                    'username': sender,
                    'conversation': target,
                    'type': 'group',
                }, room=target, include_self=False)

        if target == 'All':
            emit('new_message', data, room='All')
        else:
            emit('new_message', data, room=target)
            if sender != target:
                emit('new_message', data, room=sender)
                
            if ptype not in ('typing', 'ack', 'read', 'system', 'reaction'):
                ack_data = {"type": "ack", "sender": "Server", "to": sender, "msg_id": data.get('msg_id'), "status": data.get('status')}
                emit('new_message', ack_data, room=sender)

    @socketio.on('message_read')
    def handle_message_read(data):
        if 'user_id' not in session: return
        user = User.query.get(session['user_id'])
        if not user: return
        if not _check_rate_limit('message_read', user.id):
            return
        username = user.username
        msg_id = data.get('msg_id')
        msg = Message.query.filter_by(msg_id=msg_id).first()
        if not msg: return
        if msg.sender != username and msg.recipient != username:
            return
        if msg.status != 'read':
            msg.status = 'read'
            db.session.commit()
            emit('message_status', {'msg_id': msg_id, 'status': 'read'}, room=msg.sender)

    @socketio.on('mark_all_read')
    def handle_mark_all_read(data):
        if 'user_id' not in session: return
        user = User.query.get(session['user_id'])
        if not user: return
        if not _check_rate_limit('mark_all_read', user.id):
            return
        
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

    @socketio.on('reaction')
    def handle_reaction(data):
        if 'user_id' not in session: return
        user = User.query.get(session['user_id'])
        if not user: return
        if not _check_rate_limit('reaction', user.id):
            return

        my_username = user.username
        msg_id = data.get('msg_id')
        emoji  = data.get('emoji')

        if not msg_id or not emoji:
            return

        msg = Message.query.filter_by(msg_id=msg_id).first()
        if not msg:
            return

        if msg.sender != my_username and msg.recipient != my_username:
            group = Group.query.filter_by(name=msg.recipient).first()
            if not group or not GroupMember.query.filter_by(group_name=msg.recipient, username=my_username).first():
                return

        # Resolve target from message itself, not client input
        target = msg.recipient
        if target != 'All':
            # Check if target is a group
            is_group = bool(Group.query.filter_by(name=target).first())
            if not is_group:
                # Private message: target is the other user
                target = msg.recipient if msg.sender == my_username else msg.sender

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
        is_shared_room = (target == 'All') or bool(Group.query.filter_by(name=target).first())

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
        if not _check_rate_limit('delete_message', user.id):
            return
        
        username = user.username
        msg_id = data.get('msg_id')
        delete_type = data.get('delete_type', 'everyone') # 'me' or 'everyone'
        
        msg = Message.query.filter_by(msg_id=msg_id).first()
        if not msg: return
        
        is_sender = (msg.sender == username)
        
        if delete_type == 'everyone' and is_sender:
            db.session.delete(msg)
            db.session.commit()
            
            canonical_target = msg.recipient
            emit('message_deleted', {'msg_id': msg_id, 'to': canonical_target}, room=canonical_target)
            if canonical_target != 'All' and username != canonical_target:
                emit('message_deleted', {'msg_id': msg_id, 'to': canonical_target}, room=username)
        elif delete_type == 'me':
            from models.models import MessageVisibility
            # Check if this visibility entry already exists to prevent integrity errors
            exists = MessageVisibility.query.filter_by(msg_id=msg_id, username=username).first()
            if not exists:
                visibility = MessageVisibility(msg_id=msg_id, username=username)
                db.session.add(visibility)

            # Garbage Collection for Private Chats (Optional, optimization):
            # If both parties in a private chat have deleted the message, delete it permanently.
            if msg.recipient != 'All':
                is_group = Group.query.filter_by(name=msg.recipient).first() is not None
                if not is_group:
                    other_user = msg.recipient if is_sender else msg.sender
                    already_hidden_by_other = MessageVisibility.query.filter_by(
                        msg_id=msg_id, username=other_user
                    ).first() is not None
                    if already_hidden_by_other:
                        db.session.delete(msg)  # Cascades deletion of visibility rows
            db.session.commit()
            
            # Emit deletion to the deleting user only
            emit('message_deleted', {'msg_id': msg_id, 'to': username}, room=username)

    @socketio.on('webrtc_signaling')
    def handle_webrtc(data):
        if 'user_id' not in session: return
        user = User.query.get(session['user_id'])
        if not user: return
        if not _check_rate_limit('webrtc_signaling', user.id):
            return
        target = data.get('to')
        if target:
            data['from'] = user.username
            emit('webrtc_signaling', data, room=target)
            
    @socketio.on('status_update')
    def handle_status(data):
        if 'user_id' not in session: return
        user = User.query.get(session['user_id'])
        if not user: return
        if not _check_rate_limit('status_update', user.id):
            return
        raw_status = data.get('status', 'Available')
        if raw_status not in VALID_STATUS_VALUES:
            logger.debug("Ignoring invalid status from %s", user.username)
            raw_status = 'Available'
        username = user.username
        registry.set_status(username, raw_status, reason='manual')
        user.status = raw_status
        user.last_seen = datetime.utcnow()
        db.session.commit()
        debounced_broadcast()

    @socketio.on('join_room_request')
    def handle_join_room_request(data):
        if 'user_id' not in session: return
        if not _check_rate_limit('join_room_request', session['user_id']):
            return
        group_name = data.get('group_name')
        if group_name:
            user = User.query.get(session['user_id'])
            if user and GroupMember.query.filter_by(group_name=group_name, username=user.username).first():
                join_room(group_name)

    @socketio.on('leave_room_request')
    def handle_leave_room_request(data):
        if 'user_id' not in session: return
        if not _check_rate_limit('leave_room_request', session['user_id']):
            return
        group_name = data.get('group_name')
        if group_name:
            leave_room(group_name)

    @socketio.on('group_call_start')
    def handle_group_call_start(data):
        if 'user_id' not in session: return
        user = User.query.get(session['user_id'])
        if not user: return
        if not _check_rate_limit('group_call_start', user.id):
            return
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
        if not _check_rate_limit('group_call_join', user.id):
            return
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
        if not _check_rate_limit('group_call_signaling', user.id):
            return
        target = data.get('to')
        if target:
            data['from'] = user.username
            emit('group_call_signaling', data, room=target)

    @socketio.on('group_call_leave')
    def handle_group_call_leave(data):
        if 'user_id' not in session: return
        user = User.query.get(session['user_id'])
        if not user: return
        if not _check_rate_limit('group_call_leave', user.id):
            return
        group_name = data.get('group_name')
        if group_name:
            call_room = f"call_{group_name}"
            leave_room(call_room)
            emit('user_left_group_call', {
                "username": user.username,
                "group_name": group_name
            }, room=call_room, include_self=False)

