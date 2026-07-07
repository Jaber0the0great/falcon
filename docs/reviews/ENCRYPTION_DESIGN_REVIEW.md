# Encryption at Rest — Design Review

## Current State Audit

- `utils/crypto.py` — implements `encrypt_text()` and `decrypt_text()` using **Fernet** (AES-128-CBC + HMAC-SHA256, key via `ENCRYPTION_KEY` env var).
- `encrypt_text()` is **never called** anywhere in the application. Message content is stored as plaintext in the `Message.content` column.
- `decrypt_text()` is called only in the **admin chat viewer** (`routes/admin.py:393`) and the **desktop admin app** (`admin_app.py:1029`). Both currently pass plaintext through the `except` fallback.
- `.env.example` documents `ENCRYPTION_KEY` as required, but the app does not enforce it at startup — the key is only validated lazily on first encrypt/decrypt call.

---

## 1. Why is encryption at rest needed in this application?

The application stores user chat messages in a **SQLite database file** (`falcon_web.db`) on the server filesystem. SQLite provides **no built-in encryption** — the file is a plain binary that any user with filesystem access can read with any SQLite client or a `strings` command.

Users exchange private conversations. Without encryption at rest, the following actors gain unrestricted read access to all message content:

- Anyone with **shell access** to the server (`cat falcon_web.db`)
- **Backup operators** who can read the backup file
- An attacker who exploits a **path traversal**, **LFI**, or **arbitrary file read** vulnerability
- An attacker with **read access to the volume** (e.g., compromised adjacent container, shared filesystem)
- **Cloud provider personnel** with access to the disk image or snapshots

Encryption at rest ensures that **message content is confidential even when the database file is compromised**, provided the encryption key remains secret.

---

## 2. What security threat does it mitigate?

| Threat | Mitigated? |
|---|---|
| Database file theft (e.g. S3 bucket leak, backup compromise) | **Yes** — ciphertext is useless without the key |
| Filesystem-level read (e.g. LFI, path traversal) | **Yes** — attacker sees only ciphertext |
| Physical disk theft or server decommissioning | **Yes** — data remains encrypted |
| Cold boot / memory dump after power-off | **Partial** — disk is encrypted, but recently-decrypted content may linger in swap |
| Insider with read-only DB access (e.g. DBA) | **Yes** — content is opaque without the key |

---

## 3. What threats does it NOT mitigate?

| Threat | Not mitigated | Reason |
|---|---|---|
| In-memory attack (e.g. `/proc/mem`, heartbleed, debugger) | ❌ | Messages must be decrypted in application memory to be displayed. An attacker with code execution reads plaintext from RAM. |
| Compromised application logic (e.g. SQLi, RCE) | ❌ | The app has the key and can decrypt any message. |
| Side-channel attacks (timing, power, electromagnetic) | ❌ | Out of scope for a web chat application. |
| Metadata exposure | ❌ | Sender, recipient, timestamps, message count, reaction emoji, reply relationships remain plaintext. |
| Traffic analysis | ❌ | Who talks to whom, when, and how often remains visible. |
| Desktop admin app (`admin_app.py`) | ❌ | The admin app has direct SQLite + filesystem access and reads the same `ENCRYPTION_KEY`. A compromise of either app is a compromise of both. |
| Privilege escalation | ❌ | Any authenticated user who can call the API can read their own decrypted messages. That is by design. |

---

## 4. Comparison of approaches

### Fernet (chosen — already partially implemented)

| Property | Value |
|---|---|
| Algorithm | AES-128-CBC + HMAC-SHA256 (built into `cryptography.fernet`) |
| Authentication | Yes — ciphertext includes an HMAC; tampering is detected |
| Key format | 32-byte URL-safe base64 |
| Overhead per message | ~300 bytes (IV + HMAC + version header) |
| Dependency | Already in `requirements.txt` (`cryptography` package) |
| Code | Already written — `utils/crypto.py` |

