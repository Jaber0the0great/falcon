# Project Structure — Falcon Web Chat v1.0.0

## Overview

This document describes the project structure after the Version 1.0.0 reorganization.  
The reorganization consolidated ~30 root-level files into a clean directory hierarchy while preserving zero `sys.path` hacks and maintaining all 15 passing tests.

---

## Old Structure (Before)

```
falcon-web-chat/                        # 58 root-level entries
├── .env.example
├── .gitignore
├── CHANGELOG.md
├── LICENSE
├── README.md
├── requirements.txt
├── version.py
├── app.py                              # Flask entry point
├── config.py                           # Configuration (BASE_DIR anchor)
├── falcon_web.db                       # SQLite database (root level)
│
├── admin_app.py                        # Desktop admin (PyQt6)
├── test_web_app.py                     # Unit tests
├── test_upload_manual.py               # Upload tests
├── reset_db.py                         # Developer utility
├── check_tables.py                     # Developer utility
├── benchmark_broadcast.py              # Benchmark script
├── encrypt_migration.py                # Migration script
│
├── Run_Web.bat                         # Batch files (5)
├── Run_Admin.bat
├── Run_Cloudflare.bat
├── Run_All.bat
├── Stop_All.bat
│
├── cloudflared.exe                     # Generated artifacts (4)
├── benchmark_results.json
├── stderr.txt
├── stdout.txt
│
├── API_STANDARDIZATION_PLAN.md         # Documentation (27 files)
├── CACHE_RECOMMENDATION.md
├── DATABASE_INDEX_REVIEW.md
├── DEPLOYMENT_GUIDE.md
├── ENCRYPTION_DESIGN_REVIEW.md
├── FINAL_SECURITY_AUDIT.md
├── KEY_ROTATION.md
├── PERFORMANCE_BENCHMARK.md
├── PRODUCTION_READINESS.md
├── PROJECT_POLISH_REPORT.md
├── PROJECT_STATE_AUDIT.md
├── PROJECT_STRUCTURE_REVIEW.md
├── RELEASE_CANDIDATE.md
├── RELEASE_CHECKLIST.md
├── REMAINING_WORK.md
├── ROOT_CAUSE_ANALYSIS.md
├── SECURITY_AUDIT_PHASE_F.md
├── SECURITY_DEPENDENCY_GRAPH.md
├── SECURITY_HARDENING_PLAN.md
├── SECURITY_IMPLEMENTATION_ROADMAP.md
├── SECURITY_IMPLEMENTATION_ROADMAP_V2.md
├── SECURITY_REPORT.md
├── SECURITY_REPORT_VALIDATED.md
├── SOCKET_SECURITY_PLAN.md
├── SOCKET_THREAT_MODEL.md
├── VERSION_1_ROADMAP.md
├── VERSION_READINESS_REPORT.md
├── XSS_SINK_ANALYSIS.md
│
├── database/
│   └── database.py
├── models/
│   └── models.py
├── routes/
│   ├── __init__.py
│   ├── auth.py
│   ├── api.py
│   ├── admin.py
│   └── main.py
├── sockets/
│   └── events.py
├── utils/
│   ├── __init__.py
│   ├── crypto.py
│   ├── migration.py
│   ├── api/
│   │   ├── __init__.py
│   │   ├── response.py
│   │   └── errors.py
│   └── security/
│       ├── __init__.py
│       ├── constants.py
│       ├── validators.py
│       ├── sanitizers.py
│       ├── decorators.py
│       ├── permissions.py
│       ├── rate_limiter.py
│       └── exceptions.py
├── templates/
│   └── (5 HTML templates)
├── static/
│   ├── css/
│   ├── js/
│   ├── audio/
│   └── uploads/
└── flask_session/
```

---

## New Structure (After)

