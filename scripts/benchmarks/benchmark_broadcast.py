"""
Benchmark broadcast_user_list() at various scales.

Compares three implementations:
  Original — per-pair COUNT + per-pair last-msg queries  (before P1/P2)
  After P1  — batched unread counts, per-pair last-msg queries
  After P2  — batched unread counts + batched last-msg queries
"""
import os, sys, time, json, gc

os.environ['SECRET_KEY'] = 'bench-secret'
os.environ['ADMIN_PASSWORD_HASH'] = 'x'
os.environ['LOG_LEVEL'] = 'CRITICAL'

import eventlet
eventlet.monkey_patch()

from app import create_app
from database.database import db
from models.models import User, Message
from sqlalchemy import func, case, or_, and_, event as sa_event
from datetime import datetime

# ── Scales ──────────────────────────────────────────────────
SCALES = [
    ("10 users (10 online)",   10,  10,  5),
    ("100 users (70 online)",  100, 70,  3),
    ("200 users (140 online)", 200, 140, 2),
]

_query_count = 0

def count_queries(conn, cursor, statement, parameters, context, executemany):
    global _query_count
    _query_count += 1


def create_dataset(num_users, num_online, msg_per_pair):
    usernames = [f"u_{i:04d}" for i in range(num_users)]
    online_set = set(usernames[:num_online])

    for name in usernames:
        db.session.add(User(username=name, password_hash='x', is_banned=False,
                            status='Available' if name in online_set else 'Offline'))
    db.session.commit()

    all_users = User.query.all()
    msg_id = 0
    for i in range(num_online):
        for j in range(i + 1, num_online):
            for k in range(msg_per_pair):
                sender = usernames[i] if k % 2 == 0 else usernames[j]
                recip = usernames[j] if k % 2 == 0 else usernames[i]
                db.session.add(Message(
                    sender=sender, recipient=recip, msg_type='text',
                    content=f"m_{msg_id}",
                    status='read' if k % 2 == 0 else 'sent',
                    msg_id=f"mid_{msg_id}",
                ))
                msg_id += 1
    db.session.commit()

    online_users = [u for u in all_users if u.username in online_set]
    return all_users, online_users


def broadcast_original(all_users, online_users):
    for recipient in online_users:
        users_info = []
        for u in all_users:
            if u.username == recipient.username:
                continue
            uc = Message.query.filter_by(
                sender=u.username, recipient=recipient.username
            ).filter(Message.status != 'read').count()

            lm = Message.query.filter(
                or_(
                    and_(Message.sender == u.username, Message.recipient == recipient.username),
                    and_(Message.sender == recipient.username, Message.recipient == u.username)
                )
            ).order_by(Message.id.desc()).first()

            epoch = datetime(1970, 1, 1)
            lmt = int((lm.created_at - epoch).total_seconds() * 1000) if (lm and lm.created_at) else 0
            users_info.append({
                "name": u.username, "status": u.status,
                "last_seen": (u.last_seen.isoformat() + "Z") if u.last_seen else None,
                "unread_count": uc, "last_message_time": lmt,
            })


def broadcast_p1(all_users, online_users):
    online_unames = [u.username for u in online_users]
    rows = db.session.query(
        Message.sender, Message.recipient, func.count(Message.id).label('cnt')
    ).filter(
        Message.recipient.in_(online_unames), Message.status != 'read'
    ).group_by(Message.sender, Message.recipient).all()
    ulookup = {(r.sender, r.recipient): r.cnt for r in rows}

    for recipient in online_users:
        users_info = []
        for u in all_users:
            if u.username == recipient.username:
                continue
            uc = ulookup.get((u.username, recipient.username), 0)
            lm = Message.query.filter(
                or_(
                    and_(Message.sender == u.username, Message.recipient == recipient.username),
                    and_(Message.sender == recipient.username, Message.recipient == u.username)
                )
            ).order_by(Message.id.desc()).first()
            epoch = datetime(1970, 1, 1)
            lmt = int((lm.created_at - epoch).total_seconds() * 1000) if (lm and lm.created_at) else 0
            users_info.append({
                "name": u.username, "status": u.status,
                "last_seen": (u.last_seen.isoformat() + "Z") if u.last_seen else None,
                "unread_count": uc, "last_message_time": lmt,
            })


