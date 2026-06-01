from alembic import op
import sqlalchemy as sa


revision = '0005_target_minutes'
down_revision = '0004_correction_type'
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def upgrade():
    if not _has_column('attendance_entries', 'target_work_minutes'):
        op.add_column('attendance_entries', sa.Column('target_work_minutes', sa.Integer(), nullable=True))


def downgrade():
    if _has_column('attendance_entries', 'target_work_minutes'):
        op.drop_column('attendance_entries', 'target_work_minutes')
