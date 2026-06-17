"""
Comments Router

Endpoints:
  GET  /api/posts/{post_id}/comments         — cursor-paginated top-level comments + top-3 reply preview
  GET  /api/comments/{comment_id}/replies    — cursor-paginated replies for a single comment (\"Load more\")
  POST /api/posts/{post_id}/comments         — create a comment or reply (auth required)
  PATCH /api/comments/{comment_id}           — edit own comment (auth required)
  DELETE /api/comments/{comment_id}          — delete own comment (auth required)

Query strategy (newest-first throughout):
  - Cursor pagination: WHERE id < :cursor ORDER BY id DESC
      O(1) at any depth — uses the B-Tree PK index, never does a full table scan.
      The `+1 trick` detects has_more without a COUNT(*): fetch limit+1 rows,
      if we get limit+1 back then there IS a next page.

  - Top-3 replies per comment: SQL ROW_NUMBER() window function
      A single subquery ranks all replies for the fetched parent IDs newest-first,
      then we pull only those with rn <= 3.  Two extra DB round-trips replace the
      old selectinload(replies) which could load thousands of rows into RAM.

  - reply_count: maintained via atomic increment/decrement on create/delete.
      Never uses COUNT(*) — the count is read straight from the column.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload, selectinload

import models
from auth import CurrentUser
from database import get_db
from schemas import (
    CommentCreate,
    CommentResponse,
    CommentUpdate,
    PaginatedCommentsResponse,
)

router = APIRouter()

# Maximum number of replies shown in the initial comment load (preview).
_REPLY_PREVIEW_COUNT = 3
_DEFAULT_LIMIT = 20


# ── Helper: batch-fetch top-N replies via window function ─────────────────────

async def _batch_top_replies(
    db: AsyncSession,
    parent_ids: list[int],
    n: int = _REPLY_PREVIEW_COUNT,
) -> dict[int, list[models.Comment]]:
    """
    Fetch the N newest replies for each parent_id in two DB round-trips.

    Round-trip 1: Window-function subquery → top-N reply IDs per parent.
    Round-trip 2: Fetch full Comment + author for those IDs (selectinload batches authors).

    This avoids loading ALL replies into memory when a comment has thousands of replies
    (which is what selectinload(replies) on the parent query would do).

    Returns a dict: { parent_id: [Comment(newest), Comment, ...] }
    """
    if not parent_ids:
        return {}

    # Subquery: number replies within each parent, newest first (id DESC)
    rn_label = func.row_number().over(
        partition_by=models.Comment.parent_id,
        order_by=models.Comment.id.desc(),
    ).label("rn")

    inner = (
        select(models.Comment.id, rn_label)
        .where(models.Comment.parent_id.in_(parent_ids))
        .subquery("ranked")
    )

    # Pull only the IDs of the top-N replies per parent
    top_id_rows = await db.execute(
        select(inner.c.id).where(inner.c.rn <= n)
    )
    top_ids = top_id_rows.scalars().all()

    if not top_ids:
        return {}

    # Fetch full Comment objects + authors in one batched query.
    # selectinload generates a single IN() query for all authors — no N+1.
    reply_rows = await db.execute(
        select(models.Comment)
        .options(
            selectinload(models.Comment.author),
            noload(models.Comment.replies),   # replies of replies don't exist (max 1 level)
        )
        .where(models.Comment.id.in_(top_ids))
        .order_by(models.Comment.parent_id, models.Comment.id.desc())
    )
    replies = reply_rows.scalars().all()

    # Group by parent_id preserving newest-first order within each group
    by_parent: dict[int, list[models.Comment]] = {}
    for r in replies:
        by_parent.setdefault(r.parent_id, []).append(r)
    return by_parent


# ── GET /api/posts/{post_id}/comments ────────────────────────────────────────

@router.get("", response_model=PaginatedCommentsResponse)
async def get_comments(
    post_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    cursor: Annotated[
        int | None,
        Query(description="Cursor: ID of the last comment from the previous page (exclusive). Omit for the first page."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = _DEFAULT_LIMIT,
):
    """
    Return cursor-paginated top-level comments for a post, newest first.

    Each comment includes:
      - reply_count  (from DB column — no COUNT(*) query)
      - replies[]    (top 3 newest replies via window function)

    To paginate: pass ?cursor=<next_cursor> from the previous response.
    When next_cursor is null, you have reached the first (oldest) comment.
    """
    # Verify the post exists
    post_check = await db.execute(select(models.Post.id).where(models.Post.id == post_id))
    if post_check.scalar() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")

    # Cursor-paginated query — no COUNT(*), no OFFSET
    stmt = (
        select(models.Comment)
        .options(
            selectinload(models.Comment.author),
            noload(models.Comment.replies),  # replies loaded separately via window function
        )
        .where(models.Comment.post_id == post_id)
        .where(models.Comment.parent_id.is_(None))
        .order_by(models.Comment.id.desc())
        .limit(limit + 1)  # +1 trick: fetch one extra to detect whether a next page exists
    )
    if cursor is not None:
        # Keyset condition: only rows older (smaller ID) than the cursor
        stmt = stmt.where(models.Comment.id < cursor)

    result = await db.execute(stmt)
    comments = list(result.scalars().all())

    # Determine next_cursor from the extra row
    has_more = len(comments) > limit
    if has_more:
        comments = comments[:limit]
    next_cursor: int | None = comments[-1].id if has_more else None

    # Batch-fetch top-3 replies per comment (2 queries via window function)
    parent_ids = [c.id for c in comments]
    replies_by_parent = await _batch_top_replies(db, parent_ids)

    # Build response: manually assign the reply preview so we never touch the
    # lazy ORM relationship (which would trigger an async greenlet error)
    comment_responses: list[CommentResponse] = []
    for c in comments:
        data = CommentResponse.model_validate(c)
        data.replies = [
            CommentResponse.model_validate(r)
            for r in replies_by_parent.get(c.id, [])
        ]
        comment_responses.append(data)

    return PaginatedCommentsResponse(
        comments=comment_responses,
        next_cursor=next_cursor,
    )


# ── GET /api/comments/{comment_id}/replies ────────────────────────────────────

@router.get("/{comment_id}/replies", response_model=PaginatedCommentsResponse)
async def get_replies(
    comment_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    cursor: Annotated[
        int | None,
        Query(description="Cursor: ID of the last reply from the previous page (exclusive)."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
):
    """
    Cursor-paginated replies for a single top-level comment, newest first.

    Used by the frontend \"View X more replies\" button after the initial 3-reply
    preview has been shown. Same cursor mechanics as the parent comments endpoint.
    """
    # Verify the parent comment exists
    parent_check = await db.execute(
        select(models.Comment.id).where(models.Comment.id == comment_id)
    )
    if parent_check.scalar() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")

    stmt = (
        select(models.Comment)
        .options(
            selectinload(models.Comment.author),
            noload(models.Comment.replies),
        )
        .where(models.Comment.parent_id == comment_id)
        .order_by(models.Comment.id.desc())
        .limit(limit + 1)
    )
    if cursor is not None:
        stmt = stmt.where(models.Comment.id < cursor)

    result = await db.execute(stmt)
    replies = list(result.scalars().all())

    has_more = len(replies) > limit
    if has_more:
        replies = replies[:limit]
    next_cursor: int | None = replies[-1].id if has_more else None

    return PaginatedCommentsResponse(
        comments=[CommentResponse.model_validate(r) for r in replies],
        next_cursor=next_cursor,
    )


# ── POST /api/posts/{post_id}/comments ───────────────────────────────────────

@router.post("", response_model=CommentResponse, status_code=status.HTTP_201_CREATED)
async def create_comment(
    post_id: int,
    body: CommentCreate,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Create a top-level comment or a reply on a post.
      - body.parent_id = None  → top-level comment
      - body.parent_id = int   → reply to another comment

    Validates:
      - The post exists.
      - If parent_id is set: parent belongs to this post and is itself top-level
        (max nesting depth of 1 — no replies to replies).

    On success, increments the parent comment's reply_count atomically
    in the same transaction to keep the counter consistent.
    """
    # Verify the post exists
    post_check = await db.execute(select(models.Post.id).where(models.Post.id == post_id))
    if post_check.scalar() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")

    # Validate parent_id if replying
    if body.parent_id is not None:
        parent_result = await db.execute(
            select(models.Comment).where(models.Comment.id == body.parent_id)
        )
        parent = parent_result.scalars().first()
        if parent is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Parent comment not found",
            )
        if parent.post_id != post_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Parent comment does not belong to this post",
            )
        if parent.parent_id is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot reply to a reply — maximum nesting depth is 1",
            )

    new_comment = models.Comment(
        post_id=post_id,
        user_id=current_user.id,
        content=body.content,
        parent_id=body.parent_id,
    )
    db.add(new_comment)
    await db.flush()  # Assign new_comment.id without committing yet

    # Atomically increment parent's reply_count in the same transaction
    if body.parent_id is not None:
        await db.execute(
            update(models.Comment)
            .where(models.Comment.id == body.parent_id)
            .values(reply_count=models.Comment.reply_count + 1)
        )

    await db.commit()
    # Re-fetch with all required attributes explicitly loaded.
    # We CANNOT use db.refresh() + then assign new_comment.replies = [] because
    # assigning to an expired ORM relationship triggers a lazy-load attempt,
    # which raises MissingGreenlet in async SQLAlchemy.
    result = await db.execute(
        select(models.Comment)
        .options(selectinload(models.Comment.author), noload(models.Comment.replies))
        .where(models.Comment.id == new_comment.id)
    )
    fresh = result.scalars().one()
    return CommentResponse.model_validate(fresh)