def broadcast_p2(all_users, online_users):
    online_unames = [u.username for u in online_users]
    rows = db.session.query(
        Message.sender, Message.recipient, func.count(Message.id).label('cnt')
    ).filter(
        Message.recipient.in_(online_unames), Message.status != 'read'
    ).group_by(Message.sender, Message.recipient).all()
    ulookup = {(r.sender, r.recipient): r.cnt for r in rows}

    all_unames = [u.username for u in all_users]
    subq = db.session.query(
        func.max(Message.id).label('max_id'),
    ).select_from(Message).filter(
        Message.sender.in_(all_unames), Message.recipient.in_(all_unames)
    ).group_by(
        case((Message.sender <= Message.recipient, Message.sender), else_=Message.recipient),
        case((Message.sender <= Message.recipient, Message.recipient), else_=Message.sender),
    ).subquery()

    lm_rows = db.session.query(Message).join(subq, Message.id == subq.c.max_id).all()
    lmlookup = {}
    for m in lm_rows:
        k = (m.sender, m.recipient) if m.sender <= m.recipient else (m.recipient, m.sender)
        lmlookup[k] = m

    epoch = datetime(1970, 1, 1)
    for recipient in online_users:
        users_info = []
        for u in all_users:
            if u.username == recipient.username:
                continue
            uc = ulookup.get((u.username, recipient.username), 0)
            k = (u.username, recipient.username) if u.username <= recipient.username else (recipient.username, u.username)
            lm = lmlookup.get(k)
            lmt = int((lm.created_at - epoch).total_seconds() * 1000) if (lm and lm.created_at) else 0
            users_info.append({
                "name": u.username, "status": u.status,
                "last_seen": (u.last_seen.isoformat() + "Z") if u.last_seen else None,
                "unread_count": uc, "last_message_time": lmt,
            })


def measure(impl_fn, all_users, online_users):
    """Return (query_count, elapsed_ms)."""
    global _query_count
    gc.collect()
    sa_event.listen(db.engine, 'before_cursor_execute', count_queries)
    _query_count = 0
    t0 = time.perf_counter()
    impl_fn(all_users, online_users)
    elapsed = time.perf_counter() - t0
    sa_event.remove(db.engine, 'before_cursor_execute', count_queries)
    return _query_count, round(elapsed * 1000, 2)


def main():
    app = create_app()
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'

    results = []

    for label, num_u, num_on, mpp in SCALES:
        print(f"\n{'='*60}")
        print(f"Scale: {label}")
        print(f"{'='*60}")

        with app.app_context():
            db.create_all()
            all_u, on_u = create_dataset(num_u, num_on, mpp)
            pairs = num_on * (num_on - 1) // 2
            print(f"  Users: {num_u}, Online: {num_on}, Pairs: {pairs}")

            # Warm
            broadcast_p2(all_u, on_u)

            for vname, fn in [
                ("Original", broadcast_original),
                ("After P1", broadcast_p1),
                ("After P2", broadcast_p2),
            ]:
                qc, tms = measure(fn, all_u, on_u)
                emits = len(on_u)
                pay_kb = round(emits * (len(all_u) - 1) * 200 / 1024, 1)

                print(f"  {vname:12s}:  queries={qc:>8d}  time={tms:>8.2f}ms  "
                      f"emits={emits}  payload~={pay_kb}KB")

                results.append({
                    "scale": label, "users": num_u, "online": num_on,
                    "pairs": pairs, "version": vname, "queries": qc,
                    "time_ms": tms, "emits": emits, "payload_est_kb": pay_kb,
                })

            db.drop_all()

    # ── Summary ──
    print(f"\n\n{'='*80}")
    print("SUMMARY TABLE")
    print(f"{'='*80}")
    print(f"{'Scale':<22s} {'Version':<12s} {'Queries':>8s} {'Time(ms)':>10s} {'Emits':>6s} {'Payload(KB)':>11s}")
    print("-" * 69)
    for r in results:
        print(f"{r['scale']:<22s} {r['version']:<12s} {r['queries']:>8d} "
              f"{r['time_ms']:>10.2f} {r['emits']:>6d} {r['payload_est_kb']:>10.1f}")
    print()

    # Speedup ratios
    for label in set(r['scale'] for r in results):
        scale_results = [r for r in results if r['scale'] == label]
        orig_time = next(r['time_ms'] for r in scale_results if r['version'] == 'Original')
        for r in scale_results:
            if r['version'] != 'Original':
                ratio = orig_time / r['time_ms'] if r['time_ms'] > 0 else float('inf')
                print(f"  {label}: {r['version']} is {ratio:.1f}x faster than Original")

    with open('benchmark_results.json', 'w') as f:
        json.dump(results, f, indent=2)
    print("\nbenchmark_results.json written")


if __name__ == '__main__':
    main()
