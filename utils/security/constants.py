"""Security-related constants: limits, patterns, and standardized error messages."""

import re

# ──────────────────────────────────────────────
# Length Limits
# ──────────────────────────────────────────────

MIN_USERNAME_LENGTH: int = 3
MAX_USERNAME_LENGTH: int = 50

MIN_PASSWORD_LENGTH: int = 6
MAX_PASSWORD_LENGTH: int = 128

MIN_GROUP_NAME_LENGTH: int = 2
MAX_GROUP_NAME_LENGTH: int = 80

MAX_MESSAGE_CONTENT_LENGTH: int = 10000

MAX_FILE_NAME_LENGTH: int = 255

MAX_GROUP_DESCRIPTION_LENGTH: int = 200

MAX_GROUP_MEMBERS_PER_REQUEST: int = 50

# ──────────────────────────────────────────────
# Regex Patterns
# ──────────────────────────────────────────────

USERNAME_PATTERN: re.Pattern = re.compile(r'^[a-zA-Z0-9_\-\.@]+$')

GROUP_NAME_PATTERN: re.Pattern = re.compile(r'^[a-zA-Z0-9_\-\s]+$')

SAFE_FILENAME_PATTERN: re.Pattern = re.compile(r'^[a-zA-Z0-9_\-\.]+$')

HTML_TAG_PATTERN: re.Pattern = re.compile(r'<[^>]*>')

# ──────────────────────────────────────────────
# Standardized Error Messages
# ──────────────────────────────────────────────
# These match the existing API error message strings so that
# migration to the new utilities is transparent to clients.

# -- Authentication --
ERR_AUTH_REQUIRED: str = "Authentication required."
ERR_ADMIN_REQUIRED: str = "Admin access required."
ERR_INVALID_CREDENTIALS: str = "Invalid credentials."
ERR_USER_BANNED: str = "Your account has been banned by the administrator."
ERR_NOT_AUTHENTICATED: str = "Not authenticated."

# -- Username / Password --
ERR_USERNAME_REQUIRED: str = "Username is required."
ERR_PASSWORD_REQUIRED: str = "Password is required."
ERR_USERNAME_EXISTS: str = "Username already exists."
ERR_USERNAME_AND_PASSWORD_REQUIRED: str = "Username and password required"
ERR_INVALID_USERNAME: str = (
    "Username must be 3-50 characters and contain only "
    "letters, numbers, underscores, hyphens, dots, or @."
)
ERR_INVALID_PASSWORD: str = "Password must be at least 6 characters."

# -- Groups --
ERR_INVALID_GROUP_NAME: str = (
    "Group name must be 2-80 characters and contain only "
    "letters, numbers, spaces, underscores, and hyphens."
)
ERR_GROUP_NAME_REQUIRED: str = "Group name is required."
ERR_GROUP_NAME_TAKEN: str = "Name already taken."
ERR_SAME_USERNAME: str = "Invalid group name"
ERR_GROUP_NOT_FOUND: str = "Group not found."
ERR_NOT_GROUP_OWNER: str = "Only the group owner can invite users"
ERR_ALREADY_MEMBER: str = "Already a member"
ERR_REQUEST_PENDING: str = "Request already pending"
ERR_INVITATION_NOT_FOUND: str = "Invitation not found"
ERR_CANNOT_KICK_SELF: str = "Cannot kick yourself"
ERR_OWNER_CANNOT_LEAVE: str = "Owner cannot leave, delete the group instead"
ERR_NOT_A_MEMBER: str = "Not a member"

# -- General --
ERR_NOT_AUTHORIZED: str = "Unauthorized."
ERR_MISSING_PARAMETERS: str = "Missing parameters."
ERR_NOT_FOUND: str = "Not found."
ERR_INVALID_JSON: str = "Invalid JSON in request body."
ERR_MESSAGE_TOO_LONG: str = "Message content exceeds maximum length."
ERR_NO_FILE_PART: str = "No file part"
ERR_NO_SELECTED_FILE: str = "No selected file"
ERR_USER_NOT_FOUND: str = "User not found"