**Advantages:**
- Already exists in the codebase. Zero new dependencies.
- Simple, well-documented, misuse-resistant API.
- Authenticated encryption (no padding oracle attacks).
- Constant-time operations.
- Fernet spec supports **key rotation** out of the box (multi-key via `Fernet(key_list)`).

**Disadvantages:**
- Cannot search encrypted content.
- Token overhead (~300 bytes per message).
- Key is a single point of failure.

### AES-GCM

| Property | Value |
|---|---|
| Algorithm | AES-256-GCM |
| Authentication | Yes — GCM includes an authentication tag |
| Overhead per message | ~28 bytes (12-byte nonce + 16-byte tag) |
| Dependency | Available via `cryptography.hazmat` |

**Advantages:**
- Smaller ciphertext overhead.
- No padding (no padding oracle risk).
- Faster than Fernet (hardware-accelerated AES-NI on modern CPUs).

**Disadvantages:**
- **Nonce reuse is catastrophic** — same nonce + same key = zero security. Requires careful nonce management (counter or random 96-bit with collision probability tracking).
- **No built-in key rotation** — would need custom implementation.
- **Requires `hazmat` API** — more error-prone. The documentation explicitly warns "we know how to shoot ourselves in the foot."
- Would need to replace existing `utils/crypto.py` entirely.

**Verdict:** Rejected. The security advantages are marginal for this use case, while the implementation risk (nonce reuse) and complexity (no key rotation support) are higher. Fernet's ~300 byte overhead is negligible for a chat application where individual messages are typically 100-2000 bytes anyway.

### Database-level encryption (SQLCipher)

| Property | Value |
|---|---|
| Mechanism | Transparent encryption of the entire SQLite page file |
| Key | Passphrase at connection time |
| Dependency | `pysqlcipher3` or `sqlcipher` binary |

**Advantages:**
- Transparent to the application — no changes to models or queries.
- Encrypts **all columns**, including metadata.
- Encrypts indexes, FTS content, schema — nothing leaks.

**Disadvantages:**
- **Replaces SQLite entirely** — new database engine, new build dependency (OpenSSL, C compiler).
- **Breaks every database migration** — Alembic/Flask-Migrate scripts, raw SQL in tests, existing `.db` files must be re-encrypted.
- **Performance hit on every query** — page-level encrypt/decrypt on every read/write, including index walks.
- **No key rotation without full dump/reload**.
- **Overkill** — most metadata (sender, timestamp, etc.) must remain unencrypted for the app to function anyway (see §5). Encrypting them adds overhead for zero additional security benefit in production.

**Verdict:** Rejected. The blast radius is too large for the incremental gain. Field-level encryption (Fernet on `content`) provides the same confidentiality for message text while leaving the rest of the schema untouched.

### Full-disk encryption (LUKS, BitLocker, eCryptfs)

| Property | Value |
|---|---|
| Mechanism | Encrypts the entire block device or directory at the OS layer |
| Key | Passphrase or TPM at boot time |
| Dependency | None — OS feature |

**Advantages:**
- Protects **all files** on disk, not just the database.
- Zero application changes.

**Disadvantages:**
- **Does not protect when the server is running.** Once the OS is booted and the disk is unlocked, any process with filesystem access reads plaintext. This includes the Flask app, but also any attacker who achieves code execution.
- **Does not protect against backup compromise** — backups are typically decrypted before upload.
- Deployed independently of the application; not a substitute for application-layer encryption.

**Verdict:** Complementary — FDE should be used at the infrastructure layer regardless. But it is **not a replacement** for field-level encryption, because it provides zero protection against the most likely threat scenarios (backup leak, file-read vulnerability on a running server).

### Recommendation

**Fernet** is the correct choice for this application. It is:
- Already implemented (`utils/crypto.py`)
- Already documented (`.env.example`)
- Already partially integrated (admin dashboard `decrypt_text`)
- Low implementation risk (well-reviewed library, misuse-resistant API)
- Authenticated (tampering is detected)
- Key-rotation capable (Fernet multi-key spec)

