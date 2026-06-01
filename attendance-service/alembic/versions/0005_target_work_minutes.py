from alembic import op
import sqlalchemy as sa


revision = '0005_target_minutes'
down_revision = '0004_correction_type'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('attendance_entries', sa.Column('target_work_minutes', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('attendance_entries', 'target_work_minutes')
