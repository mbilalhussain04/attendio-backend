"""store original correction snapshot"""

from alembic import op
import sqlalchemy as sa

revision = '0003_corr_snapshot'
down_revision = '0002_correction_break_minutes'
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    for column in [
        sa.Column('original_check_in_at', sa.DateTime(), nullable=True),
        sa.Column('original_check_out_at', sa.DateTime(), nullable=True),
        sa.Column('original_break_minutes', sa.Integer(), nullable=True),
        sa.Column('entry_date', sa.Date(), nullable=True),
    ]:
        if not _has_column('attendance_correction_requests', column.name):
            op.add_column('attendance_correction_requests', column)

    bind = op.get_bind()
    bind.execute(sa.text("""
        UPDATE attendance_correction_requests
        SET
            original_check_in_at = (
                SELECT attendance_entries.check_in_at
                FROM attendance_entries
                WHERE attendance_entries.id = attendance_correction_requests.attendance_entry_id
            ),
            original_check_out_at = (
                SELECT attendance_entries.check_out_at
                FROM attendance_entries
                WHERE attendance_entries.id = attendance_correction_requests.attendance_entry_id
            ),
            original_break_minutes = (
                SELECT attendance_entries.break_minutes
                FROM attendance_entries
                WHERE attendance_entries.id = attendance_correction_requests.attendance_entry_id
            ),
            entry_date = (
                SELECT attendance_entries.date
                FROM attendance_entries
                WHERE attendance_entries.id = attendance_correction_requests.attendance_entry_id
            )
    """))


def downgrade() -> None:
    for column_name in [
        'entry_date',
        'original_break_minutes',
        'original_check_out_at',
        'original_check_in_at',
    ]:
        if _has_column('attendance_correction_requests', column_name):
            op.drop_column('attendance_correction_requests', column_name)
