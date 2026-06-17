"""
Comments Router — /api/posts/{post_id}/comments

Endpoints:
  GET  /api/posts/{post_id}/comments         — paginated top-level comments + their replies
  POST /api/posts/{post_id}/comments         — create a new comment (auth required)
  PATCH /api/comments/{comment_id}           — edit own comment (auth required)
  DELETE /api/comments/{comment_id}          — delete own comment (auth required)

Query strategy:
  Top-level comments are fetched with selectinload for replies and authors in one
  batched query (no N+1). Authors for replies are also selectinloaded in the same
  statement, so the full comment thread loads in 1–2 SQL queries total.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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


## ── GET /api/posts/{post_id}/comments ──────────────────────────────────────
@router.get("", response_model=PaginatedCommentsResponse)
async def get_comments(
    post_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    """
    Return paginated top-level comments for a post, each with their replies
    and author info pre-loaded. Uses selectinload so the entire tree is
    fetched in at most 2 SQL queries (one for comments, one batched for authors).
    """
    # Verify the post exists
    post_check = await db.execute(select(models.Post.id).where(models.Post.id == post_id))
    if post_check.scalar() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")

    # Total count of top-level comments for this post
    total_result = await db.execute(
        select(func.count())
        .select_from(models.Comment)
        .where(models.Comment.post_id == post_id)
        .where(models.Comment.parent_id.is_(None))
    )
    total = total_result.scalar() or 0

    # Fetch top-level comments with authors + replies + reply authors
    result = await db.execute(
        select(models.Comment)
        .options(
            selectinload(models.Comment.author),
            selectinload(models.Comment.replies).selectinload(models.Comment.author),
        )
        .where(models.Comment.post_id == post_id)
        .where(models.Comment.parent_id.is_(None))
        .order_by(models.Comment.created_at.asc())
        .offset(skip)
        .limit(limit)
    )
    comments = result.scalars().all()
    has_more = skip + len(comments) < total

    return PaginatedCommentsResponse(
        comments=[CommentResponse.model_validate(c) for c in comments],
        total=total,
        has_more=has_more,
    )


## ── POST /api/posts/{post_id}/comments ─────────────────────────────────────
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

    Validates that:
      - The post exists.
      - If parent_id is set, the parent comment belongs to the same post
        and is itself a top-level comment (enforces max 1 level of nesting).
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
    await db.commit()
    # Refresh with author and replies relationships loaded for the response
    await db.refresh(new_comment, attribute_names=["author", "replies"])

    return CommentResponse.model_validate(new_comment)


## ── PATCH /api/comments/{comment_id} ───────────────────────────────────────
@router.patch(
    "/{comment_id}",
    response_model=CommentResponse,
    # NOTE: this route is mounted at /api/comments so there is no post_id prefix
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
        .options(selectinload(models.Comment.author), selectinload(models.Comment.replies))
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
    await db.refresh(comment, attribute_names=["author", "replies"])
    return CommentResponse.model_validate(comment)


## ── DELETE /api/comments/{comment_id} ──────────────────────────────────────
@router.delete("/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(
    comment_id: int,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Delete a comment. Only the comment author may delete it.
    Cascade delete on the DB will also remove any replies.
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

    await db.delete(comment)
    await db.commit()
