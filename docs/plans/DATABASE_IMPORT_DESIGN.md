# Database Import Wizard — Design Document

> **Status:** Draft for review  
> **Phase:** V1.1 Phase 1  
> **Target:** Web-based migration assistant replacing the current CLI-only `utils/migration.py`

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Web Browser                              │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Step 1: Upload  │  Step 2: Validate  │  Step 3: Analyze │  │
│  │  Step 4: Conflict │  Step 5: Backup    │  Step 6: Dry Run │  │
│  │  Step 7: Import   │  Step 8: Verify    │  Step 9: Report  │  │
│  └───────────────────────────────────────────────────────────┘  │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTP (Flask routes)
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Flask Application                             │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌──────────┐ │
│  │ routes/    │  │ utils/     │  │ utils/     │  │ utils/   │ │
│  │ admin.py   │─▶│ migration/ │─▶│ backup.py  │─▶│ audit.py │ │
│  └────────────┘  │ package    │  └────────────┘  └──────────┘ │
│                  └──────┬─────┘                                 │
│                         │                                        │
│                  ┌──────▼──────┐                                 │
│                  │  scanner.py │  — DB detection, schema parse  │
│                  │  importer.py│  — Core import logic           │
│                  │  resolver.py│  — Conflict resolution         │
│                  │  validator.py│ — Schema validation           │
│                  │  printer.py │  — Report generation           │
│                  └─────────────┘                                 │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐                │
│  │ models/    │  │ database/  │  │ config.py  │                │
│  │ models.py  │  │ falcon_web │  │            │                │
│  └────────────┘  │ .db        │  └────────────┘                │
│                  └────────────┘                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Module Responsibilities

| Module | Role |
|--------|------|
| `routes/admin.py` | HTTP endpoints for wizard steps (GET form, POST step data) |
| `templates/admin/migration_wizard.html` | 9-step wizard UI (single-page with step visibility toggles) |
| `utils/migration/__init__.py` | Package init, expose `run_import()` public API |
| `utils/migration/scanner.py` | Open source DB, detect schema, identify Falcon version, return metadata |
| `utils/migration/validator.py` | Validate schema compatibility, check integrity, report issues |
| `utils/migration/resolver.py` | Conflict detection + resolution strategy application |
| `utils/migration/importer.py` | Core import logic, transaction management, rollback |
| `utils/migration/printer.py` | Report generation (JSON summary for web, text for CLI) |
| `utils/backup.py` | Pre-import backup of current database |
| `utils/audit.py` | `log_action()` for import events |
| `scripts/migrations/legacy_import.py` | CLI entry point (wraps importer.py for headless use) |

---

## 2. Database Schema Analysis

### 2.1 Current Schema (falcon_web.db)

**Table: `user`** (7 columns, 4 indexes)

| Column | Type | Constraints | Default | Notes |
|--------|------|-------------|---------|-------|
| `id` | INTEGER | PK, AUTOINCREMENT | | Internal row ID |
| `username` | VARCHAR(80) | UNIQUE, NOT NULL | | Primary user identifier, referenced by all other tables |
| `password_hash` | VARCHAR(256) | NOT NULL | | Werkzeug `generate_password_hash` output |
| `status` | VARCHAR(50) | | `'Available'` | One of: Available, Busy, Offline |
| `created_at` | DATETIME | | `datetime.utcnow` | Account creation timestamp |
| `last_seen` | DATETIME | | `datetime.utcnow` | Last socket disconnect or status change |
| `is_banned` | BOOLEAN | NOT NULL | `0` | If True, user cannot connect via socket |
| `is_admin` | BOOLEAN | NOT NULL | `0` | If True, user can access admin dashboard |

Indexes:
- PK on `id`
- UNIQUE on `username`

**Table: `message`** (17 columns, 4 indexes)

| Column | Type | Constraints | Default | Notes |
|--------|------|-------------|---------|-------|
| `id` | INTEGER | PK, AUTOINCREMENT | | Internal row ID |
| `sender` | VARCHAR(80) | NOT NULL | | Username of sender. Implied FK → user.username |
| `recipient` | VARCHAR(80) | NOT NULL | | Username of recipient, or 'All' for broadcasts |
| `msg_type` | VARCHAR(50) | NOT NULL | | `text`, `file`, `voice`, `call_log`, `system` |
| `content` | TEXT | | | Message text (may be encrypted in future) |
| `time` | VARCHAR(50) | | | ISO-formatted string timestamp |
| `duration` | INTEGER | | | Call duration in seconds (for `call_log` type) |
| `file_name` | VARCHAR(255) | | | Original filename (for `file` type) |
| `raw_data` | TEXT | | | Base64-encoded file data (legacy; new files on disk) |
| `status` | VARCHAR(50) | | `'sent'` | `sent`, `delivered`, `read` |
| `msg_id` | VARCHAR(100) | UNIQUE, NOT NULL | | UUID v4 string |
| `reactions` | TEXT | | `'{}'` | JSON dict of emoji → [usernames] |
| `reply_to` | VARCHAR(80) | | | `msg_id` of the replied-to message |
| `reply_content` | TEXT | | | Preview text of the replied-to message |
| `deleted_by_sender` | BOOLEAN | NOT NULL | `0` | Soft-delete flag for sender |
| `deleted_by_recipient` | BOOLEAN | NOT NULL | `0` | Soft-delete flag for recipient |
| `created_at` | DATETIME | | `datetime.utcnow` | Row creation timestamp |

Indexes:
- PK on `id`
- UNIQUE on `msg_id`
- IX `ix_message_recipient_status_sender` on (`recipient`, `status`, `sender`)
- IX `ix_message_sender_recipient_id` on (`sender`, `recipient`, `id`)

**Table: `group`** (5 columns, 2 indexes)

| Column | Type | Constraints | Default | Notes |
|--------|------|-------------|---------|-------|
| `id` | INTEGER | PK, AUTOINCREMENT | | Internal row ID |
| `name` | VARCHAR(80) | UNIQUE, NOT NULL | | Group chat name |
| `description` | VARCHAR(255) | | | Optional description |
| `owner_username` | VARCHAR(80) | NOT NULL | | Creator's username. Implied FK → user.username |
| `created_at` | DATETIME | | `datetime.utcnow` | |

Indexes:
- PK on `id`
- UNIQUE on `name`

**Table: `group_member`** (4 columns, 1 index)

| Column | Type | Constraints | Default | Notes |
|--------|------|-------------|---------|-------|
| `id` | INTEGER | PK, AUTOINCREMENT | | |
| `group_name` | VARCHAR(80) | NOT NULL | | Implied FK → group.name |
| `username` | VARCHAR(80) | NOT NULL | | Implied FK → user.username |
| `joined_at` | DATETIME | | `datetime.utcnow` | |

Indexes:
- PK on `id`

**Table: `group_invite`** (5 columns, 1 index)

| Column | Type | Constraints | Default | Notes |
|--------|------|-------------|---------|-------|
| `id` | INTEGER | PK, AUTOINCREMENT | | |
| `group_name` | VARCHAR(80) | NOT NULL | | Implied FK → group.name |
| `username` | VARCHAR(80) | NOT NULL | | Implied FK → user.username |
| `status` | VARCHAR(50) | | `'pending'` | `pending`, `accepted`, `rejected` |
| `invited_by` | VARCHAR(80) | NOT NULL | | Implied FK → user.username |

Indexes:
- PK on `id`

**Table: `group_join_request`** (4 columns, 1 index)

| Column | Type | Constraints | Default | Notes |
|--------|------|-------------|---------|-------|
| `id` | INTEGER | PK, AUTOINCREMENT | | |
| `group_name` | VARCHAR(80) | NOT NULL | | Implied FK → group.name |
| `username` | VARCHAR(80) | NOT NULL | | Implied FK → user.username |
| `status` | VARCHAR(50) | | `'pending'` | `pending`, `accepted`, `rejected` |

Indexes:
- PK on `id`

**Table: `system_broadcast`** (4 columns, 1 index)

