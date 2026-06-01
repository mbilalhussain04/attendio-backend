"""add requested break minutes to attendance corrections"""

from alembic import op
import sqlalchemy as sa

revision = '0002_correction_break_minutes'
down_revision = '0001_init'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('attendance_correction_requests', sa.Column('requested_break_minutes', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('attendance_correction_requests', 'requested_break_minutes')
