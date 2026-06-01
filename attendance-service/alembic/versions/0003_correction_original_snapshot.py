"""store original correction snapshot"""

from alembic import op
import sqlalchemy as sa

revision = '0003_corr_snapshot'
down_revision = '0002_correction_break_minutes'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('attendance_correction_requests', sa.Column('original_check_in_at', sa.DateTime(), nullable=True))
    op.add_column('attendance_correction_requests', sa.Column('original_check_out_at', sa.DateTime(), nullable=True))
    op.add_column('attendance_correction_requests', sa.Column('original_break_minutes', sa.Integer(), nullable=True))
    op.add_column('attendance_correction_requests', sa.Column('entry_date', sa.Date(), nullable=True))

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
    op.drop_column('attendance_correction_requests', 'entry_date')
    op.drop_column('attendance_correction_requests', 'original_break_minutes')
    op.drop_column('attendance_correction_requests', 'original_check_out_at')
    op.drop_column('attendance_correction_requests', 'original_check_in_at')