| Column | Type | Constraints | Default | Notes |
|--------|------|-------------|---------|-------|
| `id` | INTEGER | PK, AUTOINCREMENT | | |
| `message` | TEXT | NOT NULL | | Broadcast text |
| `created_at` | DATETIME | | `datetime.utcnow` | |
| `is_sent` | BOOLEAN | NOT NULL | `0` | Whether the background thread has sent it |

Indexes:
- PK on `id`

### 2.2 Important Notes

- **No foreign key constraints exist.** All relationships are application-level (implied FKs via username/group_name strings). This is by design (simplicity, avoids circular dependency issues).
- **No composite unique constraints.** The only unique constraints are single-column: `user.username`, `group.name`, `message.msg_id`.
- **No CASCADE deletes.** Deleting a user does not automatically delete their messages or group memberships. The app handles this in application code.
- **No triggers, no views, no stored procedures.** Pure table storage.

### 2.3 Correct Import Order

```
1. user            — No dependencies. Must be first.
2. group           — Depends on user (owner_username). Groups created by existing users.
3. system_broadcast— No dependencies. Can be imported anytime after step 1.
4. group_member    — Depends on user + group. Members must exist in both.
5. group_invite    — Depends on user + group. Inviter + invitee + group must exist.
6. group_join_request— Depends on user + group. Requester + group must exist.
7. message         — Depends on user (sender, recipient). Recipient can be 'All' (no user needed).
```

**Why this order:**
- User is the root dependency (referenced by 6 of 7 other tables via username)
- Group references user for owner
- GroupMember, GroupInvite, GroupJoinRequest reference both user and group
- Message references user for sender/recipient but NOT group directly (group is implied by recipient name matching group.name)
- SystemBroadcast has no dependencies

**For legacy import (chat_history.db — messages only):**
- Step 1a: Extract unique usernames from message sender/recipient fields → create User rows
- Step 2: Import Message rows

---

## 3. Wizard Workflow — 9-Step Flow

### Step 1: Upload Database

**UI:**
- File upload input accepting `.db`, `.sqlite`, `.sqlite3` files
- OR server path input (for large databases that shouldn't be uploaded via HTTP)
- OR "Auto-detect legacy DB" button (scans paths like current `utils/migration.py`)
- File size limit: 200MB via HTTP upload, unlimited via server path
- Drag-and-drop support on the upload area
- Progress bar showing upload progress

**Backend:**
- `POST /admin/migration/upload` — receives file, saves to temp dir (`/tmp/falcon_import/` or `imports/`), returns `upload_id`
- `POST /admin/migration/set_path` — accepts server-side path, validates it exists and is readable
- Temp files auto-cleaned after 24 hours (background task)

**Validation before proceeding:**
- File is a valid SQLite database (check magic bytes: `SQLite format 3\x00`)
- File is readable and not corrupted (run `PRAGMA integrity_check`)
- Store `upload_id` in session for subsequent steps

### Step 2: Validate

**UI:**
- Spinner + "Validating database..." with progress messages
- Report card showing:
  - ✅ Valid SQLite database
  - ✅ Compatible schema (or ❌ with details)
  - ✅ Falcon version detected (or ℹ️ Unknown — legacy DB)
  - ✅ Database integrity check passed (or ❌ with error details)
- If validation fails: show detailed error message with "Download validation report" button
- "Back" button to re-upload a different file

**Backend:**
- `POST /admin/migration/validate` — runs all validation checks:

| Check | Method | Action on Failure |
|-------|--------|-------------------|
| SQLite magic bytes | Read first 16 bytes, verify `SQLite format 3\x00` | Reject: "Not a valid SQLite database" |
| `PRAGMA integrity_check` | Run integrity check | Reject: "Database integrity check failed: [result]" |
| Schema detection | `scanner.py` reads `sqlite_master` tables | If no known tables found: "Unknown schema format" |
| Column compatibility | `validator.py` checks required columns per table | Warn: "Missing columns: [list]" |
| Version detection | Check for `schema_version` table or known column sets | Informational: "Detected as Falcon vX.Y" or "Unknown version" |

**Schema fingerprinting — detect which version of Falcon produced the DB:**

| Fingerprint | Likely Version |
|-------------|----------------|
| Has `user`, `message`, `group`, `group_member`, `group_invite`, `group_join_request`, `system_broadcast` tables with all columns | Falcon V1.0+ (current) |
| Has `user`, `message` tables but no group tables | Partial V1.0 (before group feature) |
| Has only `messages` table with `sender`, `recipient`, `content`, `time`, `msg_type`, `msg_id` columns | Legacy `chat_history.db` (pre-V1.0) |
| Has only `messages` table with fewer columns | Very old legacy version |

### Step 3: Analyze

**UI:**
- Dashboard-style summary of source database:

```
┌────────────────────────────────────────────────┐
│  Database Analysis                             │
│                                                │
│  File: chat_history.db                     │
│  Format: SQLite 3.x                           │
│  Version: Legacy (pre-V1.0)                   │
│  Size: 2.4 MB                                 │
│                                                │
│  ┌──────┬──────────┬────────────────────────┐ │
│  │ Table│  Records │ Details                │ │
│  ├──────┼──────────┼────────────────────────┤ │
│  │ user │ 12       │ (extracted from msgs)  │ │
│  │ msg  │ 1,247    │ text: 1,100, file: 87  │ │
│  │      │          │ voice: 60              │ │
│  │ group│ 0        │ (not in legacy schema) │ │
│  │ ...  │ ...      │                        │ │
│  └──────┴──────────┴────────────────────────┘ │
│                                                │
│  Message types: text(88%), file(7%), voice(5%) │
│  Date range: 2024-01-15 — 2025-06-30           │
│  Total users in messages: 12                   │
│  Admin users: 0                                │
└────────────────────────────────────────────────┘
```

- Download full analysis as JSON button
- "Continue" button proceeds to conflict detection

**Backend:**
- `POST /admin/migration/analyze` — reads source DB, returns comprehensive metadata:

```json
{
  "upload_id": "abc123",
  "file_path": "/tmp/falcon_import/abc123.db",
  "file_size_bytes": 2516582,
  "format": "SQLite 3.x",
  "version_detected": "legacy",
  "tables": {
    "user": { "records": 0, "columns": [], "note": "No user table — will extract from messages" },
    "message": { "records": 1247, "columns": ["sender", "recipient", "content", "time", "msg_type", "msg_id", "file_name", "raw_data", "status", "reactions", "reply_to", "reply_content", "duration"] },
    "group": { "records": 0, "columns": [], "note": "Table not found" },
    "group_member": { "records": 0, "note": "Table not found" },
    "group_invite": { "records": 0, "note": "Table not found" },
    "group_join_request": { "records": 0, "note": "Table not found" },
    "system_broadcast": { "records": 0, "note": "Table not found" }
  },
  "extracted_users": ["alice", "bob", "charlie"],
  "message_types": { "text": 1100, "file": 87, "voice": 60 },
  "date_range": { "earliest": "2024-01-15T10:30:00", "latest": "2025-06-30T14:22:00" },
  "total_file_size_mb": 45.2
}
```

### Step 4: Conflict Detection

**UI:**
- Table showing each entity type with conflict status:

```
┌──────────┬─────────┬──────────────────────────────────────┐
│ Entity   │ Count   │ Conflicts                            │
├──────────┼─────────┼──────────────────────────────────────┤
│ Users    │ 12     │ ⚠️ 3 exist: alice, bob, charlie       │
│ Messages │ 1,247  │ ✅ No conflicts                       │
│ Groups   │ 0      │ ℹ️ Not in source                     │
│ ...      │         │                                      │
└──────────┴─────────┴──────────────────────────────────────┘
```

- For each conflict type, a resolution dropdown per entity OR a bulk action:

| Conflict Type | Detection Method | Resolution Options |
|--------------|-----------------|-------------------|
| Username exists | `SELECT username FROM user` | **Skip** (keep existing, skip import), **Merge** (keep existing, but add messages to them), **Rename** (prefix `imported_` + username) |
| Group name exists | `SELECT name FROM group` | **Skip**, **Rename** (append ` (imported)`), **Merge** (add members to existing group) |
| Message msg_id exists | `SELECT msg_id FROM message` | **Skip** (keep existing, skip import), **Replace** (overwrite existing message) |
| Group name matches a username (reserved name conflict) | Check if group name = any username | **Rename** (prefix group name), **Skip** group |

- Default action: **Skip** for all conflicts (safest)

**Backend:**
- `POST /admin/migration/detect_conflicts` — scans source records against current DB
- Returns conflict report:

```json
{
  "conflicts": {
    "user": {
      "existing_usernames": ["alice", "bob", "charlie"],
      "total_in_source": 12,
      "conflict_count": 3
    },
    "message": {
      "existing_msg_ids": [],
      "total_in_source": 1247,
      "conflict_count": 0
    },
    "group": { "total_in_source": 0, "conflict_count": 0 }
  }
}
```

- `POST /admin/migration/apply_resolution` — stores user's resolution choices in session:
```json
{
  "resolutions": {
    "user": { "default": "skip", "overrides": { "alice": "merge", "bob": "merge" } },
    "message": { "default": "skip" },
    "group": { "default": "skip" }
  }
}
```

### Step 5: Backup

**UI:**
- "A backup of your current database will be created before importing."
- Show backup details: filename, estimated size, timestamp
- "Create Backup" button
- Progress bar during backup creation
- On success: ✅ Backup created at `backups/pre_import_20260704_143022.db`
- [x] I understand this backup will be used if I need to undo the import.

**Backend:**
- `POST /admin/migration/backup` — calls `utils/backup.py:create_backup()` with:
  - Prefix: `pre_import_`
  - Timestamp: current UTC time
  - Type: `manual`
- Stores `backup_path` in session
- If backup fails: abort import (cannot proceed without backup)
- The backup uses SQLite's backup API (same as `encrypt_migration.py`'s pattern)

