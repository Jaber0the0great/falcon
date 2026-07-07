# API Standardization Plan

**Version:** 1.2
**Phase:** E — API Standardization
**Status:** ✅ **Fully Complete** — All 37 JSON endpoints migrated

---

## Table of Contents

1. [Step 1 — API Inventory](#step-1--api-inventory)
2. [Step 2 — Response Analysis](#step-2--response-analysis)
3. [Step 3 — Standard Proposal](#step-3--standard-proposal)
4. [Step 4 — Compatibility](#step-4--compatibility)
5. [Step 5 — Migration Plan](#step-5--migration-plan)

---

## Mandatory API Policy

Every JSON endpoint **must** use:

- `success_response()` for success responses
- `error_response()` for error responses

Direct `jsonify()` responses are **no longer permitted** for application APIs.
Violations will be rejected during code review.

**Exceptions:**
- HTML page routes (non-JSON)
- Binary file responses (e.g., `/api/download/<filename>` on success)

## Remaining Legacy JSON Endpoints

**None.** All 37 JSON API endpoints have been migrated to `success_response()` / `error_response()`.

| # | File | Route | Method | Phase | Status |
|---|------|-------|--------|-------|--------|
| L1 | `routes/api.py` | `/api/upload` | POST | E6 | ✅ Migrated |
| L2 | `routes/api.py` | `/api/download/<filename>` | GET (error path) | E6 | ✅ Migrated |

**Count:** 0 remaining.

---

## Step 1 — API Inventory

### Legend

| Column | Meaning |
|--------|---------|
| Route | URL pattern |
| Method | HTTP method |
| Auth | Required session state |
| Status | HTTP status codes returned |
| Payload | JSON shape (abbreviated) |
| Source | Route file |

### 1.1 Page Routes (non-JSON)

These serve HTML. No standardization required.

| # | Route | Method | Auth | Status | Returns |
|---|-------|--------|------|--------|---------|
| P1 | `/` | GET | Optional | 200/302 | `chat.html` or redirect `/login` |
| P2 | `/login` | GET | Optional | 200/302 | `login.html` or redirect `/` |
| P3 | `/register` | GET | Optional | 200/302 | `register.html` or redirect `/` |
| P4 | `/admin/` | GET | Admin | 200/302 | `admin_dashboard.html` or redirect `/login` |
| P5 | `/admin/dashboard` | GET | Admin | 200/302 | `admin_dashboard.html` or redirect `/login` |
| P6 | `/admin/logout` | GET | Optional | 302 | Redirect `/login` |

**Total page routes:** 6 (excluded from further analysis — not JSON APIs).

### 1.2 Public / Auth API (Blueprint `auth`, prefix `/auth`)

| # | Route | Method | Auth | 200 | 400 | 401 | Special |
|---|-------|--------|------|-----|-----|-----|---------|
| A1 | `/auth/login` | POST | None | `{"success":true,"username":"...","is_admin":bool}` | `{"success":false,"error":"..."}` | `{"success":false,"error":"..."}` (if banned → 401) | admin path includes `is_admin` key |
| A2 | `/auth/register` | POST | None | `{"success":true,"username":"..."}` | `{"success":false,"error":"..."}` | — | 400 for validation, duplicate |
| A3 | `/auth/logout` | POST | None | `{"success":true}` | — | — | Always 200 |
| A4 | `/auth/me` | GET | None | `{"logged_in":true,"username":"..."}` | — | — | **Non-standard:** uses `logged_in` key, no `success` key |

**Format variants detected:**
- A1/A2/A3: standard `success: true/false` pattern
- A4: `logged_in` boolean instead of `success` — **deviant**

### 1.3 Core API (Blueprint `api`, prefix `/api`)

| # | Route | Method | Auth | Success payload | Error codes | Notes |
|---|-------|--------|------|----------------|-------------|-------|
| C1 | `/api/history` | GET | User | `{"success":true,"messages":[...],"total":int}` | 401, 400, 403 | Pagination via `limit`/`offset`; messages include nested payload |
| C2 | `/api/upload` | POST | User | `{"success":true,"filename":"...","original_name":"...","size":int}` | 401, 400, 413 | Multipart form |
| C3 | `/api/download/<filename>` | GET | User | Binary file (not JSON) | 400 | `login_required`; binary response on success |
| C4 | `/api/user_info` | GET | User | `{"success":true,"username":"..."}` | 401 | |
| C5 | `/api/webrtc_config` | GET | User | `{"success":true,"iceServers":[...]}` | 401 | |
| C6 | `/api/groups/create` | POST | User | `{"success":true,"message":"Group created successfully"}` | 401, 400 | |
| C7 | `/api/groups` | GET | User | `{"success":true,"groups":[...]}` | 401 | |
| C8 | `/api/calls/log` | POST | User | `{"success":true,"message":"Call log saved successfully"}` | 401, 400, 404 | |
| C9 | `/api/groups/invite` | POST | User | `{"success":true,"message":"...","errors":[]}` | 401, 400, 404, 403 | `errors` array is always `[]` on success |
| C10 | `/api/groups/invite/respond` | POST | User | `{"success":true,"message":"..."}` | 401, 400, 404 | |
| C11 | `/api/groups/request_join` | POST | User | `{"success":true,"message":"..."}` | 401, 400, 404 | |
| C12 | `/api/groups/requests` | GET | User | `{"success":true,"requests":[...]}` | 401, 400, 404, 403 | |
| C13 | `/api/groups/requests/respond` | POST | User | `{"success":true,"message":"..."}` | 401, 400, 404, 403 | |
| C14 | `/api/groups/members` | GET | User | `{"success":true,"members":[...]}` | 401, 400, 403 | |
| C15 | `/api/groups/kick` | POST | User | `{"success":true,"message":"Member kicked successfully"}` | 401, 400, 404, 403 | |
| C16 | `/api/groups/leave` | POST | User | `{"success":true,"message":"Left group successfully"}` | 401, 400, 404 | |
| C17 | `/api/groups/delete` | POST | User | `{"success":true,"message":"Group deleted successfully"}` | 401, 400, 404, 403 | |

**Total core API endpoints:** 17

**Format variants detected:**
- All use `{"success": true/false, ...}` envelope
- C1: includes `total` alongside `messages`
- C2: returns `filename`, `original_name`, `size` at top level
- C9: includes `errors` (always `[]` on success)
- All mutation endpoints include a human-readable `message` string

### 1.4 Admin API (Blueprint `admin`, prefix `/admin/api/`)

| # | Route | Method | Auth | Success payload | Error codes | Notes |
|---|-------|--------|------|----------------|-------------|-------|
| D1 | `/admin/api/stats` | GET | Admin | `{"success":true,"db_size":"...","total_users":int,"total_messages":int,"text_messages":int,"file_messages":int,"voice_messages":int,"status_distribution":{...}}` | 500, 401 | |
| D2 | `/admin/api/users` | GET | Admin | `{"success":true,"users":[...]}` | 500, 401 | |
| D3 | `/admin/api/users/add` | POST | Admin | `{"success":true,"message":"... created successfully."}` | 400, 409, 500, 401 | |
| D4 | `/admin/api/users/edit/<id>` | POST | Admin | `{"success":true,"message":"User updated successfully."}` | 400, 409, 404, 500, 401 | |
| D5 | `/admin/api/users/toggle_ban/<id>` | POST | Admin | `{"success":true,"message":"User ... has been banned/unbanned."}` | 404, 500, 401 | |
| D6 | `/admin/api/users/delete/<id>` | POST | Admin | `{"success":true,"message":"User '...' and all ... deleted successfully."}` | 404, 500, 401 | |
| D7 | `/admin/api/groups` | GET | Admin | `{"success":true,"groups":[...]}` | 500, 401 | |
| D8 | `/admin/api/groups/<name>/members` | GET | Admin | `{"success":true,"members":[...]}` | 500, 401 | |
| D9 | `/admin/api/groups/rename` | POST | Admin | `{"success":true,"message":"Group renamed ..."}` | 400, 404, 409, 500, 401 | |
| D10 | `/admin/api/groups/kick` | POST | Admin | `{"success":true,"message":"Kicked '...' from group '...'."}` | 400, 404, 500, 401 | |
| D11 | `/admin/api/groups/delete` | POST | Admin | `{"success":true,"message":"Group '...' and all ... deleted successfully."}` | 400, 404, 500, 401 | |
| D12 | `/admin/api/chats/users` | GET | Admin | `{"success":true,"users":[...],"groups":[...]}` | 500, 401 | |
| D13 | `/admin/api/chats/history` | GET | Admin | `{"success":true,"messages":[...]}` | 400, 500, 401 | |
| D14 | `/admin/api/chats/delete/<id>` | POST | Admin | `{"success":true,"message":"Message deleted permanently."}` | 404, 500, 401 | |
| D15 | `/admin/api/media` | GET | Admin | `{"success":true,"media":[...]}` | 500, 401 | |
| D16 | `/admin/api/media/delete` | POST | Admin | `{"success":true,"message":"File '...' deleted successfully."}` | 400, 404, 500, 401 | |
| D17 | `/admin/api/broadcast` | POST | Admin | `{"success":true,"message":"Broadcast message queued successfully."}` | 400, 500, 401 | |

**Total admin API endpoints:** 17

**Notable patterns:**
- All return `{"success": true/false, ...}`
- Every mutation endpoint returns `"message": "human readable string"`
- Every list endpoint returns a typed array key (`users`, `groups`, `members`, `media`, `messages`)
- Errors use `"error": "string"` without error codes

### 1.5 Endpoint Summary

| Category | Count | JSON | HTML | File |
|----------|-------|------|------|------|
| Page routes | 6 | 0 | 6 | 0 |
| Auth API | 4 | 4 | 0 | 0 |
| Core API | 17 | 16 | 0 | 1 |
| Admin API | 17 | 17 | 0 | 0 |
| **Total** | **44** | **37** | **6** | **1** |

**JSON API endpoints to standardize:** 37

---

## Step 2 — Response Analysis

### 2.1 Format Variant Catalogue

Every distinct JSON response shape found across all 37 endpoints:

#### Class A — Standard Success (top-level key) — 16 endpoints

```json
{"success": true, "<resource_key>": <value>}
```

Used by: C4 (`user_info`), C5 (`webrtc_config`), C7 (`groups`), C12 (`requests`), C14 (`members`), D1 (`stats`), D2 (`users`), D7 (`groups`), D8 (`members`), D12 (`chats/users`), D13 (`chats/history`), D15 (`media`), C1 (`history` — also has `total`)

**Variation:** C1 adds `"total": <int>` for pagination.

#### Class B — Success with Message — 14 endpoints

```json
{"success": true, "message": "<human readable string>"}
```

Used by: C6, C8, C10, C11, C13, C15, C16, C17, D3, D4, D5, D6, D9, D10, D11, D14, D16, D17

**Note:** Some endpoints return ONLY `message`, no data resource.

#### Class C — Success with Mixed Payload — 2 endpoints

```json
{"success": true, "filename": "...", "original_name": "...", "size": <int>}
{"success": true, "message": "...", "errors": []}
```

Used by: C2 (`upload`), C9 (`invite`)

#### Class D — Standard Error — All error paths

```json
{"success": false, "error": "<message string>"}
```

Used by every endpoint on failure. **HTTP status codes vary inconsistently** for the same logical error category.

#### Class E — Non-standard Format — 1 endpoint

```json
{"logged_in": true, "username": "..."}
{"logged_in": false}
```

Used by: A4 (`/auth/me`)

**Deviation:** Uses `logged_in` instead of `success`, no `error` key.

#### Class F — Binary (non-JSON) — 1 endpoint

```json
Binary file stream
{"success": false, "error": "Invalid filename"}
```

Used by: C3 (`download`). Success is not JSON; error is JSON.

#### Class G — Admin Auth Error (global before_request)

```json
{"success": false, "error": "Unauthorized admin access."}
```

Status 401. Consistent with other error formats.

### 2.2 Inconsistency Summary

| Issue | Examples | Severity |
|-------|----------|----------|
| `success` casing mismatch | `True` vs `true` used in source code | Low |
| `/auth/me` uses `logged_in` instead of `success` | `{"logged_in": true}` vs `{"success": true}` | **High** — different key name |
| No standard error code | `"error": "Invalid filename"` vs `"error": "File type not allowed."` | Medium — all strings, no machine-readable code |
| HTTP status codes for same error type vary | Missing group name returns 400; missing auth returns 401; missing permission returns 403 | Medium — current behavior is reasonable but undocumented |
| Page routes use inconsistently cased `success` | Python `True` vs JSON `true` (Python `jsonify` handles this) | Low |
| `/api/history` includes `total` at top level | No other endpoint exposes pagination metadata | Medium — should go in `meta` |
| `/admin/api/stats` returns flat fields | `db_size`, `total_users`, etc. are all top-level alongside `success` | Medium — should nest under `data` |
| `message` vs `error` on success vs failure | Both are human-readable strings but use different keys | Low |
| `errors` in invite endpoint | `"errors": []` on success is empty array — unusual pattern | Low |
| `/api/calls/log` returns `{"success":true,"message":"..."}` | No data beyond the message | Low — all mutation endpoints behave this way |

### 2.3 Current HTTP Status Code Usage

| Code | Usage | Endpoints |
|------|-------|-----------|
| 200 | Success | All |
| 302 | Redirect (not logged in) | P1-P6 |
| 400 | Validation failure / bad request | A1, A2, C1-C17, D3-D16 |
| 401 | Not authenticated | A1, C1-C17, D1-D17 |
| 403 | Not authorized (not owner / not member) | C1, C9, C10-C17 |
| 404 | Resource not found | C8, C9-C17, D4-D14 |
| 409 | Conflict (duplicate) | D3, D4, D9 |
| 413 | Payload too large | C2 |
| 500 | Server error | D1-D17 |

**Observation:** No endpoint uses 429 (rate limit). Flask's `@rate_limit` decorator currently returns 200 with `{"success": false, "error": "Rate limit exceeded"}` — this is a **latent bug**: rate-limited requests should return **429 Too Many Requests**.

---

## Step 3 — Standard Proposal

### 3.1 Standard Response Envelope

Every JSON API response MUST use this envelope:

#### Success

```json
{
    "success": true,
    "data": <any>,
    "error": null,
    "meta": {}
}
```

#### Failure

```json
{
    "success": false,
    "data": null,
    "error": {
        "code": "ERROR_CODE",
        "message": "Human-readable description"
    },
    "meta": {}
}
```

**Rules:**

1. `success` — boolean, always present. `true` or `false`. Never a string or int.
2. `data` — present on both success and failure. `null` on failure. Contains the resource payload on success.
3. `error` — `null` on success. Object with `code` and `message` on failure.
4. `meta` — object, always present. Contains metadata like pagination, timestamps, request ID. Empty object `{}` when no metadata.

### 3.2 Error Codes

Standard error code strings. Hierarchical: `CATEGORY.SUBCATEGORY`.

#### Authentication & Authorization

| Code | HTTP | Description |
|------|------|-------------|
| `AUTH.REQUIRED` | 401 | No valid session |
| `AUTH.INVALID_CREDENTIALS` | 401 | Wrong username or password |
| `AUTH.BANNED` | 401 | User account is banned |
| `AUTH.FORBIDDEN` | 403 | Not authorized for this action |
| `AUTH.ADMIN_REQUIRED` | 401 | Admin session required |

#### Validation

| Code | HTTP | Description |
|------|------|-------------|
| `VALIDATION.REQUIRED_FIELD` | 400 | Missing required field |
| `VALIDATION.INVALID_FORMAT` | 400 | Field fails format validation |
| `VALIDATION.TOO_LONG` | 400 | Exceeds maximum length |
| `VALIDATION.INVALID_FILENAME` | 400 | Filename rejected |
| `VALIDATION.FILE_TYPE` | 400 | File extension not allowed |

#### Resource Errors

| Code | HTTP | Description |
|------|------|-------------|
| `RESOURCE.NOT_FOUND` | 404 | Resource does not exist |
| `RESOURCE.CONFLICT` | 409 | Resource already exists (duplicate) |
| `RESOURCE.NOT_MEMBER` | 403 | User is not a group member |
| `RESOURCE.ALREADY_MEMBER` | 400 | User is already a group member |
| `RESOURCE.ALREADY_REQUESTED` | 400 | Join request already pending |
| `RESOURCE.OWNER_CANNOT_LEAVE` | 400 | Group owner cannot leave; delete instead |

#### Rate Limiting

| Code | HTTP | Description |
|------|------|-------------|
| `RATE_LIMIT.EXCEEDED` | 429 | Too many requests |

#### Server Errors

| Code | HTTP | Description |
|------|------|-------------|
| `SERVER.INTERNAL_ERROR` | 500 | Unexpected server error |
| `SERVER.UNAVAILABLE` | 503 | Temporary service disruption |

#### Upload

| Code | HTTP | Description |
|------|------|-------------|
| `UPLOAD.FILE_TOO_LARGE` | 413 | Exceeds maximum file size |

### 3.3 Data Shapes

Each endpoint's `data` field on success:

#### `POST /auth/login`

```json
{
    "success": true,
    "data": {
        "username": "Alice",
        "is_admin": false
    },
    "error": null,
    "meta": {}
}
```

*`is_admin` omitted when `false` (or always present — pick one).*

#### `GET /auth/me`

```json
{
    "success": true,
    "data": {
        "logged_in": true,
        "username": "Alice"
    },
    "error": null,
    "meta": {}
}
```

```json
{
    "success": true,
    "data": {
        "logged_in": false
    },
    "error": null,
    "meta": {}
}
```

**Model change:** Always return `"success": true` with `data.logged_in` as a boolean. This deprecates the current `{"logged_in": true/false}` top-level key.

#### `GET /api/history`

```json
{
    "success": true,
    "data": {
        "messages": [...]
    },
    "error": null,
    "meta": {
        "total": 150,
        "limit": 50,
        "offset": 0,
        "has_more": true
    }
}
```

**Change:** `total` moves from top level to `meta.total`.

#### `GET /api/groups`

```json
{
    "success": true,
    "data": {
        "groups": [
            {
                "name": "DevTeam",
                "description": "...",
                "owner": "Alice",
                "is_owner": true,
                "is_member": true,
                "has_invite": false,
                "has_request": false
            }
        ]
    },
    "error": null,
    "meta": {}
}
```

#### Mutation endpoints (e.g., `POST /api/groups/create`)

```json
{
    "success": true,
    "data": {
        "message": "Group created successfully"
    },
    "error": null,
    "meta": {}
}
```

**Design decision:** Keep `message` inside `data` so that the frontend can display it. Alternatively, `data` could be `null` and the message is for logging only. I recommend putting it in `data` since the admin dashboard renders it in toasts.

#### `GET /admin/api/stats`

```json
{
    "success": true,
    "data": {
        "db_size": "1.23 MB (1234567 bytes)",
        "total_users": 42,
        "total_messages": 1000,
        "text_messages": 800,
        "file_messages": 150,
        "voice_messages": 50,
        "status_distribution": {
            "Available": 10,
            "Offline": 30,
            "Busy": 2
        }
    },
    "error": null,
    "meta": {}
}
```

**Change:** Flat fields move from top level to `data`.

### 3.4 Error Response Examples

#### Validation error

```json
{
    "success": false,
    "data": null,
    "error": {
        "code": "VALIDATION.REQUIRED_FIELD",
        "message": "Username and password required"
    },
    "meta": {}
}
```

#### Auth error

```json
{
    "success": false,
    "data": null,
    "error": {
        "code": "AUTH.INVALID_CREDENTIALS",
        "message": "Invalid credentials"
    },
    "meta": {}
}
```

#### Rate limited

```json
{
    "success": false,
    "data": null,
    "error": {
        "code": "RATE_LIMIT.EXCEEDED",
        "message": "Rate limit exceeded. Try again later."
    },
    "meta": {}
}
```

HTTP status: **429** (currently returns 200 — this is a bug fix).

#### Server error

```json
{
    "success": false,
    "data": null,
    "error": {
        "code": "SERVER.INTERNAL_ERROR",
        "message": "An unexpected error occurred"
    },
    "meta": {}
}
```

**Never expose exception messages to the client in production.**

### 3.5 Metadata (`meta`)

The `meta` object is always present. Standard keys:

| Key | Type | Always? | Description |
|-----|------|---------|-------------|
| `total` | int | No | Total item count (pagination) |
| `limit` | int | No | Items per page (pagination) |
| `offset` | int | No | Current offset (pagination) |
| `has_more` | bool | No | Whether more pages exist (pagination) |
| `timestamp` | string | Optional | ISO 8601 server timestamp |
| `request_id` | string | Optional | Correlation ID for request tracing |

### 3.6 Pagination Standard

For list endpoints that support pagination (currently only `GET /api/history`):

**Request query params:**
```
?limit=50&offset=0
```

`limit`: max items per page (cap at 200).
`offset`: zero-based index of first item.

**Response meta:**
```json
"meta": {
    "total": 150,
    "limit": 50,
    "offset": 0,
    "has_more": true
}
```

**Rules:**
- `total` = total items matching the query (not just the current page).
- `has_more` = `(offset + len(items)) < total`.
- If `total` is unknown or expensive to compute, omit `total` and set `has_more` based on `len(items) == limit`.

### 3.7 Validation Error Detail

For endpoints with multiple validated fields, consider an optional `details` array within `error`:

```json
{
    "success": false,
    "data": null,
    "error": {
        "code": "VALIDATION.INVALID_FORMAT",
        "message": "One or more fields are invalid",
        "details": [
            {"field": "username", "code": "VALIDATION.TOO_SHORT", "message": "Minimum 3 characters"},
            {"field": "password", "code": "VALIDATION.TOO_SHORT", "message": "Minimum 8 characters"}
        ]
    },
    "meta": {}
}
```

**Implementation note:** This is a future enhancement. Current validation is simple (one error per request). Implement `details` only when an endpoint needs to report multiple field errors simultaneously.

---

## Step 4 — Compatibility

### 4.1 Endpoints That Will Change

| # | Endpoint | Change Type | Current | New |
|---|----------|-------------|---------|-----|
| 1 | `GET /auth/me` | **Breaking** | `{"logged_in": true/false}` | `{"success": true, "data": {"logged_in": true/false, "username": "..."}, "error": null, "meta": {}}` |
| 2 | All 37 JSON endpoints | **Breaking** | Top-level resource keys (`messages`, `groups`, `users`, etc.) | Nested under `data` |
| 3 | All 37 JSON endpoints | **Breaking** | `"error": "string"` on failure | `"error": {"code": "...", "message": "..."}` on failure |
| 4 | All 37 JSON endpoints | **Additive** | No `meta` key | `"meta": {}` always present |
| 5 | `GET /api/history` | **Breaking** | `total` at top level | `total` in `meta` |
| 6 | Rate-limited endpoints | **Bug fix** | 200 with `{"success": false, "error": "..."}` | 429 with standard error envelope |
| 7 | All admin mutation endpoints | **Breaking** | `message` at top level | `message` inside `data` |
| 8 | `POST /api/groups/invite` | **Breaking** | `errors: []` at top level | `errors` inside `data` |
| 9 | `GET /admin/api/stats` | **Breaking** | Flat top-level fields | Fields nested under `data` |
| 10 | `POST /api/upload` | **Breaking** | `filename`, `original_name`, `size` at top level | Nested under `data` |

**Total breaking changes:** 9 out of 37 endpoints change shape.

### 4.2 Frontend Files That Will Need Updates

| File | Endpoints consumed | Nature of change |
|------|--------------------|-------------------|
| `static/js/app.js` | `/api/history`, `/auth/logout`, `/api/upload`, `/api/groups/create`, `/api/groups/request_join`, `/api/groups/invite/respond`, `/api/groups/requests`, `/api/groups/members`, `/api/groups/requests/respond`, `/api/groups/kick`, `/api/groups/delete`, `/api/groups/leave`, `/api/groups/invite` | All fetch calls read `data.success` (unchanged) but must read `data.data.<key>` instead of `data.<key>` for nested fields. Error reading changes from `data.error` to `data.error.message`. |
| `static/js/socket.js` | `/api/user_info`, `/api/groups` | Same pattern: `data.success` unchanged, `data.data.username` / `data.data.groups` instead of `data.username` / `data.groups` |
| `templates/admin/admin_dashboard.html` | All 17 admin API endpoints | Same pattern as above for all read operations |

### 4.3 Tests That Will Need Updates

| Test file | Tests affected | Nature of change |
|-----------|----------------|-------------------|
| `test_web_app.py` | `test_history_filtering_alice_deletes_for_me` | `data['messages']` → `data['data']['messages']` |
| `test_web_app.py` | `test_history_filtering_bob_deletes_for_me` | Same as above |
| `test_web_app.py` | `test_case_insensitive_login` | `data['username']` → `data['data']['username']` |
| `test_web_app.py` | `test_create_group_no_members` | `data['success']` unchanged, but any field reads change |
| `test_web_app.py` | `test_create_group_with_members` | Same as above |
| `test_web_app.py` | `test_call_logging` | `data_hist['messages'][0]['type']` → `data_hist['data']['messages'][0]['type']` |
| `test_web_app.py` | `test_group_history_access` | `data['messages'][0]['content']` → `data['data']['messages'][0]['content']` |
| `test_web_app.py` | `test_admin_login_credentials` | `data['is_admin']` → `data['data']['is_admin']` |
| `test_web_app.py` | `test_admin_api_stats` | `data['total_users']` → `data['data']['total_users']` |

### 4.4 Backward Compatible vs Breaking

| Change | Backward Compatible? | Reason |
|--------|---------------------|--------|
| Adding `meta` key | **Yes** | Extra key ignored by existing clients |
| Adding `data` key alongside existing keys | **Yes** (temporary) | Old and new keys coexist; after migration, remove old keys |
| Moving fields from top level to `data` | **No** | Existing clients reading `data.messages` will find `undefined` |
| Changing `error` from string to object | **No** | Existing clients reading `data.error` will get an object instead of a string |
| Changing HTTP status for rate limit (200→429) | **No** | Existing `fetch().json()` still works, but `response.ok` flips from true to false |
| Changing `logged_in` to `data.logged_in` | **No** | Key path changes |

### 4.5 Dual-Payload Transition Strategy

To maintain backward compatibility during migration, each endpoint can temporarily emit BOTH formats:

```python
# Transition — endpoint returns:
{
    "success": true,
    "data": {"messages": [...]},
    "messages": [...],          # ← legacy key, removed after migration
    "error": null,
    "meta": {"total": 150}
}
```

**Recommendation:** Do NOT use dual payloads. The frontend is a single-page app deployed atomically with the backend. Coordinate the release: update the frontend and backend in the same deploy. The migration is a small, focused set of changes across 3 JS files + 4 Python route files.

---

## Step 5 — Migration Plan

**Goal:** Convert all 37 JSON endpoints to the standard shape without regressions.

**Strategy:** Co-deploy frontend + backend changes. Each phase covers one route file and its frontend consumer(s). **Each phase requires explicit approval before the next begins.**

---

### 5.1 Phase Order

#### Phase E1 — API Infrastructure (✅ Complete)

**Files:** `utils/api/__init__.py`, `utils/api/errors.py`, `utils/api/response.py` (new)

**Goal:** Create response helpers, error codes, and response builders. **No endpoint migration.**

**Implemented:**
- `success_response(data, message, status_code=200)` — standard success envelope
- `error_response(code, message, details, status_code=400)` — standard error envelope
- `paginated_response(items, total, offset, limit)` — standard paginated envelope
- `ErrorCode` constants — 40+ codes across 8 categories (AUTH, VALIDATION, GROUP, MESSAGE, FILE, ADMIN, RATE_LIMIT, SERVER)
- `ErrorCategory` enum — category groupings

**Standard response format:**

```python
# Success
{"success": true, "data": <any>}                       # status 200

# Error
{"success": false, "error": {"code": "AUTH_INVALID_CREDENTIALS", "message": "..."}}  # status varies

# Paginated
{"success": true, "data": [<items>], "meta": {"total": N, "offset": 0, "limit": 50}}
```

**No existing endpoints were modified.**

---

#### Phase E2 — Authentication Endpoints (🔲 Awaiting Approval)

**Files:** `routes/auth.py`, `static/js/app.js`, `test_web_app.py`

Migrate `/auth/login`, `/auth/register`, `/auth/logout`, `/auth/me` to use `success_response()` / `error_response()`.

**Changes per endpoint:**

##### `POST /auth/login` (Success)
Before:
```python
return jsonify({"success": True, "username": user.username, "is_admin": True})
```
After:
```python
return success_response({"username": user.username, "is_admin": True})
```

##### `POST /auth/login` (Failure)
Before:
```python
return jsonify({"success": False, "error": "Invalid credentials"}), 401
```
After:
```python
return error_response("AUTH_INVALID_CREDENTIALS", "Invalid username or password", status_code=401)
```

##### `POST /auth/register`
Before:
```python
return jsonify({"success": True, "username": user.username})
```
After:
```python
return success_response({"username": user.username})
```

##### `GET /auth/me`
Before:
```python
return jsonify({"logged_in": True, "username": session['username']})
return jsonify({"logged_in": False})
```
After:
```python
return success_response({"logged_in": True, "username": session['username']})
return success_response({"logged_in": False})
```

**Frontend impact:** `app.js` login handler reads `data.username` and `data.is_admin` → change to `data.data.username` and `data.data.is_admin`.

**Test impact:** Update test assertions that read response fields.

---

#### Phase E3 — Core API (✅ Complete)

**Files:** `routes/api.py`, `static/js/app.js`, `static/js/socket.js`, `test_web_app.py`

Migrate history, upload, download (error path), user-info, webrtc-config, call-log endpoints. Standardize all error messages to error codes.

##### Key changes:
- `GET /api/history` — wrap `messages` under `data.messages`, move `total` to `meta.total`
- `GET /api/user_info` — standard envelope
- `GET /api/webrtc_config` — standard envelope
- `POST /api/upload` — standard envelope
- Error paths — all use `error_response()` with error codes

**Frontend impact:** All fetch callers read `data.data.*` instead of top-level resource keys.

---

#### Phase E4 — Group API (✅ Complete)

**Files:** `routes/api.py`, `static/js/app.js`, `test_web_app.py`

Migrate all `/api/groups/*` endpoints (create, list, invite, respond, join-request, members, kick, leave, delete).

**Key changes:**
- All mutation endpoints use `success_response({"message": "..."})` or `success_response()`
- `POST /api/groups/invite` — move `errors` array into `data.errors`
- All error paths use error codes

---

#### Phase E5 — Admin API (✅ Complete)

**Files:** `routes/admin.py`, `templates/admin/admin_dashboard.html`, `test_web_app.py`

Migrate all 17 `/admin/api/*` endpoints.

**Key changes:**
- Nest resource fields under `data`
- Replace `"error": "string"` with `error_response()` using error codes
- Add `"meta": {}` for paginated endpoints

**Frontend impact:** `admin_dashboard.html` — all ~17 endpoint reads change from `data.<field>` to `data.data.<field>`.

---

#### Phase E6 — Cleanup & Consistency (✅ Complete)

**Files:** All route files, test files

- Remove any legacy dual-payload keys
- Final consistency sweep across all endpoints
- Verify all 40+ error codes are used at least once
- Ensure the rate limiter decorator response matches the standard error envelope
- **Pagination metadata normalization:** Move `total`, `offset`, `limit` (currently inside `data`) into a top-level `meta.pagination` object. Currently `GET /api/history` returns `{..., "data": {"messages": [...], "total": N, "offset": O, "limit": L}}`. In Phase E6 this becomes `{..., "data": {"messages": [...]}, "meta": {"pagination": {"total": N, "offset": O, "limit": L}}}`. This is documentation only — no response structure change before Phase E6.
- **API Version metadata:** Every response will include a top-level `meta.api_version` string (e.g., `"1.1"`) to allow frontend feature detection and graceful deprecation. The `success_response()` / `error_response()` helpers will be updated to accept an optional `api_version` parameter; if omitted it defaults to the current version. The version will also be exposed via a `GET /api/version` endpoint. **Documentation only — not implemented before Phase E6.**
- Final test pass

---

### 5.2 Rollback Plan

Each phase is self-contained. To roll back:
1. Revert the phase's changes
2. Re-deploy the previous version of the affected files (frontend + backend together)

The frontend and backend are coupled for response shape. A mismatch will break data display. For this reason:

- **Deploy frontend + backend changes in the same release.**
- **Use feature flags** if zero-downtime is required (serve both formats, frontend reads new format, fall back to old format if `data.data` is undefined).

### 5.3 Testing Strategy

1. Each phase updates its own tests.
2. Run all tests after each phase.
3. Manual E2E test:
   - Login as a user
   - Send a message
   - Load chat history
   - Verify content is displayed
   - Login as admin
   - Verify admin dashboard data loads
4. Run encryption migration script to verify Phase D integration still works.

### 5.4 Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Frontend reads `data.data` from old backend | Low (co-deployed) | High (no data shown) | Deploy frontend+backend together; use dual-payload as safety net |
| Error object breaks alert() call | Medium | Medium (alert shows "[object Object]") | Well-known risk; test all error paths |
| Admin dashboard broken | Low (tested) | High (ops impact) | Manual E2E test before deploy |
| Phase dependency chain | Medium | Medium | Each phase is self-contained; rollback per phase |

---

## Appendix A — Current vs Proposed Response Comparison

### `POST /auth/login` (Success)

**Current:**
```json
{"success": true, "username": "Alice", "is_admin": true}
```

**Proposed:**
```json
{"success": true, "data": {"username": "Alice", "is_admin": true}, "error": null, "meta": {}}
```

### `GET /api/history` (Success)

**Current:**
```json
{"success": true, "messages": [...], "total": 150}
```

**Proposed:**
```json
{"success": true, "data": {"messages": [...]}, "error": null, "meta": {"total": 150, "limit": 50, "offset": 0, "has_more": true}}
```

### `POST /api/groups/create` (Failure — unauthorized)

**Current:**
```json
{"success": false, "error": "Not authenticated"}
```
- Status: 401

**Proposed:**
```json
{"success": false, "data": null, "error": {"code": "AUTH.REQUIRED", "message": "Not authenticated"}, "meta": {}}
```
- Status: 401

### `POST /api/groups/create` (Failure — rate limited)

**Current:**
```json
{"success": false, "error": "Rate limit exceeded"}
```
- Status: 200

**Proposed:**
```json
{"success": false, "data": null, "error": {"code": "RATE_LIMIT.EXCEEDED", "message": "Rate limit exceeded"}, "meta": {}}
```
- Status: 429

---

## Appendix B — Full Error Code Table

| Code | HTTP | Current error string(s) |
|------|------|------------------------|
| `AUTH.REQUIRED` | 401 | "Not authenticated" |
| `AUTH.INVALID_CREDENTIALS` | 401 | "Invalid credentials" |
| `AUTH.BANNED` | 401 | "Invalid username or password" (deliberately ambiguous) |
| `AUTH.FORBIDDEN` | 403 | "Unauthorized", "Only the group owner can invite users" |
| `AUTH.ADMIN_REQUIRED` | 401 | "Unauthorized admin access." |
| `VALIDATION.REQUIRED_FIELD` | 400 | "Username and password required", "Group name is required", "Missing parameters" |
| `VALIDATION.INVALID_FORMAT` | 400 | Various validation error messages |
| `VALIDATION.INVALID_FILENAME` | 400 | "Invalid filename" |
| `VALIDATION.FILE_TYPE` | 400 | "File type not allowed." |
| `RESOURCE.NOT_FOUND` | 404 | "Recipient not found", "Group not found", "Invitation not found", "Member not found", etc. |
| `RESOURCE.CONFLICT` | 409 | "User 'X' already exists.", "Group name 'X' already exists." |
| `RESOURCE.ALREADY_MEMBER` | 400 | "Already a member" |
| `RESOURCE.ALREADY_REQUESTED` | 400 | "Request already pending" |
| `RESOURCE.OWNER_CANNOT_LEAVE` | 400 | "Owner cannot leave, delete the group instead" |
| `UPLOAD.FILE_TOO_LARGE` | 413 | "File too large." |
| `RATE_LIMIT.EXCEEDED` | 429 | "Rate limit exceeded" |
| `SERVER.INTERNAL_ERROR` | 500 | Various exception messages |
