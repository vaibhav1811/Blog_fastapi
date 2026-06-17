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
    ## Replies are included when loading top-level comments on the post page.
    ## Empty list by default — never None — so templates can always iterate.
    replies: list["CommentResponse"] = []

# Required for the self-referential replies field
CommentResponse.model_rebuild()


class PaginatedCommentsResponse(BaseModel):
    comments: list[CommentResponse]
    total: int
    has_more: bool


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


