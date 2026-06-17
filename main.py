from typing import Annotated
from contextlib import asynccontextmanager
import asyncio
import logging
import os
from fastapi.exception_handlers import http_exception_handler,request_validation_exception_handler
 
import httpx
from fastapi import FastAPI, Request, HTTPException, status,Depends
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates 
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy import select,func,text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import models
from database import engine, get_db
from routers import posts, users
from routers import comments as comments_router
from routers.posts import _fetch_like_data, get_optional_user
from config import settings


async def _fetch_comment_counts(db, post_ids: list[int]) -> dict[int, int]:
    """Batch-fetch comment counts for a list of post IDs (top-level + replies)."""
    if not post_ids:
        return {}
    from sqlalchemy import select, func
    result = await db.execute(
        select(models.Comment.post_id, func.count().label("n"))
        .where(models.Comment.post_id.in_(post_ids))
        .group_by(models.Comment.post_id)
    )
    return {row.post_id: row.n for row in result}


logger = logging.getLogger(__name__)


async def keep_alive_ping():
    """
    Self-ping background task to prevent Render's free tier from spinning down
    the instance due to inactivity. Pings the /health endpoint every 10 minutes.
    Only runs when the RENDER_EXTERNAL_URL environment variable is set
    (i.e., only in the Render production environment).
    """
    render_url = os.getenv("RENDER_EXTERNAL_URL")
    if not render_url:
        logger.info("RENDER_EXTERNAL_URL not set — keep-alive ping disabled (local dev mode).")
        return

    health_url = f"{render_url.rstrip('/')}/health"
    logger.info(f"Keep-alive ping task started. Will ping {health_url} every 10 minutes.")

    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            await asyncio.sleep(10 * 60)  # wait 10 minutes
            try:
                resp = await client.get(health_url)
                logger.info(f"Keep-alive ping → {resp.status_code}")
            except Exception as exc:
                logger.warning(f"Keep-alive ping failed: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start the self-ping keep-alive task on startup
    ping_task = asyncio.create_task(keep_alive_ping())
    yield
    # Shutdown: cancel the ping task cleanly
    ping_task.cancel()
    try:
        await ping_task
    except asyncio.CancelledError:
        pass
    await engine.dispose()
  

app = FastAPI(lifespan=lifespan)

app.mount("/static", StaticFiles(directory="static"), name="static")
# app.mount("/media", StaticFiles(directory="media"), name="media")

templates = Jinja2Templates(directory="templates") 

app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(posts.router, prefix="/api/posts", tags=["posts"])
# Comments as a sub-route of posts (POST /api/posts/{post_id}/comments)
app.include_router(
    comments_router.router,
    prefix="/api/posts/{post_id}/comments",
    tags=["comments"],
)
# Standalone comment routes for edit/delete (no post_id prefix needed)
app.include_router(
    comments_router.router,
    prefix="/api/comments",
    tags=["comments"],
)

## Security Headers Middleware
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)

    response.headers["X-Frame-Options"] = "SAMEORIGIN"

    response.headers["X-Content-Type-Options"] = "nosniff"

    if "Referrer-Policy" not in response.headers:
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

    if request.url.hostname not in ("localhost", "127.0.0.1"):
        response.headers["Strict-Transport-Security"] = (
            "max-age=63072000; includeSubDomains"
        )

    return response



## Health Check Endpoint
@app.get("/health")
async def health_check(db: Annotated[AsyncSession, Depends(get_db)]):
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        ) from exc
    return {"status": "healthy"}

# posts: list[dict] = [
#     {"id": 1,
#      "author": "Corey Schafer",
#      "title": "Fastapi is awesome", 
#      "content": "This is the first post.", 
#      "date_posted": "April 22, 2025",
#      },
#     {"id": 2,
#      "author": "Corey Schafer",
#      "title": "Python leading AI", 
#      "content": "This is the second post.",  
#      "date_posted": "April 23, 2025",
#      },
    
# ]

# fastapi use decorartor for routes
#include in scheme = false, used to hide the route from the documentation

## home
## home route - paginated
@app.get("/", include_in_schema=False, name="home")
@app.get("/posts", include_in_schema=False, name="posts")
async def home(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[models.User | None, Depends(get_optional_user)] = None,
):
    count_result = await db.execute(select(func.count()).select_from(models.Post))
    total = count_result.scalar() or 0

    result = await db.execute(
        select(models.Post)
        .options(selectinload(models.Post.author))
        .order_by(models.Post.date_posted.desc())
        .limit(settings.post_per_page),
    )
    posts_list = result.scalars().all()
    has_more = len(posts_list) < total

    # Batch-fetch like counts + comment counts (3 queries total for any page size)
    post_ids = [p.id for p in posts_list]
    like_count_map, liked_post_ids = await _fetch_like_data(db, post_ids, current_user)
    comment_count_map = await _fetch_comment_counts(db, post_ids)

    # Attach counts directly to ORM objects for Jinja access
    for post in posts_list:
        post.like_count = like_count_map.get(post.id, 0)
        post.user_has_liked = post.id in liked_post_ids
        post.comment_count = comment_count_map.get(post.id, 0)

    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "posts": posts_list,
            "title": "Home",
            "limit": settings.post_per_page,
            "has_more": has_more,
        },
    )


