"""initial storage registry

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-16
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stored_objects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("module", sa.String(length=60), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("object_key", sa.String(length=512), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("content_type", sa.String(length=120), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("visibility", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key"),
    )
    op.create_index(op.f("ix_stored_objects_category"), "stored_objects", ["category"], unique=False)
    op.create_index(op.f("ix_stored_objects_company_id"), "stored_objects", ["company_id"], unique=False)
    op.create_index(op.f("ix_stored_objects_module"), "stored_objects", ["module"], unique=False)
    op.create_index(op.f("ix_stored_objects_object_key"), "stored_objects", ["object_key"], unique=True)
    op.create_index(op.f("ix_stored_objects_owner_user_id"), "stored_objects", ["owner_user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_stored_objects_owner_user_id"), table_name="stored_objects")
    op.drop_index(op.f("ix_stored_objects_object_key"), table_name="stored_objects")
    op.drop_index(op.f("ix_stored_objects_module"), table_name="stored_objects")
    op.drop_index(op.f("ix_stored_objects_company_id"), table_name="stored_objects")
    op.drop_index(op.f("ix_stored_objects_category"), table_name="stored_objects")
    op.drop_table("stored_objects")
