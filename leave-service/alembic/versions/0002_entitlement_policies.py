"""employee entitlement policies and grants"""
from alembic import op
from app.db.base import Base
from app.models import leave  # noqa

revision = "0002_entitlement_policies"
down_revision = "0001_init"
branch_labels = None
depends_on = None


def upgrade():
    Base.metadata.tables["leave_entitlement_policies"].create(bind=op.get_bind(), checkfirst=True)
    Base.metadata.tables["leave_entitlement_grants"].create(bind=op.get_bind(), checkfirst=True)


def downgrade():
    Base.metadata.tables["leave_entitlement_grants"].drop(bind=op.get_bind(), checkfirst=True)
    Base.metadata.tables["leave_entitlement_policies"].drop(bind=op.get_bind(), checkfirst=True)
