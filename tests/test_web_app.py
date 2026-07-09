import unittest
from app import create_app
from database.database import db
from models.models import User, Message
from flask import session

from config import Config

class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False
    SECRET_KEY = 'test-secret-key-for-testing-only'

class FalconWebTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        
        db.create_all()
        
        # Insert test users
        self.u1 = User(username='Alice')
        self.u1.set_password('password123')
        self.u2 = User(username='Bob')
        self.u2.set_password('password123')
        db.session.add_all([self.u1, self.u2])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_message_columns(self):
        """Verify deleted_by_sender and deleted_by_recipient exist and default to False."""
        msg = Message(
            sender='Alice',
            recipient='Bob',
            msg_type='text',
            content='Hello Bob',
            msg_id='msg-1'
        )
        db.session.add(msg)
        db.session.commit()
        
        db_msg = Message.query.filter_by(msg_id='msg-1').first()
        self.assertIsNotNone(db_msg)
        self.assertFalse(db_msg.deleted_by_sender)
        self.assertFalse(db_msg.deleted_by_recipient)

    def test_history_filtering_alice_deletes_for_me(self):
        """Verify /api/history hides a message from Alice if Alice deleted it 'for me only'."""
        msg = Message(
            sender='Alice',
            recipient='Bob',
            msg_type='text',
            content='Secret message',
            msg_id='msg-secret',
            status='read'
        )
        db.session.add(msg)
        db.session.commit()

        # Try retrieving as Alice (sender) before deletion
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.u1.id
            sess['username'] = 'Alice'
            
        res = self.client.get('/api/history?target=Bob')
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(len(data['data']['messages']), 1)
        self.assertEqual(data['data']['messages'][0]['msg_id'], 'msg-secret')

        # Alice deletes for self
        from models.models import MessageVisibility
        v = MessageVisibility(msg_id='msg-secret', username='Alice')
        db.session.add(v)
        db.session.commit()

        # Alice retrieves history now: should be empty
        res = self.client.get('/api/history?target=Bob')
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(len(data['data']['messages']), 0)

        # Bob (recipient) retrieves history: should still see it since he did not delete it
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.u2.id
            sess['username'] = 'Bob'

        res = self.client.get('/api/history?target=Alice')
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(len(data['data']['messages']), 1)
        self.assertEqual(data['data']['messages'][0]['msg_id'], 'msg-secret')

    def test_history_filtering_bob_deletes_for_me(self):
        """Verify /api/history hides a message from Bob if Bob deleted it 'for me only'."""
        msg = Message(
            sender='Alice',
            recipient='Bob',
            msg_type='text',
            content='Hello there',
            msg_id='msg-hello',
            status='read'
        )
        db.session.add(msg)
        db.session.commit()

        # Bob deletes for self
        from models.models import MessageVisibility
        v = MessageVisibility(msg_id='msg-hello', username='Bob')
        db.session.add(v)
        db.session.commit()

        # Bob retrieves history: should be empty
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.u2.id
            sess['username'] = 'Bob'

        res = self.client.get('/api/history?target=Alice')
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(len(data['data']['messages']), 0)

        # Alice retrieves history: should still see it
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.u1.id
            sess['username'] = 'Alice'

        res = self.client.get('/api/history?target=Bob')
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(len(data['data']['messages']), 1)

    def test_case_insensitive_login(self):
        """Verify that login is case-insensitive and sets session['username'] correctly."""
        with self.client as c:
            res = c.post('/auth/login', json={
                'username': 'alICe',
                'password': 'password123'
            })
            data = res.get_json()
            self.assertTrue(data['success'])
            # It should return the canonical casing from database
            self.assertEqual(data['data']['username'], 'Alice')
            # Verify the session has canonical casing
            self.assertEqual(session['username'], 'Alice')

    def test_index_route_username_normalization(self):
        """Verify that index route normalizes session['username'] to match database casing."""
        # Set session with incorrect casing (e.g. 'alice')
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.u1.id
            sess['username'] = 'alICe' # incorrect casing
            
        # Get index route and verify session has been corrected to 'Alice'
        with self.client as c:
            res = c.get('/')
            self.assertEqual(res.status_code, 200)
            self.assertEqual(session['username'], 'Alice')

    def test_create_group_no_members(self):
        """Verify successful group creation without extra members."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.u1.id
            sess['username'] = 'Alice'
            
        res = self.client.post('/api/groups/create', json={
            'name': 'TestGroup',
            'description': 'A nice test group'
        })
        data = res.get_json()
        self.assertTrue(data['success'])
        
        # Verify group exists in DB
        from models.models import Group, GroupMember
        group = Group.query.filter_by(name='TestGroup').first()
        self.assertIsNotNone(group)
        self.assertEqual(group.owner_username, 'Alice')
        self.assertEqual(group.description, 'A nice test group')
        
        # Verify Alice is a member
        member = GroupMember.query.filter_by(group_name='TestGroup', username='Alice').first()
        self.assertIsNotNone(member)

    def test_create_group_with_members(self):
        """Verify group creation and automatic addition of selected members."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.u1.id
            sess['username'] = 'Alice'
            
        res = self.client.post('/api/groups/create', json={
            'name': 'DevTeam',
            'description': 'Developers room',
            'members': ['Bob', 'Charlie']  # Charlie doesn't exist, Bob does
        })
        data = res.get_json()
        self.assertTrue(data['success'])
        
        from models.models import GroupMember
        # Alice (owner) is a member
        m_alice = GroupMember.query.filter_by(group_name='DevTeam', username='Alice').first()
        self.assertIsNotNone(m_alice)
        
        # Bob (existing user) is added as member
        m_bob = GroupMember.query.filter_by(group_name='DevTeam', username='Bob').first()
        self.assertIsNotNone(m_bob)
        
        # Charlie (non-existent user) is NOT added
        m_charlie = GroupMember.query.filter_by(group_name='DevTeam', username='Charlie').first()
        self.assertIsNone(m_charlie)

    def test_create_group_validation(self):
        """Verify validation rules for group name."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.u1.id
            sess['username'] = 'Alice'
            
        # Empty name
        res = self.client.post('/api/groups/create', json={'name': ''})
        self.assertEqual(res.status_code, 400)
        
        # Reserved name 'All'
        res = self.client.post('/api/groups/create', json={'name': 'All'})
        self.assertEqual(res.status_code, 400)
        
        # Name taken by user
        res = self.client.post('/api/groups/create', json={'name': 'Bob'})
        self.assertEqual(res.status_code, 400)

    def test_call_logging(self):
        """Verify that POST /api/calls/log creates a call log message in the database."""
        # Log in as Alice
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.u1.id
            sess['username'] = 'Alice'
            
        res = self.client.post('/api/calls/log', json={
            'recipient': 'Bob',
            'status': 'completed',
            'duration': 45
        })
        data = res.get_json()
        self.assertTrue(data['success'])
        
        # Verify call log message in database
        db_msg = Message.query.filter_by(msg_type='call_log').first()
        self.assertIsNotNone(db_msg)
        self.assertEqual(db_msg.sender, 'Alice')
        self.assertEqual(db_msg.recipient, 'Bob')
        self.assertEqual(db_msg.content, 'completed')
        self.assertEqual(db_msg.duration, 45)
        
        # Retrieve history as Bob and check if call log message is returned
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.u2.id
            sess['username'] = 'Bob'
            
        res_hist = self.client.get('/api/history?target=Alice')
        data_hist = res_hist.get_json()
        self.assertTrue(data_hist['success'])
        self.assertEqual(len(data_hist['data']['messages']), 1)
        self.assertEqual(data_hist['data']['messages'][0]['type'], 'call_log')
        self.assertEqual(data_hist['data']['messages'][0]['content'], 'completed')
        self.assertEqual(data_hist['data']['messages'][0]['duration'], 45)

    def test_group_history_access(self):
        """Verify that only members can retrieve group chat history and see messages from other members."""
        from models.models import Group, GroupMember
        
        # Create group manually
        g = Group(name='SecretClub', owner_username='Alice')
        db.session.add(g)
        db.session.commit()
        
        # Add members: Alice and Bob
        db.session.add_all([
            GroupMember(group_name='SecretClub', username='Alice'),
            GroupMember(group_name='SecretClub', username='Bob')
        ])
        db.session.commit()
        
        # Alice sends a message to the group
        msg = Message(
            sender='Alice',
            recipient='SecretClub',
            msg_type='text',
            content='Welcome to the club!',
            msg_id='msg-club-1'
        )
        db.session.add(msg)
        db.session.commit()
        
        # Bob tries to load history: should succeed and return Alice's message
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.u2.id
            sess['username'] = 'Bob'
            
        res = self.client.get('/api/history?target=SecretClub')
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(len(data['data']['messages']), 1)
        self.assertEqual(data['data']['messages'][0]['sender'], 'Alice')
        self.assertEqual(data['data']['messages'][0]['content'], 'Welcome to the club!')
        
        # Non-member (e.g. create user Charlie who is not in the group) tries to load history: should fail
        u3 = User(username='Charlie')
        u3.set_password('password123')
        db.session.add(u3)
        db.session.commit()
        
        with self.client.session_transaction() as sess:
            sess['user_id'] = u3.id
            sess['username'] = 'Charlie'
            
        res = self.client.get('/api/history?target=SecretClub')
        self.assertEqual(res.status_code, 403)

    def test_admin_login_credentials(self):
        """Verify that login with admin credentials returns is_admin flag."""
        # Create an admin user in the database
        admin_user = User(username='admin', is_admin=True)
        admin_user.set_password('admin_secure_pass')
        db.session.add(admin_user)
        db.session.commit()

        res = self.client.post('/auth/login', json={
            'username': 'admin',
            'password': 'admin_secure_pass'
        })
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertTrue(data['data']['is_admin'])
        
        # Verify admin session is set
        with self.client.session_transaction() as sess:
            self.assertTrue(sess.get('admin_logged_in'))

    def test_admin_dashboard_unauthorized(self):
        """Verify that accessing admin dashboard without logging in redirects to /login."""
        res = self.client.get('/admin/')
        self.assertEqual(res.status_code, 302)
        self.assertTrue(res.location.endswith('/login'))

    def test_admin_dashboard_authorized(self):
        """Verify that accessing admin dashboard works when logged in as admin."""
        with self.client.session_transaction() as sess:
            sess['admin_logged_in'] = True
            
        res = self.client.get('/admin/')
        self.assertEqual(res.status_code, 200)

    def test_admin_api_stats(self):
        """Verify that the stats API returns expected data metrics."""
        with self.client.session_transaction() as sess:
            sess['admin_logged_in'] = True
            
        res = self.client.get('/admin/api/stats')
        data = res.get_json()
        d = data.get('data', data)
        self.assertTrue(data['success'])
        self.assertEqual(d['total_users'], 2) # Alice & Bob
        self.assertEqual(d['total_messages'], 0)

    def test_admin_api_user_management(self):
        """Verify admin user API: add, edit, and delete."""
        with self.client.session_transaction() as sess:
            sess['admin_logged_in'] = True
            
        # Add new user
        res = self.client.post('/admin/api/users/add', json={
            'username': 'Dave',
            'password': 'davepassword'
        })
        data = res.get_json()
        self.assertTrue(data['success'])
        
        # Verify user exists
        dave = User.query.filter_by(username='Dave').first()
        self.assertIsNotNone(dave)
        
        # Edit user
        res = self.client.post(f'/admin/api/users/edit/{dave.id}', json={
            'username': 'David',
            'status': 'Busy',
            'password': 'newpassword'
        })
        data = res.get_json()
        self.assertTrue(data['success'])
        
        # Verify name changed
        david = User.query.filter_by(username='David').first()
        self.assertIsNotNone(david)
        self.assertEqual(david.status, 'Busy')
        self.assertIsNone(User.query.filter_by(username='Dave').first())
        
        # Delete user
        res = self.client.post(f'/admin/api/users/delete/{david.id}')
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertIsNone(User.query.filter_by(username='David').first())

    def test_chat_history_ordering_and_pagination(self):
        """Verify history fetches the newest messages first, sorted chronologically."""
        # Insert 55 messages from Alice to Bob
        from utils.crypto import encrypt_text
        for idx in range(1, 56):
            msg = Message(
                sender='Alice',
                recipient='Bob',
                msg_type='text',
                content=encrypt_text(f'Msg-{idx}'),
                msg_id=f'msg-uuid-{idx}',
                status='read'
            )
            db.session.add(msg)
        db.session.commit()

        # Alice requests history: target=Bob
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.u1.id
            sess['username'] = 'Alice'

        # Page 1 (offset=0, limit=50): should return the latest 50 messages (6 to 55)
        # and they must be in ascending chronological order (6, 7, ... 55).
        res = self.client.get('/api/history?target=Bob&limit=50&offset=0')
        data = res.get_json()
        self.assertTrue(data['success'])
        
        messages = data['data']['messages']
        self.assertEqual(len(messages), 50)
        self.assertEqual(messages[0]['content'], 'Msg-6')
        self.assertEqual(messages[-1]['content'], 'Msg-55')

        # Page 2 (offset=50, limit=50): should return the remaining oldest 5 messages (1 to 5)
        # in ascending chronological order (1, 2, ... 5).
        res = self.client.get('/api/history?target=Bob&limit=50&offset=50')
        data = res.get_json()
        self.assertTrue(data['success'])
        
        messages_p2 = data['data']['messages']
        self.assertEqual(len(messages_p2), 5)
        self.assertEqual(messages_p2[0]['content'], 'Msg-1')
        self.assertEqual(messages_p2[-1]['content'], 'Msg-5')

    def test_registration_group_name_conflict(self):
        """Verify registration fails if username matches an existing group name."""
        from models.models import Group
        # Create an existing group named "Gamers"
        g = Group(name='Gamers', owner_username='Alice')
        db.session.add(g)
        db.session.commit()

        # Try to register a user named "Gamers"
        res = self.client.post('/auth/register', json={
            'username': 'Gamers',
            'password': 'password123'
        })
        data = res.get_json()
        self.assertFalse(data['success'])

    def test_group_creation_username_conflict(self):
        """Verify group creation fails if name matches a normal user or admin user."""
        # u1 is Alice, u2 is Bob. Admin username is "admin" (seeded in env setup, but let's register one)
        from models.models import User
        admin = User(username='AdminUser', is_admin=True)
        admin.set_password('password123')
        db.session.add(admin)
        db.session.commit()

        with self.client.session_transaction() as sess:
            sess['user_id'] = self.u1.id
            sess['username'] = 'Alice'

        # Conflict with Alice (normal user)
        res = self.client.post('/api/groups/create', json={'name': 'Alice'})
        data = res.get_json()
        self.assertFalse(data['success'])

        # Conflict with AdminUser (admin user)
        res = self.client.post('/api/groups/create', json={'name': 'AdminUser'})
        data = res.get_json()
        self.assertFalse(data['success'])

    def test_group_rename_username_conflict(self):
        """Verify group renaming fails if the new name matches an existing username."""
        from models.models import Group
        # Create group "Alpha"
        g = Group(name='Alpha', owner_username='Alice')
        db.session.add(g)
        db.session.commit()

        with self.client.session_transaction() as sess:
            sess['admin_logged_in'] = True

        # Rename group "Alpha" to "Bob" (which is an existing username)
        res = self.client.post('/admin/api/groups/rename', json={
            'old_name': 'Alpha',
            'new_name': 'Bob'
        })
        data = res.get_json()
        self.assertFalse(data['success'])

    def test_group_delete_for_me(self):
        """Verify that 'Delete for Me' hides a group message only for the deleveler."""
        from models.models import Group, GroupMember, Message, MessageVisibility
        # Setup group Alpha with Alice and Bob
        g = Group(name='Alpha', owner_username='Alice')
        db.session.add(g)
        m1 = GroupMember(group_name='Alpha', username='Alice')
        m2 = GroupMember(group_name='Alpha', username='Bob')
        db.session.add_all([m1, m2])
        
        # Message from Alice to Group Alpha
        msg = Message(
            sender='Alice',
            recipient='Alpha',
            msg_type='text',
            content='Group secret',
            msg_id='msg-group-1',
            status='sent'
        )
        db.session.add(msg)
        db.session.commit()

        # Alice deletes the message "for me"
        v = MessageVisibility(msg_id='msg-group-1', username='Alice')
        db.session.add(v)
        db.session.commit()

        # Alice fetches history for Alpha: should NOT see the message
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.u1.id
            sess['username'] = 'Alice'
        res = self.client.get('/api/history?target=Alpha')
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(len(data['data']['messages']), 0)

        # Bob fetches history for Alpha: should STILL see the message
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.u2.id
            sess['username'] = 'Bob'
        res = self.client.get('/api/history?target=Alpha')
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(len(data['data']['messages']), 1)
        self.assertEqual(data['data']['messages'][0]['msg_id'], 'msg-group-1')

    def test_group_delete_for_everyone(self):
        """Verify that deleting a group message for everyone deletes it permanently."""
        from models.models import Group, GroupMember, Message
        g = Group(name='Alpha', owner_username='Alice')
        db.session.add(g)
        m1 = GroupMember(group_name='Alpha', username='Alice')
        db.session.add(m1)
        
        # Message from Alice to Group Alpha
        msg = Message(
            sender='Alice',
            recipient='Alpha',
            msg_type='text',
            content='Ephemeral group message',
            msg_id='msg-group-2',
            status='sent'
        )
        db.session.add(msg)
        db.session.commit()

        # Alice (sender) deletes the message permanently (Delete for Everyone)
        db_msg = Message.query.filter_by(msg_id='msg-group-2').first()
        db.session.delete(db_msg)
        db.session.commit()

        # Alice fetches history for Alpha: should be empty
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.u1.id
            sess['username'] = 'Alice'
        res = self.client.get('/api/history?target=Alpha')
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(len(data['data']['messages']), 0)

    def test_migration_legacy_delete_flags(self):
        """Verify legacy deleted_by_sender and deleted_by_recipient flags are migrated."""
        from models.models import Message, MessageVisibility
        # Add a message with legacy flags set to True
        msg1 = Message(
            sender='Alice',
            recipient='Bob',
            msg_type='text',
            content='Legacy deleted sender',
            msg_id='msg-legacy-1',
            deleted_by_sender=True
        )
        msg2 = Message(
            sender='Alice',
            recipient='Bob',
            msg_type='text',
            content='Legacy deleted recipient',
            msg_id='msg-legacy-2',
            deleted_by_recipient=True
        )
        db.session.add_all([msg1, msg2])
        db.session.commit()

        # Simulate the migration block manually to check it works
        sender_deletes = Message.query.filter_by(deleted_by_sender=True).all()
        for m in sender_deletes:
            exists = MessageVisibility.query.filter_by(msg_id=m.msg_id, username=m.sender).first()
            if not exists:
                db.session.add(MessageVisibility(msg_id=m.msg_id, username=m.sender))
        
        recipient_deletes = Message.query.filter_by(deleted_by_recipient=True).all()
        for m in recipient_deletes:
            if m.recipient != 'All':
                exists = MessageVisibility.query.filter_by(msg_id=m.msg_id, username=m.recipient).first()
                if not exists:
                    db.session.add(MessageVisibility(msg_id=m.msg_id, username=m.recipient))
        db.session.commit()

        # Verify visibility records exist
        v1 = MessageVisibility.query.filter_by(msg_id='msg-legacy-1', username='Alice').first()
        self.assertIsNotNone(v1)
        v2 = MessageVisibility.query.filter_by(msg_id='msg-legacy-2', username='Bob').first()
        self.assertIsNotNone(v2)

    def test_reaction_routing_security(self):
        """Verify that emitting a reaction with a spoofed 'to' field derives target from DB."""
        from app import socketio
        from models.models import Message
        
        # Insert a private message from Alice to Bob
        msg = Message(
            sender='Alice',
            recipient='Bob',
            msg_type='text',
            content='Private reaction test',
            msg_id='msg-private-reaction-1',
            status='sent'
        )
        db.session.add(msg)
        db.session.commit()

        # Log in as Alice in flask test client
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.u1.id
            sess['username'] = 'Alice'

        # Connect socketio test client for Alice
        alice_socket = socketio.test_client(self.app, flask_test_client=self.client)
        
        # Connect socketio test client for Bob (intended recipient)
        bob_client = self.app.test_client()
        with bob_client.session_transaction() as sess:
            sess['user_id'] = self.u2.id
            sess['username'] = 'Bob'
        bob_socket = socketio.test_client(self.app, flask_test_client=bob_client)
        
        # Connect socketio test client for Charlie (third user, not in the private conversation)
        u3 = User(username='Charlie')
        u3.set_password('password123')
        db.session.add(u3)
        db.session.commit()
        
        charlie_client = self.app.test_client()
        with charlie_client.session_transaction() as sess:
            sess['user_id'] = u3.id
            sess['username'] = 'Charlie'
        charlie_socket = socketio.test_client(self.app, flask_test_client=charlie_client)

        # Clear received events for all sockets
        alice_socket.get_received()
        bob_socket.get_received()
        charlie_socket.get_received()

        # Alice emits a reaction targeting 'All' (malicious spoofing)
        alice_socket.emit('reaction', {
            'msg_id': 'msg-private-reaction-1',
            'emoji': '❤️',
            'to': 'All' # Spoofed target
        })

        charlie_received = charlie_socket.get_received()
        bob_received = bob_socket.get_received()
        
        # Charlie is in room 'All'. If the spoofed 'All' was trusted, Charlie would receive 'reaction_update'.
        # Verify Charlie did NOT receive any reaction updates.
        reaction_updates_charlie = [e for e in charlie_received if e['name'] == 'reaction_update']
        self.assertEqual(len(reaction_updates_charlie), 0)

        # Bob is in the private conversation. Bob SHOULD receive the reaction_update.
        reaction_updates_bob = [e for e in bob_received if e['name'] == 'reaction_update']
        self.assertEqual(len(reaction_updates_bob), 1)
        self.assertEqual(reaction_updates_bob[0]['args'][0]['msg_id'], 'msg-private-reaction-1')

    def test_send_message_database_exception_handling(self):
        """Verify database exception during message send triggers rollback, error ack, and recovers session."""
        from app import socketio
        from unittest.mock import patch
        from sqlalchemy.exc import IntegrityError

        # Log in as Alice
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.u1.id
            sess['username'] = 'Alice'

        alice_socket = socketio.test_client(self.app, flask_test_client=self.client)
        
        # Connect Bob's socket to receive messages
        bob_client = self.app.test_client()
        with bob_client.session_transaction() as sess:
            sess['user_id'] = self.u2.id
            sess['username'] = 'Bob'
        bob_socket = socketio.test_client(self.app, flask_test_client=bob_client)

        # Clear initial connection events
        alice_socket.get_received()
        bob_socket.get_received()

        # Patch db.session.commit to raise an exception once
        with patch('database.database.db.session.commit', side_effect=IntegrityError("mocked constraint fail", "params", None)):
            alice_socket.emit('send_message', {
                'to': 'Bob',
                'type': 'text',
                'content': 'First message (fails)',
                'time': '12:00',
                'msg_id': 'msg-fail-1'
            })

        # Alice should receive a failed acknowledgment
        alice_events = alice_socket.get_received()
        acks = [e for e in alice_events if e['name'] == 'new_message' and e['args'][0].get('type') == 'ack']
        self.assertEqual(len(acks), 1)
        self.assertEqual(acks[0]['args'][0]['status'], 'failed')

        # Bob should NOT receive the message (verify no duplicate/spurious emits)
        bob_events = bob_socket.get_received()
        new_msgs_bob = [e for e in bob_events if e['name'] == 'new_message' and e['args'][0].get('type') == 'text']
        self.assertEqual(len(new_msgs_bob), 0)

        # Verify that the session has rolled back successfully and is fully usable.
        # Send a second message normally (without mock patch)
        alice_socket.emit('send_message', {
            'to': 'Bob',
            'type': 'text',
            'content': 'Second message (succeeds)',
            'time': '12:01',
            'msg_id': 'msg-success-1'
        })

        # Alice should receive a successful ack
        alice_events_2 = alice_socket.get_received()
        acks_2 = [e for e in alice_events_2 if e['name'] == 'new_message' and e['args'][0].get('type') == 'ack']
        self.assertEqual(len(acks_2), 1)
        self.assertEqual(acks_2[0]['args'][0]['status'], 'delivered')

        # Bob should receive the second message successfully (verifies future messages continue working)
        bob_events_2 = bob_socket.get_received()
        new_msgs_bob_2 = [e for e in bob_events_2 if e['name'] == 'new_message' and e['args'][0].get('type') == 'text']
        self.assertEqual(len(new_msgs_bob_2), 1)
        self.assertEqual(new_msgs_bob_2[0]['args'][0]['content'], 'Second message (succeeds)')

    def test_message_read_receipt_logic(self):
        """Verify message_read behavior on backend for private, group, and broadcast messages."""
        from app import socketio
        from models.models import Group, GroupMember, Message

        # 1. Private chat message read receipt
        msg_private = Message(
            sender='Alice',
            recipient='Bob',
            msg_type='text',
            content='Private read test',
            msg_id='msg-private-read-1',
            status='sent'
        )
        # 2. Group chat message read receipt
        g = Group(name='AlphaGroup', owner_username='Alice')
        db.session.add(g)
        m1 = GroupMember(group_name='AlphaGroup', username='Bob')
        db.session.add(m1)
        
        msg_group = Message(
            sender='Alice',
            recipient='AlphaGroup',
            msg_type='text',
            content='Group read test',
            msg_id='msg-group-read-1',
            status='sent'
        )
        # 3. Broadcast message read receipt
        msg_broadcast = Message(
            sender='Alice',
            recipient='All',
            msg_type='text',
            content='Broadcast read test',
            msg_id='msg-broadcast-read-1',
            status='sent'
        )
        db.session.add_all([msg_private, msg_group, msg_broadcast])
        db.session.commit()

        # Connect Bob's socket
        bob_client = self.app.test_client()
        with bob_client.session_transaction() as sess:
            sess['user_id'] = self.u2.id
            sess['username'] = 'Bob'
        bob_socket = socketio.test_client(self.app, flask_test_client=bob_client)
        bob_socket.get_received()

        # Bob emits message_read for private message
        bob_socket.emit('message_read', {'msg_id': 'msg-private-read-1'})
        
        # Verify private message status is now 'read'
        db_private = Message.query.filter_by(msg_id='msg-private-read-1').first()
        self.assertEqual(db_private.status, 'read')

        # Bob emits message_read for group message (should be rejected/ignored on backend)
        bob_socket.emit('message_read', {'msg_id': 'msg-group-read-1'})
        db_group = Message.query.filter_by(msg_id='msg-group-read-1').first()
        self.assertEqual(db_group.status, 'sent') # Stays 'sent'

        # Bob emits message_read for broadcast message (should be rejected/ignored on backend)
        bob_socket.emit('message_read', {'msg_id': 'msg-broadcast-read-1'})
        db_broadcast = Message.query.filter_by(msg_id='msg-broadcast-read-1').first()
        self.assertEqual(db_broadcast.status, 'sent') # Stays 'sent'

if __name__ == '__main__':
    unittest.main()

