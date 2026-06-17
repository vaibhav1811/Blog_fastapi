# Comment System — Production Implementation Guide

This document captures every architectural decision, code change, and design pattern
used to build the production-grade comment system for this FastAPI blog.

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Architecture Decisions](#2-architecture-decisions)
3. [Database Changes](#3-database-changes)
4. [API Layer Changes](#4-api-layer-changes)
5. [Frontend (JavaScript)](#5-frontend-javascript)
6. [Template Changes](#6-template-changes)
7. [Bug Fix Log](#7-bug-fix-log)
8. [Query Performance Summary](#8-query-performance-summary)
9. [How to Rebuild Docker](#9-how-to-rebuild-docker)

---

## 1. Problem Statement

The existing codebase had a comment icon on post cards with no backend or frontend
functionality. The goal was to implement a **Twitter/Instagram-grade comment system**
that would remain performant at scale (millions of comments), using only
FastAPI + PostgreSQL + vanilla JavaScript (no Redis, no background queues).

The three core anti-patterns to eliminate were:

| Anti-pattern | Why it fails at scale |
|---|---|
| `OFFSET/LIMIT` pagination | Full table scan grows with page depth — `OFFSET 10000` reads 10,000 rows |
| `selectinload(replies)` — load ALL replies per comment | A comment with 5,000 replies loads all 5,000 into RAM on every page load |
| `COUNT(*)` for totals | Requires a full sequential scan; slow on large tables |

---

## 2. Architecture Decisions

### 2.1 Cursor-Based Pagination (Keyset Pagination)

**Decision:** Replace `skip`/`limit` with a cursor (the `id` of the last seen item).

**Why:** SQL can use the B-Tree primary key index for a constant-time seek:
```sql
-- Old (slow) — scans 10,000 rows to skip them
SELECT * FROM comments OFFSET 10000 LIMIT 20;

-- New (fast) — direct index seek regardless of depth
SELECT * FROM comments WHERE id < :cursor ORDER BY id DESC LIMIT 20;
```

**Sort Order:** Newest first (`ORDER BY id DESC`). This mirrors Instagram/Twitter.

**next_cursor mechanism (the `+1 trick`):**
- Fetch `limit + 1` rows.
- If we get back `limit + 1`, there IS a next page → set `next_cursor = last_row.id`.
- Slice back to `limit` rows and return. No `COUNT(*)` needed.
- When `next_cursor` is `None`, the client knows it has reached the end.

### 2.2 1-Level Nesting Only (Flat Threaded Comments)

**Decision:** Comments can have replies, but replies cannot have replies.
`parent_id` must point to a top-level comment (`parent_id IS NULL`).

**Why:** Recursive nesting requires recursive CTEs or multiple round-trips. Flat
threading (used by Instagram, Twitter, YouTube) is simpler, faster, and avoids
UI complexity. The constraint is enforced at the API level:
```python
if parent.parent_id is not None:
    raise HTTPException(400, "Cannot reply to a reply — max nesting depth is 1")
```

### 2.3 SQL Window Function for Top-3 Reply Preview

**Decision:** On the GET comments endpoint, show only the **3 newest replies** per
comment, fetched in a single batch query using `ROW_NUMBER()`.

**Why:** With `selectinload(replies)` (the original approach), fetching 20 comments
could load 20 × N replies into RAM — potentially tens of thousands of rows.

The window-function approach costs exactly **2 extra DB queries** for any page size:

```sql
-- Query 1: Get top-3 reply IDs per parent (one round-trip for ALL parents)
SELECT id FROM (
    SELECT id,
           ROW_NUMBER() OVER (PARTITION BY parent_id ORDER BY id DESC) AS rn
    FROM comments
    WHERE parent_id IN (101, 102, 103, ...)   -- all parent IDs from the page
) ranked
WHERE rn <= 3;

-- Query 2: Fetch full Comment objects for those IDs
SELECT * FROM comments WHERE id IN (...);
```

### 2.4 Denormalized `reply_count` Column

**Decision:** Add a `reply_count INTEGER` column to the `comments` table, maintained
by increment/decrement in the create/delete endpoints.

**Why:** Without this column, displaying "View 47 more replies" would require a
`SELECT COUNT(*) FROM comments WHERE parent_id = X` query — one per comment per
page load. With the denormalized counter, the count is free (already in the row).

Increment on reply creation:
```python
await db.execute(
    update(Comment)
    .where(Comment.id == parent_id)
    .values(reply_count=Comment.reply_count + 1)
)
```

Decrement on reply deletion (with floor at 0 for safety):
```python
await db.execute(
    update(Comment)
    .where(Comment.id == parent_id)
    .values(reply_count=func.greatest(Comment.reply_count - 1, 0))
)
```

### 2.5 Composite Index for Cursor Queries

A composite index `(post_id, parent_id, id)` was added to support the cursor query:
```sql
WHERE post_id = :x AND parent_id IS NULL AND id < :cursor ORDER BY id DESC
```
PostgreSQL can satisfy this with an **index-only scan** — no heap access needed.

---

## 3. Database Changes

### 3.1 Alembic Migration

**File:** `alembic/versions/c7e2f80b1a39_add_reply_count_to_comments.py`

Changes applied on `alembic upgrade head`:
1. `ALTER TABLE comments ADD COLUMN reply_count INTEGER NOT NULL DEFAULT 0`
2. Back-fill: `UPDATE comments SET reply_count = (SELECT COUNT(*) FROM comments r WHERE r.parent_id = comments.id) WHERE parent_id IS NULL`
3. `CREATE INDEX ix_comments_post_parent_id ON comments (post_id, parent_id, id)`

**Rollback** (`alembic downgrade`):
1. Drop the index
2. Drop the `reply_count` column

### 3.2 Model Update

**File:** `models.py` — `Comment` class

```python
# Added field:
reply_count: Mapped[int] = mapped_column(
    Integer, nullable=False, default=0, server_default="0"
)
```

---

## 4. API Layer Changes

**File:** `routers/comments.py` — complete rewrite

### Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/posts/{post_id}/comments` | Cursor-paginated top-level comments + top-3 reply preview |
| `GET` | `/api/comments/{comment_id}/replies` | NEW — cursor-paginated replies for a single comment |
| `POST` | `/api/posts/{post_id}/comments` | Create comment or reply |
| `PATCH` | `/api/comments/{comment_id}` | Edit own comment |
| `DELETE` | `/api/comments/{comment_id}` | Delete own comment |

### Schema Changes (`schemas.py`)

**`CommentResponse`** — added `reply_count: int = 0`

**`PaginatedCommentsResponse`** — replaced `total: int` + `has_more: bool` with:
```python
class PaginatedCommentsResponse(BaseModel):
    comments: list[CommentResponse]
    next_cursor: int | None  # None = no more pages
```

### Critical Bug Fixed: MissingGreenlet

**Bug:** In async SQLAlchemy, assigning `orm_object.relationship = []` after
`db.commit()` triggers an implicit lazy-load of the expired collection
(to fire removal events), which raises `MissingGreenlet` in async context.

**Symptom:** `POST /api/posts/{id}/comments` returned HTTP 500 with plain-text
body `"Internal Server Error"` instead of JSON.

**Fix:** After commit, re-fetch the object with a clean `SELECT` that uses
`noload(replies)` to prevent any relationship access:
```python
await db.commit()
result = await db.execute(
    select(models.Comment)
    .options(selectinload(models.Comment.author), noload(models.Comment.replies))
    .where(models.Comment.id == new_comment.id)
)
fresh = result.scalars().one()
return CommentResponse.model_validate(fresh)
```

---

## 5. Frontend (JavaScript)

**File:** `static/js/comments.js` — new module (modeled after `likes.js`)

### Design Principles

- **Module pattern:** ES6 `export`/`import` only. One public function: `initComments(postId)`.
- **Event delegation:** One `click` listener on `#commentsList` handles all buttons
  (reply, edit, delete, load-more) for both initial and dynamically added elements.
  No re-binding needed when new comments are appended.
- **Optimistic UI:** New comments appear instantly. On failure, an inline error
  message is shown and the DOM is rolled back.
- **Cursor state:** Module-level `_nextCursor` tracks the current pagination position.

### Key Functions

| Function | Responsibility |
|---|---|
| `initComments(postId)` | Entry point — fetches user, shows form if logged in, loads first page |
| `_loadMoreComments()` | Fetches next cursor page, appends to `#commentsList` |
| `_buildCommentHTML(comment)` | Builds full comment card HTML string (XSS-safe via `escapeHtml`) |
| `_buildReplyHTML(reply)` | Builds reply card HTML string |
| `_bindContainerEvents(container)` | Sets up event delegation switch on `data-action` attribute |
| `_handleReplySubmit(parentId)` | POST reply, prepend to replies container |
| `_handleEditSave(commentId)` | PATCH comment content, update DOM in place |
| `_handleDelete(commentId)` | DELETE with optimistic fade-out, remove from DOM |
| `_handleLoadMoreReplies(btn)` | GET `/api/comments/{id}/replies` with cursor, append |
| `_showInlineError(container, msg)` | Inline error toast, auto-removes after 4 seconds |

### Error Handling

All `response.json()` calls in error paths are wrapped in `try/catch` to prevent
`SyntaxError` if the server returns a non-JSON body (e.g., a raw 500):
```javascript
if (!response.ok) {
    let errorMsg = `Server error (${response.status}). Please try again.`;
    try {
        const err = await response.json();
        errorMsg = getErrorMessage(err);
    } catch { /* response body was not JSON */ }
    throw new Error(errorMsg);
}
```

---

## 6. Template Changes

**File:** `templates/post.html`

Added a full `<section id="comments">` below the post content containing:
- `#commentForm` — hidden by default, shown by JS when user is logged in
- `#commentInput` — textarea with 2000-char limit + live character counter
- `#commentsList` — populated entirely by `comments.js` (no server-side rendering)
- `#loadMoreCommentsWrap` — hidden until a next page exists
- Login prompt paragraph for unauthenticated users (hidden by JS when logged in)

Scripts block wires up `comments.js`:
```javascript
import { initComments } from '/static/js/comments.js';
initComments({{ post.id }});
```

---

## 7. Bug Fix Log

| # | Bug | Root Cause | Fix |
|---|---|---|---|
| 1 | `POST /comments` → HTTP 500, plain-text body | `new_comment.replies = []` after commit triggered MissingGreenlet lazy-load | Re-fetch with `noload(replies)` after commit |
| 2 | `SyntaxError: Unexpected token 'I'` in JS | `response.json()` on plain-text error body | Wrapped error `response.json()` in `try/catch` |

---

## 8. Query Performance Summary

For a page of 20 top-level comments, the number of DB round-trips:

| Phase | Queries | Notes |
|---|---|---|
| POST existence check | 1 | `SELECT posts.id WHERE id=X` |
| Top-level comments (cursor) | 1 | Index seek on `(post_id, parent_id, id)` |
| Batch author load | 1 | `selectinload` → single `IN()` query |
| Window function reply IDs | 1 | `ROW_NUMBER()` subquery over `parent_ids` |
| Fetch reply objects | 1 | `SELECT WHERE id IN (top_ids)` |
| Batch reply author load | 1 | `selectinload` → single `IN()` query |
| **Total** | **6** | **Constant — does not grow with comment count** |

Compare to the naive approach:
- Old `OFFSET` query: scans N rows to skip them — O(N)
- Old `selectinload(replies)`: could load thousands of reply objects into RAM
- Old `COUNT(*)`: sequential scan for each page load

---

## 9. How to Rebuild Docker

The application runs inside a Docker container. Any change to source files
(Python, HTML templates, JavaScript, CSS) requires rebuilding the image.

### Why a Rebuild is Needed

Docker bakes a snapshot of your source code into the image at build time.
The `COPY . ./` instruction in the `Dockerfile` captures everything at that moment.
Editing files on your host machine has **no effect** on a running container.

### Step-by-Step Rebuild

```powershell
# Step 1: Stop the currently running container
# Press Ctrl+C in the terminal where docker run is active
# OR find and kill it:
docker ps                          # find container ID
docker stop <container_id>

# Step 2: Rebuild the image
# The --no-cache flag forces a full rebuild (use only if you suspect stale layers)
docker build -t fastapi-app .

# Step 3: Start the new container
docker run -p 8080:8080 --env-file .env fastapi-app
```

### When is Each Step Required?

| Change Type | Rebuild Image? | Restart Container? |
|---|---|---|
| `.py` (Python/FastAPI) | ✅ Yes | — (rebuild includes restart) |
| `.html` (Jinja2 templates) | ✅ Yes | — |
| `.js` / `.css` (static files) | ✅ Yes | — |
| `.env` (environment variables) | ❌ No | ✅ Yes (pass new `--env-file`) |
| `alembic/versions/` (migrations) | ✅ Yes | — (migration runs on startup) |

### Fast Rebuild (Why It's Not Slow)

The `Dockerfile` uses layer caching. Only the layers that changed are rebuilt:

```
Layer 1: Python base image        → CACHED (never changes)
Layer 2: uv / pip dependencies    → CACHED (only rebuilds if pyproject.toml changes)
Layer 3: COPY source files        → RE-RUNS (your code changed here)
Layer 4: uv sync (install project) → RE-RUNS (depends on layer 3)
```

A typical rebuild with no dependency changes takes **~30 seconds**.

### One-Liner Rebuild + Restart

```powershell
docker build -t fastapi-app . && docker run -p 8080:8080 --env-file .env fastapi-app
```

> **Note:** Alembic runs `alembic upgrade head` automatically at container startup
> (defined in the `Dockerfile` CMD or entrypoint). New migrations are applied
> without any manual steps.