### Step 6: Dry Run

**UI:**
- Simulation report:

```
┌────────────────────────────────────────────────────┐
│  Dry Run — No changes made to your database        │
│                                                    │
│  📋 Import Summary                                 │
│  ┌──────────────────────┬────────┬────────┬──────┐ │
│  │ Entity               │ Import │ Skip   │ Total│ │
│  ├──────────────────────┼────────┼────────┼──────┤ │
│  │ Users (new)          │ 9      │ 3      │ 12   │ │
│  │ Messages             │ 1,247  │ 0      │ 1,247│ │
│  │ Groups               │ 0      │ 0      │ 0    │ │
│  └──────────────────────┴────────┴────────┴──────┘ │
│                                                    │
│  ⚠️ Warnings:                                      │
│  • 3 users already exist (will be skipped)        │
│  • No group data in source database               │
│  • 87 file messages reference files not on disk   │
│                                                    │
│  Estimated execution time: ~2 seconds              │
│                                                    │
│  ┌────────────────────────────────────────────────┐│
│  │ [Back]  [Download Dry Run Report]  [Import]   ││
│  └────────────────────────────────────────────────┘│
```

**Backend:**
- `POST /admin/migration/dry_run` — performs a simulated import:
  1. Opens source DB (read-only)
  2. Walks through every record applying resolution rules
  3. Counts what would be imported, skipped, replaced
  4. Does NOT write anything to the database
  5. Returns full simulation report

```json
{
  "will_import": { "user": 9, "message": 1247, "group": 0 },
  "will_skip": { "user": 3, "message": 0, "group": 0 },
  "will_replace": {},
  "warnings": ["3 users already exist (will be skipped)", "87 file messages reference files not on disk"],
  "estimated_duration_seconds": 2,
  "import_order": ["user", "group", "system_broadcast", "group_member", "group_invite", "group_join_request", "message"],
  "transactions_planned": 14
}
```

### Step 7: Import

**UI:**
- Progress screen with live updates:

```
┌────────────────────────────────────────────────┐
│  Importing... 45%                              │
│  ███████████████░░░░░░░░░░░░░░░░               │
│                                                │
│  ✅ Users imported: 9/9                        │
│  🔄 Messages importing: 562/1,247             │
│  ⏳ Groups: skipped (no source data)          │
│                                                │
│  Elapsed: 1.2s | Est. remaining: 1.5s         │
│  Do not close this window.                    │
└────────────────────────────────────────────────┘
```

- If error occurs: show error with "Rollback" button

**Backend:**
- `POST /admin/migration/execute` — executes the import:

**Transaction strategy:**
- Each entity type is imported in its own transaction
- Total 7 transactions (one per table)
- Within a transaction, records are batch-inserted (BATCH_SIZE=500)
- If any transaction fails:
  1. Roll back that transaction
  2. STOP further imports
  3. Report partial failure
  4. Offer to rollback via pre-import backup (Step 5)

```
Transaction 1: INSERT INTO user (...) VALUES (...)   ── 9 rows
Transaction 2: INSERT INTO group (...) VALUES (...)  ── 0 rows (skipped)
Transaction 3: INSERT INTO system_broadcast (...)    ── 0 rows (skipped)
Transaction 4: INSERT INTO group_member (...)        ── 0 rows (skipped)
Transaction 5: INSERT INTO group_invite (...)        ── 0 rows (skipped)
Transaction 6: INSERT INTO group_join_request (...)  ── 0 rows (skipped)
Transaction 7: INSERT INTO message (...) VALUES (...) ── 500+500+247 rows
```

**Why separate transactions (not one big transaction):**
- If messages fail (largest table), users are still imported (partial progress)
- Avoids locking the database for the entire duration
- Each transaction is small and fast
- The pre-import backup is the safety net for full rollback

**Concurrency handling:**
- Import sets a flag in the session: `import_in_progress = True`
- If another import is already running, reject with "Import already in progress"
- Admin can view the app during import but should avoid writes

### Step 8: Verification

**UI:**
- Verification running animation
- Progress: Checking referential integrity...

```
┌────────────────────────────────────────────────┐
│  Verification Results                          │
│                                                │
│  ✅ Users imported: 9                          │
│     • All users queryable by username          │
│     • All users have password_hash set         │
│  ✅ Messages imported: 1,247                   │
│     • All messages have valid sender/recipient │
│     • All msg_id values are unique             │
│  ✅ Referential integrity: PASSED              │
│     • Every message.sender → user.username     │
│     • Every message.recipient → user.username  │
│     • No orphaned records                      │
│                                                │
│  📊 Row counts match expected: YES             │
└────────────────────────────────────────────────┘
```

**Backend:**
- `POST /admin/migration/verify` — runs post-import checks:

1. **Row count check**: Compare actual `SELECT COUNT(*)` against expected numbers
2. **Referential integrity**: Check every implied FK resolves:
   - `message.sender` IN `SELECT username FROM user` (exclude 'All')
   - `message.recipient` IN `SELECT username FROM user` (exclude 'All')
   - `group.owner_username` IN `SELECT username FROM user`
   - `group_member.group_name` IN `SELECT name FROM group`
   - `group_member.username` IN `SELECT username FROM user`
   - `group_invite.group_name` IN `SELECT name FROM group`
   - `group_invite.username` IN `SELECT username FROM user`
   - `group_join_request.group_name` IN `SELECT name FROM group`
   - `group_join_request.username` IN `SELECT username FROM user`