```
falcon-web-chat/                        # 12 root entries (clean)
├── .env.example
├── .gitignore
├── CHANGELOG.md
├── LICENSE
├── README.md
├── requirements.txt
├── version.py
├── app.py
├── config.py
│
├── admin/                              # Desktop administration app
│   ├── __init__.py
│   └── admin_app.py                    # Moved from root; PyQt6 admin panel
│
├── assets/                             # Project assets (not Flask-served)
│   ├── .gitkeep
│   ├── branding/
│   ├── icons/
│   └── screenshots/
│
├── backups/                            # Database & key backups
│   ├── .gitkeep
│   └── README.md                       # Restore workflow docs
│
├── database/
│   ├── database.py                     # SQLAlchemy DB init
│   └── falcon_web.db                   # SQLite database (moved from root)
│
├── docs/                               # All documentation
│   ├── audits/
│   │   ├── FINAL_SECURITY_AUDIT.md
│   │   ├── PROJECT_STATE_AUDIT.md
│   │   └── SECURITY_AUDIT_PHASE_F.md
│   ├── guides/
│   │   ├── DEPLOYMENT_GUIDE.md
│   │   └── KEY_ROTATION.md
│   ├── plans/
│   │   ├── API_STANDARDIZATION_PLAN.md
│   │   ├── SECURITY_HARDENING_PLAN.md
│   │   ├── SECURITY_IMPLEMENTATION_ROADMAP.md
│   │   ├── SECURITY_IMPLEMENTATION_ROADMAP_V2.md
│   │   └── SOCKET_SECURITY_PLAN.md
│   ├── releases/
│   │   ├── RELEASE_CANDIDATE.md
│   │   └── RELEASE_CHECKLIST.md
│   ├── reports/
│   │   ├── CACHE_RECOMMENDATION.md
│   │   ├── DATABASE_INDEX_REVIEW.md
│   │   ├── PERFORMANCE_BENCHMARK.md
│   │   ├── PRODUCTION_READINESS.md
│   │   ├── PROJECT_POLISH_REPORT.md
│   │   └── VERSION_READINESS_REPORT.md
│   ├── reviews/
│   │   ├── ENCRYPTION_DESIGN_REVIEW.md
│   │   ├── ROOT_CAUSE_ANALYSIS.md
│   │   ├── SECURITY_DEPENDENCY_GRAPH.md
│   │   ├── SECURITY_REPORT.md
│   │   ├── SECURITY_REPORT_VALIDATED.md
│   │   ├── SOCKET_THREAT_MODEL.md
│   │   └── XSS_SINK_ANALYSIS.md
│   ├── roadmaps/
│   │   └── VERSION_1_ROADMAP.md
│   ├── PROJECT_STRUCTURE.md            # This file
│   └── REMAINING_WORK.md
│
├── flask_session/                      # Session files (gitignored)
│
├── logs/                               # Runtime logs (gitignored)
│   ├── .gitkeep
│   └── README.md                       # Logging guidelines
│
├── models/
│   └── models.py
│
├── routes/
│   ├── __init__.py
│   ├── auth.py
│   ├── api.py
│   ├── admin.py
│   └── main.py
│
├── run/                                # Batch files for startup
│   ├── Run_Web.bat                     # Starts server + opens browser
│   ├── Run_Admin.bat                   # Starts desktop admin panel
│   ├── Run_Cloudflare.bat              # Tunnel + auto-clipboard + browser
│   ├── Run_All.bat                     # Starts web + cloudflare only
│   └── Stop_All.bat                    # Kills all services
│
├── scripts/                            # Executable scripts
│   ├── __init__.py
│   ├── benchmarks/
│   │   ├── __init__.py
│   │   └── benchmark_broadcast.py      # Moved from root
│   ├── dev/
│   │   ├── __init__.py
│   │   ├── reset_db.py                 # Moved from root
│   │   └── check_tables.py             # Moved from root
│   └── migrations/
│       ├── __init__.py
│       └── encrypt_migration.py        # Moved from root
│
├── sockets/
│   └── events.py
│
├── static/
│   ├── css/
│   ├── js/
│   ├── audio/
│   ├── uploads/                        # User uploads (gitignored content)
│
├── templates/
│   ├── base.html
│   ├── login.html
│   ├── register.html
│   ├── chat.html
│   └── admin/
│       └── admin_dashboard.html
│
├── tests/                              # Unit tests
│   ├── __init__.py
│   ├── test_web_app.py                 # Moved from root; 15 tests ALL PASS
│   └── test_upload_manual.py           # Moved from root
│
└── utils/                              # Reusable library code (unchanged)
    ├── __init__.py
    ├── crypto.py
    ├── migration.py
    ├── api/
    │   ├── __init__.py
    │   ├── response.py
    │   └── errors.py
    └── security/
        ├── __init__.py
        ├── constants.py
        ├── validators.py
        ├── sanitizers.py
        ├── decorators.py
        ├── permissions.py
        ├── rate_limiter.py
        └── exceptions.py
```

---

## Files Moved

| From (root) | To | Reason |
|---|---|---|
| `admin_app.py` | `admin/admin_app.py` | Desktop app → `admin/` package |
| `test_web_app.py` | `tests/test_web_app.py` | Tests → `tests/` package |
| `test_upload_manual.py` | `tests/test_upload_manual.py` | Tests → `tests/` package |
| `reset_db.py` | `scripts/dev/reset_db.py` | Developer utility → `scripts/dev/` |
| `check_tables.py` | `scripts/dev/check_tables.py` | Developer utility → `scripts/dev/` |
| `benchmark_broadcast.py` | `scripts/benchmarks/benchmark_broadcast.py` | Benchmark → `scripts/benchmarks/` |
| `encrypt_migration.py` | `scripts/migrations/encrypt_migration.py` | Migration → `scripts/migrations/` |
| `falcon_web.db` | `database/falcon_web.db` | DB → `database/` for colocation |
| `Run_*.bat`, `Stop_All.bat` | `run/` | Batch files → `run/` |
| All 27 `.md` files | `docs/` subdirectories | Doc consolidation |
| `benchmark_results.json` | _deleted_ | Generated artifact |
| `stderr.txt` | _deleted_ | Runtime artifact |
| `stdout.txt` | _deleted_ | Runtime artifact |
| `cloudflared.exe` | _deleted_ | Downloaded binary |