## post_page
@app.get("/posts/{post_id}", include_in_schema=False)
async def post_page(
    request: Request,
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
    if post:
        # Attach like + comment count for the template
        like_count_map, liked_post_ids = await _fetch_like_data(db, [post_id], current_user)
        comment_count_map = await _fetch_comment_counts(db, [post_id])
        post.like_count = like_count_map.get(post_id, 0)
        post.user_has_liked = post_id in liked_post_ids
        post.comment_count = comment_count_map.get(post_id, 0)

        title = post.title[:50]
        return templates.TemplateResponse(
            request,
            "post.html",
            {"post": post, "title": title},
        )
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")


## user_posts_page
## user_posts_page route - paginated
@app.get("/users/{user_id}/posts", include_in_schema=False, name="user_posts")
async def user_posts_page(
    request: Request,
    user_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[models.User | None, Depends(get_optional_user)] = None,
):
    result = await db.execute(select(models.User).where(models.User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    count_result = await db.execute(
        select(func.count())
        .select_from(models.Post)
        .where(models.Post.user_id == user_id),
    )
    total = count_result.scalar() or 0

    result = await db.execute(
        select(models.Post)
        .options(selectinload(models.Post.author))
        .where(models.Post.user_id == user_id)
        .order_by(models.Post.date_posted.desc())
        .limit(settings.post_per_page),
    )
    posts_list = result.scalars().all()
    has_more = len(posts_list) < total

    # Batch-fetch like counts + comment counts
    post_ids = [p.id for p in posts_list]
    like_count_map, liked_post_ids = await _fetch_like_data(db, post_ids, current_user)
    comment_count_map = await _fetch_comment_counts(db, post_ids)
    for post in posts_list:
        post.like_count = like_count_map.get(post.id, 0)
        post.user_has_liked = post.id in liked_post_ids
        post.comment_count = comment_count_map.get(post.id, 0)

    return templates.TemplateResponse(
        request,
        "user_posts.html",
        {
            "posts": posts_list,
            "user": user,
            "title": f"{user.username}'s Posts",
            "limit": settings.post_per_page,
            "has_more": has_more,
        },
    ) 


## login and register template_routes
@app.get("/login", include_in_schema=False)
async def login_page(request: Request):
    return templates.TemplateResponse(
        request,
        "login.html",
        {"title": "Login"},
    )


@app.get("/register", include_in_schema=False)
async def register_page(request: Request):
    return templates.TemplateResponse(
        request,
        "register.html",
        {"title": "Register"},
    )

@app.get("/account", include_in_schema=False)
async def account_page(request: Request):
    return templates.TemplateResponse(
        request,
        "account.html",
        {"title": "Account"},
    )

## main.py template routes
@app.get("/forgot-password", include_in_schema=False)
async def forgot_password_page(request: Request):
    return templates.TemplateResponse(
        request,
        "forgot_password.html",
        {"title": "Forgot Password"},
    )


@app.get("/reset-password", include_in_schema=False)
async def reset_password_page(request: Request):
    response = templates.TemplateResponse(
        request,
        "reset_password.html",
        {"title": "Reset Password"},
    )
    response.headers["Referrer-Policy"] = "no-referrer" # we set the Referrer-Policy header to "no-referrer" for the reset password page to enhance security by preventing the browser from sending the Referer header when navigating away from this page, which can help protect sensitive information in the URL (such as the reset token) from being exposed to third-party sites or in browser history, reducing the risk of token leakage and potential misuse. 
    return response

## StarletteHTTPException Handler
@app.exception_handler(StarletteHTTPException)
async def general_http_exception_handler(request: Request, exception: StarletteHTTPException):
    

    if request.url.path.startswith("/api"):
       return await http_exception_handler(request, exception)
    
    message = (
        exception.detail
        if exception.detail
        else "An error occurred. Please check your request and try again."
    )

    return templates.TemplateResponse(
        request,
        "error.html",
        {
            "status_code": exception.status_code,
            "title": exception.status_code,
            "message": message,
        },
        status_code=exception.status_code,
    )



### RequestValidationError Handler
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exception: RequestValidationError):
    if request.url.path.startswith("/api"):
        return await request_validation_exception_handler(request, exception)
    
    return templates.TemplateResponse(
        request,
        "error.html",
        {
            "status_code": status.HTTP_422_UNPROCESSABLE_CONTENT,
            "title": status.HTTP_422_UNPROCESSABLE_CONTENT,
            "message": "Invalid request. Please check your input and try again.",
        },
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
    )


