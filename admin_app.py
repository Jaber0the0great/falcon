import sys
import os
import sqlite3
import datetime
import subprocess
import threading

# Matplotlib integration
try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.figure import Figure
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QLabel, QTableWidget, QTableWidgetItem, QHeaderView,
    QLineEdit, QDialog, QFormLayout, QMessageBox, QTabWidget,
    QComboBox, QFrame, QStackedWidget, QGroupBox, QAbstractItemView,
    QMenu, QTextEdit, QDateEdit
)
from PyQt6.QtCore import Qt, QSize, QPoint, QDate
from PyQt6.QtGui import QFont, QColor, QIcon, QPalette, QAction

# Attempt to import werkzeug for password hashing compatibility
try:
    from werkzeug.security import generate_password_hash
except ImportError:
    # Fallback to simple secure hash if werkzeug is not installed
    import hashlib
    def generate_password_hash(password):
        salt = "falcon_salt_12345"
        h = hashlib.sha256((password + salt).encode()).hexdigest()
        return f"sha256$falcon${h}"

# Decryption logic with the shared static Falcon key
try:
    from cryptography.fernet import Fernet
    CHAT_KEY = b'v-9_2fGzS_L0N8oX5x6y_Kz_jZ1M9Wv8m_U3k_QWzY8='
    CIPHER = Fernet(CHAT_KEY)
    def decrypt_text(encrypted_text):
        if not encrypted_text:
            return encrypted_text
        try:
            return CIPHER.decrypt(encrypted_text.encode()).decode()
        except Exception:
            return encrypted_text
except ImportError:
    def decrypt_text(encrypted_text):
        return encrypted_text

class ResetPasswordDialog(QDialog):
    def __init__(self, username, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Reset Password: {username}")
        self.setMinimumWidth(350)
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        form_group = QGroupBox("New Credentials")
        form_layout = QFormLayout(form_group)
        
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText("Enter new password")
        
        form_layout.addRow("New Password:", self.password_input)
        layout.addWidget(form_group)
        
        btn_layout = QHBoxLayout()
        self.save_btn = QPushButton("Reset Password")
        self.save_btn.clicked.connect(self.accept)
        self.save_btn.setStyleSheet("background-color: #f59e0b; color: white; font-weight: bold; border-radius: 6px; padding: 8px;")
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        self.cancel_btn.setStyleSheet("background-color: #475569; color: white; border-radius: 6px; padding: 8px;")
        
        btn_layout.addWidget(self.save_btn)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)
        
    def get_password(self):
        return self.password_input.text()

class AddUserDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add New User")
        self.setMinimumWidth(350)
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # Form Container
        form_group = QGroupBox("User Credentials")
        form_layout = QFormLayout(form_group)
        
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Enter username")
        
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText("Enter password")
        
        form_layout.addRow("Username:", self.username_input)
        form_layout.addRow("Password:", self.password_input)
        
        layout.addWidget(form_group)
        
        # Buttons
        btn_layout = QHBoxLayout()
        self.save_btn = QPushButton("Save User")
        self.save_btn.clicked.connect(self.accept)
        self.save_btn.setStyleSheet("""
            QPushButton {
                background-color: #10b981;
                color: white;
                font-weight: bold;
                border-radius: 6px;
                padding: 8px;
            }
            QPushButton:hover {
                background-color: #059669;
            }
        """)
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #475569;
                color: white;
                border-radius: 6px;
                padding: 8px;
            }
            QPushButton:hover {
                background-color: #334155;
            }
        """)
        
        btn_layout.addWidget(self.save_btn)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)
        
    def get_data(self):
        return self.username_input.text().strip(), self.password_input.text()

class EditUserDialog(QDialog):
    def __init__(self, username, current_status, parent=None):
        super().__init__(parent)
        self.username = username
        self.setWindowTitle(f"Edit User: {username}")
        self.setMinimumWidth(380)
        self.init_ui(current_status)
        
    def init_ui(self, current_status):
        layout = QVBoxLayout(self)
        
        form_group = QGroupBox(f"Profile Info: {self.username}")
        form_layout = QFormLayout(form_group)
        
        self.username_input = QLineEdit(self.username)
        
        self.status_input = QComboBox()
        self.status_input.addItems(["Available", "Offline", "Busy", "In a call"])
        self.status_input.setCurrentText(current_status)
        
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText("(Leave empty to keep current password)")
        
        form_layout.addRow("Username:", self.username_input)
        form_layout.addRow("Status:", self.status_input)
        form_layout.addRow("New Password:", self.password_input)
        
        layout.addWidget(form_group)
        
        # Buttons
        btn_layout = QHBoxLayout()
        self.save_btn = QPushButton("Save Changes")
        self.save_btn.clicked.connect(self.accept)
        self.save_btn.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                color: white;
                font-weight: bold;
                border-radius: 6px;
                padding: 8px;
            }
            QPushButton:hover {
                background-color: #2563eb;
            }
        """)
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #475569;
                color: white;
                border-radius: 6px;
                padding: 8px;
            }
            QPushButton:hover {
                background-color: #334155;
            }
        """)
        
        btn_layout.addWidget(self.save_btn)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)
        
    def get_data(self):
        return (
            self.username_input.text().strip(), 
            self.status_input.currentText(),
            self.password_input.text()
        )

class AdminApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Falcon Chat - Administration Control Panel")
        self.resize(1150, 780)
        self.db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'falcon_web.db')
        self.server_process = None
        self.init_theme()
        self.init_ui()
        self.refresh_all()

    def get_db_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_theme(self):
        # Premium dark slate stylesheet
        self.setStyleSheet("""
            QMainWindow {
                background-color: #0f172a;
            }
            QWidget {
                color: #f8fafc;
                font-family: 'Segoe UI', Inter, Arial;
            }
            QGroupBox {
                font-weight: bold;
                border: 1px solid #334155;
                border-radius: 8px;
                margin-top: 12px;
                padding: 10px;
                background-color: #1e293b;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
            QTableWidget {
                background-color: #1e293b;
                alternate-background-color: #0f172a;
                border: 1px solid #334155;
                gridline-color: #334155;
                border-radius: 8px;
            }
            QTableWidget::item {
                padding: 5px;
            }
            QTableWidget::item:selected {
                background-color: #3b82f6;
                color: white;
            }
            QHeaderView::section {
                background-color: #334155;
                color: #f8fafc;
                padding: 6px;
                border: 1px solid #1e293b;
                font-weight: bold;
            }
            QLineEdit, QComboBox {
                background-color: #0f172a;
                border: 1px solid #475569;
                border-radius: 6px;
                padding: 6px;
                color: #f8fafc;
            }
            QLineEdit:focus, QComboBox:focus {
                border: 1px solid #3b82f6;
            }
            QLabel {
                font-size: 13px;
            }
            QDialog {
                background-color: #0f172a;
            }
        """)

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        
        # Left Sidebar for navigation
        sidebar = QFrame()
        sidebar.setFixedWidth(200)
        sidebar.setStyleSheet("""
            QFrame {
                background-color: #1e293b;
                border-radius: 10px;
                border: 1px solid #334155;
            }
            QPushButton {
                background-color: transparent;
                color: #94a3b8;
                border: none;
                border-radius: 6px;
                padding: 12px;
                text-align: left;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #334155;
                color: #f8fafc;
            }
            QPushButton:checked {
                background-color: #3b82f6;
                color: white;
            }
        """)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(10, 20, 10, 20)
        sidebar_layout.setSpacing(15)
        
        title_label = QLabel("🦅 Falcon Admin")
        title_label.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #3b82f6; border: none; background: transparent; padding-left: 5px;")
        sidebar_layout.addWidget(title_label)
        
        # Divider line
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background-color: #334155; border: none;")
        sidebar_layout.addWidget(line)
        
        self.btn_users = QPushButton("👥 Users")
        self.btn_users.setCheckable(True)
        self.btn_users.setChecked(True)
        
        self.btn_messages = QPushButton("💬 Messages")
        self.btn_messages.setCheckable(True)
        
        self.btn_groups = QPushButton("👥 Groups")
        self.btn_groups.setCheckable(True)
        
        self.btn_media = QPushButton("📁 Media Manager")
        self.btn_media.setCheckable(True)
        
        self.btn_stats = QPushButton("📊 Visual Analytics")
        self.btn_stats.setCheckable(True)
        
        self.btn_server = QPushButton("🎛️ Server & Broadcast")
        self.btn_server.setCheckable(True)
        
        # Navigation logic
        self.nav_group = [self.btn_users, self.btn_messages, self.btn_groups, self.btn_media, self.btn_stats, self.btn_server]
        for btn in self.nav_group:
            btn.clicked.connect(self.on_nav_clicked)
            sidebar_layout.addWidget(btn)
            
        sidebar_layout.addStretch()
        
        # Quick Refresh Button
        self.btn_refresh = QPushButton("🔄 Refresh Data")
        self.btn_refresh.setStyleSheet("""
            background-color: #475569;
            color: white;
            border-radius: 6px;
            padding: 10px;
            font-weight: bold;
        """)
        self.btn_refresh.clicked.connect(self.refresh_all)
        sidebar_layout.addWidget(self.btn_refresh)
        
        main_layout.addWidget(sidebar)
        
        # Right stacked pages
        self.stacked_widget = QStackedWidget()
        
        # PAGE 1: Users Management
        self.page_users = QWidget()
        users_layout = QVBoxLayout(self.page_users)
        users_layout.setContentsMargins(0, 0, 0, 0)
        
        # Top Controls Bar
        users_top_bar = QHBoxLayout()
        self.user_search = QLineEdit()
        self.user_search.setPlaceholderText("🔍 Search users by name...")
        self.user_search.textChanged.connect(self.filter_users_table)
        users_top_bar.addWidget(self.user_search)
        
        self.btn_add_user = QPushButton("➕ Add User")
        self.btn_add_user.setStyleSheet("""
            QPushButton {
                background-color: #10b981;
                color: white;
                font-weight: bold;
                border-radius: 6px;
                padding: 8px 15px;
            }
            QPushButton:hover {
                background-color: #059669;
            }
        """)
        self.btn_add_user.clicked.connect(self.on_add_user_clicked)
        users_top_bar.addWidget(self.btn_add_user)
        users_layout.addLayout(users_top_bar)
        
        # Users Table
        self.users_table = QTableWidget()
        self.users_table.setColumnCount(7)
        self.users_table.setHorizontalHeaderLabels([
            "ID", "Username", "Password Hash (Werkzeug Hashed)", "Status", "Created At", "Last Seen", "Messages"
        ])
        self.users_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.users_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.users_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.users_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.users_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.users_table.verticalHeader().setVisible(False)
        self.users_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.users_table.customContextMenuRequested.connect(self.on_user_context_menu)
        users_layout.addWidget(self.users_table)
        
        # Action Buttons Row
        users_actions_layout = QHBoxLayout()
        
        self.btn_edit_user = QPushButton("✏️ Edit Selected User")
        self.btn_edit_user.setStyleSheet("""
            QPushButton { background-color: #3b82f6; color: white; font-weight: bold; border-radius: 6px; padding: 10px; }
            QPushButton:hover { background-color: #2563eb; }
        """)
        self.btn_edit_user.clicked.connect(self.on_edit_user_clicked)
        
        self.btn_delete_user = QPushButton("🗑️ Delete User & Messages (Cascade)")
        self.btn_delete_user.setStyleSheet("""
            QPushButton { background-color: #ef4444; color: white; font-weight: bold; border-radius: 6px; padding: 10px; }
            QPushButton:hover { background-color: #dc2626; }
        """)
        self.btn_delete_user.clicked.connect(self.on_delete_user_clicked)
        
        users_actions_layout.addWidget(self.btn_edit_user)
        users_actions_layout.addWidget(self.btn_delete_user)
        users_layout.addLayout(users_actions_layout)
        
        self.stacked_widget.addWidget(self.page_users)
        
        # PAGE 2: Messages Browser
        self.page_messages = QWidget()
        msg_layout = QVBoxLayout(self.page_messages)
        msg_layout.setContentsMargins(0, 0, 0, 0)
        
        # Message Filters Bar
        msg_top_bar = QHBoxLayout()
        msg_top_bar.addWidget(QLabel("Filter by User:"))
        
        self.msg_user_filter = QComboBox()
        self.msg_user_filter.currentIndexChanged.connect(self.load_messages)
        msg_top_bar.addWidget(self.msg_user_filter, 1)
        
        self.msg_search = QLineEdit()
        self.msg_search.setPlaceholderText("🔍 Search decrypted message content...")
        self.msg_search.textChanged.connect(self.filter_messages_table)
        msg_top_bar.addWidget(self.msg_search, 2)
        
        # Date Filter
        msg_top_bar.addWidget(QLabel("Since:"))
        self.msg_date_filter = QDateEdit()
        self.msg_date_filter.setCalendarPopup(True)
        self.msg_date_filter.setDate(QDate.currentDate().addDays(-7)) # Default to last 7 days
        self.msg_date_filter.dateChanged.connect(self.load_messages)
        msg_top_bar.addWidget(self.msg_date_filter)
        
        msg_layout.addLayout(msg_top_bar)
        
        # Messages Table
        self.messages_table = QTableWidget()
        self.messages_table.setColumnCount(8)
        self.messages_table.setHorizontalHeaderLabels([
            "ID", "Sender", "Recipient", "Type", "Decrypted Content", "Time", "Status", "Message ID"
        ])
        self.messages_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.messages_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.messages_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.messages_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.messages_table.verticalHeader().setVisible(False)
        self.messages_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.messages_table.customContextMenuRequested.connect(self.on_message_context_menu)
        msg_layout.addWidget(self.messages_table)
        
        # Message Action
        msg_actions = QHBoxLayout()
        self.btn_delete_msg = QPushButton("🗑️ Delete Selected Message")
        self.btn_delete_msg.setStyleSheet("""
            QPushButton { background-color: #ef4444; color: white; font-weight: bold; border-radius: 6px; padding: 10px; }
            QPushButton:hover { background-color: #dc2626; }
        """)
        self.btn_delete_msg.clicked.connect(self.on_delete_message_clicked)
        msg_actions.addWidget(self.btn_delete_msg)
        msg_layout.addLayout(msg_actions)
        
        self.stacked_widget.addWidget(self.page_messages)
        
        # PAGE 3: Groups Management
        self.page_groups = QWidget()
        groups_layout = QVBoxLayout(self.page_groups)
        groups_layout.setContentsMargins(0, 0, 0, 0)
        
        # Groups Table
        self.groups_table = QTableWidget()
        self.groups_table.setColumnCount(4)
        self.groups_table.setHorizontalHeaderLabels(["ID", "Group Name", "Owner", "Created At"])
        self.groups_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.groups_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.groups_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.groups_table.verticalHeader().setVisible(False)
        self.groups_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.groups_table.customContextMenuRequested.connect(self.on_group_context_menu)
        groups_layout.addWidget(self.groups_table)
        
        # Group Actions
        groups_actions = QHBoxLayout()
        self.btn_delete_group = QPushButton("🗑️ Delete Selected Group")
        self.btn_delete_group.setStyleSheet("background-color: #ef4444; color: white; font-weight: bold; border-radius: 6px; padding: 10px;")
        self.btn_delete_group.clicked.connect(self.on_delete_group_clicked)
        groups_actions.addWidget(self.btn_delete_group)
        groups_layout.addLayout(groups_actions)
        
        self.stacked_widget.addWidget(self.page_groups)
        
        # PAGE 4: Media Manager
        self.page_media = QWidget()
        media_layout = QVBoxLayout(self.page_media)
        media_layout.setContentsMargins(0, 0, 0, 0)
        
        # Media Table
        self.media_table = QTableWidget()
        self.media_table.setColumnCount(4)
        self.media_table.setHorizontalHeaderLabels(["Filename", "Size (MB)", "Modified Time", "Type"])
        self.media_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.media_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.media_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.media_table.verticalHeader().setVisible(False)
        media_layout.addWidget(self.media_table)
        
        # Media Actions
        media_actions = QHBoxLayout()
        self.btn_delete_file = QPushButton("🗑️ Delete Selected File")
        self.btn_delete_file.setStyleSheet("background-color: #ef4444; color: white; font-weight: bold; border-radius: 6px; padding: 10px;")
        self.btn_delete_file.clicked.connect(self.on_delete_file_clicked)
        media_actions.addWidget(self.btn_delete_file)
        media_layout.addLayout(media_actions)
        
        self.stacked_widget.addWidget(self.page_media)
        
        # PAGE 5: Platform Statistics
        self.page_stats = QWidget()
        stats_layout = QVBoxLayout(self.page_stats)
        stats_layout.setContentsMargins(0, 0, 0, 0)
        
        stats_group = QGroupBox("System Statistics & Overview")
        stats_grid = QFormLayout(stats_group)
        stats_grid.setVerticalSpacing(20)
        
        self.stat_db_path = QLabel("-")
        self.stat_db_size = QLabel("-")
        self.stat_total_users = QLabel("-")
        self.stat_total_messages = QLabel("-")
        self.stat_text_messages = QLabel("-")
        self.stat_file_messages = QLabel("-")
        self.stat_voice_messages = QLabel("-")
        
        for lbl in [self.stat_db_path, self.stat_db_size, self.stat_total_users, 
                    self.stat_total_messages, self.stat_text_messages, 
                    self.stat_file_messages, self.stat_voice_messages]:
            lbl.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
            lbl.setStyleSheet("color: #3b82f6;")
            
        stats_grid.addRow("SQLite Database Path:", self.stat_db_path)
        stats_grid.addRow("Database File Size:", self.stat_db_size)
        stats_grid.addRow("Total Users Registered:", self.stat_total_users)
        stats_grid.addRow("Total Messages Logged:", self.stat_total_messages)
        stats_grid.addRow("Text Messages:", self.stat_text_messages)
        stats_grid.addRow("File/Image Messages:", self.stat_file_messages)
        stats_grid.addRow("Voice Notes:", self.stat_voice_messages)
        
        stats_layout.addWidget(stats_group)
        
        # Charts Area
        if HAS_MATPLOTLIB:
            self.charts_container = QWidget()
            self.charts_layout = QHBoxLayout(self.charts_container)
            
            self.canvas_status = FigureCanvas(Figure(figsize=(5, 3), facecolor='#1e293b'))
            self.canvas_msgs = FigureCanvas(Figure(figsize=(5, 3), facecolor='#1e293b'))
            
            self.charts_layout.addWidget(self.canvas_status)
            self.charts_layout.addWidget(self.canvas_msgs)
            stats_layout.addWidget(self.charts_container)
        else:
            stats_layout.addWidget(QLabel("Install matplotlib to see visual charts."))
            
        stats_layout.addStretch()
        self.stacked_widget.addWidget(self.page_stats)
        
        # PAGE 6: Server Control & Broadcast
        self.page_server = QWidget()
        server_layout = QVBoxLayout(self.page_server)
        
        # Broadcast Section
        bc_group = QGroupBox("📢 System Broadcast (Web Message)")
        bc_layout = QVBoxLayout(bc_group)
        self.bc_input = QTextEdit()
        self.bc_input.setPlaceholderText("Type a message to all online users...")
        self.bc_input.setMaximumHeight(100)
        self.btn_send_bc = QPushButton("Send Broadcast to All Users")
        self.btn_send_bc.setStyleSheet("background-color: #3b82f6; color: white; font-weight: bold; padding: 10px; border-radius: 6px;")
        self.btn_send_bc.clicked.connect(self.on_send_broadcast)
        bc_layout.addWidget(self.bc_input)
        bc_layout.addWidget(self.btn_send_bc)
        server_layout.addWidget(bc_group)
        
        # Server Control Section
        srv_group = QGroupBox("🎛️ Flask Server Management")
        srv_layout = QVBoxLayout(srv_group)
        
        srv_btns = QHBoxLayout()
        self.btn_start_srv = QPushButton("🚀 Start Server")
        self.btn_start_srv.setStyleSheet("background-color: #10b981; color: white; font-weight: bold; padding: 10px; border-radius: 6px;")
        self.btn_start_srv.clicked.connect(self.start_server)
        
        self.btn_stop_srv = QPushButton("🛑 Stop Server")
        self.btn_stop_srv.setStyleSheet("background-color: #ef4444; color: white; font-weight: bold; padding: 10px; border-radius: 6px;")
        self.btn_stop_srv.clicked.connect(self.stop_server)
        self.btn_stop_srv.setEnabled(False)
        
        srv_btns.addWidget(self.btn_start_srv)
        srv_btns.addWidget(self.btn_stop_srv)
        srv_layout.addLayout(srv_btns)
        
        self.srv_log = QTextEdit()
        self.srv_log.setReadOnly(True)
        self.srv_log.setStyleSheet("background-color: #000; color: #0f0; font-family: 'Courier New';")
        srv_layout.addWidget(QLabel("Server Logs:"))
        srv_layout.addWidget(self.srv_log)
        
        server_layout.addWidget(srv_group)
        self.stacked_widget.addWidget(self.page_server)
        
        main_layout.addWidget(self.stacked_widget, 1)

    def on_nav_clicked(self):
        sender = self.sender()
        for btn in self.nav_group:
            btn.setChecked(btn == sender)
            
        if sender == self.btn_users:
            self.stacked_widget.setCurrentIndex(0)
        elif sender == self.btn_messages:
            self.stacked_widget.setCurrentIndex(1)
        elif sender == self.btn_groups:
            self.stacked_widget.setCurrentIndex(2)
        elif sender == self.btn_media:
            self.stacked_widget.setCurrentIndex(3)
        elif sender == self.btn_stats:
            self.stacked_widget.setCurrentIndex(4)
            self.update_charts()
        elif sender == self.btn_server:
            self.stacked_widget.setCurrentIndex(5)

    def on_user_context_menu(self, pos):
        index = self.users_table.indexAt(pos)
        if not index.isValid():
            return
            
        row = index.row()
        self.users_table.selectRow(row)
        username = self.users_table.item(row, 1).text().replace(" (BANNED)", "")
        is_banned = " (BANNED)" in self.users_table.item(row, 1).text()
        
        menu = QMenu(self)
        
        edit_action = QAction("✏️ Edit Profile", self)
        edit_action.triggered.connect(self.on_edit_user_clicked)
        
        reset_action = QAction("🔑 Reset Password", self)
        reset_action.triggered.connect(self.on_reset_password_clicked)
        
        ban_text = "🔓 Unban User" if is_banned else "🚫 Ban User"
        ban_action = QAction(ban_text, self)
        ban_action.triggered.connect(self.on_toggle_ban_clicked)
        
        delete_action = QAction("🗑️ Delete User (Cascade)", self)
        delete_action.triggered.connect(self.on_delete_user_clicked)
        
        menu.addAction(edit_action)
        menu.addAction(reset_action)
        menu.addSeparator()
        menu.addAction(ban_action)
        menu.addSeparator()
        menu.addAction(delete_action)
        
        menu.exec(self.users_table.viewport().mapToGlobal(pos))

    def on_message_context_menu(self, pos):
        index = self.messages_table.indexAt(pos)
        if not index.isValid():
            return
            
        row = index.row()
        self.messages_table.selectRow(row)
        
        menu = QMenu(self)
        delete_action = QAction("🗑️ Delete Message", self)
        delete_action.triggered.connect(self.on_delete_message_clicked)
        
        menu.addAction(delete_action)
        menu.exec(self.messages_table.viewport().mapToGlobal(pos))

    def on_group_context_menu(self, pos):
        index = self.groups_table.indexAt(pos)
        if not index.isValid():
            return
            
        row = index.row()
        self.groups_table.selectRow(row)
        group_name = self.groups_table.item(row, 1).text()
        
        menu = QMenu(self)
        delete_action = QAction("🗑️ Delete Group", self)
        delete_action.triggered.connect(self.on_delete_group_clicked)
        
        menu.addAction(delete_action)
        menu.exec(self.groups_table.viewport().mapToGlobal(pos))

    def on_reset_password_clicked(self):
        selected = self.users_table.selectedRanges()
        if not selected: return
        row = selected[0].topRow()
        username = self.users_table.item(row, 1).text().replace(" (BANNED)", "")
        
        dialog = ResetPasswordDialog(username, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_pass = dialog.get_password()
            if not new_pass:
                QMessageBox.warning(self, "Error", "Password cannot be empty.")
                return
                
            conn = self.get_db_connection()
            cursor = conn.cursor()
            try:
                p_hash = generate_password_hash(new_pass)
                cursor.execute("UPDATE user SET password_hash = ? WHERE username = ?", (p_hash, username))
                conn.commit()
                QMessageBox.information(self, "Success", f"Password for {username} reset successfully.")
                self.refresh_all()
            except Exception as e:
                QMessageBox.critical(self, "DB Error", str(e))
            finally:
                conn.close()

    def on_toggle_ban_clicked(self):
        selected = self.users_table.selectedRanges()
        if not selected: return
        row = selected[0].topRow()
        username = self.users_table.item(row, 1).text().replace(" (BANNED)", "")
        is_banned = " (BANNED)" in self.users_table.item(row, 1).text()
        
        action = "unban" if is_banned else "ban"
        reply = QMessageBox.question(
            self, "Confirm Action",
            f"Are you sure you want to {action} user '{username}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            conn = self.get_db_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("UPDATE user SET is_banned = ? WHERE username = ?", (not is_banned, username))
                conn.commit()
                QMessageBox.information(self, "Success", f"User {username} has been {action}ned.")
                self.refresh_all()
            except Exception as e:
                QMessageBox.critical(self, "DB Error", str(e))
            finally:
                conn.close()

    def refresh_all(self):
        self.load_users()
        self.load_user_filter()
        self.load_messages()
        self.load_groups()
        self.load_media()
        self.load_stats()

    def load_groups(self):
        if not os.path.exists(self.db_path): return
        self.groups_table.setRowCount(0)
        conn = self.get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM `group` ORDER BY id ASC")
            for i, r in enumerate(cursor.fetchall()):
                self.groups_table.insertRow(i)
                self.groups_table.setItem(i, 0, QTableWidgetItem(str(r['id'])))
                self.groups_table.setItem(i, 1, QTableWidgetItem(r['name']))
                self.groups_table.setItem(i, 2, QTableWidgetItem(r['owner_username']))
                self.groups_table.setItem(i, 3, QTableWidgetItem(str(r['created_at'])))
        except Exception as e:
            print("Error loading groups:", e)
        finally:
            conn.close()

    def on_delete_group_clicked(self):
        selected = self.groups_table.selectedRanges()
        if not selected: return
        row = selected[0].topRow()
        group_name = self.groups_table.item(row, 1).text()
        
        reply = QMessageBox.question(self, "Delete Group", f"Delete group '{group_name}' and all its messages?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            conn = self.get_db_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("DELETE FROM `group` WHERE name = ?", (group_name,))
                cursor.execute("DELETE FROM group_member WHERE group_name = ?", (group_name,))
                cursor.execute("DELETE FROM group_invite WHERE group_name = ?", (group_name,))
                cursor.execute("DELETE FROM group_join_request WHERE group_name = ?", (group_name,))
                cursor.execute("DELETE FROM message WHERE recipient = ?", (group_name,))
                conn.commit()
                self.load_groups()
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))
            finally:
                conn.close()

    def load_media(self):
        upload_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')
        if not os.path.exists(upload_dir): return
        self.media_table.setRowCount(0)
        files = os.listdir(upload_dir)
        for i, f in enumerate(files):
            fpath = os.path.join(upload_dir, f)
            if os.path.isfile(fpath):
                self.media_table.insertRow(self.media_table.rowCount())
                row = self.media_table.rowCount() - 1
                size_mb = os.path.getsize(fpath) / (1024 * 1024)
                mtime = datetime.datetime.fromtimestamp(os.path.getmtime(fpath)).strftime('%Y-%m-%d %H:%M')
                ext = f.split('.')[-1] if '.' in f else 'N/A'
                
                self.media_table.setItem(row, 0, QTableWidgetItem(f))
                self.media_table.setItem(row, 1, QTableWidgetItem(f"{size_mb:.2f}"))
                self.media_table.setItem(row, 2, QTableWidgetItem(mtime))
                self.media_table.setItem(row, 3, QTableWidgetItem(ext.upper()))

    def on_delete_file_clicked(self):
        selected = self.media_table.selectedRanges()
        if not selected: return
        row = selected[0].topRow()
        fname = self.media_table.item(row, 0).text()
        fpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads', fname)
        
        reply = QMessageBox.question(self, "Delete File", f"Permanently delete {fname}?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            try:
                os.remove(fpath)
                self.load_media()
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))

    def load_users(self):
        if not os.path.exists(self.db_path):
            return
            
        self.users_table.setRowCount(0)
        conn = self.get_db_connection()
        cursor = conn.cursor()
        
        try:
            # Query users and calculate sent messages count
            cursor.execute("""
                SELECT u.id, u.username, u.password_hash, u.status, u.created_at, u.last_seen, u.is_banned,
                (SELECT COUNT(*) FROM message WHERE sender = u.username) as sent_count
                FROM user u
                ORDER BY u.id ASC
            """)
            rows = cursor.fetchall()
            
            for i, r in enumerate(rows):
                self.users_table.insertRow(i)
                
                # ID
                self.users_table.setItem(i, 0, QTableWidgetItem(str(r['id'])))
                
                # Username
                u_item = QTableWidgetItem(r['username'])
                if r['is_banned']:
                    u_item.setForeground(QColor("#ef4444"))
                    u_item.setText(r['username'] + " (BANNED)")
                self.users_table.setItem(i, 1, u_item)
                
                # Password hash (Masked or full)
                hash_item = QTableWidgetItem(r['password_hash'])
                hash_item.setFont(QFont("Courier New", 10))
                self.users_table.setItem(i, 2, hash_item)
                
                # Status
                status = r['status']
                status_item = QTableWidgetItem(status)
                if status == "Available" or status == "Online":
                    status_item.setForeground(QColor("#10b981"))
                elif status == "Offline":
                    status_item.setForeground(QColor("#94a3b8"))
                else:
                    status_item.setForeground(QColor("#f59e0b"))
                self.users_table.setItem(i, 3, status_item)
                
                # Created At
                self.users_table.setItem(i, 4, QTableWidgetItem(str(r['created_at'])))
                
                # Last Seen
                self.users_table.setItem(i, 5, QTableWidgetItem(str(r['last_seen'])))
                
                # Message Count
                self.users_table.setItem(i, 6, QTableWidgetItem(f"{r['sent_count']} sent"))
                
        except Exception as e:
            QMessageBox.critical(self, "Database Error", f"Could not load users:\n{e}")
        finally:
            conn.close()

    def filter_users_table(self, text):
        for i in range(self.users_table.rowCount()):
            username = self.users_table.item(i, 1).text().lower()
            if text.lower() in username:
                self.users_table.setRowHidden(i, False)
            else:
                self.users_table.setRowHidden(i, True)

    def load_user_filter(self):
        # Refresh user dropdown list for Messages page
        self.msg_user_filter.blockSignals(True)
        self.msg_user_filter.clear()
        self.msg_user_filter.addItem("All Users", "all")
        
        if os.path.exists(self.db_path):
            conn = self.get_db_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT username FROM user ORDER BY username ASC")
                for r in cursor.fetchall():
                    self.msg_user_filter.addItem(r['username'], r['username'])
            except Exception:
                pass
            finally:
                conn.close()
        self.msg_user_filter.blockSignals(False)

    def load_messages(self):
        if not os.path.exists(self.db_path):
            return
            
        self.messages_table.setRowCount(0)
        
        selected_user = self.msg_user_filter.currentData()
        selected_date = self.msg_date_filter.date().toPyDate().strftime("%Y-%m-%d")
        
        conn = self.get_db_connection()
        cursor = conn.cursor()
        
        try:
            query = "SELECT * FROM message WHERE 1=1"
            params = []
            
            if selected_user != "all":
                query += " AND (sender = ? OR recipient = ?)"
                params.extend([selected_user, selected_user])
                
            # Filter by date if created_at column exists
            try:
                query += " AND (created_at >= ? OR created_at IS NULL)"
                params.append(selected_date + " 00:00:00")
            except Exception:
                pass
                
            query += " ORDER BY id DESC"
            
            cursor.execute(query, params)
                
            rows = cursor.fetchall()
            for i, r in enumerate(rows):
                self.messages_table.insertRow(i)
                
                # ID
                self.messages_table.setItem(i, 0, QTableWidgetItem(str(r['id'])))
                
                # Sender
                self.messages_table.setItem(i, 1, QTableWidgetItem(r['sender']))
                
                # Recipient
                self.messages_table.setItem(i, 2, QTableWidgetItem(r['recipient']))
                
                # Type
                mtype = r['msg_type']
                self.messages_table.setItem(i, 3, QTableWidgetItem(mtype))
                
                # Decrypted Content
                content = r['content']
                if mtype == 'text' and content:
                    decrypted = decrypt_text(content)
                elif mtype == 'file':
                    decrypted = f"[File Attachment] Name: {r['file_name'] or 'N/A'}"
                elif mtype == 'voice':
                    decrypted = f"[Voice Recording] Duration: {r['duration'] or 0}s"
                else:
                    decrypted = content or ""
                    
                self.messages_table.setItem(i, 4, QTableWidgetItem(decrypted))
                
                # Time
                self.messages_table.setItem(i, 5, QTableWidgetItem(r['time']))
                
                # Status
                self.messages_table.setItem(i, 6, QTableWidgetItem(r['status']))
                
                # Msg ID
                self.messages_table.setItem(i, 7, QTableWidgetItem(r['msg_id']))
                
        except Exception as e:
            QMessageBox.critical(self, "Database Error", f"Could not load messages:\n{e}")
        finally:
            conn.close()

    def filter_messages_table(self, text):
        for i in range(self.messages_table.rowCount()):
            content = self.messages_table.item(i, 4).text().lower()
            sender = self.messages_table.item(i, 1).text().lower()
            recipient = self.messages_table.item(i, 2).text().lower()
            
            search_query = text.lower()
            if search_query in content or search_query in sender or search_query in recipient:
                self.messages_table.setRowHidden(i, False)
            else:
                self.messages_table.setRowHidden(i, True)

    def load_stats(self):
        self.stat_db_path.setText(self.db_path)
        
        if os.path.exists(self.db_path):
            size_bytes = os.path.getsize(self.db_path)
            size_mb = size_bytes / (1024 * 1024)
            self.stat_db_size.setText(f"{size_mb:.2f} MB ({size_bytes:,} bytes)")
            
            conn = self.get_db_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT COUNT(*) FROM user")
                self.stat_total_users.setText(str(cursor.fetchone()[0]))
                
                cursor.execute("SELECT COUNT(*) FROM message")
                self.stat_total_messages.setText(str(cursor.fetchone()[0]))
                
                cursor.execute("SELECT COUNT(*) FROM message WHERE msg_type = 'text'")
                self.stat_text_messages.setText(str(cursor.fetchone()[0]))
                
                cursor.execute("SELECT COUNT(*) FROM message WHERE msg_type = 'file'")
                self.stat_file_messages.setText(str(cursor.fetchone()[0]))
                
                cursor.execute("SELECT COUNT(*) FROM message WHERE msg_type = 'voice'")
                self.stat_voice_messages.setText(str(cursor.fetchone()[0]))
            except Exception:
                pass
            finally:
                conn.close()
        else:
            self.stat_db_size.setText("Database File Missing")

    def on_add_user_clicked(self):
        dialog = AddUserDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            username, password = dialog.get_data()
            if not username or not password:
                QMessageBox.warning(self, "Input Error", "Username and Password cannot be empty.")
                return
                
            conn = self.get_db_connection()
            cursor = conn.cursor()
            try:
                # Check for existing user
                cursor.execute("SELECT id FROM user WHERE username = ?", (username,))
                if cursor.fetchone():
                    QMessageBox.warning(self, "Conflict", f"User '{username}' already exists.")
                    return
                
                # Hash the password using Werkzeug compatibility
                p_hash = generate_password_hash(password)
                now_str = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                
                cursor.execute("""
                    INSERT INTO user (username, password_hash, status, created_at, last_seen)
                    VALUES (?, ?, ?, ?, ?)
                """, (username, p_hash, "Offline", now_str, now_str))
                conn.commit()
                QMessageBox.information(self, "Success", f"User '{username}' created successfully!")
                self.refresh_all()
            except Exception as e:
                QMessageBox.critical(self, "Database Error", f"Could not create user:\n{e}")
            finally:
                conn.close()

    def on_edit_user_clicked(self):
        selected_ranges = self.users_table.selectedRanges()
        if not selected_ranges:
            QMessageBox.warning(self, "Selection Required", "Please select a user to edit.")
            return
            
        row = selected_ranges[0].topRow()
        user_id = self.users_table.item(row, 0).text()
        username = self.users_table.item(row, 1).text().replace(" (BANNED)", "")
        status = self.users_table.item(row, 3).text()
        
        dialog = EditUserDialog(username, status, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_username, new_status, new_password = dialog.get_data()
            if not new_username:
                QMessageBox.warning(self, "Input Error", "Username cannot be empty.")
                return
                
            conn = self.get_db_connection()
            cursor = conn.cursor()
            try:
                # Check if renaming username conflicts with another user
                if new_username != username:
                    cursor.execute("SELECT id FROM user WHERE username = ?", (new_username,))
                    if cursor.fetchone():
                        QMessageBox.warning(self, "Conflict", f"User '{new_username}' already exists.")
                        return
                
                # Update base columns
                if new_password:
                    p_hash = generate_password_hash(new_password)
                    cursor.execute("""
                        UPDATE user 
                        SET username = ?, status = ?, password_hash = ?
                        WHERE id = ?
                    """, (new_username, new_status, p_hash, user_id))
                else:
                    cursor.execute("""
                        UPDATE user 
                        SET username = ?, status = ?
                        WHERE id = ?
                    """, (new_username, new_status, user_id))
                
                # Update username references in messages table to keep references aligned
                if new_username != username:
                    cursor.execute("UPDATE message SET sender = ? WHERE sender = ?", (new_username, username))
                    cursor.execute("UPDATE message SET recipient = ? WHERE recipient = ?", (new_username, username))
                    
                conn.commit()
                QMessageBox.information(self, "Success", "User updated successfully!")
                self.refresh_all()
            except Exception as e:
                QMessageBox.critical(self, "Database Error", f"Could not update user:\n{e}")
            finally:
                conn.close()

    def on_delete_user_clicked(self):
        selected_ranges = self.users_table.selectedRanges()
        if not selected_ranges:
            QMessageBox.warning(self, "Selection Required", "Please select a user to delete.")
            return
            
        row = selected_ranges[0].topRow()
        username = self.users_table.item(row, 1).text().replace(" (BANNED)", "")
        
        # Confirm Delete Dialog
        reply = QMessageBox.question(
            self, 
            "Cascade Deletion Confirmation", 
            f"Are you sure you want to delete user '{username}'?\n\n"
            "⚠️ CRITICAL: Deleting this user will permanently delete their account AND all messages sent by or to this user!",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            conn = self.get_db_connection()
            cursor = conn.cursor()
            try:
                # 1. Delete user account
                cursor.execute("DELETE FROM user WHERE username = ?", (username,))
                
                # 2. Delete messages (sent or received by this user)
                cursor.execute("DELETE FROM message WHERE sender = ? OR recipient = ?", (username, username))
                
                conn.commit()
                QMessageBox.information(self, "Deleted", f"User '{username}' and all associated messages deleted successfully!")
                self.refresh_all()
            except Exception as e:
                QMessageBox.critical(self, "Database Error", f"Failed to delete user:\n{e}")
            finally:
                conn.close()

    def on_delete_message_clicked(self):
        selected_ranges = self.messages_table.selectedRanges()
        if not selected_ranges:
            QMessageBox.warning(self, "Selection Required", "Please select a message to delete.")
            return
            
        row = selected_ranges[0].topRow()
        msg_id = self.messages_table.item(row, 0).text()
        sender = self.messages_table.item(row, 1).text()
        recipient = self.messages_table.item(row, 2).text()
        
        reply = QMessageBox.question(
            self,
            "Delete Message Confirmation",
            f"Delete message ID {msg_id} (from {sender} to {recipient}) permanently?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            conn = self.get_db_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("DELETE FROM message WHERE id = ?", (msg_id,))
                conn.commit()
                QMessageBox.information(self, "Deleted", "Message deleted successfully!")
                self.refresh_all()
            except Exception as e:
                QMessageBox.critical(self, "Database Error", f"Failed to delete message:\n{e}")
            finally:
                conn.close()

    # --- Analytics & Server Methods ---
    def update_charts(self):
        if not HAS_MATPLOTLIB: return
        conn = self.get_db_connection()
        cursor = conn.cursor()
        try:
            # 1. User Status Distribution
            cursor.execute("SELECT status, COUNT(*) as count FROM user GROUP BY status")
            status_data = cursor.fetchall()
            labels = [r['status'] for r in status_data]
            values = [r['count'] for r in status_data]
            
            self.canvas_status.figure.clear()
            ax1 = self.canvas_status.figure.add_subplot(111)
            ax1.pie(values, labels=labels, autopct='%1.1f%%', colors=['#3b82f6', '#10b981', '#f59e0b', '#ef4444'])
            ax1.set_title("User Status Distribution", color='white')
            self.canvas_status.figure.tight_layout()
            self.canvas_status.draw()
            
            # 2. Message Type Distribution
            cursor.execute("SELECT msg_type, COUNT(*) as count FROM message GROUP BY msg_type")
            msg_data = cursor.fetchall()
            m_labels = [r['msg_type'] for r in msg_data]
            m_values = [r['count'] for r in msg_data]
            
            self.canvas_msgs.figure.clear()
            ax2 = self.canvas_msgs.figure.add_subplot(111)
            ax2.bar(m_labels, m_values, color='#3b82f6')
            ax2.set_title("Message Type Distribution", color='white')
            ax2.tick_params(colors='white')
            self.canvas_msgs.figure.tight_layout()
            self.canvas_msgs.draw()
            
        except Exception as e:
            print("Chart Update Error:", e)
        finally:
            conn.close()

    def on_send_broadcast(self):
        msg = self.bc_input.toPlainText().strip()
        if not msg: return
        
        conn = self.get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO system_broadcast (message, is_sent) VALUES (?, 0)", (msg,))
            conn.commit()
            self.bc_input.clear()
            QMessageBox.information(self, "Success", "Broadcast message queued. Web server will send it soon.")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
        finally:
            conn.close()

    def start_server(self):
        if self.server_process: return
        try:
            script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app.py')
            self.server_process = subprocess.Popen(
                [sys.executable, script_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            self.btn_start_srv.setEnabled(False)
            self.btn_stop_srv.setEnabled(True)
            self.srv_log.append("--- Server Started ---")
            
            # Start logging thread
            threading.Thread(target=self.consume_server_logs, daemon=True).start()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to start server: {e}")

    def consume_server_logs(self):
        for line in iter(self.server_process.stdout.readline, ''):
            if not self.server_process: break
            self.srv_log.append(line.strip())
        self.server_process.stdout.close()

    def stop_server(self):
        if not self.server_process: return
        self.server_process.terminate()
        self.server_process = None
        self.btn_start_srv.setEnabled(True)
        self.btn_stop_srv.setEnabled(False)
        self.srv_log.append("--- Server Stopped ---")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = AdminApp()
    window.show()
    sys.exit(app.exec())
