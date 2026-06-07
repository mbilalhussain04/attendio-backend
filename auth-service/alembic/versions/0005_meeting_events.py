"""separate meeting events from schedule assignments

Revision ID: 0005_meeting_events
Revises: 0004_schedule_assignment_indexes
Create Date: 2026-06-07
"""
from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa

revision = '0005_meeting_events'
down_revision = '0004_schedule_assignment_indexes'
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _index_exists(table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return False
    return any(index.get('name') == index_name for index in inspector.get_indexes(table_name))


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str]) -> None:
    if not _index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns, unique=False)


def _drop_index_if_exists(index_name: str, table_name: str) -> None:
    if _index_exists(table_name, index_name):
        op.drop_index(index_name, table_name=table_name)


def _metadata(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _is_meeting(metadata: dict) -> bool:
    kind = str(metadata.get('entry_kind') or '').strip().lower()
    provider = str(metadata.get('external_provider') or '').strip().lower()
    source = str(metadata.get('source') or '').strip().lower()
    return (
        kind == 'meeting'
        or provider == 'microsoft_teams'
        or source == 'microsoft_graph'
        or bool(metadata.get('calendar_owner_id') or metadata.get('calendar_owner_email'))
    )


def _create_meeting_events_table() -> None:
    if not _table_exists('meeting_events'):
        op.create_table(
            'meeting_events',
            sa.Column('id', sa.Uuid(), nullable=False),
            sa.Column('company_id', sa.Uuid(), nullable=False),
            sa.Column('employee_id', sa.Uuid(), nullable=False),
            sa.Column('title', sa.String(length=140), nullable=False),
            sa.Column('work_date', sa.Date(), nullable=False),
            sa.Column('start_time', sa.Time(), nullable=False),
            sa.Column('end_time', sa.Time(), nullable=False),
            sa.Column('color', sa.String(length=24), nullable=True),
            sa.Column('status', sa.String(length=20), nullable=False),
            sa.Column('notes', sa.String(length=500), nullable=True),
            sa.Column('location', sa.String(length=200), nullable=True),
            sa.Column('attendee_emails', sa.JSON(), nullable=False),
            sa.Column('repeat_rule', sa.String(length=80), nullable=True),
            sa.Column('external_provider', sa.String(length=80), nullable=True),
            sa.Column('external_id', sa.String(length=255), nullable=True),
            sa.Column('external_link', sa.String(length=500), nullable=True),
            sa.Column('source', sa.String(length=40), nullable=False),
            sa.Column('metadata', sa.JSON(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['employee_id'], ['users.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )
    _create_index_if_missing('ix_meeting_events_company_id', 'meeting_events', ['company_id'])
    _create_index_if_missing('ix_meeting_events_employee_id', 'meeting_events', ['employee_id'])
    _create_index_if_missing('ix_meeting_events_work_date', 'meeting_events', ['work_date'])
    _create_index_if_missing('ix_meeting_events_external_provider', 'meeting_events', ['external_provider'])
    _create_index_if_missing('ix_meeting_events_external_id', 'meeting_events', ['external_id'])
    _create_index_if_missing('ix_meeting_events_company_date_employee', 'meeting_events', ['company_id', 'work_date', 'employee_id'])
    _create_index_if_missing('ix_meeting_events_company_status_date', 'meeting_events', ['company_id', 'status', 'work_date'])
    _create_index_if_missing('ix_meeting_events_company_external', 'meeting_events', ['company_id', 'external_provider', 'external_id'])


def _migrate_existing_meetings() -> None:
    if not _table_exists('schedule_assignments') or not _table_exists('shift_templates'):
        return
    bind = op.get_bind()
    meeting_events = sa.table(
        'meeting_events',
        sa.column('id', sa.Uuid()),
        sa.column('company_id', sa.Uuid()),
        sa.column('employee_id', sa.Uuid()),
        sa.column('title', sa.String(length=140)),
        sa.column('work_date', sa.Date()),
        sa.column('start_time', sa.Time()),
        sa.column('end_time', sa.Time()),
        sa.column('color', sa.String(length=24)),
        sa.column('status', sa.String(length=20)),
        sa.column('notes', sa.String(length=500)),
        sa.column('location', sa.String(length=200)),
        sa.column('attendee_emails', sa.JSON()),
        sa.column('repeat_rule', sa.String(length=80)),
        sa.column('external_provider', sa.String(length=80)),
        sa.column('external_id', sa.String(length=255)),
        sa.column('external_link', sa.String(length=500)),
        sa.column('source', sa.String(length=40)),
        sa.column('metadata', sa.JSON()),
        sa.column('created_at', sa.DateTime(timezone=True)),
        sa.column('updated_at', sa.DateTime(timezone=True)),
    )
    schedule_assignments = sa.table('schedule_assignments', sa.column('id'))
    existing_ids = {row[0] for row in bind.execute(sa.text('SELECT id FROM meeting_events')).all()}
    rows = bind.execute(sa.text("""
        SELECT
            sa.id,
            sa.company_id,
            sa.employee_id,
            sa.work_date,
            sa.status,
            sa.notes,
            sa.metadata,
            sa.created_at,
            sa.updated_at,
            st.name AS shift_name,
            st.start_time,
            st.end_time,
            st.color
        FROM schedule_assignments sa
        JOIN shift_templates st ON st.id = sa.shift_template_id
    """)).mappings().all()
    migrated_ids = []
    for row in rows:
        metadata = _metadata(row.get('metadata'))
        if not _is_meeting(metadata):
            continue
        migrated_ids.append(row['id'])
        if row['id'] in existing_ids:
            continue
        metadata['entry_kind'] = 'meeting'
        bind.execute(meeting_events.insert().values(
            id=row['id'],
            company_id=row['company_id'],
            employee_id=row['employee_id'],
            title=(row.get('shift_name') or 'Meeting')[:140],
            work_date=row['work_date'],
            start_time=row['start_time'],
            end_time=row['end_time'],
            color=row.get('color') or '#2563eb',
            status=row.get('status') or 'published',
            notes=row.get('notes'),
            location=metadata.get('location'),
            attendee_emails=metadata.get('attendee_emails') or [],
            repeat_rule=metadata.get('repeat_rule'),
            external_provider=metadata.get('external_provider'),
            external_id=metadata.get('external_id'),
            external_link=metadata.get('external_link'),
            source=metadata.get('source') or 'manual',
            metadata=metadata,
            created_at=row['created_at'],
            updated_at=row['updated_at'],
        ))
    if migrated_ids:
        bind.execute(schedule_assignments.delete().where(schedule_assignments.c.id.in_(migrated_ids)))


def upgrade() -> None:
    _create_meeting_events_table()
    _migrate_existing_meetings()


def downgrade() -> None:
    if _table_exists('meeting_events'):
        _drop_index_if_exists('ix_meeting_events_company_external', 'meeting_events')
        _drop_index_if_exists('ix_meeting_events_company_status_date', 'meeting_events')
        _drop_index_if_exists('ix_meeting_events_company_date_employee', 'meeting_events')
        _drop_index_if_exists('ix_meeting_events_external_id', 'meeting_events')
        _drop_index_if_exists('ix_meeting_events_external_provider', 'meeting_events')
        _drop_index_if_exists('ix_meeting_events_work_date', 'meeting_events')
        _drop_index_if_exists('ix_meeting_events_employee_id', 'meeting_events')
        _drop_index_if_exists('ix_meeting_events_company_id', 'meeting_events')
        op.drop_table('meeting_events')
