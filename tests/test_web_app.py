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
        db_msg = Message.query.filter_by(msg_id='msg-secret').first()
        db_msg.deleted_by_sender = True
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
        db_msg = Message.query.filter_by(msg_id='msg-hello').first()
        db_msg.deleted_by_recipient = True
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

if __name__ == '__main__':
    unittest.main()
