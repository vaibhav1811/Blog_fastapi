## Imports for Posts Router
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import models
from database import get_db
from schemas import PostCreate, PostResponse, PostUpdate, PaginatedPostsResponse, LikeResponse
from auth import CurrentUser, verify_access_token
from fastapi.security import OAuth2PasswordBearer

router = APIRouter()

oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="api/users/token", auto_error=False)


async def get_optional_user(
    token: Annotated[str | None, Depends(oauth2_scheme_optional)] = None,
    db: AsyncSession = Depends(get_db),
) -> models.User | None:
    """
    Returns the current user if a valid token is present, otherwise None.
    Used for endpoints that are public but show personalised data when logged in
    (e.g. whether the current user has already liked a post).
    """
    if token is None:
        return None
    user_id = verify_access_token(token)
    if user_id is None:
        return None
    try:
        user_id_int = int(user_id)
    except (TypeError, ValueError):
        return None
    result = await db.execute(select(models.User).where(models.User.id == user_id_int))
    return result.scalars().first()


def _build_post_responses(
    posts: list[models.Post],
    like_count_map: dict[int, int],
    liked_post_ids: set[int],
) -> list[PostResponse]:
    """
    Convert Post ORM objects into PostResponse Pydantic models enriched
    with pre-fetched like counts and the current user's liked status.
    Centralised here to avoid duplicating this logic across route handlers.
    """
    responses = []
    for post in posts:
        pr = PostResponse.model_validate(post)
        pr.like_count = like_count_map.get(post.id, 0)
        pr.user_has_liked = post.id in liked_post_ids
        responses.append(pr)
    return responses


async def _fetch_like_data(
    db: AsyncSession,
    post_ids: list[int],
    current_user: models.User | None,
) -> tuple[dict[int, int], set[int]]:
    """
    Batch-fetch like counts and the current user's liked set.

    Uses two indexed GROUP BY queries regardless of how many post IDs are
    provided — this prevents the N+1 query problem when loading feed pages.

    Returns:
        like_count_map  — {post_id: count}
        liked_post_ids  — set of post_ids already liked by current_user
    """
    if not post_ids:
        return {}, set()

    # Query 1: batch COUNT per post (single SQL, uses index on post_id)
    counts_result = await db.execute(
        select(models.PostLike.post_id, func.count().label("n"))
        .where(models.PostLike.post_id.in_(post_ids))
        .group_by(models.PostLike.post_id)
    )
    like_count_map = {row.post_id: row.n for row in counts_result}

    # Query 2: which posts has the current user already liked?
    liked_post_ids: set[int] = set()
    if current_user:
        liked_result = await db.execute(
            select(models.PostLike.post_id)
            .where(models.PostLike.post_id.in_(post_ids))
            .where(models.PostLike.user_id == current_user.id)
        )
        liked_post_ids = {row.post_id for row in liked_result}

    return like_count_map, liked_post_ids


## get_posts
@router.get("", response_model=PaginatedPostsResponse)
async def get_posts(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[models.User | None, Depends(get_optional_user)] = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
):
    # Total count for pagination
    count_result = await db.execute(select(func.count()).select_from(models.Post))
    total = count_result.scalar() or 0

    result = await db.execute(
        select(models.Post)
        .options(selectinload(models.Post.author))
        .order_by(models.Post.date_posted.desc())
        .offset(skip)
        .limit(limit),
    )
    posts = result.scalars().all()
    has_more = skip + len(posts) < total

    # Batch-fetch like counts and user's liked set (2 queries for any page size)
    post_ids = [p.id for p in posts]
    like_count_map, liked_post_ids = await _fetch_like_data(db, post_ids, current_user)

    return PaginatedPostsResponse(
        posts=_build_post_responses(posts, like_count_map, liked_post_ids),
        total=total,
        skip=skip,
        limit=limit,
        has_more=has_more,
    )


## create_post
@router.post(
    "",
    response_model=PostResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_post(
    post: PostCreate,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    new_post = models.Post(
        title=post.title,
        content=post.content,
        user_id=current_user.id,
    )
    db.add(new_post)
    await db.commit()
    # Refresh the author relationship so the response can include author data
    await db.refresh(new_post, attribute_names=["author"])
    return new_post


## get_post — single post with like data
@router.get("/{post_id}", response_model=PostResponse)
async def get_post(
    post_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[models.User | None, Depends(get_optional_user)] = None,
):
    result = await db.execute(
        select(models.Post)
        .options(selectinload(models.Post.author))
        .where(models.Post.id == post_id),
    )
    post = result.scalars().first()
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")

    like_count_map, liked_post_ids = await _fetch_like_data(db, [post_id], current_user)
    pr = PostResponse.model_validate(post)
    pr.like_count = like_count_map.get(post_id, 0)
    pr.user_has_liked = post_id in liked_post_ids
    return pr


## toggle_like — POST /api/posts/{post_id}/like
@router.post("/{post_id}/like", response_model=LikeResponse)
async def toggle_like(
    post_id: int,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Toggle a like on a post for the current authenticated user.

    - User has NOT liked → inserts PostLike row → returns liked=True
    - User HAS liked     → deletes PostLike row → returns liked=False

    The composite primary key (user_id, post_id) on post_likes guarantees
    uniqueness at the DB level — no application-level duplicate checks needed.
    Returns the updated like count and new liked state.
    """
    # Verify the post exists
    post_check = await db.execute(
        select(models.Post.id).where(models.Post.id == post_id)
    )
    if post_check.scalar() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")

    # Check if the user already liked this post
    existing_result = await db.execute(
        select(models.PostLike).where(
            models.PostLike.post_id == post_id,
            models.PostLike.user_id == current_user.id,
        )
    )
    existing_like = existing_result.scalars().first()

    if existing_like:
        # Unlike: remove the row
        await db.delete(existing_like)
        liked = False
    else:
        # Like: add a new row
        new_like = models.PostLike(post_id=post_id, user_id=current_user.id)
        db.add(new_like)
        liked = True

    await db.commit()

    # Return the fresh like count after the toggle
    count_result = await db.execute(
        select(func.count())
        .select_from(models.PostLike)
        .where(models.PostLike.post_id == post_id)
    )
    like_count = count_result.scalar() or 0

    return LikeResponse(liked=liked, like_count=like_count)


## update_post_full
@router.put("/{post_id}", response_model=PostResponse)
async def update_post_full(
    post_id: int,
    post_data: PostCreate,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(models.Post).where(models.Post.id == post_id))
    post = result.scalars().first()
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found",
        )

    if post.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this post",
        )

    post.title = post_data.title
    post.content = post_data.content

    await db.commit()
    await db.refresh(post, attribute_names=["author"])
    return post


## update_post_partial
@router.patch("/{post_id}", response_model=PostResponse)
async def update_post_partial(
    post_id: int,
    post_data: PostUpdate,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(models.Post).where(models.Post.id == post_id))
    post = result.scalars().first()
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found",
        )

    if post.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this post",
        )

    update_data = post_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(post, field, value)

    await db.commit()
    await db.refresh(post, attribute_names=["author"])
    return post


## delete_post
@router.delete("/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_post(
    post_id: int,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(models.Post).where(models.Post.id == post_id))
    post = result.scalars().first()
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found",
        )

    if post.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this post",
        )

    await db.delete(post)
    await db.commit()