#!/usr/bin/env python3
"""
encrypt_migration.py — Encrypt/decrypt existing message content at rest.

Usage:
    python encrypt_migration.py --dry-run          # Report stats, no DB changes
    python encrypt_migration.py --run               # Backup + batch encrypt
    python encrypt_migration.py --verify            # Decrypt random samples
    python encrypt_migration.py --run --no-backup   # Skip backup

Requires ENCRYPTION_KEY to be set.
"""
import argparse
import os
import sqlite3
import shutil
import sys
import random
from datetime import datetime

# ── Validate key early ────────────────────────────────────────────────
if not os.environ.get('ENCRYPTION_KEY'):
    print("FATAL: ENCRYPTION_KEY environment variable is not set.")
    print("Set it before running this script, e.g.:")
    print("  $env:ENCRYPTION_KEY = 'base64_32_byte_key_here'")
    sys.exit(1)

from utils.crypto import encrypt_text, decrypt_text, is_encrypted

DB_PATH = os.environ.get('DB_PATH', 'database/falcon_web.db')
BATCH_SIZE = 100


def get_connection():
    if not os.path.isfile(DB_PATH):
        print(f"FATAL: Database not found at {DB_PATH}")
        sys.exit(1)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_stats(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM message")
    total = cursor.fetchone()[0]

    cursor.execute("SELECT id, msg_type, content, reply_content FROM message")
    plaintext = 0
    encrypted = 0
    skipped = 0
    errors = []

    for row in cursor:
        if row['msg_type'] != 'text':
            skipped += 1
            continue

        content = row['content']
        reply = row['reply_content']

        try:
            c_enc = is_encrypted(content) if content else True
            r_enc = is_encrypted(reply) if reply else True

            if c_enc and r_enc:
                encrypted += 1
            else:
                plaintext += 1
        except Exception as e:
            errors.append(f"msg.id={row['id']}: {e}")
            plaintext += 1

    return {
        "total_messages": total,
        "plaintext": plaintext,
        "already_encrypted": encrypted,
        "skipped_non_text": skipped,
        "errors": errors,
    }


def dry_run():
    conn = get_connection()
    try:
        stats = get_stats(conn)
        print("=" * 50)
        print("  ENCRYPTION MIGRATION — DRY RUN")
        print("=" * 50)
        print(f"  Total messages:         {stats['total_messages']}")
        print(f"  Plaintext (needs enc):  {stats['plaintext']}")
        print(f"  Already encrypted:      {stats['already_encrypted']}")
        print(f"  Skipped (non-text):     {stats['skipped_non_text']}")
        if stats['errors']:
            print(f"  Errors:                 {len(stats['errors'])}")
            for e in stats['errors'][:10]:
                print(f"    - {e}")
        print("-" * 50)
        to_process = stats['plaintext']
        if to_process == 0:
            print("  No messages to encrypt.")
        else:
            print(f"  Ready to encrypt {to_process} message(s).")
            print(f"  Estimated batches of {BATCH_SIZE}: {(to_process + BATCH_SIZE - 1) // BATCH_SIZE}")
        print("=" * 50)
    finally:
        conn.close()


def backup_database():
    backup_path = f"{DB_PATH}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    print(f"  Backing up {DB_PATH} → {backup_path} ... ", end="", flush=True)
    shutil.copy2(DB_PATH, backup_path)
    print("OK")
    return backup_path


def migrate(batch_size=BATCH_SIZE, do_backup=True):
    if do_backup:
        backup_database()

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id, content, reply_content FROM message WHERE msg_type = 'text'")
    rows = cursor.fetchall()

    total = len(rows)
    encrypted_count = 0
    error_count = 0
    batch = []

    print(f"  Processing {total} text message(s) in batches of {batch_size} ...")

    for idx, row in enumerate(rows, 1):
        msg_id = row['id']
        content = row['content']
        reply = row['reply_content']

        new_content = content
        new_reply = reply

        try:
            if content and not is_encrypted(content):
                new_content = encrypt_text(content)
            if reply and not is_encrypted(reply):
                new_reply = encrypt_text(reply)
        except Exception as e:
            print(f"  ERROR on msg.id={msg_id}: {e}")
            error_count += 1
            continue

        if new_content != content or new_reply != reply:
            batch.append((new_content, new_reply, msg_id))

        if len(batch) >= batch_size or idx == total:
            if batch:
                cursor.executemany(
                    "UPDATE message SET content = ?, reply_content = ? WHERE id = ?",
                    batch
                )
                conn.commit()
                encrypted_count += len(batch)
                batch = []
            if idx % (batch_size * 5) == 0 or idx == total:
                print(f"  Progress: {idx}/{total} ({(idx / total) * 100:.1f}%)")

    print(f"  Done. Encrypted: {encrypted_count}, Errors: {error_count}")
    conn.close()


def verify(sample_count=10):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM message WHERE msg_type = 'text'")
    total = cursor.fetchone()[0]

    if total == 0:
        print("  No text messages to verify.")
        conn.close()
        return

    actual_samples = min(sample_count, total)
    cursor.execute(
        "SELECT id, content, reply_content FROM message WHERE msg_type = 'text' ORDER BY RANDOM() LIMIT ?",
        (actual_samples,)
    )
    rows = cursor.fetchall()

    passed = 0
    failed = 0

    for row in rows:
        msg_id = row['id']
        content = row['content']
        reply = row['reply_content']

        try:
            if content:
                decrypted = decrypt_text(content)
                if decrypted == content and len(content) > 20:
                    print(f"  FAIL msg.id={msg_id}: content appears undecrypted (still looks like ciphertext)")
                    failed += 1
                else:
                    passed += 1
            if reply:
                decrypted_reply = decrypt_text(reply)
                if decrypted_reply == reply and len(reply) > 20:
                    print(f"  FAIL msg.id={msg_id}: reply_content appears undecrypted")
                    failed += 1
        except Exception as e:
            print(f"  FAIL msg.id={msg_id}: {e}")
            failed += 1

    print(f"  Verification: {passed}/{actual_samples} passed, {failed} failed")
    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Encrypt message content at rest")
    parser.add_argument('--dry-run', action='store_true', help='Show stats without modifying DB')
    parser.add_argument('--run', action='store_true', help='Run migration (backup + encrypt)')
    parser.add_argument('--verify', action='store_true', help='Verify decryption on random samples')
    parser.add_argument('--no-backup', action='store_true', help='Skip database backup')
    parser.add_argument('--batch-size', type=int, default=BATCH_SIZE, help=f'Batch size (default: {BATCH_SIZE})')
    parser.add_argument('--samples', type=int, default=10, help='Number of samples to verify (default: 10)')

    args = parser.parse_args()

    if not (args.dry_run or args.run or args.verify):
        parser.print_help()
        sys.exit(1)

    if args.dry_run:
        dry_run()

    if args.run:
        print()
        print("--- Starting Migration ---")
        migrate(batch_size=args.batch_size, do_backup=not args.no_backup)
        print("--- Migration Complete ---")

    if args.verify:
        print()
        print("--- Verification ---")
        verify(sample_count=args.samples)
        print("--- Verification Complete ---")


if __name__ == '__main__':
    main()
