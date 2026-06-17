"""add_reply_count_to_comments

Adds a denormalized reply_count column to the comments table so the API
can return exact reply totals without running COUNT(*) on every request.
Also adds a composite index (post_id, parent_id, id) to accelerate the
cursor-based pagination query used by the upgraded GET /comments endpoint.

Revision ID: c7e2f80b1a39
Revises: 4b61a33ab980
Create Date: 2026-06-17 13:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7e2f80b1a39'
down_revision: Union[str, Sequence[str], None] = '4b61a33ab980'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add reply_count column — defaults to 0 for new rows
    op.add_column(
        'comments',
        sa.Column(
            'reply_count',
            sa.Integer(),
            server_default='0',
            nullable=False,
        ),
    )

    # 2. Back-fill existing data from the replies already in the table.
    #    Only top-level comments (parent_id IS NULL) can have replies,
    #    so reply rows are left at 0 by default correctly.
    op.execute("""
        UPDATE comments
        SET reply_count = (
            SELECT COUNT(*)
            FROM comments AS replies
            WHERE replies.parent_id = comments.id
        )
        WHERE parent_id IS NULL
    """)

    # 3. Composite index for the cursor-pagination query:
    #      WHERE post_id = :x AND parent_id IS NULL AND id < :cursor
    #      ORDER BY id DESC
    #    PostgreSQL will use this index for an efficient index-only scan.
    op.create_index(
        'ix_comments_post_parent_id',
        'comments',
        ['post_id', 'parent_id', 'id'],
    )


def downgrade() -> None:
    op.drop_index('ix_comments_post_parent_id', table_name='comments')
    op.drop_column('comments', 'reply_count')
