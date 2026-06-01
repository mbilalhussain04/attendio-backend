from alembic import op
import sqlalchemy as sa

revision = "0003_delivery_views"
down_revision = "0002_channels"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "notification_delivery_views",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade():
    op.drop_table("notification_delivery_views")
