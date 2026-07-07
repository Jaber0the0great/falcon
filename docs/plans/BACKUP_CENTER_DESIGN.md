# Backup & Restore Center — Design Document

> Version 1.1, Phase 2
> Status: Draft — do not implement before approval

---

## 1. Objective

Build a **Backup & Restore Center** in the admin panel that replaces the ad-hoc CLI-only backup system (`utils/backup.py`) with a web UI covering creation, download, restore, export, and history of backups and imports.

The feature concept was renamed from "Database Export" to **Backup & Restore Center** to reflect a broader scope: not just exporting the database, but managing the full lifecycle of backup creation, restoration, rollback, and integrity verification alongside the import history from Phase 1.

---

## 2. Current State (As-Is)

| Component | Status |
|---|---|
| `utils/backup.py` | CLI-only, flat file layout in `backups/`, no checksums, no UI |
| Pre-import backups | Created automatically by `importer.py` before every import |
| Backup storage | 66 backup files in a single flat directory (`backups/`) |
| Checksums | SHA256 only computed for import reports (in `printer.py`), **not** for standalone backups |
| Restore | Only possible via `restore_backup()` Python call or manual file copy |
| Uploads storage | 69 files, ~13 MB in `static/uploads/` — **not included** in any backup |
| Import history | Reports saved to `logs/imports/<import_id>/report.json` — no UI to browse them |

### Existing Backup Flow

```
create_backup(db_path, label)
  ├── sqlite3.backup(source → dest)   # online backup API, 50 pages per iteration
  └── returns {success, path, filename, size, timestamp}

restore_backup(backup_path, target_path)
  ├── sqlite3.backup(backup → target)
  └── returns {success, path}

list_backups(backup_dir)
  └── returns [{filename, path, size, mtime, is_pre_import}, ...]

prune_backups(retain_count=10)
  └── deletes oldest backups beyond retain_count
```

---

## 3. Backup Format Analysis

### Option A — SQLite Only

| Aspect | Detail |
|---|---|
| **Contents** | Single `.db.backup.*` file via `sqlite3.backup()` |
| **Size** | ~52 KB (current DB) |
| **Speed** | Fast (~100ms) |
| **Integrity** | SQLite internal integrity (atomics, WAL) |
| **Restore** | `sqlite3.backup()` — no intermediate format needed |
| **Portability** | Works with any SQLite tool |
| **Limitation** | No uploaded files, no config, no logs |

**Verdict:** Essential as the core backup primitive. Already implemented in `utils/backup.py`.

---

### Option B — ZIP Package (Database + Uploads)

| Aspect | Detail |
|---|---|
| **Contents** | `falcon_web.db` + `static/uploads/*` + `backups/*` (optional) + `config/` (optional) |
| **Format** | `.zip` file with manifest JSON |
| **Size** | ~13 MB (current DB + uploads) |
| **Speed** | Medium (~2–5 seconds depending on upload count) |
| **Integrity** | ZIP CRC-32 per entry + SHA256 manifest checksum |
| **Restore** | Extract ZIP, overwrite DB, restore uploads directory |
| **Portability** | Universal ZIP — works on any OS |
| **Limitation** | Larger files, slower creation, more complex restore |

**Verdict:** Recommended as the primary user-facing backup format. Covers all user data.

---

### Option C — Database + Uploads + Configuration

| Aspect | Detail |
|---|---|
| **Contents** | Everything in B + `.env` (or environment variables), `config.py`, encryption keys |
| **Format** | ZIP with manifest |
| **Size** | ~13 MB + config (~10 KB) |
| **Integrity** | Same as B |
| **Restore** | Same as B + re-apply config |
| **Risk** | Bundling `.env` with secrets into a downloadable ZIP is a **security concern** |

**Verdict:** Suitable for **on-server** disaster recovery only. NOT for user downloads. Should be an admin-only on-server operation with confirmation.

---

### Option D — Full Application Backup

| Aspect | Detail |
|---|---|
| **Contents** | C + Python environment (`venv/`, `requirements.txt`), logs, metadata |
| **Format** | Tarball or ZIP |
| **Size** | ~50–200 MB (includes venv) |
| **Integrity** | Same as B/C |
| **Restore** | Extract + reinstall |
| **Complexity** | High — OS-dependent, Python version-specific, path-dependent |

**Verdict:** Out of scope. Python environment should be managed by CI/CD, not backup system.

---

### Comparison Matrix