# -- Members list --
ERR_MEMBERS_MUST_BE_LIST: str = "Members must be a list."
ERR_TOO_MANY_MEMBERS: str = "At most 50 members allowed per request."

# ──────────────────────────────────────────────
# Upload / File Validation
# ──────────────────────────────────────────────

MAX_UPLOAD_SIZE: int = 50 * 1024 * 1024  # 50 MB

# Allowlisted file extensions.  Only files whose final extension
# (and all intermediate extension segments) are in this set
# will be accepted.
#
# Categories:
#   Images    .jpg .jpeg .png .gif .bmp .webp .svg .ico
#   Audio     .mp3 .wav .ogg .flac .aac .m4a .wma
#   Video     .mp4 .avi .mkv .mov .wmv .flv .webm
#   Documents .pdf .doc .docx .xls .xlsx .ppt .pptx .txt .rtf .csv .md
#   Archives  .zip .rar .7z .tar .gz
#   Other     .json .xml .yaml .yml .log
ALLOWED_EXTENSIONS: frozenset = frozenset({
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg', '.ico',
    '.mp3', '.wav', '.ogg', '.flac', '.aac', '.m4a', '.wma',
    '.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm',
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.txt', '.rtf', '.csv', '.md',
    '.zip', '.rar', '.7z', '.tar', '.gz',
    '.json', '.xml', '.yaml', '.yml', '.log',
})

# Characters that are never valid in a filename.  Each character
# in this set causes an immediate rejection with a clear error
# rather than being silently stripped.
DANGEROUS_FILENAME_CHARS: frozenset = frozenset(
    # C0 control characters (0x00-0x1F) including null byte
    ''.join(chr(i) for i in range(0x20)) +
    # DEL (0x7F)
    chr(0x7F) +
    # Unicode bidi overrides and directional markers
    '\u202E\u202D\u202B\u202A\u2066\u2067\u2068\u2069\u200F\u200E'
)

# Advisory MIME-type blocklist.  Content-Type is user-controlled
# and MUST NOT be trusted for security decisions.  These types are
# flagged as additional hints; the actual file type is determined
# by the extension allowlist and (eventually) magic-byte inspection.
SUSPICIOUS_MIME_TYPES: frozenset = frozenset({
    'application/x-msdownload',
    'application/x-msdos-program',
    'application/x-msi',
    'application/x-bat',
    'application/x-sh',
    'application/x-csh',
    'application/x-php',
})

# ──────────────────────────────────────────────
# Socket.IO Rate Limits
# ──────────────────────────────────────────────

# Maximum events per second per user for each Socket.IO event.
# Events not listed here are not rate-limited.
# NOTE: In-memory rate limit state is per-process. For multi-worker
# deployments, replace with a shared store (Redis, etc.).
SOCKET_IO_RATE_LIMITS: dict = {
    'send_message': 15,
    'message_read': 15,
    'mark_all_read': 3,
    'reaction': 10,
    'delete_message': 5,
    'webrtc_signaling': 30,
    'status_update': 3,
    'join_room_request': 3,
    'leave_room_request': 3,
    'group_call_start': 3,
    'group_call_join': 10,
    'group_call_signaling': 30,
    'group_call_leave': 3,
    'heartbeat': 2,
}

# ──────────────────────────────────────────────
# Presence / Status
# ──────────────────────────────────────────────

# The only user status values the application recognizes.
# Any value outside this set is silently replaced with the default.
VALID_STATUS_VALUES: frozenset = frozenset({
    'Available', 'Busy', 'Away', 'Invisible', 'Offline',
})

# How often the client sends a heartbeat (seconds).
# Must match the client-side interval.
HEARTBEAT_INTERVAL_SECONDS: int = 60

# How long without a heartbeat before auto-setting to Away.
# 180s = 3 missed heartbeats at 60s interval. Tolerates brief network
# hiccups/backgrounding while still catching idle users within 3 minutes.
AWAY_TIMEOUT_SECONDS: int = 180

# How long without a heartbeat before considering Offline (for broadcast).
# Acts as a stale-connection safety net. Must be > AWAY_TIMEOUT_SECONDS.
# 300s = 5 minutes = 5 missed heartbeats.
PRESENCE_TIMEOUT_SECONDS: int = 300

