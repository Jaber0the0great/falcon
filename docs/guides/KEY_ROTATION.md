# Key Rotation & Operations Guide

**Applies to:** Fernet encryption at rest for `Message.content` and `Message.reply_content` (Phase D).

## Table of Contents

1. [Generating a New Encryption Key](#1-generating-a-new-encryption-key)
2. [Initial Deployment](#2-initial-deployment)
3. [Rotating Keys with MultiFernet](#3-rotating-keys-with-multifernet)
4. [Removing Old Keys Safely](#4-removing-old-keys-safely)
5. [Lost Key Recovery](#5-lost-key-recovery)
6. [Disaster Recovery](#6-disaster-recovery)
7. [Database Backup Strategy](#7-database-backup-strategy)
8. [Migration Workflow](#8-migration-workflow)
9. [Environment Variable Examples](#9-environment-variable-examples)
10. [Emergency Rollback Procedure](#10-emergency-rollback-procedure)
11. [Production Deployment Recommendations](#11-production-deployment-recommendations)
12. [Common Operational Mistakes to Avoid](#12-common-operational-mistakes-to-avoid)

---

## 1. Generating a New Encryption Key

Fernet keys are 32 bytes of cryptographically random data, Base64-urlsafe-encoded (44 characters).

**Generation (recommended):**

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**Output example:**

```
nbOtuNVx3iAnHiFbAX8dqfZOeBnQ6lxkdYl6RL9Prow=
```

**Alternative (OpenSSL):**

```bash
openssl rand -base64 32
```

The output must be exactly 44 characters ending with `=` or `==`. Validate with:

```bash
python -c "from cryptography.fernet import Fernet; Fernet('nbOtuNVx3iAnHiFbAX8dqfZOeBnQ6lxkdYl6RL9Prow=')"
# No output = valid
```

**Store the key immediately** in a secure vault (see §7). If you lose the key before writing it down, the data is permanently unrecoverable.

---

## 2. Initial Deployment

### Prerequisites

- Python 3.10+ with `cryptography` package installed
- Application code from Phase D or later
- A valid `ENCRYPTION_KEY`

### Setup steps

1. **Generate an encryption key** (see §1).
2. **Set the environment variable:**

   ```bash
   # Linux / macOS
   export ENCRYPTION_KEY="nbOtuNVx3iAnHiFbAX8dqfZOeBnQ6lxkdYl6RL9Prow="

   # Windows PowerShell
   $env:ENCRYPTION_KEY = "nbOtuNVx3iAnHiFbAX8dqfZOeBnQ6lxkdYl6RL9Prow="
   ```

3. **Add to `.env`** (never commit to version control):

   ```ini
   ENCRYPTION_KEY=nbOtuNVx3iAnHiFbAX8dqfZOeBnQ6lxkdYl6RL9Prow=
   ```

4. **Run the migration script in dry-run mode:**

   ```bash
   python encrypt_migration.py --dry-run
   ```

   This reports how many messages will be encrypted.

5. **Run the actual migration:**

   ```bash
   python encrypt_migration.py --run
   ```

   This creates a timestamped backup (`falcon_web.db.backup.YYYYMMDD_HHMMSS`) and encrypts all text messages.

6. **Verify the migration:**

   ```bash
   python encrypt_migration.py --verify --samples 20
   ```

7. **Start the application:**

   ```bash
   python app.py
   ```

### What gets encrypted

- `Message.content` where `msg_type = 'text'`
- `Message.reply_content` on any message that has a quoted reply

### What stays plaintext

Everything else: `sender`, `recipient`, `msg_type`, `time`, `duration`, `file_name`, `status`, `msg_id`, `reactions`, `raw_data`, and all columns on non-Message tables.

---

## 3. Rotating Keys with MultiFernet

The application uses `cryptography.fernet.MultiFernet`. The *first* key in the list is used for encryption; *all* keys are tried for decryption in order.

This means you can rotate keys **without re-encrypting existing data**.

### When to rotate

- Scheduled rotation policy (e.g., every 12 months)
- Key compromise or suspected breach
- Compliance requirement (PCI-DSS, SOC 2, etc.)

### Rotation procedure

1. **Generate a new key** (see §1).

2. **Move the current key to the old-keys list and set the new key as current.**

   ```bash
   export ENCRYPTION_KEY_OLD_KEYS="$ENCRYPTION_KEY"
   export ENCRYPTION_KEY="<newly_generated_key>"
   ```

   If you already have old keys, append:

   ```bash
   export ENCRYPTION_KEY_OLD_KEYS="$ENCRYPTION_KEY,$ENCRYPTION_KEY_OLD_KEYS"
   export ENCRYPTION_KEY="<newly_generated_key>"
   ```

3. **Update `.env`** with the new values.

4. **Restart the application.**

5. **Verify old messages are still readable:**

   ```bash
   python encrypt_migration.py --dry-run
   # Expected: 0 plaintext (all messages already encrypted, no re-encryption needed)
   python encrypt_migration.py --verify --samples 20
   # Expected: all pass
   ```

6. **Optionally re-encrypt existing messages with the new key** (see §3.1).

### 3.1 Re-encrypting existing messages (optional)

New messages are automatically encrypted with the current key. Old messages remain encrypted with their original key and are decrypted via `MultiFernet` trying old keys in sequence.

Re-encryption is **safe but unnecessary** for correctness. Do it only if:

- You want old messages under a single key for simplicity
- You are retiring the old key (see §4)
- Compliance requires it

**Procedure:**

```bash
# Ensure ENCRYPTION_KEY has the NEW key and ENCRYPTION_KEY_OLD_KEYS has the OLD key(s)
python encrypt_migration.py --run
```

The migration script skips already-encrypted content by default. When it encounters a message encrypted with an old key, `is_encrypted()` returns `True`, so the message is left alone. To force re-encryption, modify the script or run a targeted UPDATE query.

### Performance note

`MultiFernet` tries each key sequentially during decryption until one succeeds. With one old key, worst-case decryption is 2× Fernet attempts (~200 µs per message). With 10 old keys, worst-case is 11× (~1 ms per message). This is negligible for per-message or per-page loads but should be considered if the old-key list grows unbounded.

**Recommendation:** Keep at most 3–5 old keys. Every 2–3 rotations, re-encrypt with the current key and remove the oldest keys (see §4).

---

## 4. Removing Old Keys Safely

Removing an old key makes messages encrypted with that key **permanently unreadable**.

### Before removing a key

1. **Identify messages encrypted with the old key.**

   The easiest approach is to attempt decryption with and without the key. A safer method is to re-encrypt all messages with the current key first.

2. **Re-encrypt existing messages with the current key.**

   ```bash
   # Set ENCRYPTION_KEY (current) + ENCRYPTION_KEY_OLD_KEYS (key to retire)
   python encrypt_migration.py --run --no-backup
   ```

   **Warning:** The current migration script (`encrypt_migration.py`) skips already-encrypted content. It will NOT re-encrypt messages that are already encrypted (even with an old key). For a full re-encryption pass, you need to temporarily modify the script or run a custom script.

   **Custom re-encryption script:**

   ```python
   import os, sqlite3
   os.environ['ENCRYPTION_KEY_OLD_KEYS'] = ''
   from utils.crypto import encrypt_text, decrypt_text, is_encrypted

   conn = sqlite3.connect('falcon_web.db')
   rows = conn.execute("SELECT id, content, reply_content FROM message WHERE msg_type = 'text'").fetchall()
   for bulk_start in range(0, len(rows), 100):
       batch = rows[bulk_start:bulk_start + 100]
       updates = []
       for row in batch:
           new_c = encrypt_text(decrypt_text(row[1])) if row[1] else row[1]
           new_r = encrypt_text(decrypt_text(row[2])) if row[2] else row[2]
           updates.append((new_c, new_r, row[0]))
       conn.executemany("UPDATE message SET content=?, reply_content=? WHERE id=?", updates)
       conn.commit()
   conn.close()
   ```

   This decrypts each message with the old key (via `MultiFernet`) then re-encrypts with the new key.

3. **Verify all messages decrypt with the current key only.**

   ```bash
   # Temporarily clear ENCRYPTION_KEY_OLD_KEYS
   unset ENCRYPTION_KEY_OLD_KEYS
   python encrypt_migration.py --verify --samples 100
   ```

4. **Remove the old key from `ENCRYPTION_KEY_OLD_KEYS`** in your `.env` and secret store.

5. **Restart the application.**

---

## 5. Lost Key Recovery

### Single key lost

If you have a backup of the key (e.g., in a password manager or vault), restore it.

If the key is gone with no backup:

- **Messages encrypted with that key are permanently unreadable.**
- There is no backdoor, no master key, and no recovery mechanism for Fernet.
- The application will still function — it will display ciphertext as-is (the `except` clause in `decrypt_text` returns the input unchanged).

### What to do

1. **Stop the application** to prevent any new data from being stored.
2. **Check all possible locations:** vaults, password managers, CI/CD secrets, team members' backups, old `.env` files, server configuration management.
3. **If the key is truly lost:**
   - Generate a new key.
   - Set `ENCRYPTION_KEY` to the new key.
   - Delete or archive the old database (its messages are unrecoverable).
   - Start fresh with no encrypted messages.
4. **If you have partial key material** (e.g., you remember most of the Base64 string but a few characters are corrupted), you can brute-force Fernet keys only by trying all possible complete keys — the key space is 2¹²⁸. This is infeasible. Accept the loss.

### Prevention

- Store the key in at least two independent locations (e.g., AWS Secrets Manager + Bitwarden).
- Include the key in your disaster recovery runbook.
- Test key retrieval as part of your onboarding process for new operators.

---

## 6. Disaster Recovery

### Scenario A: Database file corrupted

1. Restore the latest uncorrupted backup of `falcon_web.db`.
2. Ensure `ENCRYPTION_KEY` matches the key that was active when the backup was taken.
3. If keys have been rotated since the backup, include all intervening keys in `ENCRYPTION_KEY_OLD_KEYS`.
4. Start the application.

### Scenario B: Server lost completely

1. Provision a new server.
2. Deploy the application code (from Git).
3. Restore the database from backup.
4. Set `ENCRYPTION_KEY` (and `ENCRYPTION_KEY_OLD_KEYS` if needed) from the secret store.
5. Run `python encrypt_migration.py --verify --samples 50` to confirm.
6. Start the application.

### Scenario C: Key and database both lost

This is a **total data loss** event. There is no recovery path. All message content is gone.

1. Generate a new `ENCRYPTION_KEY`.
2. Start with an empty database.
3. Users will see no chat history.
4. Investigate root cause and improve backup/key-storage procedures.

### Scenario D: Key rotated but old key lost before re-encryption

Messages encrypted with the discarded key become permanently unreadable.

1. If `ENCRYPTION_KEY_OLD_KEYS` still contains the old key, recovery is possible — set it back.
2. If the old key is gone, those messages are lost.
3. Run `python encrypt_migration.py --dry-run` to see how many messages are still encrypted with unknown keys.
4. Generate a new key and continue.

---

## 7. Database Backup Strategy

### What to back up

| Item | Criticality | Notes |
|------|-------------|-------|
| `falcon_web.db` | Required | Contains encrypted message content |
| `ENCRYPTION_KEY` (current) | **Required** | Without this, DB is useless |
| `ENCRYPTION_KEY_OLD_KEYS` (all) | Required | Needed to decrypt messages from before the last rotation |
| Application code | Required | From version control |
| `.env` / config | Required | Contains all secrets together |

### Backup frequency

- **Database:** Hourly in production, daily in staging. Use `sqlite3` backup API or file-level copy with a write lock.
- **Keys:** Every rotation event (immediately after generating a new key).

### Key storage

- **Primary:** AWS Secrets Manager, HashiCorp Vault, Azure Key Vault, or GCP Secret Manager.
- **Secondary (offline):** Encrypted password manager (Bitwarden, 1Password) or GPG-encrypted file stored offline.
- **Never:** In the same S3 bucket as the database backup.

### Backup rotation and retention

- Keep daily backups for 30 days.
- Keep weekly backups for 12 months.
- Test a restore at least quarterly.

### Verifying backups

```bash
# Restore backup to a test location
cp falcon_web.db.backup.20260101_120000 /tmp/test_restore.db
DB_PATH=/tmp/test_restore.db python encrypt_migration.py --verify --samples 50
# Expect: all pass
```

---

## 8. Migration Workflow

### First-time migration (plaintext → encrypted)

```
┌─────────────┐     ┌──────────┐     ┌─────────┐     ┌──────────┐
│ 1. Generate │────→│ 2. Set   │────→│ 3. Dry  │────→│ 4. Verify│
│    key      │     │ ENV vars │     │   Run   │     │  stats   │
└─────────────┘     └──────────┘     └─────────┘     └──────────┘
                                              │
                                              ▼
                                      ┌──────────┐     ┌──────────┐
                                      │ 5. Run   │────→│ 6. Verify│
                                      │ migration│     │ samples  │
                                      └──────────┘     └──────────┘
                                              │
                                              ▼
                                      ┌──────────┐
                                      │ 7. Start │
                                      │   app    │
                                      └──────────┘
```

### Key rotation workflow

```
┌─────────────┐     ┌─────────────┐     ┌──────────┐     ┌──────────┐
│ 1. Generate │────→│ 2. Move old │────→│ 3. Update│────→│ 4. Verify│
│   new key   │     │  key → OLD  │     │  .env    │     │  decrypt │
└─────────────┘     └─────────────┘     └──────────┘     └──────────┘
                                              │
                                              ▼
                                      ┌──────────┐
                                      │ 5. Restart│
                                      │   app    │
                                      └──────────┘
```

### Key retirement workflow

```
┌──────────────┐     ┌──────────────┐     ┌──────────┐     ┌──────────┐
│ 1. Re-encrypt│────→│ 2. Verify    │────→│ 3. Remove │────→│ 4. Restart│
│    all msgs  │     │    decrypt   │     │   old key │     │   app    │
└──────────────┘     └──────────────┘     └──────────┘     └──────────┘
```

---

## 9. Environment Variable Examples

### Minimal (no old keys)

```ini
ENCRYPTION_KEY=nbOtuNVx3iAnHiFbAX8dqfZOeBnQ6lxkdYl6RL9Prow=
```

### With one old key

```ini
ENCRYPTION_KEY=r3NwKX9pLmZ7qT2vB4cD6fG8hJ0kM1oP5sU7wY9eI2uA=
ENCRYPTION_KEY_OLD_KEYS=nbOtuNVx3iAnHiFbAX8dqfZOeBnQ6lxkdYl6RL9Prow=
```

### With multiple old keys (comma-separated, no spaces)

```ini
ENCRYPTION_KEY=r3NwKX9pLmZ7qT2vB4cD6fG8hJ0kM1oP5sU7wY9eI2uA=
ENCRYPTION_KEY_OLD_KEYS=nbOtuNVx3iAnHiFbAX8dqfZOeBnQ6lxkdYl6RL9Prow=,a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w=
```

### Windows PowerShell

```powershell
$env:ENCRYPTION_KEY = "nbOtuNVx3iAnHiFbAX8dqfZOeBnQ6lxkdYl6RL9Prow="
$env:ENCRYPTION_KEY_OLD_KEYS = "r3NwKX9pLmZ7qT2vB4cD6fG8hJ0kM1oP5sU7wY9eI2uA="
```

### Linux / macOS (temporary)

```bash
export ENCRYPTION_KEY="nbOtuNVx3iAnHiFbAX8dqfZOeBnQ6lxkdYl6RL9Prow="
export ENCRYPTION_KEY_OLD_KEYS="r3NwKX9pLmZ7qT2vB4cD6fG8hJ0kM1oP5sU7wY9eI2uA="
```

### Docker

```dockerfile
ENV ENCRYPTION_KEY=nbOtuNVx3iAnHiFbAX8dqfZOeBnQ6lxkdYl6RL9Prow=
```

Or via Docker Compose secrets:

```yaml
services:
  app:
    environment:
      ENCRYPTION_KEY_FILE: /run/secrets/encryption_key
      ENCRYPTION_KEY_OLD_KEYS_FILE: /run/secrets/encryption_key_old
    secrets:
      - encryption_key
      - encryption_key_old
```

---

## 10. Emergency Rollback Procedure

### When to roll back

- The migration script introduced a bug that corrupts data.
- Encryption is causing production outages.
- You need to revert to the pre-encryption state immediately.

### Rollback steps

1. **Stop the application.**

   ```bash
   # Kill the Flask/SocketIO process
   pkill -f "python app.py"
   ```

2. **Confirm the pre-migration backup exists.**

   ```bash
   ls -la falcon_web.db.backup.*
   ```

   If no backup exists, skip to step 4 and accept data loss for messages created after migration.

3. **Restore the pre-migration backup.**

   ```bash
   cp falcon_web.db.backup.20260101_120000 falcon_web.db
   ```

4. **Remove or clear `ENCRYPTION_KEY`** from `.env` or set it to an empty value (the application will skip encryption/decryption if the key is missing; `encrypt_text`/`decrypt_text` return their input unchanged).

5. **Restart the application.**

   ```bash
   python app.py
   ```

### Important caveats

- **Data created between migration and rollback is lost.** The pre-migration backup does not contain messages sent after the migration ran.
- **Do NOT attempt an in-place decrypt.** Always restore from backup. An in-place decrypt script is error-prone and slower than a file copy.
- **After rollback, the application reverts to storing plaintext.** All new messages will be plaintext until encryption is re-enabled.

### Post-rollback

1. Identify the root cause of the rollback.
2. Fix the issue in a development environment.
3. Generate a new encryption key (do not reuse the old one — it may have been exposed during the incident).
4. Re-run the migration workflow (§8).

---

## 11. Production Deployment Recommendations

### Key management

- Use a dedicated secrets manager (AWS Secrets Manager, HashiCorp Vault) for `ENCRYPTION_KEY`.
- Never embed the key in source code, Docker images, or CI/CD logs.
- Restrict access to the key to the minimum set of operators.
- Audit key access — every decryption of a vault secret should be logged.

### Database

- Switch from SQLite to PostgreSQL before production (SQLite has no concurrent-write scaling).
- Use encrypted storage for the database volume (LUKS, EBS encryption, or SQLCipher).
- Run regular `VACUUM` to reclaim space after the migration (encrypted blobs may be slightly larger than plaintext).

### Monitoring

- Alert if `encrypt_migration.py --verify` detects failures.
- Alert if `ENCRYPTION_KEY` is unset or invalid on application startup.
- Monitor `_get_cipher()` exception rate in application logs — frequent decrypt failures may indicate a missing old key.

### Testing

- Before any rotation, run the migration script's `--dry-run` and `--verify` in a staging environment with a copy of production data.
- Include key rotation in your disaster recovery drill at least once per quarter.
- Automate rotation testing in CI/CD: generate a temporary key, encrypt a test message, rotate the key, verify decryption, retire the old key.

### Deployment order

1. Deploy code changes (Phase D) with `ENCRYPTION_KEY` set.
2. Run `encrypt_migration.py --dry-run` to confirm.
3. Run `encrypt_migration.py --run` to encrypt existing messages.
4. Run `encrypt_migration.py --verify` to confirm.
5. Monitor application logs for 24 hours.
6. Announce the deployment.

---

## 12. Common Operational Mistakes to Avoid

### 1. Losing the key before verifying the backup

If you rotate keys and immediately discard the old key without verifying that the backup can be restored with it, the backup becomes useless.

**Mitigation:** Test backup restoration quarterly. Keep old keys in the vault for at least one backup retention cycle after rotation.

### 2. Forgetting to include old keys during restore

When restoring from a backup that predates a key rotation, you must include all keys that were active between the backup date and the rotation date.

**Mitigation:** Tag each backup with the current key fingerprint (SHA-256 of key material). Document which keys were active during which period.

```bash
python -c "import hashlib; import os; k = os.environ['ENCRYPTION_KEY'].encode(); print(hashlib.sha256(k).hexdigest()[:16])"
```

### 3. Committing the key to version control

Once a key is in Git history, it is exposed forever — even if you delete it in a later commit.

**Mitigation:** Use `.env` files with `gitignore`. Use CI/CD secrets for deployment. Scan Git history for secrets with tools like `trufflehog` or `git-secrets`.

### 4. Running the migration without a backup

The `--run` flag creates a backup by default, but `--run --no-backup` does not. If the migration script has a bug, there is no recovery without a backup.

**Mitigation:** Always run without `--no-backup` in production. Take an additional manual backup before any migration.

### 5. Encrypting call_log or system messages

The migration script skips `msg_type != 'text'`, but the `encrypt_migration.py` verification sample only checks text messages. If a future code change accidentally encrypts call_log content, the verification step may not catch it.

**Mitigation:** Run a separate query to confirm call_log content is not encrypted after migration:

```bash
python -c "
import os, sqlite3
from utils.crypto import is_encrypted
conn = sqlite3.connect('falcon_web.db')
rows = conn.execute(\"SELECT id, content FROM message WHERE msg_type='call_log'\").fetchall()
bad = [r[0] for r in rows if is_encrypted(r[1])]
if bad: print(f'WARNING: {len(bad)} call_log messages are encrypted: {bad}')
else: print('OK: No call_log messages encrypted')
conn.close()
"
```

### 6. Running out of disk space mid-migration

The backup is a full copy of the database. A 1 GB database requires at least 2 GB free (1 GB for backup + 1 GB for original). The migration itself also writes to the DB.

**Mitigation:** Check disk space before running. Monitor during migration.

### 7. Not testing key rotation in staging

Rotating keys in production without having tested the procedure in staging is the most common cause of key-rotation failures.

**Mitigation:** Automate the rotation test in staging as part of your CI/CD pipeline.

### 8. Assuming `decrypt_text` on plaintext is an error

`decrypt_text("Hello")` returns `"Hello"` — it does NOT raise an error. This is by design for backward compatibility but can mask bugs where plaintext is being returned when ciphertext was expected.

**Mitigation:** Use `is_encrypted()` before `decrypt_text()` if you need to verify that the input was actually encrypted. Enable verbose logging during development to surface unexpected plaintext returns.
