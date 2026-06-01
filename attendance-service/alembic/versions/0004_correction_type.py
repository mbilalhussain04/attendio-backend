from alembic import op
import sqlalchemy as sa


revision = '0004_correction_type'
down_revision = '0003_corr_snapshot'
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def upgrade():
    for column in [
        sa.Column('correction_type', sa.String(length=80), nullable=True),
        sa.Column('requester_timezone', sa.String(length=100), nullable=True),
    ]:
        if not _has_column('attendance_correction_requests', column.name):
            op.add_column('attendance_correction_requests', column)


def downgrade():
    for column_name in ['requester_timezone', 'correction_type']:
        if _has_column('attendance_correction_requests', column_name):
            op.drop_column('attendance_correction_requests', column_name)
