from alembic import op
import sqlalchemy as sa


revision = '0004_correction_type'
down_revision = '0003_corr_snapshot'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('attendance_correction_requests', sa.Column('correction_type', sa.String(length=80), nullable=True))
    op.add_column('attendance_correction_requests', sa.Column('requester_timezone', sa.String(length=100), nullable=True))


def downgrade():
    op.drop_column('attendance_correction_requests', 'requester_timezone')
    op.drop_column('attendance_correction_requests', 'correction_type')