| Criterion | A — SQLite | B — DB+Uploads | C — +Config | D — Full App |
|---|---|---|---|---|
| Data completeness | DB only | All user data | All data + secrets | Everything |
| Size | ~52 KB | ~13 MB | ~13 MB | ~50–200 MB |
| Speed | Fast | Medium | Medium | Slow |
| Restore complexity | Trivial | Low | Medium | High |
| Security risk | None | Low | **High** (secrets) | High |
| Download for user | Safe | Safe | **No** | No |
| Server-side DR | Partial | Full | Full | Overkill |

---

## 4. Recommended Approach

**Two-tier backup system:**

| Tier | Format | API | When | Who |
|---|---|---|---|---|
| **Quick Backup** | SQLite only (`db.backup.*`) | `create_backup()` | Automatic (pre-import) + manual | System + Admin |
| **Full Backup** | ZIP (DB + uploads + manifest.json) | New `utils/backup_center.py` | Manual, scheduled | Admin |

### Manifest Structure (Full Backup ZIP)

```
backup_20260705_120000.zip
├── manifest.json
├── falcon_web.db
└── uploads/
    ├── voice_message_abc.webm
    ├── photo_xyz.jpg
    └── ...
```

**`manifest.json`:**
```json
{
  "backup_id": "bck_a1b2c3d4",
  "created_at": "2026-07-05T12:00:00Z",
  "format_version": 2,
  "type": "full",
  "contents": {
    "database": {
      "file": "falcon_web.db",
      "size_bytes": 53248,
      "sha256": "abc123..."
    },
    "uploads": {
      "count": 69,
      "size_bytes": 13900000,
      "sha256": "def456...",
      "files": [
        {"path": "uploads/voice_message_abc.webm", "size": 1234, "sha256": "..."}
      ]
    }
  },
  "backup_sha256": "full_archive_checksum"
}
```

### File Naming

| Backup Type | Pattern |
|---|---|
| Quick (SQLite) | `falcon_web.db.backup.{YYYYmmdd_HHMMSSfff}` |
| Pre-import | `pre_import_{import_id}_falcon_web.db.backup.{YYYYmmdd_HHMMSSfff}` |
| Full (ZIP) | `full_backup_{YYYYmmdd_HHMMSS}.zip` |

---

## 5. Storage Requirements

| Item | Current | Projected (1 year) | Notes |
|---|---|---|---|
| Database | 52 KB | 1–5 MB | Linear growth with messages/users |
| Uploads | 13 MB | 50–200 MB | Voice messages + media |
| Quick backup (per copy) | 52 KB | 1–5 MB | ~50 KB today |
| Full backup (per copy) | 13 MB | 50–200 MB | DB + uploads |
| Retention (default) | 10 copies | 10 copies | Configurable |
| Total (10 quick + 5 full) | ~65 MB | 250 MB–1 GB | Acceptable for single-server |

**Recommendation:** No special storage infrastructure needed. Use `backups/` directory with subdirectories (`quick/`, `full/`, `pre_import/`).

---

## 6. Feature Design

### 6.1 Create Backup

**Quick Backup** (SQLite only)
- Button: "Create Quick Backup"
- Calls `create_backup()` → saves to `backups/quick/`
- Shows success with filename, size, timestamp
- Computes SHA256 of the backup file and stores it

**Full Backup** (ZIP)
- Button: "Create Full Backup"
- Streams DB + uploads into ZIP with manifest
- Saves to `backups/full/`
- Shows progress indicator (packing DB, packing uploads, checksumming)
- Computes SHA256 of the ZIP and stores it

### 6.2 Download Backup

- **Quick backups**: Direct download of `.db.backup.*` file
- **Full backups**: Direct download of `.zip` file
- Content-Disposition header with original filename
- Rate-limited (admin only)

### 6.3 Restore Backup

**Critical operation — requires confirmation flow:**

1. User selects a backup from the history list
2. Clicks "Restore"
3. Modal dialog:
   - Shows backup metadata (date, size, SHA256)
   - Warns: "This will replace the current database and all uploaded files. This action cannot be undone without a prior backup."
   - Checkbox: "I have a recent backup of the current state" (required)
   - Text input: type "RESTORE" to confirm
   - Button: "Restore from Backup" (disabled until both conditions met)
4. On confirm:
   - Auto-create a quick backup of the **current** database (pre-restore safety net)
   - For quick backup: `restore_backup(backup_path)` replaces DB
   - For full backup: extract ZIP, replace DB, replace uploads directory
   - Verify SHA256 of restored data
   - Show result: success/failure with details
   - Offer "Rollback" button for 30 seconds after restore (see §7)

