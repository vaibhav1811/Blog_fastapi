## Imports for Posts Router
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status,Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import models
from database import get_db
from schemas import PostCreate, PostResponse, PostUpdate , PaginatedPostsResponse
from auth import CurrentUser
router = APIRouter()

## get_posts
@router.get("", response_model=PaginatedPostsResponse)
async def get_posts(
            db: Annotated[AsyncSession, Depends(get_db)],
            skip: Annotated[int, Query(ge=0)] = 0,
            limit: Annotated[int, Query(ge=1, le=100)] = 10,
            ):
    # Get the total count of posts
    count_result = await db.execute(select(func.count()).select_from(models.Post))
    total = count_result.scalar() or 0

    result = await db.execute(
        select(models.Post)
        .options(selectinload(models.Post.author))
        .order_by(models.Post.date_posted.desc()) #order by date posted in descending order to get the latest posts first
        .offset(skip)
        .limit(limit),
        #order by date posted in descending order to get the latest posts first
    
    )
    posts = result.scalars().all()
    has_more = skip + len(posts) < total 
   ## get_posts - return PaginatedPostsResponse
    return PaginatedPostsResponse(
        posts=[PostResponse.model_validate(post) for post in posts], #we need to convert each post to a PostResponse model using the model_validate method, because the posts we get from the database are SQLAlchemy models, and we need to convert them to Pydantic models before returning them in the response. the model_validate method is used to create a Pydantic model instance from a SQLAlchemy model instance, and it will also validate the data according to the fields defined in the PostResponse model.
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
    current_user:CurrentUser, 
    db: Annotated[AsyncSession, Depends(get_db)]):

    

    new_post = models.Post(
        title=post.title,
        content=post.content,
        user_id=current_user.id,
    )
    db.add(new_post)
    await db.commit()
    await db.refresh(new_post, attribute_names=["author"]) #the attribute_names parameter is used to specify which relationships to load when refreshing the object after committing it to the database. in this case, we want to load the author relationship of the post, so that we can access the username of the author in the response without making additional queries to the database for each post. if we didnt specify attribute_names, then the author relationship would not be loaded and we would get an error when trying to access new_post.author.username in the response model.
    return new_post



## get_post
@router.get("/{post_id}", response_model=PostResponse)
async def get_post(post_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(
        select(models.Post)
        .options(selectinload(models.Post.author))
        .where(models.Post.id == post_id),
    )
    post = result.scalars().first()
    if post:
        return post
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")


## update_post_full
@router.put("/{post_id}", response_model=PostResponse)
async def update_post_full(
    post_id: int,
    post_data: PostCreate,
    current_user:CurrentUser,
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
    current_user:CurrentUser,
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
async def delete_post(post_id: int,current_user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]):
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