---

## Import Changes

All files moved use `python -m path.to.module` from project root, ensuring CWD is always in `sys.path`.  
Zero `sys.path.insert` or `sys.path.append` workarounds remain.

| File | Change | Mechanism |
|---|---|---|
| `admin/admin_app.py` | `os.path.dirname(...)` → up 1 level for DB path, uploads, script refs | Data path fix (not import hack) |
| `scripts/dev/reset_db.py` | `os.path.dirname(...)` → up 2 levels for DB path | Data path fix |
| `scripts/dev/check_tables.py` | Added `import os`, absolute path for DB | Direct path reference |
| `scripts/migrations/encrypt_migration.py` | `DB_PATH` default → `database/falcon_web.db` | Relative from CWD |
| `scripts/benchmarks/benchmark_broadcast.py` | **Removed** `sys.path.insert(0, '.')` | No-op when CWD is root |
| `utils/migration.py` | **Removed** `sys.path.append(...)` | Redundant when CWD is root |
| `config.py` | `SQLALCHEMY_DATABASE_URI` → `database/falcon_web.db` | DB path update |
| `tests/test_web_app.py` | No changes needed | `from app import create_app` resolves from CWD |
| `tests/test_upload_manual.py` | No changes needed | Same mechanism |

### Raw `sys.path` workarounds removed

| File | Line | Removed Code |
|---|---|---|
| `utils/migration.py:11` | `sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))` |
| `benchmark_broadcast.py:18` | `sys.path.insert(0, '.')` |

---

## Dependency Graph

```
app.py                                    # Flask entry, eventlet.monkey_patch()
  ├── config.py                           # BASE_DIR, SQLALCHEMY_DATABASE_URI
  ├── version.py                          # __version__
  ├── database/database.py                # db = SQLAlchemy()
  ├── models/models.py                    # User, Message, Group, ...
  ├── routes/
  │   ├── auth.py                         # /login, /register, /logout
  │   ├── api.py                          # /api/* endpoints (37, standardized)
  │   ├── admin.py                        # /admin/* endpoints
  │   └── main.py                         # /, /chat, /admin/dashboard
  ├── sockets/events.py                   # Socket.IO event handlers (13)
  └── utils/                              # Library code
       ├── crypto.py                      # Fernet encryption
       ├── migration.py                   # Legacy DB migration helper
       └── api/
            ├── response.py               # success_response(), error_response()
            └── errors.py                 # ErrorCode enum
       └── security/
            ├── constants.py              # Limits, patterns, error strings
            ├── validators.py             # Username, password, group validation
            ├── sanitizers.py             # HTML, filename sanitization
            ├── decorators.py             # @login_required, @admin_required
            ├── permissions.py            # AuthZ checks
            ├── rate_limiter.py           # Per-user/per-IP rate limiting
            └── exceptions.py             # SecurityError hierarchy

admin/admin_app.py                        # Desktop PyQt6 admin (optional)
  ├── app.py (via import, QThread)        # Starts Flask in background thread
  └── [PyQt6, matplotlib optional]        # External deps

tests/test_web_app.py                     # 15 unit tests (ALL PASS)
  └── app.py, config.py, database, models # All imported from CWD (project root)

scripts/
  ├── dev/reset_db.py                     # DB reset utility
  │   └── app.py, database.database
  ├── dev/check_tables.py                 # DB inspection
  ├── benchmarks/benchmark_broadcast.py   # Performance benchmark
  │   └── app.py, database.database, models.models
  └── migrations/encrypt_migration.py     # At-rest encryption migration
      └── utils.crypto

run/Run_*.bat                             # CD to root, then python -m ...
```

## How to Run

```bash
# Web server
cd project/root
python -m app                                  # or run\Run_Web.bat

# Desktop admin
python -m admin.admin_app                       # or run\Run_Admin.bat

# Cloudflare tunnel
cloudflared tunnel --url http://localhost:5000  # or run\Run_Cloudflare.bat

# Tests
python -m unittest tests.test_web_app           # 15 tests

# Developer tools
python -m scripts.dev.reset_db
python -m scripts.dev.check_tables
python -m scripts.benchmarks.benchmark_broadcast
python -m scripts.migrations.encrypt_migration --dry-run
```
