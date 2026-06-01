from sqlalchemy import select
from sqlalchemy.orm import configure_mappers

from app.db.session import SessionLocal
from app.models import base  # noqa: F401
from app.models.permission import Permission
from app.models.role import Role

PERMISSIONS = [
    ('users.invite', 'Invite users'),
    ('users.impersonate', 'Impersonate users'),
    ('users.reset_pin', 'Reset kiosk pin'),
    ('roles.manage', 'Manage roles'),
    ('audit.read', 'Read audit logs'),
    ('reports.company', 'Read company reports'),
    ('api_keys.manage', 'Manage API keys'),
    ('settings.tenant', 'Manage tenant settings'),
    ('settings.kiosk', 'Manage kiosk settings'),
    ('org.view_self', 'View own organization path'),
    ('org.view_team', 'View team organization tree'),
    ('org.view_company', 'View company organization tree'),
    ('schedule.view_self', 'View own schedule'),
    ('schedule.view_team', 'View team schedule'),
    ('schedule.view_company', 'View company schedule'),
    ('schedule.manage', 'Manage schedules'),
    ('attendance.check_in', 'Check in attendance'),
    ('attendance.check_out', 'Check out attendance'),
    ('attendance.break_start', 'Start attendance breaks'),
    ('attendance.break_end', 'End attendance breaks'),
    ('attendance.manual_entry', 'Create manual attendance entries'),
    ('attendance.view_self', 'View own attendance records'),
    ('attendance.view_team', 'View team attendance records'),
    ('attendance.view_company', 'View company attendance reports'),
    ('attendance.approve', 'Approve attendance corrections'),
    ('attendance.lock', 'Lock attendance periods'),
    ('attendance.export', 'Export attendance data'),
    ('attendance.configure', 'Configure attendance settings'),
    ('attendance.kiosk_manage', 'Manage attendance kiosks'),
    ('attendance.shift_manage', 'Manage attendance shifts'),
    ('attendance.holiday_manage', 'Manage attendance holidays'),
    ('attendance.geofence_manage', 'Manage attendance geofences'),
    ('attendance.notification_manage', 'Manage attendance notifications'),
    ('attendance.job_run', 'Run attendance jobs'),
    ('leave.request', 'Request leave'),
    ('leave.view_self', 'View own leave records'),
    ('leave.view_company', 'View company leave records'),
    ('leave.review', 'Review leave requests'),
    ('leave.configure', 'Configure leave policies'),
]

ROLE_MAP = {
    'company_owner': [
        'users.invite',
        'users.impersonate',
        'users.reset_pin',
        'roles.manage',
        'audit.read',
        'reports.company',
        'api_keys.manage',
        'settings.tenant',
        'settings.kiosk',
        'org.view_self',
        'org.view_team',
        'org.view_company',
        'schedule.view_self',
        'schedule.view_team',
        'schedule.view_company',
        'schedule.manage',
        'attendance.check_in',
        'attendance.check_out',
        'attendance.break_start',
        'attendance.break_end',
        'attendance.manual_entry',
        'attendance.view_self',
        'attendance.view_team',
        'attendance.view_company',
        'attendance.approve',
        'attendance.lock',
        'attendance.export',
        'attendance.configure',
        'attendance.kiosk_manage',
        'attendance.shift_manage',
        'attendance.holiday_manage',
        'attendance.geofence_manage',
        'attendance.notification_manage',
        'attendance.job_run',
        'leave.request',
        'leave.view_self',
        'leave.view_company',
        'leave.review',
        'leave.configure',
    ],
    'manager': [
        'reports.company',
        'org.view_self',
        'org.view_team',
        'schedule.view_self',
        'schedule.view_team',
        'attendance.check_in',
        'attendance.check_out',
        'attendance.break_start',
        'attendance.break_end',
        'attendance.view_self',
        'attendance.view_team',
        'attendance.approve',
        'leave.request',
        'leave.view_self',
        'leave.review',
    ],
    'team_lead': [
        'org.view_self',
        'org.view_team',
        'schedule.view_self',
        'schedule.view_team',
        'attendance.check_in',
        'attendance.check_out',
        'attendance.break_start',
        'attendance.break_end',
        'attendance.view_self',
        'attendance.view_team',
        'leave.request',
        'leave.view_self',
    ],
    'hr_admin': [
        'users.invite',
        'users.reset_pin',
        'reports.company',
        'org.view_self',
        'org.view_team',
        'org.view_company',
        'schedule.view_self',
        'schedule.view_team',
        'schedule.view_company',
        'schedule.manage',
        'attendance.check_in',
        'attendance.check_out',
        'attendance.break_start',
        'attendance.break_end',
        'attendance.manual_entry',
        'attendance.view_self',
        'attendance.view_team',
        'attendance.view_company',
        'attendance.approve',
        'attendance.export',
        'attendance.shift_manage',
        'attendance.holiday_manage',
        'attendance.notification_manage',
        'leave.request',
        'leave.view_self',
        'leave.view_company',
        'leave.review',
        'leave.configure',
    ],
    'employee': [
        'org.view_self',
        'schedule.view_self',
        'attendance.check_in',
        'attendance.check_out',
        'attendance.break_start',
        'attendance.break_end',
        'attendance.view_self',
        'leave.request',
        'leave.view_self',
    ],
}


def ensure_seed_data():
    # Load all ORM models before first query so relationship targets are registered.
    configure_mappers()

    db = SessionLocal()
    try:
        permission_objects = {}
        for key, name in PERMISSIONS:
            item = db.scalar(select(Permission).where(Permission.key == key))
            if not item:
                item = Permission(key=key, name=name, description=name)
                db.add(item)
                db.flush()
            permission_objects[key] = item
        for key, perm_keys in ROLE_MAP.items():
            role = db.scalar(select(Role).where(Role.key == key, Role.company_id.is_(None)))
            if not role:
                role = Role(key=key, name=key.replace('_', ' ').title(), company_id=None, is_system=True)
                db.add(role)
                db.flush()
            role.permissions = [permission_objects[p] for p in perm_keys]
            db.add(role)
        db.commit()
    finally:
        db.close()


if __name__ == '__main__':
    ensure_seed_data()
