"""scheduling

Revision ID: 0002_scheduling
Revises: 0001_initial
Create Date: 2026-05-24
"""
from alembic import op
import sqlalchemy as sa

revision = '0002_scheduling'
down_revision = '0001_initial'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'shift_templates',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=140), nullable=False),
        sa.Column('code', sa.String(length=40), nullable=True),
        sa.Column('start_time', sa.Time(), nullable=False),
        sa.Column('end_time', sa.Time(), nullable=False),
        sa.Column('break_minutes', sa.Integer(), nullable=False),
        sa.Column('timezone', sa.String(length=100), nullable=True),
        sa.Column('location_id', sa.String(length=80), nullable=True),
        sa.Column('department_id', sa.String(length=80), nullable=True),
        sa.Column('color', sa.String(length=24), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('metadata', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_shift_templates_company_id'), 'shift_templates', ['company_id'], unique=False)

    op.create_table(
        'roster_templates',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=140), nullable=False),
        sa.Column('shift_template_id', sa.Uuid(), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=True),
        sa.Column('end_date', sa.Date(), nullable=True),
        sa.Column('days_of_week', sa.JSON(), nullable=False),
        sa.Column('employee_ids', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('metadata', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['shift_template_id'], ['shift_templates.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_roster_templates_company_id'), 'roster_templates', ['company_id'], unique=False)
    op.create_index(op.f('ix_roster_templates_shift_template_id'), 'roster_templates', ['shift_template_id'], unique=False)

    op.create_table(
        'schedule_assignments',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('employee_id', sa.Uuid(), nullable=False),
        sa.Column('shift_template_id', sa.Uuid(), nullable=False),
        sa.Column('work_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('notes', sa.String(length=500), nullable=True),
        sa.Column('metadata', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['employee_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['shift_template_id'], ['shift_templates.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_schedule_assignments_company_id'), 'schedule_assignments', ['company_id'], unique=False)
    op.create_index(op.f('ix_schedule_assignments_employee_id'), 'schedule_assignments', ['employee_id'], unique=False)
    op.create_index(op.f('ix_schedule_assignments_shift_template_id'), 'schedule_assignments', ['shift_template_id'], unique=False)
    op.create_index(op.f('ix_schedule_assignments_work_date'), 'schedule_assignments', ['work_date'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_schedule_assignments_work_date'), table_name='schedule_assignments')
    op.drop_index(op.f('ix_schedule_assignments_shift_template_id'), table_name='schedule_assignments')
    op.drop_index(op.f('ix_schedule_assignments_employee_id'), table_name='schedule_assignments')
    op.drop_index(op.f('ix_schedule_assignments_company_id'), table_name='schedule_assignments')
    op.drop_table('schedule_assignments')
    op.drop_index(op.f('ix_roster_templates_shift_template_id'), table_name='roster_templates')
    op.drop_index(op.f('ix_roster_templates_company_id'), table_name='roster_templates')
    op.drop_table('roster_templates')
    op.drop_index(op.f('ix_shift_templates_company_id'), table_name='shift_templates')
    op.drop_table('shift_templates')
