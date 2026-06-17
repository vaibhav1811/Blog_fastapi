from datetime import datetime
from pydantic import BaseModel, ConfigDict,EmailStr, Field

class UserBase(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    email: EmailStr = Field(max_length=120)


    

class UserCreate(UserBase):
    password: str = Field(min_length=8)
    pass

class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    image_file:str | None
    image_path: str

class UserPrivate(UserPublic):
    email: EmailStr

class UserUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=1, max_length=50)
    email: EmailStr | None = Field(default=None, max_length=120)
   

class Token(BaseModel):
    access_token: str
    token_type: str

class PostBase(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1)
  

class PostCreate(PostBase):
    pass


class PostUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    content: str | None = Field(default=None, min_length=1)    

class PostResponse(PostBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    date_posted: datetime
    author: UserPublic
    ## Like fields — populated by batch queries, not DB columns.
    like_count: int = 0
    user_has_liked: bool = False
    ## Comment count — populated by batch queries, not DB columns.
    comment_count: int = 0


## Like Toggle Response
class LikeResponse(BaseModel):
    liked: bool       # True = user now likes the post, False = unliked
    like_count: int   # Updated total count after the toggle


## ── Comment Schemas ──────────────────────────────────────────────

class CommentCreate(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    parent_id: int | None = None   # None = top-level comment; set = reply


class CommentUpdate(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class CommentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    post_id: int
    user_id: int
    content: str
    parent_id: int | None
    created_at: datetime
    updated_at: datetime | None
    author: UserPublic
    ## Denormalized counter — read directly from DB column, no COUNT(*) query.
    reply_count: int = 0
    ## Top-N replies are populated by a window-function batch query, not a lazy ORM load.
    ## Always a list (never None) so the JS can safely iterate.
    replies: list["CommentResponse"] = []

# Required for the self-referential replies field
CommentResponse.model_rebuild()


class PaginatedCommentsResponse(BaseModel):
    """
    Cursor-based paginated response for comments and replies.

    Pagination flow:
      1. Fetch first page (no cursor).
      2. If next_cursor is not None, pass it as ?cursor=<id> to get the next page.
      3. When next_cursor is None, you have reached the end.

    This replaces the old skip/limit/total approach. No total count is returned
    because computing it requires a COUNT(*) query and is not needed for infinite-
    scroll UIs (same approach used by Instagram, YouTube comment threads).
    """
    comments: list[CommentResponse]
    ## The ID of the last comment in this page. Pass as ?cursor on the next request.
    ## None means this is the final page — no more comments exist.
    next_cursor: int | None


## Paginated Post Response Schema
class PaginatedPostsResponse(BaseModel):
    posts: list[PostResponse]
    total: int
    skip: int  #number of items to skip before starting to collect the result set
    limit: int
    has_more: bool #boolean indicating if there are more items to fetch beyond the current page of

    
## Password Reset Schemas
class ForgotPasswordRequest(BaseModel):
    email: EmailStr = Field(max_length=120)


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