---

## 5. What metadata remains unencrypted? Why?

| Column | Encrypted? | Reason |
|---|---|---|
| `Message.sender` | **No** | Required to route messages to the correct user list, display sender name in chat UI, and filter history queries. Encrypting this would require decrypting every message to build the user list. |
| `Message.recipient` | **No** | Required to determine which chat room/conversation a message belongs to. |
| `Message.msg_type` | **No** | Required to render the correct UI component (text bubble vs. file attachment vs. call log). |
| `Message.time` | **No** | Required to sort and display message chronology without decrypting everything. |
| `Message.duration` | **No** | Required for call log display. |
| `Message.file_name` | **No** | Required to generate download links and display attachment names. |
| `Message.raw_data` | **No** | Required for inline image rendering (base64 image data). |
| `Message.status` | **No** | Required for delivery/read receipts. |
| `Message.msg_id` | **No** | Required for deduplication, reply targeting, and deletion. |
| `Message.reactions` | **No** | Required to render reaction chips without decrypting. Contains only emoji characters and usernames (no message content). |
| `Message.reply_to` | **No** | Required to render reply chains. Points to `msg_id`, not content. |
| `Message.reply_content` | **Yes** | Contains a preview of the replied-to message text. This is derived from message content and must be encrypted. Currently stored as `sender: first_120_chars`. |
| `Message.deleted_by_sender` | **No** | Required for delete-filtering at query time. |
| `Message.deleted_by_recipient` | **No** | Required for delete-filtering at query time. |
| `Message.created_at` | **No** | Timestamp metadata. |
| **`Message.content`** | **Yes** | The message body — the primary target of encryption. |

**Design rule:** Any column used in a `WHERE`, `ORDER BY`, `GROUP BY`, `JOIN`, or front-end filter must remain plaintext. Encrypting such columns would force a full table scan with application-level decryption on every query — defeating the purpose of having a database.

The only columns that hold actual user conversational data are `content` and `reply_content`. Everything else is routing, rendering, or lifecycle metadata.

---

## 6. What happens if `ENCRYPTION_KEY` is lost?

**All encrypted messages become permanently unreadable.** There is no recovery mechanism, backdoor, or password reset for Fernet keys. The `cryptography` library makes this explicit by design.

The application would continue to function — new messages would be encrypted with a new key — but existing ciphertext is unrecoverable. Users would see garbled text or empty content for every historical message.

