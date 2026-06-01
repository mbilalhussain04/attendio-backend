"""add requested break minutes to attendance corrections"""

from alembic import op
import sqlalchemy as sa

revision = '0002_correction_break_minutes'
down_revision = '0001_init'
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    if not _has_column('attendance_correction_requests', 'requested_break_minutes'):
        op.add_column('attendance_correction_requests', sa.Column('requested_break_minutes', sa.Integer(), nullable=True))


def downgrade() -> None:
    if _has_column('attendance_correction_requests', 'requested_break_minutes'):
        op.drop_column('attendance_correction_requests', 'requested_break_minutes')
