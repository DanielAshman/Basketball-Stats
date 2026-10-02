"""Add pose_keypoints table

Revision ID: 001
Revises:
Create Date: 2026-10-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'pose_keypoints',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('frame_id', UUID(as_uuid=True), sa.ForeignKey('frames.id'), nullable=False),
        sa.Column('track_id', sa.Integer(), nullable=False),
        sa.Column('keypoints', JSONB(), nullable=False),
        sa.Column('confidence_score', sa.Numeric(5, 3), nullable=True),
        sa.Column('bbox_x', sa.Integer(), nullable=True),
        sa.Column('bbox_y', sa.Integer(), nullable=True),
        sa.Column('bbox_width', sa.Integer(), nullable=True),
        sa.Column('bbox_height', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
    )
    op.create_index('idx_pose_keypoints_frame', 'pose_keypoints', ['frame_id'])
    op.create_index('idx_pose_keypoints_track', 'pose_keypoints', ['track_id'])


def downgrade() -> None:
    op.drop_index('idx_pose_keypoints_track', table_name='pose_keypoints')
    op.drop_index('idx_pose_keypoints_frame', table_name='pose_keypoints')
    op.drop_table('pose_keypoints')