# Debounce window for presence broadcasts (milliseconds).
# Prevents rapid connect/disconnect/status-change from flooding clients.
PRESENCE_DEBOUNCE_MS: int = 500

# How often the background task checks for timed-out users (seconds).
PRESENCE_CHECK_INTERVAL_SECONDS: int = 30

# ──────────────────────────────────────────────
# User Settings / Username
# ──────────────────────────────────────────────

# Minimum cooldown between username changes (days).
# A user who renames must wait this long before renaming again.
USERNAME_CHANGE_COOLDOWN_DAYS: int = 30

# Usernames that cannot be claimed (case-insensitive comparison).
RESERVED_USERNAMES: frozenset = frozenset({
    'System', 'Server', 'All',
    'admin', 'administrator', 'root',
    'user', 'guest', 'anonymous', 'deleted',
})

# ──────────────────────────────────────────────
# HTTP Rate Limits (requests per window below)
# Every authenticated endpoint has a per-user limit;
# login/register/page routes use per-IP limits.
# Socket.IO rate limits are defined separately
# in SOCKET_IO_RATE_LIMITS (see above).
# ──────────────────────────────────────────────

RATE_LIMIT_WINDOW_SECONDS: int = 60  # default window for all limits below

# -- Authentication (per IP) --
AUTH_LOGIN_LIMIT: int = 5
AUTH_REGISTER_LIMIT: int = 3
AUTH_LOGOUT_LIMIT: int = 10

# -- File Upload (per user) --
UPLOAD_LIMIT: int = 6
DOWNLOAD_LIMIT: int = 30

# -- Messaging & History (per user) --
HISTORY_LIMIT: int = 30
CALL_LOG_LIMIT: int = 10

# -- Group Management (per user) --
GROUP_CREATE_LIMIT: int = 5
GROUP_LIST_LIMIT: int = 30
GROUP_INVITE_LIMIT: int = 10
GROUP_INVITE_RESPOND_LIMIT: int = 10
GROUP_JOIN_REQUEST_LIMIT: int = 10
GROUP_JOIN_REQUESTS_LIST_LIMIT: int = 20
GROUP_JOIN_REQUESTS_RESPOND_LIMIT: int = 10
GROUP_MEMBERS_LIMIT: int = 20
GROUP_KICK_LIMIT: int = 10
GROUP_LEAVE_LIMIT: int = 5
GROUP_DELETE_LIMIT: int = 3

# -- Admin (per admin user) --
ADMIN_PAGE_LIMIT: int = 20
ADMIN_STATS_LIMIT: int = 20
ADMIN_USER_LIST_LIMIT: int = 20
ADMIN_USER_ADD_LIMIT: int = 5
ADMIN_USER_EDIT_LIMIT: int = 10
ADMIN_USER_BAN_LIMIT: int = 10
ADMIN_USER_DELETE_LIMIT: int = 5
ADMIN_GROUP_LIST_LIMIT: int = 20
ADMIN_GROUP_MEMBERS_LIMIT: int = 20
ADMIN_GROUP_RENAME_LIMIT: int = 5
ADMIN_GROUP_KICK_LIMIT: int = 10
ADMIN_GROUP_DELETE_LIMIT: int = 5
ADMIN_CHAT_USERS_LIMIT: int = 20
ADMIN_CHAT_HISTORY_LIMIT: int = 20
ADMIN_CHAT_DELETE_LIMIT: int = 10
ADMIN_MEDIA_LIST_LIMIT: int = 20
ADMIN_MEDIA_DELETE_LIMIT: int = 10
ADMIN_BROADCAST_LIMIT: int = 5

# -- Read-only / Config (per user / per IP) --
USER_INFO_LIMIT: int = 30
WEBRTC_CONFIG_LIMIT: int = 30

# -- Page routes (per IP) --
PAGE_LIMIT: int = 30
REGISTER_PAGE_LIMIT: int = 10

# -- Upload error messages --
ERR_FILE_TOO_LARGE: str = "File too large."
ERR_FILE_TYPE_NOT_ALLOWED: str = "File type not allowed."
ERR_INVALID_FILENAME: str = "Invalid filename"
