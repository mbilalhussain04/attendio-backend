"""schedule assignment read indexes

Revision ID: 0004_schedule_assignment_indexes
Revises: 0003_user_permission_overrides
Create Date: 2026-06-06
"""
from alembic import op
import sqlalchemy as sa

revision = '0004_schedule_assignment_indexes'
down_revision = '0003_user_permission_overrides'
branch_labels = None
depends_on = None


def _index_exists(table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(index.get('name') == index_name for index in inspector.get_indexes(table_name))


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str]) -> None:
    if not _index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns, unique=False)


def _drop_index_if_exists(index_name: str, table_name: str) -> None:
    if _index_exists(table_name, index_name):
        op.drop_index(index_name, table_name=table_name)


def upgrade() -> None:
    _create_index_if_missing(
        'ix_schedule_assignments_company_date_employee',
        'schedule_assignments',
        ['company_id', 'work_date', 'employee_id'],
    )
    _create_index_if_missing(
        'ix_schedule_assignments_company_status_date',
        'schedule_assignments',
        ['company_id', 'status', 'work_date'],
    )


def downgrade() -> None:
    _drop_index_if_exists('ix_schedule_assignments_company_status_date', 'schedule_assignments')
    _drop_index_if_exists('ix_schedule_assignments_company_date_employee', 'schedule_assignments')