# ── PATCH /api/comments/{comment_id} ─────────────────────────────────────────

@router.patch(
    "/{comment_id}",
    response_model=CommentResponse,
    # NOTE: mounted at /api/comments so there is no post_id prefix
)
async def update_comment(
    comment_id: int,
    body: CommentUpdate,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Edit the content of an existing comment. Only the comment's author may edit it."""
    result = await db.execute(
        select(models.Comment)
        .options(selectinload(models.Comment.author), noload(models.Comment.replies))
        .where(models.Comment.id == comment_id)
    )
    comment = result.scalars().first()
    if not comment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")
    if comment.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to edit this comment",
        )

    comment.content = body.content
    comment.updated_at = datetime.now(UTC)
    await db.commit()
    # Re-fetch after commit for the same reason as create_comment:
    # avoid MissingGreenlet on the expired replies relationship.
    result = await db.execute(
        select(models.Comment)
        .options(selectinload(models.Comment.author), noload(models.Comment.replies))
        .where(models.Comment.id == comment_id)
    )
    fresh = result.scalars().one()
    return CommentResponse.model_validate(fresh)


# ── DELETE /api/comments/{comment_id} ────────────────────────────────────────

@router.delete("/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(
    comment_id: int,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Delete a comment. Only the comment author may delete it.
    DB cascade delete removes any replies automatically.

    If this is a reply, decrements the parent comment's reply_count atomically
    (floored at 0 via GREATEST for safety against counter drift).
    """
    result = await db.execute(
        select(models.Comment).where(models.Comment.id == comment_id)
    )
    comment = result.scalars().first()
    if not comment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")
    if comment.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this comment",
        )

    # Atomically decrement parent reply_count, floored at 0 for safety
    if comment.parent_id is not None:
        await db.execute(
            update(models.Comment)
            .where(models.Comment.id == comment.parent_id)
            .values(reply_count=func.greatest(models.Comment.reply_count - 1, 0))
        )

    await db.delete(comment)
    await db.commit()