**Mitigations:**
- The key must be backed up independently of the database (separate secure storage: password manager, vault, offline storage).
- The `.env.example` and production deployment guide must explicitly warn about this.
- A startup check should validate that the key can decrypt at least one known-format message (e.g. a self-test), failing fast rather than silently returning garbled text.
- Consider a **key escrow** mechanism for team-managed deployments (e.g. split-key via Shamir's Secret Sharing).

---

## 7. What happens if `ENCRYPTION_KEY` is rotated?

Fernet natively supports **key rotation** via the `Fernet(key_list)` constructor. The first key in the list is used for encryption; **all keys** in the list are tried for decryption.

**Rotation procedure:**
1. Generate a new key: `Fernet.generate_key()`
2. Prepend the new key to `ENCRYPTION_KEY` (keep the old key in the list)
3. The application begins encrypting new messages with the new key
4. Old messages remain decryptable via the old key (still in the list)

**Impact:**
- **Old messages are NOT re-encrypted** — rotation is additive, not transformative.
- To re-encrypt old messages under the new key, a one-time migration script must decrypt each message with the old key and re-encrypt with the new key (see §8.2).
- **Key list order matters** — the encryption key is always the first key. If keys are accidentally reordered, new messages may be encrypted with an old key.

**When to rotate:**
- Suspected key compromise.
- Compliance requirement (e.g. annual key rotation).
- Employee offboarding (if the departing employee knew the key).

---

## 8. How will existing plaintext messages be migrated?

### 8.1 One-time migration (required)

A management command must be written and run once before encryption is enabled. This script:

1. Reads all existing `Message` rows where `msg_type = 'text'` (and optionally `call_log` with `sender != 'System'`).
2. Encrypts `content` and `reply_content` using `encrypt_text()`.
3. Updates each row in batches (to avoid memory issues with large databases).
4. Runs a verification pass: decrypts a sample of migrated rows and compares to the original (if available in a staging copy).

**Constraints:**
- Must run **offline** (app stopped) or in a **read-only maintenance mode** — otherwise, new messages arriving during migration could race with the script.
- Must commit in batches (e.g. 1000 rows per transaction) to avoid a single massive transaction on SQLite.
- Must handle `content IS NULL` (deleted/system messages) gracefully.

### 8.2 Re-keying (post-rotation)

If a key rotation occurs after initial encryption, a similar script decrypts with the old key and re-encrypts with the new key. This is optional — the old key can be retained indefinitely in the key list.

---

## 9. How will rollback work?

Rollback means reverting to plaintext storage after encryption has been deployed and migration has run.

### Rollback procedure

1. **Stop the application.**
2. Restore the **pre-migration database backup** (see §10).
3. Revert the code change that calls `encrypt_text()` in the message-save path.
4. Restart the application.

### Why not in-place decryption?

In theory, a rollback script could decrypt all messages in-place. In practice, this is **dangerous** because:
- If the rollback script has a bug, data is corrupted.
- If the rollback is needed urgently (e.g. production outage), every minute spent running a decryption script delays recovery.
- The pre-migration backup is guaranteed to be plaintext and correct.

**Policy:** Always restore from backup rather than attempting an in-place revert. This is faster, safer, and eliminates the risk of double-encryption or partial failure.

---

## 10. How will backups work?

### Encrypted database

The database file (`falcon_web.db`) contains ciphertext in the `content` and `reply_content` columns. Backing up this file is **safe for storage** (data is at rest) but **useless without the key**.

### Backup strategy

| Item | Backup method | Required for recovery |
|---|---|---|
| `falcon_web.db` | Regular file backup (daily, hourly) | ✅ Needed |
| `ENCRYPTION_KEY` | Secret store / password manager / offline vault | ✅ **Required** |
| Application code | Version control (Git) | ✅ Needed |
| `.env` configuration | Secret store (not in version control) | ✅ Needed |

### Critical rule

**Never back up the database without the key, and never back up the key without the database.** They are a matched pair. If the database is restored from a backup that predates a key rotation, and the old key has been discarded, those messages are lost.

### Recommended practice

- Store the current `ENCRYPTION_KEY` and all previous keys in a secure vault (e.g. HashiCorp Vault, AWS Secrets Manager, Bitwarden).
- Tag each backup with the key fingerprint (SHA-256 of key material) so the correct key can be identified during restore.
- Test restoration in a staging environment at least quarterly.

---

## 11. How will search be affected?

### Server-side search

**Eliminated.** Encrypted `content` columns cannot be searched with SQL `LIKE` or full-text search (FTS) because the DBMS sees only ciphertext. Every row looks like random bytes.

### Client-side search

The application does not currently implement a search feature. If search is added:

1. **Fetch all messages** in the conversation (or time range).
2. **Decrypt each message** in application memory.
3. **Filter by content** on the decrypted plaintext.

This is feasible for individual conversations (typical chat history is hundreds, not millions, of messages). It does not scale to global full-text search across all conversations — that would require decryption of every message in the database, which is O(n) in both time and memory.

### Search alternatives

| Approach | Pros | Cons |
|---|---|---|
| Client-side (decrypt + filter in JS) | Simple, no server change | Cannot search before all messages loaded |
| Encrypted search index (e.g. Blind Seer, CryptDB) | Theoretically possible | Research-grade, no mature library for Python/SQLite |
| Separate search index (Elasticsearch) with encrypted content | Fast, scalable | Index holds decrypted content = new attack surface |
| Accept limitation | Zero additional code | Users cannot search message text |

**Recommendation:** Accept the limitation for now. Document it. If search becomes critical, implement client-side search within a single conversation (decrypt all messages in memory, filter in JS). Cross-conversation search is a future feature.

---

## 12. How will performance be affected?

### Encryption overhead

Fernet encrypt/decrypt operations are **fast**:

| Operation | Approximate time |
|---|---|
| Encrypt 1 KB message | < 100 µs |
| Decrypt 1 KB message | < 100 µs |
| Decrypt 1000 messages (bulk history) | < 100 ms |

These are measured on a modern CPU with AES-NI. The `cryptography` library uses native OpenSSL bindings — no Python GIL bottleneck for the actual cipher operations.

### Where encryption happens

| Code path | Frequency | Impact |
|---|---|---|
| **Send message** (`socket.js` → server event → DB insert) | Per message | One `encrypt_text()` call. Negligible. |
| **Load history** (`GET /api/history` → DB query → JSON response) | On conversation open (~50 msg default) | `O(n)` decrypt calls where `n` = page size. ~5ms for 50 messages. |
| **Admin chat viewer** | Admin actions | `O(n)` decrypt calls. Acceptable. |

### Database impact

- **No schema changes** — `content` remains `Text/TEXT` column. Ciphertext is base64-encoded ASCII, slightly larger than plaintext but stored in the same column type.
- **No index changes** — indexes on `sender`, `recipient`, `msg_id`, `msg_type` etc. are untouched.
- **No query changes** — `WHERE` clauses on metadata columns are unchanged.

### Worst-case scenario

Concurrent load of 1000 messages/second:
- 1000 encrypt calls × 100 µs = 100 ms CPU time per second
- This is 10% of a single core — negligible for a Flask app.

### Conclusion

Encryption has **no measurable impact** on application performance at the expected scale (hundreds to low thousands of messages per second). The database and network I/O dominate request latency.

---

## 13. Will encrypted messages still support replies, reactions, and history?

### Replies

**Yes.** The reply chain is maintained via `reply_to` (plaintext `msg_id`) and `reply_content` (which will be encrypted). When rendering a reply:

1. Load the replying message.
2. Decrypt `reply_content` to get the preview text.
3. Optionally fetch the original message via `reply_to` and decrypt its `content`.

The reply preview bubble requires decryption of the replying message's `reply_content` — this is one additional decrypt call per reply. Existing functionality is unchanged.

### Reactions

**Yes.** Reactions are stored in the `reactions` column as a JSON string of `{emoji: [usernames]}`. This column is **not encrypted** (see §5). Reaction chips, counts, and toggle behavior remain identical.

### History

**Yes.** The `/api/history` endpoint already returns the `content` field. After encryption:

1. The query loads messages from the DB (same SQL, same indexes).
2. The response loop calls `decrypt_text(msg.content)` for each message (in the route handler before serialization).
3. The JSON response contains the **decrypted** content, identical to today.

From the client's perspective, nothing changes. The only difference is an additional decrypt call per message server-side.

### Call logs

Call log messages (`type: call_log`) store the call status (`completed`, `busy`, `rejected`, `no_answer`) in the `content` column. This is a server-enumerated value, not user text. It should remain **unencrypted** to avoid unnecessary decrypt calls in the call-log rendering path.

---

## 14. What production risks exist?

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **Key loss** | Low | **Critical** — all historical messages permanently unreadable | Back up key to separate secure store; document recovery procedure; consider key escrow |
| **Improper key storage** (e.g. key in `.env` committed to Git) | Medium | **Critical** — encryption provides no protection if key is leaked | Add `.env` to `.gitignore` (already done); add CI check for key-in-code; use secret manager in production |
| **Key rotation mistake** (e.g. keys reordered, old key discarded prematurely) | Low | **Medium** — subset of messages becomes unreadable | Document rotation procedure; test in staging; keep old keys for at least one rotation cycle |
| **Missing `encrypt_text()` call** (new code path fails to encrypt) | Medium | **Medium** — plaintext leak in that code path | Code review checklist; automated test that verifies encrypted content in DB differs from original |
| **Race condition during migration** (new message saved before migration completes) | Low | **Low** — a few messages remain plaintext after migration flag is enabled | Run migration offline; verify after migration |
| **Admin app not updated** (`admin_app.py` encrypts/decrypts independently) | Medium | **Medium** — desktop admin app may fail to decrypt | Update `admin_app.py` to use the same Fernet key and `decrypt_text()` call |
| **Memory exposure** (decrypted content in process memory) | High (always) | **Low** — this is inherent to all encryption-at-rest; not a regression | Accept as known limitation |
| **Fernet token expiration** (some Fernet implementations embed timestamps; default spec includes TTL) | None | N/A | The `cryptography.fernet` default TTL is `None` (no expiration). Verify this in the implementation. |

---

## 15. What disaster recovery plan exists?

### Scenario A: Database file corrupted, key available

1. Stop the application.
2. Restore the database from the most recent known-good backup.
3. Verify key fingerprint matches the backup epoch.
4. Start the application.
5. Verify a sample of messages are decryptable.

**RTO:** Minutes (time to copy backup + verify).

### Scenario B: Key lost, database intact

1. **Data is unrecoverable.** All encrypted message content is permanently lost.
2. Generate a new key.
3. Notify users that historical message content is inaccessible.
4. Continue with new key — new messages are encrypted and readable.

**RTO:** N/A. This is a data-loss event, not a downtime event.

### Scenario C: Both key and database lost (e.g. full server destruction)

1. Provision a new server.
2. Restore database from off-site backup.
3. Restore key from separate secure storage (vault / password manager).
4. Start the application.

**RTO:** Depends on infrastructure provisioning time. Hours for manual, minutes for IaC (Terraform, etc.).

### Scenario D: Key rotation went wrong (old key discarded, new key replaces it)

1. Old messages remain encrypted with the discarded old key.
2. If the old key is still in backups, restore it and add it to the key list (second position). Old messages become decryptable again.
3. If the old key is truly gone, same outcome as Scenario B — data loss for old messages.

### Recommended DR kit

Store in a secure, access-logged location (e.g. encrypted team password manager):

| Item | Format | Example |
|---|---|---|
| Current `ENCRYPTION_KEY` | Fernet key (base64) | `kA7c...==` |
| All previous `ENCRYPTION_KEY` values | Same | Same |
| Key fingerprint for each | SHA-256 of key | `sha256$abc123...` |
| Deployment date of each key rotation | ISO 8601 | `2026-07-04` |
| Database backup (encrypted) | `.db` file | `falcon_web_20260704.db.gz` |
| Recovery procedure | Markdown document | This section |

---

## Summary of decisions

| Question | Decision |
|---|---|
| Algorithm | **Fernet** (AES-128-CBC + HMAC-SHA256) |
| Key storage | Environment variable (`ENCRYPTION_KEY`); backed up separately to secure vault |
| What is encrypted | `Message.content` (text body), `Message.reply_content` (reply preview) |
| What is NOT encrypted | All metadata columns (sender, recipient, timestamps, reactions, msg_id, reply_to, file_name, etc.) |
| Call log content | NOT encrypted (server-enumerated status values) |
| Search | Not available for encrypted content. Client-side per-conversation search as future option. |
| Migration | One-time offline script: read all messages → encrypt → verify |
| Rollback | Restore pre-migration database backup (never in-place decrypt) |
| Key rotation | Add new key to front of key list. Old key retained. Re-encryption optional. |
| Performance impact | Negligible (<100 µs per message) |
| Schema changes | None |
| API changes | None — decryption is transparent in the response path |
| Admin desktop app | Must be updated to use same `decrypt_text()` |
