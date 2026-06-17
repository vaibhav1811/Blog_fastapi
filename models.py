from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from config import settings # for accessing configuration settings, such as AWS credentials and S3 bucket name



class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    image_file: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
        default=None,
    )
    

    posts: Mapped[list[Post]] = relationship(
        back_populates="author",
        cascade="all, delete-orphan",
        )
    
    ## User.reset_tokens relationship
    reset_tokens: Mapped[list[PasswordResetToken]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        # This relationship allows us to access the password reset tokens associated with a user. The cascade option ensures that when a user is deleted, all their associated password reset tokens are also deleted, preventing orphaned records in the database and maintaining data integrity.
    )

    ## User.liked_posts relationship — all PostLike rows created by this user
    liked_posts: Mapped[list[PostLike]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    ## User.comments relationship
    comments: Mapped[list[Comment]] = relationship(
        back_populates="author",
        cascade="all, delete-orphan",
    )

    @property
    def image_path(self) -> str:
        if self.image_file:
            return f"https://{settings.s3_bucket_name}.s3.{settings.s3_region}.amazonaws.com/profile_pics/{self.image_file}"
        return "/static/profile_pics/default.jpg"


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    date_posted: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    # NOTE: The old `likes` counter column has been removed.
    # Like counts are now computed from the post_likes junction table,
    # which provides per-user tracking and prevents duplicate likes.

    author: Mapped[User] = relationship(back_populates="posts")

    ## Post.post_likes relationship — all PostLike rows for this post
    post_likes: Mapped[list[PostLike]] = relationship(
        back_populates="post",
        cascade="all, delete-orphan",
    )

    ## Post.comments relationship — all Comments for this post
    comments: Mapped[list[Comment]] = relationship(
        back_populates="post",
        cascade="all, delete-orphan",
    )


class PostLike(Base):
    """
    Junction table recording which user liked which post.

    Uses a composite primary key (user_id, post_id) to enforce
    uniqueness at the database level — a user can only like a
    post once, with zero application-level duplicate checks.

    Indexes:
      - post_id index (created automatically from FK) enables fast
        COUNT(*) GROUP BY queries when loading like counts for a
        page of posts.
      - user_id index enables fast lookup of all posts a user liked.
    """
    __tablename__ = "post_likes"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    post_id: Mapped[int] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )

    user: Mapped[User] = relationship(back_populates="liked_posts")
    post: Mapped[Post] = relationship(back_populates="post_likes")


class Comment(Base):
    """
    Stores comments (and optionally replies) on blog posts.

    parent_id is nullable:
      - NULL  → top-level comment
      - set   → reply to another comment (one level of nesting supported)

    Cascade delete: deleting a post removes all its comments.
    Cascade delete on replies: deleting a top-level comment removes its replies.
    """
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    post_id: Mapped[int] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Denormalized counter maintained by create/delete endpoints (no COUNT(*) needed).
    # Only meaningful on top-level comments; replies always have reply_count = 0.
    reply_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # parent_id: NULL = top-level comment; set = reply to another comment
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("comments.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        default=None,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )

    author: Mapped[User] = relationship(back_populates="comments")
    post: Mapped[Post] = relationship(back_populates="comments")

    # Self-referential for replies
    replies: Mapped[list[Comment]] = relationship(
        back_populates="parent",
        foreign_keys=[parent_id],
        cascade="all, delete-orphan",
    )
    parent: Mapped[Comment | None] = relationship(
        back_populates="replies",
        remote_side=[id],
        foreign_keys=[parent_id],
    )


## PasswordResetToken model
class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False) # SHA-256 hash is 64 characters long,used for securely storing the token in the database without exposing the actual token value, enhancing security by preventing unauthorized access to the token even if the database is compromised.
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )

    user: Mapped[User] = relationship(back_populates="reset_tokens")