3. **Unique constraint check**: Verify no duplicates in `user.username`, `group.name`, `message.msg_id`
4. **Message sender/recipient sanity**: No messages where `sender = recipient` (self-messages; allowed? currently possible in app — warn but don't fail)

### Step 9: Report

**UI:**

```
┌──────────────────────────────────────────────────────┐
│  ✅ Import Complete                                  │
│                                                      │
│  ┌──────────────────────────────────────────────┐   │
│  │ Import Report — 2026-07-04 14:30:22 UTC      │   │
│  ├──────────────────────────────────────────────┤   │
│  │ Source file:    chat_history.db               │   │
│  │ Source version: Legacy (pre-V1.0)             │   │
│  │ Duration:       3.2 seconds                   │   │
│  │ Status:         ✓ Successful                  │   │
│  │ Backup:         pre_import_20260704_143022.db │   │
│  ├──────────────────────────────────────────────┤   │
│  │ Table           │ Imported │ Skipped │ Total │   │
│  │─────────────────┼──────────┼─────────┼───────┤   │
│  │ User            │ 9        │ 3       │ 12    │   │
│  │ Group           │ 0        │ 0       │ 0     │   │
│  │ SystemBroadcast │ 0        │ 0       │ 0     │   │
│  │ GroupMember     │ 0        │ 0       │ 0     │   │
│  │ GroupInvite     │ 0        │ 0       │ 0     │   │
│  │ GroupJoinRequest│ 0        │ 0       │ 0     │   │
│  │ Message         │ 1,247    │ 0       │ 1,247 │   │
│  ├──────────────────────────────────────────────┤   │
│  │ Warnings:                                     │   │
│  │ • 87 file messages reference files not on disk│   │
│  └──────────────────────────────────────────────┘   │
│                                                      │
│  [Download Full Report (JSON)]  [Download Log]      │
│  [View Import Log in Admin]    [Done]               │
└──────────────────────────────────────────────────────┘
```

**Backend:**
- `POST /admin/migration/report` — generates and stores the report:

```json
{
  "import_id": "IMP-20260704-001",
  "timestamp": "2026-07-04T14:30:22Z",
  "source_file": "chat_history.db",
  "source_version": "legacy",
  "duration_seconds": 3.2,
  "status": "success",
  "backup_file": "pre_import_20260704_143022.db",
  "results": {
    "user": { "imported": 9, "skipped": 3, "replaced": 0, "total": 12 },
    "message": { "imported": 1247, "skipped": 0, "replaced": 0, "total": 1247 },
    "group": { "imported": 0, "skipped": 0, "replaced": 0, "total": 0 },
    "system_broadcast": { "imported": 0, "skipped": 0, "total": 0 },
    "group_member": { "imported": 0, "skipped": 0, "total": 0 },
    "group_invite": { "imported": 0, "skipped": 0, "total": 0 },
    "group_join_request": { "imported": 0, "skipped": 0, "total": 0 }
  },
  "warnings": ["87 file messages reference files not on disk"],
  "errors": []
}
```

- Report is saved to `logs/imports/IMP-20260704-001.json` for future reference
- Audit log entry created via `utils/audit.py`

---

## 4. Conflict Resolution Strategies

### 4.1 Username Conflicts

**Detection:** Source user.username matches existing user.username (case-insensitive)

| Strategy | Behavior | Use Case |
|----------|----------|----------|
| **Skip** | Skip creating this user. Messages from/to this user are attributed to the existing user. | Safest default. |
| **Merge** | Skip creating this user (they already exist). All their messages are imported with their existing username. | When the same person is re-importing their own data. |
| **Rename** | Create a new user with modified name: `alice` → `alice_imported` (or `alice_2` if `_imported` also exists). Messages use the new name. | When the username collision is accidental. |

### 4.2 Group Name Conflicts

**Detection:** Source group.name matches existing group.name (case-insensitive)

| Strategy | Behavior | Use Case |
|----------|----------|----------|
| **Skip** | Skip importing this group entirely. | Default. |
| **Rename** | Import group with modified name: `General` → `General (imported)`. | When the group is distinct and needs to exist alongside the current one. |
| **Merge** | Add imported members to the existing group. Skip group creation. | When the group represents the same chat. |

### 4.3 Message ID Conflicts

**Detection:** Source message.msg_id matches existing message.msg_id

| Strategy | Behavior | Use Case |
|----------|----------|----------|
| **Skip** | Skip importing this message. Keep existing. | Default. Safest. |
| **Replace** | Delete existing message, insert source message. | When the source is the authoritative copy. |

### 4.4 Media File Conflicts

Legacy DB stores file data in `raw_data` (base64 in the message row). Current app stores files on disk in `static/uploads/`.

| Strategy | Behavior | Use Case |
|----------|----------|----------|
| **Skip files** | Import message without file data (text-only). | Default. Files are usually old/irrelevant. |
| **Extract files** | Decode base64 from `raw_data`, write to `static/uploads/` with new unique filename, update `file_name` in message. | When preserving file attachments is important. |

### 4.5 Broadcast Conflicts

**Detection:** Source system_broadcast.id matches existing (unlikely since PKs are autoincrement). Check by message content + created_at.

| Strategy | Behavior |
|----------|----------|
| **Skip** | Skip importing duplicates. |
| **Import all** | Import all broadcasts (may create duplicates). |

---

## 5. Rollback Strategy

### 5.1 Automatic Rollback (within a transaction)

If a batch INSERT fails (e.g., constraint violation):

```python
try:
    db.session.execute(batch_insert)
    db.session.commit()
except IntegrityError:
    db.session.rollback()
    logger.error("Batch failed, rolling back transaction")
    raise ImportError("Failed to insert batch at record N")
```

- Only the current transaction is rolled back
- Previous transactions (already committed) remain
- User is notified of partial failure
- Full recovery requires the pre-import backup (Step 5)

### 5.2 Full Rollback (via backup)

- **Triggered by:** User clicks "Rollback Import" on failure/report page
- **Action:**
  1. Stop the app (or set maintenance mode)
  2. Rename current DB to `falcon_web.db.failed_import_<timestamp>`
  3. Copy backup file to `database/falcon_web.db`
  4. Resume the app
- **Result:** Database is in the exact state before the import
- **Alternative (in-app, if import was small):** Reverse the import by deleting imported records:
  - Track all inserted PKs during import
  - `DELETE FROM user WHERE id IN (...imported_ids...)`
  - `DELETE FROM message WHERE id IN (...imported_ids...)`
  - This is risky with concurrent access; backup restore is safer

### 5.3 Partial Rollback

If only some tables were imported (e.g., users imported but messages failed):
- Option A: Restore from backup (lose users too)
- Option B: Continue by fixing message import and re-running
- Option C: Manually delete users (via admin panel)

**Recommendation:** Always offer backup restore. For advanced users, offer partial rollback.

---

## 6. Transaction Strategy

| Transaction | Table(s) | Batch Size | Rollback Scope |
|-------------|----------|-----------|----------------|
| TX1 | user | 500 | User inserts only |
| TX2 | group | 100 | Group inserts only |
| TX3 | system_broadcast | 500 | Broadcast inserts only |
| TX4 | group_member | 500 | Member inserts only |
| TX5 | group_invite | 500 | Invite inserts only |
| TX6 | group_join_request | 500 | Request inserts only |
| TX7 | message | 500 | Message inserts only |

**Why batch at 500:**
- SQLite performance degrades with very large transactions (memory for rollback journal)
- 500 rows per batch keeps each transaction under ~1MB of journal
- Balance between speed (fewer commits) and safety (smaller rollback scope)

**Transaction isolation:** SERIALIZABLE (SQLite default)

**Overall flow:**
```
BEGIN TX1 → batch insert users → COMMIT
BEGIN TX2 → batch insert groups → COMMIT
BEGIN TX3 → batch insert broadcasts → COMMIT
BEGIN TX4 → batch insert members → COMMIT
BEGIN TX5 → batch insert invites → COMMIT
BEGIN TX6 → batch insert join requests → COMMIT
BEGIN TX7 → batch insert messages → COMMIT
```

If TX7 fails:
- TX1–TX6 are already committed
- Rollback TX7
- Report: "7/7 tables processed. Messages failed. Run 'Rollback' to undo all changes."

---

## 7. Backup Strategy

### 7.1 Pre-Import Backup

- **Method:** SQLite backup API (`backup_database()` from `encrypt_migration.py`)
- **File naming:** `pre_import_<YYYYMMDD_HHMMSS>.db`
- **Directory:** `backups/`
- **Encryption:** If `ENCRYPTION_KEY` is set, encrypt the backup; store initialization vector alongside
- **Verification:** After backup completes, verify file size > 0 and `PRAGMA quick_check` passes on the backup

### 7.2 Backup Lifecycle

- Pre-import backups are retained indefinitely (they represent restore points)
- Admin can delete old pre-import backups from the backup management UI
- A warning is shown: "This backup is associated with import IMP-20260704-001. Deleting it will make that import irreversible."

### 7.3 Additional Safety

- Before any write operation, the import writes a `.import_lock` file to `database/`
- If the app crashes during import, on next startup it detects the lock file and alerts admin to check database integrity
- Lock file contains: upload_id, start_time, last_transaction

---

## 8. Security Considerations

### 8.1 Malicious SQLite Files

| Threat | Detection | Mitigation |
|--------|-----------|------------|
| File is not a SQLite DB | Check magic bytes `SQLite format 3\x00` | Reject at upload step |
| File contains SQLite exploits (extension loading, shell commands) | Check `PRAGMA compile_options` for `ENABLE_LOAD_EXTENSION` | SQLite Python driver does not enable extension loading by default |
| File is a zip/renamed executable | Magic byte check catches this | Reject |
| File triggers billion laughs (XML bomb via SQLite FTS?) | SQLite FTS is not enabled in standard builds | Low risk; not applicable |
| Zip bomb disguised as SQLite (extremely high compression ratio) | Enforce max file size (200MB upload, unlimited server path) | Upload: 200MB hard cap. Server path: warn if >1GB |
| File with malicious trigger/view | Check `sqlite_master` for triggers, views, virtual tables | Warn if found; skip importing triggers/views |
| Corrupted database causes crash | `PRAGMA integrity_check` before processing | Run in subprocess with timeout; catch segfaults |

### 8.2 Version Mismatch

| Scenario | Detection | Action |
|----------|-----------|--------|
| Source has additional columns not in current schema | Schema comparison in validator | Warn. Import only known columns. Skip unknown columns. |
| Source is missing required columns | Schema comparison | Warn. Use defaults for missing columns. Skip table if critical column missing. |
| Source has different column types (e.g., REAL instead of INTEGER) | Column type comparison | Log. SQLite is type-flexible; cast during import. |
| Source has different constraints (e.g., no NOT NULL) | Constraint inspection | Log. Apply current app's constraints during insert. |

### 8.3 Corrupted Database

| Issue | Detection | Action |
|-------|-----------|--------|
| Database file is truncated | `PRAGMA page_count` returns fewer pages than header claims | Reject with message: "Database appears truncated. Try running `PRAGMA integrity_check` manually." |
| Index corruption | `PRAGMA integrity_check` returns errors | Reject. "Database has integrity errors. Please repair first: `sqlite3 source.db 'PRAGMA integrity_check;'"` |
| Malformed UTF-8 in text fields | Attempt `.encode('utf-8')` on each text field | Warn per-field. Replace invalid bytes with U+FFFD (replacement character). |

### 8.4 Duplicate Primary Keys

| Issue | Detection | Resolution |
|-------|-----------|------------|
| Source user.id matches existing user.id | Not relevant — we do NOT import `id` column (it's autoincrement) | N/A. Always let SQLite assign new IDs. |
| Source message.msg_id matches existing | Conflict detection step | Skip or Replace per user's resolution choice |
| Source group.name matches existing | Conflict detection step | Skip or Rename per user's choice |
| Two source records with same msg_id | Detect during dry run | Warn. Import first occurrence, skip duplicate. |

### 8.5 Missing Tables

| Scenario | Detection | Action |
|----------|-----------|--------|
| No tables at all | `sqlite_master` query returns 0 user tables | Reject: "Empty database — no tables found." |
| Only `messages` table exists | Schema fingerprinting | Treat as legacy import. Extract users from messages. |
| Missing `user` table | Schema comparison | Legacy mode: extract users from messages. Standard mode: reject — cannot proceed without user table. |
| Missing `group` table | Schema comparison | Warn: groups not available. Import users, messages, broadcasts only. |

### 8.6 Missing Columns

| Scenario | Detection | Action |
|----------|-----------|--------|
| Message table missing `msg_id` column | Column inspection | Generate UUIDs during import |
| Message table missing `created_at` column | Column inspection | Use current timestamp or parse `time` column |
| User table missing `password_hash` column | Column inspection | Set default password (from `MIGRATION_DEFAULT_PASSWORD` env var) |
| User table missing `is_banned` column | Column inspection | Default to `False` |

### 8.7 Invalid Foreign Keys (implied)

| Issue | Detection | Resolution |
|-------|-----------|------------|
| message.sender references non-existent user | Referential integrity check | Fall back to 'Unknown' user or skip message. Warn. |
| group.owner_username references non-existent user | Referential integrity check | Create the owner user with default password. Warn. |
| group_member.username references non-existent user | Referential integrity check | Create member user with default password. Warn. Or skip membership. |
| group_member.group_name references non-existent group | Referential integrity check | Skip membership record. Warn. |

### 8.8 Race Conditions

| Issue | Mitigation |
|-------|------------|
| User registers during import with same username | Lock user table during import (writes blocked). Re-run conflict detection after lock. |
| Admin deletes user during import | Lock all tables during import (writes blocked). Or use SERIALIZABLE isolation. |
| Message arrives during import | New messages use autoincrement IDs and new msg_ids — no conflict. Accept concurrent writes during import (they don't interfere). |

**Strategy:** Use a short write lock on `user` and `group` tables during import (these are small). Allow concurrent writes to `message` (it uses pre-conflict-checked msg_ids).

---

## 9. Testing Strategy

### 9.1 Unit Tests

| Test | File | What to Verify |
|------|------|----------------|
| Scanner detects all 7 tables | `test_scanner.py` | Correct table list, column list, row counts |
| Scanner detects legacy DB | `test_scanner.py` | Identifies as `legacy` version, extracts users from messages |
| Scanner rejects non-SQLite file | `test_scanner.py` | Error: "Not a valid SQLite database" |
| Scanner rejects corrupted DB | `test_scanner.py` | Error: "Database integrity check failed" |
| Validator accepts complete schema | `test_validator.py` | No errors, all tables validated |
| Validator detects missing column | `test_validator.py` | Warning: "message table missing column 'msg_id'" |
| Resolver detects username conflict | `test_resolver.py` | 3 conflicts detected |
| Resolver applies skip strategy | `test_resolver.py` | Conflicting records marked as skip |
| Resolver applies rename strategy | `test_resolver.py` | Conflicting records have modified names |
| Importer imports clean DB | `test_importer.py` | All records inserted, correct row counts |
| Importer handles duplicate msg_id | `test_importer.py` | Skip mode: duplicate skipped. Replace mode: duplicate overwritten. |
| Importer rolls back on constraint violation | `test_importer.py` | Failed batch rolled back, no partial inserts |

### 9.2 Integration Tests

| Test | What to Verify |
|------|----------------|
| Full 9-step wizard | Complete import matches expected result |
| Legacy import (messages only) | Users extracted, messages imported, no groups |
| Import with conflicts (skip) | Conflicting records skipped, rest imported |
| Import with conflicts (rename) | Conflicting records imported with modified names |
| Import empty source DB | No records imported, no errors |
| Import with all resolution strategies | Each strategy correctly applied to its assigned records |
| Backup created before import | Backup file exists and integrity check passes |
| Rollback via backup restore | Database returns to pre-import state |
| Verification step catches referential errors | Orphaned records detected |

### 9.3 Edge Case Tests

| Test | Expected Behavior |
|------|-------------------|
| Upload .txt file instead of .db | Step 2 rejects: "Not a valid SQLite database" |
| Upload 0-byte file | Step 1 rejects or Step 2 rejects |
| Upload file with 500k messages | Step 7 imports in batches of 500, completes successfully |
| Upload file with special characters in usernames | Handled gracefully (usernames are VARCHAR(80), validated) |
| Import while another import is running | Step 7 rejects: "Import already in progress" |
| Browser tab closed during Step 7 | Import continues server-side. Admin can check import status via resume endpoint |
| Source file deleted before Step 7 | Step 7 fails: "Source file not found. Please re-upload." |

### 9.4 Legacy `chat_history.db` Specific Tests

| Test | Expected Behavior |
|------|-------------------|
| Legacy DB with 100 users (extracted) | 100 users created, 12 from messages |
| Legacy DB with no msg_id column | UUIDs generated for all messages |
| Legacy DB with empty sender/recipient | Those messages skipped, warning logged |
| Legacy DB with only 'Server' sender | 'Server' messages skipped (no user created) |
| Legacy DB with file messages | Files referenced but not on disk → warning in report |
| Legacy DB with Unicode content | Content imported correctly, no encoding errors |

---

## 10. File Layout

```
utils/migration/
├── __init__.py          # Package init, exposes run_import(source_path, resolutions, ...)
├── scanner.py           # DB detection, schema discovery, version fingerprinting
├── validator.py         # Schema validation, integrity checks, column compatibility
├── resolver.py          # Conflict detection + resolution strategy application
├── importer.py          # Core import logic, batch inserts, transaction management
└── printer.py           # Report generation (JSON summary, human-readable text)

scripts/migrations/
└── legacy_import.py     # CLI entry point wrapping utils/migration/ package

routes/
└── admin.py             # New wizard routes (unchanged existing routes)

templates/admin/
└── migration_wizard.html  # 9-step wizard single-page template
```

### CLI Entry Point (Legacy Support)

```bash
# New usage (V1.1+):
python -m scripts.migrations.legacy_import --source chat_history.db

# Options:
#   --source PATH       Path to source database (required)
#   --password STR      Default password for imported users (default: env MIGRATION_DEFAULT_PASSWORD)
#   --conflict STR      Conflict strategy: skip, merge, rename (default: skip)
#   --dry-run           Simulate import without writing
#   --backup            Create backup before import
#   --report PATH       Save import report to file (default: stdout)
#   --batch-size N      Records per transaction batch (default: 500)

# Old usage (deprecated, prints warning):
python utils/migration.py
# → "WARNING: This CLI is deprecated. Use 'python -m scripts.migrations.legacy_import' instead."
```

---

## 11. UI Component Hierarchy

```
migration_wizard.html
├── Step Indicator Bar (Step 1–9, current highlighted, completed checkmarked)
├── Step 1: Upload
│   ├── File upload area (drag-drop + click)
│   ├── Server path input
│   └── Auto-detect legacy button
├── Step 2: Validate
│   ├── Validation progress (animated)
│   └── Validation result cards (pass/fail/warn)
├── Step 3: Analyze
│   ├── Database summary card
│   ├── Table breakdown table
│   └── Download analysis JSON button
├── Step 4: Conflict Detection
│   ├── Conflict summary per entity
│   ├── Resolution dropdown per conflict group
│   └── Default resolution selector
├── Step 5: Backup
│   ├── Backup details card
│   ├── Progress bar
│   └── Confirmation checkbox
├── Step 6: Dry Run
│   ├── Simulation summary table
│   ├── Warnings list
│   └── Download dry run report button
├── Step 7: Import
│   ├── Live progress per table
│   ├── Overall progress bar
│   └── Elapsed time
├── Step 8: Verification
│   ├── Verification progress
│   ├── Integrity check results
│   └── Row count comparison
└── Step 9: Report
    ├── Final summary table
    ├── Warnings and errors
    ├── Download buttons (JSON, log)
    └── Done / Rollback buttons
```

---

## 12. Data Flow Diagram

```
Source DB                    Temp Storage              Target DB (falcon_web.db)
──────────                  ────────────              ─────────────────────────
chat_history.db ──Upload──▶ /tmp/falcon_import/       database/falcon_web.db
(legacy or                    ├── <upload_id>.db          (current running DB)
 Falcon 1.0)                  └── <upload_id>.meta
         │                                                 ▲
         │  Step 2: scanner.py reads sqlite_master         │
         │  Step 3: scanner.py counts rows                 │
         │  Step 4: resolver.py compares with target       │
         │  Step 5: backup.py creates backup ──────────────┤
         │  Step 6: importer.py dry run                    │
         │  Step 7: importer.py batch INSERT ──────────────┘
         │  Step 8: validator.py verify
         ▼
    Cleaned up after 24h
```

---

## 13. Error Handling Matrix

| Error | Where Detected | User Visible Message | System Action |
|-------|---------------|---------------------|---------------|
| File is not SQLite | Step 2 | "The selected file is not a valid SQLite database." | Log error, allow re-upload |
| Corrupted database | Step 2 | "Database integrity check failed. Please repair and try again." | Log details, allow re-upload |
| Unknown schema | Step 2 | "Unable to identify the database schema. This may be from an incompatible application." | Log schema details, allow re-upload |
| No write permission on Target DB | Step 5 | "Cannot write to the database. Check file permissions." | Log, abort |
| Backup creation failed | Step 5 | "Failed to create backup. Aborting import." | Log, abort |
| Constraint violation during import | Step 7 | "Error importing records: [detail]. The failed batch has been rolled back." | Log, rollback batch, offer rollback |
| Source file deleted before Step 7 | Step 7 | "Source file not found. Please start over." | Log, abort, clean temp files |
| Server crashes during Step 7 | S7 | On next startup: "An import was interrupted. Check database integrity." | .import_lock detection, log |
| Out of disk space | Step 7 | "Insufficient disk space. Free up space and try again." | Log, rollback, abort |
| Timeout (import > 5 minutes) | Step 7 | Extend timeout, or process in background with status polling | Async task with progress endpoint |

---

## 14. Async Import (for Large Databases)

For databases with >50k records (import takes >5 seconds), use a background thread:

1. User submits Step 7 → returns immediately with `import_id` and status "processing"
2. Frontend polls `GET /admin/migration/status/<import_id>` every 1 second
3. Backend runs import in a background thread (via `threading.Thread`)
4. Status endpoint returns JSON:
   ```json
   {
     "status": "in_progress",
     "progress_pct": 45,
     "current_step": "Importing messages (562/1247)",
     "elapsed_seconds": 1.2
   }
   ```
5. On completion, frontend navigates to Step 8

**Why not Celery/Redis:** The app has no message broker. A simple background thread is sufficient for an admin-only feature that runs infrequently.

---

## 15. Extended Capabilities

The following 7 capabilities extend the base 9-step wizard design. They are integrated into the relevant steps below.

### 15.1 Import Preview

**What:** Before import, show a comprehensive per-entity breakdown of what will happen.

**Integration:**
- New dedicated **Step 3.5: Import Preview** between Analyze and Conflict Detection
- OR merged into Step 6 (Dry Run) which already shows simulated results

**Preview table format:**

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Import Preview — chat_history.db                                       │
│                                                                         │
│  ┌──────────┬──────────┬──────────┬─────────┬─────────┬────────┬──────┐│
│  │ Entity   │ Existing │ Incoming │ Import  │ Skip    │ Merge  │Renam ││
│  ├──────────┼──────────┼──────────┼─────────┼─────────┼────────┼──────┤│
│  │ Users    │ 15       │ 12       │ 9       │ 3       │ 0      │ 0    ││
│  │ Messages │ 4,283    │ 1,247    │ 1,247   │ 0       │ 0      │ 0    ││
│  │ Groups   │ 3        │ 0        │ 0       │ 0       │ 0      │ 0    ││
│  │ Members  │ 12       │ 0        │ 0       │ 0       │ 0      │ 0    ││
│  │ Invites  │ 5        │ 0        │ 0       │ 0       │ 0      │ 0    ││
│  │ Requests │ 2        │ 0        │ 0       │ 0       │ 0      │ 0    ││
│  │ Broadcast│ 8        │ 0        │ 0       │ 0       │ 0      │ 0    ││
│  └──────────┴──────────┴──────────┴─────────┴─────────┴────────┴──────┘│
│                                                                         │
│  Existing = records currently in target database                         │
│  Incoming = records available in source                                 │
│  Import/Skip/Merge/Rename = result of current conflict resolution       │
└─────────────────────────────────────────────────────────────────────────┘
```

**Backend:** The preview is generated by `resolver.py` after conflict detection and resolution choices have been applied. It's a read-only computation:

```python
def generate_preview(source_conn, target_session, resolutions):
    """Return a per-entity breakdown of what will be imported, skipped, etc."""
    return {
        "user": {
            "existing": User.query.count(),
            "incoming": count_source_rows(source_conn, "user") or len(extract_users(source_conn)),
            "will_import": ...,
            "will_skip": ...,
            "will_merge": ...,
            "will_rename": ...
        },
        # ... same for message, group, group_member, group_invite, group_join_request, system_broadcast
    }
```

### 15.2 Per-Entity Selection

**What:** Admin can uncheck entities they don't want to import. Unchecked entities are skipped entirely.

**Integration:**
- Step 4 (Conflict Detection) renders per-entity toggle cards:

```
☑ Users       — 12 users (3 conflicts)
☑ Messages    — 1,247 messages (0 conflicts)
☐ Groups      — 0 groups (no source data)
☐ Invites     — 0 invites (no source data)
☐ Media Files — 87 files (extract from raw_data: 45.2 MB)
☐ Broadcasts  — 0 broadcasts (no source data)
```

**Backend:** The `resolutions` payload is extended with an `enabled` field per entity:

```json
{
  "enabled": {
    "user": true,
    "message": true,
    "group": false,
    "group_member": false,
    "group_invite": false,
    "group_join_request": false,
    "system_broadcast": false,
    "media": true
  },
  "resolutions": {
    "user": { "default": "skip", "overrides": {} },
    "message": { "default": "skip" },
    "media": { "default": "skip_files" }
  }
}
```

**Import order respects disabled entities:** If `group` is disabled, `group_member`, `group_invite`, and `group_join_request` are also disabled automatically (they depend on `group`). The UI warns about this cascade.

### 15.3 Per-Entity Conflict Policies

**What:** Each entity type gets its own conflict resolution dropdown with type-appropriate options.

**Integration:**
- Step 4 (Conflict Detection) shows a per-entity policy selector:

```
┌──────────┬─────────────────────────────────────────────────────┐
│ Entity   │ Conflict Policy                                     │
├──────────┼─────────────────────────────────────────────────────┤
│ Users    │ [Skip duplicates ▼]  [Replace]  [Rename]            │
│ Messages │ [Skip duplicates ▼]  [Import all]                    │
│ Groups   │ [Merge ▼]  [Rename]  [Skip]                         │
│ Media    │ [Skip files ▼]  [Extract files]                     │
│ Broadcast│ [Skip duplicates ▼]  [Import all]                    │
│ Members  │ [Import all ▼]  [Skip conflicts]                    │
│ Invites  │ [Import all ▼]  [Skip conflicts]                    │
│ Requests │ [Import all ▼]  [Skip conflicts]                    │
└──────────┴─────────────────────────────────────────────────────┘
```

**Policy definitions per entity:**

| Entity | Policy Options | Effect |
|--------|---------------|--------|
| `user` | **Skip** — keep existing, skip import | Default |
| | **Replace** — update existing user's password_hash, status, is_admin | Destructive |
| | **Rename** — create new user with modified name | Safe |
| `message` | **Skip duplicates** — skip if msg_id exists | Default |
| | **Import all** — import even if msg_id exists (rename msg_id with UUID) | Safe |
| | **Replace** — overwrite existing message with same msg_id | Destructive |
| `group` | **Skip** — skip importing groups | Default |
| | **Rename** — rename conflicting groups | Safe |
| | **Merge** — add members to existing group, skip creation | Safe |
| `group_member` | **Import all** — no conflict check (no unique constraint) | Default |
| | **Skip conflicts** — skip if same group_name+username exists | Safe |
| `group_invite` | **Import all** — no conflict check | Default |
| | **Skip conflicts** — skip if same group_name+username+status exists | Safe |
| `group_join_request` | **Import all** — no conflict check | Default |
| | **Skip conflicts** — skip if same group_name+username+status exists | Safe |
| `system_broadcast` | **Skip duplicates** — skip if same message+created_at | Default |
| | **Import all** — import all | Safe |
| `media` | **Skip files** — import message without file data | Default |
| | **Extract files** — decode base64, write to disk, link in message | Destructive (disk writes) |

**Backend:** The `resolutions` payload now supports per-entity policies:

```json
{
  "policies": {
    "user": "skip",
    "message": "skip_duplicates",
    "group": "merge",
    "group_member": "import_all",
    "group_invite": "import_all",
    "group_join_request": "import_all",
    "system_broadcast": "skip_duplicates",
    "media": "skip_files"
  },
  "enabled": { ... },
  "resolutions": { ... }
}
```

### 15.4 Visual Progress Indicator

**What:** Live progress bars during import with per-entity granularity.

**Integration:**
- Step 7 (Import) renders:

```
┌────────────────────────────────────────────────────────────────────┐
│  Importing...  73%                                                 │
│  ████████████████████████████████░░░░░░░░░░░░                      │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ Table           │ Progress          │ Status   │ Count      │   │
│  ├─────────────────────────────────────────────────────────────┤   │
│  │ ✅ Users        │ ████████████████  │ Done     │ 9/9        │   │
│  │ ⏳ Groups       │ (skipped)         │ Skipped  │ 0          │   │
│  │ ✅ Broadcasts   │ ████████████████  │ Done     │ 0/0        │   │
│  │ ⏳ Members      │ (skipped)         │ Skipped  │ 0          │   │
│  │ ⏳ Invites      │ (skipped)         │ Skipped  │ 0          │   │
│  │ ⏳ Requests     │ (skipped)         │ Skipped  │ 0          │   │
│  │ 🔄 Messages     │ ████████░░░░░░░░  │ 562/1247 │ Importing  │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  Elapsed: 1.2s │ Est. remaining: 1.5s │ [Cancel Import]           │
└────────────────────────────────────────────────────────────────────┘
```

**Backend implementation:**

The importer runs in a background thread (for imports > 5s) or synchronously (for small imports). Progress is tracked in a shared dictionary keyed by `import_id`:

```python
# utils/migration/importer.py

import threading

import_progress = {}  # import_id -> { "status": str, "progress_pct": int, "tables": {...}, "cancel": bool }

def run_import(source_path, resolutions, policies, enabled, import_id, app):
    """Run import in background thread, updating import_progress dict."""
    def _worker():
        import_progress[import_id] = {
            "status": "in_progress",
            "progress_pct": 0,
            "tables": { t: {"status": "pending", "current": 0, "total": 0} for t in IMPORT_ORDER },
            "cancel": False,
            "error": None
        }
        try:
            with app.app_context():
                for table in IMPORT_ORDER:
                    if import_progress[import_id]["cancel"]:
                        import_progress[import_id]["status"] = "cancelled"
                        return
                    # ... import logic, updating import_progress[import_id] ...
            import_progress[import_id]["status"] = "completed"
        except Exception as e:
            import_progress[import_id]["status"] = "failed"
            import_progress[import_id]["error"] = str(e)

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    return import_id
```

**Status endpoint for polling:**

```python
@api_bp.route('/admin/migration/status/<import_id>', methods=['GET'])
def get_import_status(import_id):
    progress = importer.import_progress.get(import_id)
    if not progress:
        return error_response("IMPORT_NOT_FOUND", "Import not found", 404)
    return success_response(progress)
```

### 15.5 Cancelling Long-Running Imports

**What:** Admin can cancel an in-progress import. The cancellation is graceful (finishes current batch, then stops).

**Integration:**
- Step 7 (Import) shows a **Cancel Import** button
- Available only while status is `in_progress`
- After clicking: confirm dialog "Are you sure? Partially imported data will remain."

**Backend:**

```python
@api_bp.route('/admin/migration/cancel/<import_id>', methods=['POST'])
def cancel_import(import_id):
    progress = importer.import_progress.get(import_id)
    if not progress or progress["status"] != "in_progress":
        return error_response("CANCEL_INVALID", "Import is not in progress", 400)
    progress["cancel"] = True
    return success_response({"message": "Cancellation requested. Finishing current batch..."})
```

**Cancellation behavior:**
1. Worker thread checks `import_progress[import_id]["cancel"]` before starting each table
2. If `cancel=True`, skip remaining tables
3. Current batch completes (atomic) then stops
4. Status becomes `cancelled`
5. Report shows partial results: "Cancelled at user's request. 3/7 tables imported."
6. Admin can rollback via pre-import backup or keep the partial import

**Safety:** Cancellation does NOT roll back already-committed transactions. This is by design — partial imports may be salvageable. Full rollback requires the pre-import backup.

### 15.6 Automatic Rollback on Failure

**What:** If any transaction fails, the system automatically rolls back the failed batch and offers full rollback options.

**Integration:**
- Replaces the manual "Rollback" button approach in the original design
- Automatic within the transaction scope; full-import rollback still requires user confirmation

**Backend flow:**

```python
def import_table(table_name, rows, policies, table_progress, cancel_flag):
    """Import a single table in batches. Auto-rollback on failure."""
    BATCH_SIZE = 500
    total = len(rows)
    table_progress["total"] = total
    table_progress["status"] = "in_progress"

    for i in range(0, total, BATCH_SIZE):
        if cancel_flag and cancel_flag():
            return 0  # cancelled

        batch = rows[i:i + BATCH_SIZE]
        try:
            # Transform and insert
            insert_batch(table_name, batch, policies)
            db.session.commit()
            table_progress["current"] = min(i + BATCH_SIZE, total)
        except IntegrityError as e:
            db.session.rollback()
            logger.error("Batch %d failed for %s: %s", i // BATCH_SIZE, table_name, e)
            table_progress["status"] = "failed"
            table_progress["error"] = str(e)
            raise ImportBatchError(table_name, i, str(e))  # propagates up
        except Exception as e:
            db.session.rollback()
            logger.error("Unexpected error in batch %d for %s: %s", i // BATCH_SIZE, table_name, e)
            table_progress["status"] = "failed"
            raise ImportBatchError(table_name, i, str(e))

    table_progress["status"] = "completed"
    return total
```

**Full-import failure handler:**

```python
def _worker():
    try:
        for table in IMPORT_ORDER:
            if cancel_flag and cancel_flag():
                progress["status"] = "cancelled"
                return
            import_table(table, ...)
        progress["status"] = "completed"
    except ImportBatchError as e:
        progress["status"] = "failed"
        progress["error"] = str(e)
        progress["auto_rollback_available"] = True
        # Automatic partial rollback is NOT done here (committed tables stay committed)
        # But we set a flag so the UI offers full rollback via backup
        return
```

**After failure, the UI shows:**

```
┌────────────────────────────────────────────────────────────┐
│  ❌ Import Failed                                           │
│                                                             │
│  Messages batch #2 failed: UNIQUE constraint failed          │
│                                                             │
│  6/7 tables completed. Messages were partially imported.     │
│                                                             │
│  ┌──────────────────────┐  ┌─────────────────────────────┐ │
│  │ Rollback (via backup)│  │ Keep partial import         │ │
│  └──────────────────────┘  └─────────────────────────────┘ │
└────────────────────────────────────────────────────────────┘
```

### 15.7 Final Import Summary

**What:** A comprehensive, downloadable, storable import report generated at the end.

**Integration:**
- Replaces/extends Step 9 (Report) with a richer summary
- Stored to `logs/imports/` for future reference
- Accessible from the maintenance dashboard (Phase 7)

**Summary format:**

```json
{
  "import_id": "IMP-20260704-001",
  "timestamp": "2026-07-04T14:30:22Z",
  "source": {
    "filename": "chat_history.db",
    "size_bytes": 2516582,
    "version_detected": "legacy",
    "tables_found": ["messages"]
  },
  "target": {
    "database": "database/falcon_web.db",
    "version": "1.1.0",
    "pre_import_backup": "pre_import_20260704_143022.db"
  },
  "configuration": {
    "enabled_entities": ["user", "message"],
    "policies": {
      "user": "skip",
      "message": "skip_duplicates",
      "media": "skip_files"
    },
    "batch_size": 500
  },
  "results": {
    "status": "completed",
    "duration_seconds": 3.2,
    "cancelled": false,
    "entities": {
      "user": {
        "existing_before": 15,
        "incoming": 12,
        "imported": 9,
        "skipped": 3,
        "merged": 0,
        "renamed": 0,
        "replaced": 0,
        "failed": 0,
        "status": "completed"
      },
      "message": {
        "existing_before": 4283,
        "incoming": 1247,
        "imported": 1247,
        "skipped": 0,
        "merged": 0,
        "renamed": 0,
        "replaced": 0,
        "failed": 0,
        "status": "completed"
      }
    },
    "totals": {
      "imported": 1256,
      "skipped": 3,
      "failed": 0
    }
  },
  "warnings": [
    "87 file messages reference files not on disk (media policy: skip_files)"
  ],
  "errors": []
}
```

**Storage:**
- Saved to `logs/imports/IMP-YYYYMMDD-NNN.json`
- Logged in `AuditLog` (Phase 7 integration)
- Downloadable from Step 9 UI as JSON or human-readable text

**Audit log entry:**
```python
log_action(
    actor=session['username'],
    action='import',
    target_type='system',
    target_id='IMP-20260704-001',
    details=json.dumps({"source": "chat_history.db", "imported": 1256, "skipped": 3, "status": "completed"}),
    success=True
)
```

---

## 16. Implementation Phases (Backend Infrastructure)

These phases build the backend infrastructure **only**. No UI (templates/routes) until all backend modules are complete and tested.

### Phase 1a — Package Structure & Scanner

**Files:**
- `utils/migration/__init__.py`
- `utils/migration/scanner.py`
- `tests/test_scanner.py`

**Goal:** Open any SQLite file, detect schema, fingerprint version, return metadata.

**Deliverables:**
- `scanner.scan(filepath)` → dict with tables, columns, row counts, version fingerprint, file metadata
- `scanner.detect_version(schema_info)` → `'v1.0'`, `'legacy'`, or `'unknown'`
- `scanner.extract_users_from_messages(conn)` → list of unique usernames (for legacy DBs)
- Unit tests for all 3 functions with synthetic test databases

### Phase 1b — Validator

**Files:**
- `utils/migration/validator.py`
- `tests/test_validator.py`

**Goal:** Validate a source schema against the expected Falcon schema.

**Deliverables:**
- `validator.validate_schema(schema_info)` → list of `ValidationIssue` objects (error/warning/info)
- `validator.check_integrity(conn)` → `(passed: bool, message: str)`
- `validator.check_column_compatibility(source_columns, expected_columns)` → missing/extra columns
- Unit tests with complete, partial, and malformed schemas

### Phase 1c — Resolver

**Files:**
- `utils/migration/resolver.py`
- `tests/test_resolver.py`

**Goal:** Detect conflicts between source and target, apply resolution policies.

**Deliverables:**
- `resolver.detect_conflicts(source_conn, target_session)` → conflict report per entity
- `resolver.generate_preview(source_conn, target_session, config)` → per-entity breakdown (existing, incoming, import, skip, merge, rename)
- `resolver.apply_resolutions(records, entity_type, policy, resolutions)` → transformed records ready for import
- Unit tests for conflict detection, preview generation, and policy application

### Phase 1d — Importer

**Files:**
- `utils/migration/importer.py`
- `tests/test_importer.py`

**Goal:** Execute the import with batch transactions, progress tracking, cancel support, and rollback.

**Deliverables:**
- `importer.run_import(source_path, config, app)` — main entry point
- `importer.import_progress` — shared dict for status polling
- `importer.cancel_import(import_id)` — graceful cancellation
- Background thread worker for async execution
- Automatic rollback on batch failure
- Unit tests with clean import, duplicate handling, cancellation, and failure scenarios

### Phase 1e — Printer & CLI

**Files:**
- `utils/migration/printer.py`
- `scripts/migrations/legacy_import.py`
- `tests/test_printer.py`

**Goal:** Generate reports and provide CLI entry point.

**Deliverables:**
- `printer.generate_report(import_results, config)` → report dict
- `printer.save_report(report, filepath)` → write JSON to disk
- `printer.format_human_readable(report)` → text summary
- Updated `legacy_import.py` CLI wrapping the new package
- Deprecation warning in old `utils/migration.py`

### Phase 1f — Web Routes (UI Phase — not yet)

**Files:**
- `routes/admin.py` — new wizard routes
- `templates/admin/migration_wizard.html` — 9-step single-page template
- `utils/backup.py` — pre-import backup hook

**Goal:** Wire backend modules into the web wizard. (Not implemented yet — awaiting approval.)

---

*End of design document. Implementation begins with Phase 1a: Package Structure & Scanner.*