### 6.4 Export Database

- Shortcut for creating a Quick Backup and immediately offering the download
- One-click flow: "Export" → creates backup → starts download
- No confirmation needed (non-destructive read-only operation)
- Equivalent to: Create Quick Backup + Download in one action

### 6.5 Import History

- Browseable list of all past imports from `logs/imports/<import_id>/`
- Columns: Import ID, Date, Status (completed/failed/cancelled), Rows imported, Source file
- Each row expandable to show: per-table breakdown, SHA256, pre-import backup path, error detail
- Link to the pre-import backup for rollback (see §7)
- Search/filter by status, date range

### 6.6 Backup History

- Browseable list of all backups across all categories:
  - Quick backups (`backups/quick/`)
  - Full backups (`backups/full/`)
  - Pre-import backups (`backups/pre_import/`)
- Columns: Type (Quick/Full/Pre-Import), Filename, Size, Created, SHA256
- Actions per row: Download, Restore, Delete
- Sortable by date (default: newest first)
- Search/filter by type, date range
- Pagination (20 per page)

---

## 7. Restore & Rollback Workflow

```
Normal flow:
  Restore from backup B
    ├── 1. Auto-create pre-restore backup of current DB  (safety net)
    ├── 2. Perform restore (SQLite backup or ZIP extract)
    ├── 3. Verify SHA256
    ├── 4. Show success
    └── 5. Offer "Rollback" button (30-second window)

Rollback flow:
  Click "Rollback"
    ├── 1. Use pre-restore backup created in step 1
    ├── 2. Restore that backup
    ├── 3. Show success
    └── 4. Delete the pre-restore backup (cleanup)

Rollback via Import History:
  Any failed or unwanted import can be rolled back by:
    ├── 1. Go to Import History
    ├── 2. Find the import
    ├── 3. Click "Rollback via pre-import backup"
    ├── 4. `restore_backup(pre_import_backup_path)`
    └── 5. Verify and confirm

Direct restore from backup history:
  ├── 1. Select any backup in list
  ├── 2. Click Restore
  ├── 3. Confirmation modal
  └── 4. Execute
```

---

## 8. Integrity & Checksum Verification

| Operation | Verification |
|---|---|
| Create Quick Backup | SHA256 of backup file, stored in sidecar `.sha256` file and in registry |
| Create Full Backup | SHA256 per file in manifest + SHA256 of entire ZIP |
| Restore (Quick) | SHA256 of backup compared to stored value before restore |
| Restore (Full) | SHA256 of ZIP verified before extraction; per-file SHA256 verified after extraction |
| Download | Content-disposition + SHA256 displayed on page for manual verification |
| Scheduled check | Optional: re-checksum all backups on a schedule, report mismatches |

### Error Handling

| Scenario | Action |
|---|---|
| SHA256 mismatch before restore | Block restore, show error, log warning |
| SHA256 mismatch during scheduled check | Mark backup as "corrupted" in UI, highlight in red |
| Restore fails mid-operation | Pre-restore backup still exists, show rollback button |
| Backup file deleted from disk | Mark as "missing" in UI, remove from list with warning |

---

## 9. Backup Retention Policy

| Policy | Default | Configurable? | Applies to |
|---|---|---|---|
| Quick backups to keep | 10 | Yes | `backups/quick/` |
| Full backups to keep | 5 | Yes | `backups/full/` |
| Pre-import backups to keep | 20 | No | `backups/pre_import/` |
| Auto-prune on create | Yes | Yes | After each new backup creation |
| Manual prune | Yes | N/A | User action from UI |

**Pruning algorithm** (already implemented in `prune_backups()`):
1. Sort backups by creation time (newest first)
2. Remove entries beyond the retention limit
3. Log deleted files

**Enhancement:** Add retention-by-age (e.g., "delete backups older than 90 days") in addition to count-based.

---

## 10. Admin UI Navigation & Layout

### Sidebar Update

```
Falcon Admin
─────────────
  Dashboard       (existing)
  DB Import       (existing from Phase 1g)
  Backup Center   (NEW — replaces "DB Export" placeholder)
─────────────
  Logout
```

### Page Layout

The Backup & Restore Center will be a **tabbed page** within the admin section:

```
┌─────────────────────────────────────────────────┐
│  Backup & Restore Center                         │
├─────────────────────────────────────────────────┤
│  [Create]  [Backup History]  [Import History]    │   ← Tabs
├─────────────────────────────────────────────────┤
│                                                   │
│  ┌─ Create Backup ───────────────────────────┐   │
│  │                                            │   │
│  │  [Create Quick Backup]  [Create Full Bkup] │   │
│  │                                            │   │
│  │  Recent: 3 quick backups in last 24h       │   │
│  │          1 full backup yesterday            │   │
│  │          Next auto-prune: 10 quick, 5 full  │   │
│  └────────────────────────────────────────────┘   │
│                                                   │
│  ┌─ Quick Actions ───────────────────────────┐   │
│  │                                            │   │
│  │  [Export Database]   → creates + downloads │   │
│  │                                    .db     │   │
│  └────────────────────────────────────────────┘   │
│                                                   │
└─────────────────────────────────────────────────┘
```

---

## 11. API Endpoints (New)

All under `/admin/api/backup-center/` prefix:

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/admin/backup-center` | Page render |
| `POST` | `/admin/api/backup-center/create-quick` | Create SQLite-only backup |
| `POST` | `/admin/api/backup-center/create-full` | Create ZIP (DB+uploads) backup |
| `GET` | `/admin/api/backup-center/list` | List all backups (with type filter) |
| `GET` | `/admin/api/backup-center/download/<backup_id>` | Download a backup file |
| `POST` | `/admin/api/backup-center/restore` | Restore from a backup |
| `POST` | `/admin/api/backup-center/rollback` | Rollback to pre-restore snapshot |
| `DELETE` | `/admin/api/backup-center/delete/<backup_id>` | Delete a backup |
| `GET` | `/admin/api/backup-center/verify/<backup_id>` | Verify SHA256 of a backup |
| `GET` | `/admin/api/backup-center/import-history` | List import history |
| `GET` | `/admin/api/backup-center/import-history/<import_id>` | Get import detail |

---

## 12. New Files & Changes

### New Files

| File | Purpose |
|---|---|
| `utils/backup_center.py` | ZIP backup creation, manifest generation, full restore logic |
| `routes/backup_center.py` | Blueprint for all backup-center routes |
| `templates/admin/admin_backup_center.html` | Single-page UI (tabbed) |
| `docs/plans/BACKUP_CENTER_DESIGN.md` | This document |

### Modified Files

| File | Change |
|---|---|
| `utils/backup.py` | Add SHA256 computation to `create_backup()`, add subdirectory support (`backups/quick/`, `backups/pre_import/`) |
| `utils/migration/printer.py` | Minor: expose `sha256_checksum()` as public helper (already exists) |
| `app.py` | Register `backup_center_bp` |
| `backups/README.md` | Update to reflect new subdirectory structure |
| `templates/admin/admin_db_import.html` | Add "Backup Center" link in sidebar |

---

## 13. Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| User restores from backup without current backup | Data loss | Auto-create pre-restore backup before every restore |
| Full backup ZIP contains malicious uploads | Security risk on restore | SHA256 verification; files were uploaded by authenticated users |
| Restore fails mid-operation | Corrupted DB | Pre-restore backup guarantees rollback; atomic replace |
| Backups fill disk | Service outage | Prune on create; configurable retention; warning when disk < 20% free |
| SHA256 mismatch due to bitrot | Data corruption | On-restore verification blocks corrupted restore |

---

## 14. Implementation Plan

| Step | Scope | Depends On |
|---|---|---|
| 2a | `utils/backup_center.py` — ZIP creation, manifest, full restore | — |
| 2b | Enhance `utils/backup.py` — SHA256, subdirectory support, sidecar checksums | — |
| 2c | `routes/backup_center.py` — all endpoints | 2a, 2b |
| 2d | `templates/admin/admin_backup_center.html` — tabbed UI | 2c |
| 2e | Register blueprint, wire sidebar links, add tests | 2a–2d |
| 2f | Verify all tests pass (include new backup_center tests) | 2a–2e |

---

## 15. Approval Checklist

- [ ] Two-tier format (quick SQLite + full ZIP) is acceptable
- [ ] Pre-restore auto-backup is sufficient rollback protection
- [ ] Retention-by-count (10 quick, 5 full) is a sensible default
- [ ] Full backup includes DB + uploads only (not config/secrets)
- [ ] No changes to the import engine or existing backup API contracts
- [ ] Sidebar label: "Backup Center"
