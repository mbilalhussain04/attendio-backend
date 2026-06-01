"""user permission overrides

Revision ID: 0003_user_permission_overrides
Revises: 0002_scheduling
Create Date: 2026-05-26
"""
from alembic import op
import sqlalchemy as sa

revision = '0003_user_permission_overrides'
down_revision = '0002_scheduling'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'user_permission_overrides',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('permission_id', sa.Uuid(), nullable=False),
        sa.Column('effect', sa.String(length=10), nullable=False),
        sa.ForeignKeyConstraint(['permission_id'], ['permissions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'permission_id', name='user_permission_override_uq'),
    )


def downgrade() -> None:
    op.drop_table('user_permission_overrides')
