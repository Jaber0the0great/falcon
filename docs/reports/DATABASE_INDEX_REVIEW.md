# Database Index Review

## Schema

### Message Table

```sql
CREATE TABLE message (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sender          VARCHAR(80) NOT NULL,
    recipient       VARCHAR(80) NOT NULL,
    msg_type        VARCHAR(50) NOT NULL,
    content         TEXT,
    time            VARCHAR(50),
    duration        INTEGER,
    file_name       VARCHAR(255),
    raw_data        TEXT,
    status          VARCHAR(50) DEFAULT 'sent',
    msg_id          VARCHAR(100) UNIQUE NOT NULL,
    reactions       TEXT DEFAULT '{}',
    reply_to        VARCHAR(80),
    reply_content   TEXT,
    deleted_by_sender      BOOLEAN DEFAULT 0 NOT NULL,
    deleted_by_recipient   BOOLEAN DEFAULT 0 NOT NULL,
    created_at      DATETIME
);
```

### Current Indexes

| Name | Columns | Type |
|------|---------|------|
| `pk_message` | `id` | PRIMARY KEY (auto-indexed) |
| `uq_message_msg_id` | `msg_id` | UNIQUE (auto-indexed) |

**No other indexes exist.** Every broadcast query performs a full table scan.

---

## Query Analysis

### Query 1: Unread Counts (batch, after P1+P2)

```sql
SELECT sender, recipient, COUNT(id) AS cnt
FROM message
WHERE recipient IN ('alice', 'bob', ...)
  AND status != 'read'
GROUP BY sender, recipient
```

| Property | Detail |
|----------|--------|
| Filter columns | `recipient` (IN list), `status` (inequality) |
| Group columns | `sender`, `recipient` |
| Order columns | none |
| Current execution | **Full table scan** — SQLite reads every row in the `message` table |
| Rows examined at 200 users | ~19,460 (all messages) |
| Likely seqscan? | **Yes.** Without an index, SQLite has no choice. |

**Recommended index:** `(recipient, status, sender)`

```sql
CREATE INDEX ix_message_recipient_status_sender
    ON message (recipient, status, sender);
```

| Aspect | Detail |
|--------|--------|
| Why it helps | `recipient` filters first (fast IN lookup), `status` narrows to unread, `sender` covers GROUP BY without sort |
| Query benefited | Unread count batch query |
| Expected impact | Full scan → index range scan over only rows matching `recipient IN (...)` |
| Storage cost | ~(VARCHAR(80) × 3 + rowid) × unread rows — negligible |
| Write overhead | Every INSERT/UPDATE on `sender/recipient/status` updates the index |
| Worth adding now? | **Yes.** Trivial storage cost, immediate query improvement. |

---

### Query 2: Last-message per pair (batch, after P2)

```sql
SELECT MAX(id) AS max_id
FROM message
WHERE sender IN ('alice', 'bob', ...)
  AND recipient IN ('alice', 'bob', ...)
GROUP BY
    CASE WHEN sender <= recipient THEN sender ELSE recipient END,
    CASE WHEN sender <= recipient THEN recipient ELSE sender END
```

Then JOIN back: `SELECT message.* ... JOIN subq ON message.id = subq.max_id`

| Property | Detail |
|----------|--------|
| Filter columns | `sender` (IN list), `recipient` (IN list) |
| Group columns | `CASE` expressions over `(sender, recipient)` |
| Order columns | none (MAX(id) is an aggregate) |
| Current execution | **Full table scan** — every message row read |
| Likely seqscan? | **Yes.** Even with an index on `(sender, recipient)`, the CASE expressions prevent SQLite from using the index for the GROUP BY. However, an index on `(sender, recipient)` would still help the WHERE clause filter rows. |

**Recommended index:** `(sender, recipient, id)`

```sql
CREATE INDEX ix_message_sender_recipient_id
    ON message (sender, recipient, id);
```

| Aspect | Detail |
|--------|--------|
| Why it helps | The WHERE `sender IN (...)` filter uses the index prefix. The `id` column at the end covers `MAX(id)` as a "top-of-index" lookup per group (though the CASE grouping still requires a sort). |
| Query benefited | Last-message batch subquery |
| Expected impact | Full scan → much smaller scan of only rows matching `sender IN (usernames) AND recipient IN (usernames)`. However, since the `usernames` list includes ALL users (not just online), this is essentially "all messages." Impact is smaller than query 1's index. |
| Storage cost | ~(VARCHAR(80) × 2 + INTEGER) × all rows — moderate |
| Write overhead | Every INSERT updates the index |
| Worth adding now? | **Defer.** The full table scan is fast enough for the message volumes this app supports (< 1M messages). Only add if message count exceeds 100K and query 2 becomes a bottleneck. |

---

## Recommended Indexes (Priority Order)

### Add Now (Tier 1)

#### Index 1: `(recipient, status, sender)`

```sql
CREATE INDEX ix_message_recipient_status_sender
    ON message (recipient, status, sender);
```

| Property | Value |
|----------|-------|
| **Impact** | Eliminates full table scan for unread count query |
| **Query** | `SELECT sender, recipient, COUNT(id) WHERE recipient IN (...) AND status != 'read' GROUP BY sender, recipient` |
| **Storage** | Small (only unread rows would need index entries in practice) |
| **Write cost** | Low — `status` changes from 'sent' → 'read' on mark_read, requiring index update |
| **Priority** | **High** — this query runs on every connect, disconnect, message send, message read, and status change |

---

### Add Later (Tier 2)

#### Index 2: `(sender, recipient, id)`

```sql
CREATE INDEX ix_message_sender_recipient_id
    ON message (sender, recipient, id);
```

| Property | Value |
|----------|-------|
| **Impact** | Reduces scan scope for last-message query, covers MAX(id) |
| **Query** | Last-message subquery: `WHERE sender IN (...) AND recipient IN (...) GROUP BY CASE...` |
| **Storage** | Moderate (every message row indexed) |
| **Write cost** | Moderate (every INSERT adds one entry) |
| **Priority** | **Medium** — current full scan is tolerable up to ~100K messages |

---

## Redundant / Unnecessary Indexes

None currently exist (only PK and unique constraints).

## Composite Index Opportunities

The two indexes above (`(recipient, status, sender)` and `(sender, recipient, id)`) cover all broadcast queries. No additional composite indexes are needed.

## SQLite-Specific Notes

1. **SQLite uses one index per table per query** (in most cases). It picks the best single index. The `(recipient, status, sender)` index is the most important because the unread query runs most frequently.
2. **`IN (...)` with many values**: SQLite handles `IN` lists with hundreds of entries efficiently. For 500 online users, `recipient IN (500 values)` is well within SQLite's capability.
3. **`status != 'read'` inequality**: SQLite can use the index for the inequality filter as well as the equality prefix.
4. **`VARCHAR(80)` index entries**: Each entry is ~80 bytes × 3 columns + rowid overhead. For 100K messages, the `(recipient, status, sender)` index is ~3 MB.
