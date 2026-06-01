from alembic import op
import sqlalchemy as sa
revision = "0002_channels"
down_revision = "0001_initial"
branch_labels = None
depends_on = None
def upgrade():
    op.create_table("notification_templates",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("key", sa.String(120), nullable=False),
        sa.Column("channels", sa.JSON(), nullable=False), sa.Column("title_template", sa.String(180), nullable=False),
        sa.Column("body_template", sa.String(500), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("key"))
    op.create_table("notification_deliveries",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("notification_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(40), nullable=False), sa.Column("status", sa.String(20), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False), sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["notification_id"], ["notifications.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_notification_deliveries_notification_id", "notification_deliveries", ["notification_id"])
def downgrade():
    op.drop_index("ix_notification_deliveries_notification_id", table_name="notification_deliveries")
    op.drop_table("notification_deliveries"); op.drop_table("notification_templates")
