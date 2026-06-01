from pathlib import Path
from fastapi import APIRouter, Depends, UploadFile, File, Request, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps.auth import require_permissions
from app.models.associations import UserPermissionOverride
from app.models.permission import Permission
from app.schemas.employee import EmployeeCreateRequest, BulkEmployeeCreateRequest, EmployeeUpdateRequest, EmployeeStatusRequest
from app.services.auth import service
from app.services.billing_policy import assert_limit_available

router = APIRouter(prefix='/employees')


def req_meta(request):
    return {'ip_address': request.client.host if request.client else None, 'user_agent': request.headers.get('user-agent')}


def serialize_user(user, generated_password=None, db: Session | None = None):
    perms = sorted({perm.key for role in user.roles for perm in role.permissions}) if getattr(user, 'roles', None) else []
    overrides = {'allow': [], 'deny': []}
    if db is not None:
        rows = db.execute(
            select(UserPermissionOverride.effect, Permission.key)
            .join(Permission, Permission.id == UserPermissionOverride.permission_id)
            .where(UserPermissionOverride.user_id == user.id)
        ).all()
        overrides = {
            'allow': sorted(key for effect, key in rows if effect == 'allow'),
            'deny': sorted(key for effect, key in rows if effect == 'deny'),
        }
        perms = service.permission_keys_for_user(db, user)
    role_key = user.roles[0].key if getattr(user, 'roles', None) and user.roles else None
    role_name = user.roles[0].name if getattr(user, 'roles', None) and user.roles else None
    metadata = user.metadata_json or {}
    return {
        'id': str(user.id),
        'company_id': str(user.company_id),
        'employee_code': user.employee_code,
        'external_employee_id': user.external_employee_id,
        'payroll_employee_id': user.payroll_employee_id,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'email': user.email,
        'phone': user.phone,
        'profile_picture': metadata.get('profile_picture_url'),
        'avatar_url': metadata.get('profile_picture_url'),
        'provider': user.provider,
        'status': user.status,
        'role_key': role_key,
        'role_name': role_name,
        'job_title': metadata.get('job_title'),
        'department': metadata.get('department'),
        'manager_id': metadata.get('manager_id'),
        'manager_name': metadata.get('manager_name'),
        'branch_id': metadata.get('branch_id'),
        'branch_name': metadata.get('branch_name'),
        'project_ids': metadata.get('project_ids') or [],
        'project_names': metadata.get('project_names') or [],
        'contract_type': metadata.get('contract_type'),
        'employment_type': metadata.get('employment_type'),
        'expected_hours_period': metadata.get('expected_hours_period') or ('monthly' if metadata.get('monthly_hours') else 'weekly'),
        'expected_hours': metadata.get('expected_hours') or metadata.get('monthly_hours') or metadata.get('weekly_hours'),
        'weekly_hours': metadata.get('weekly_hours'),
        'monthly_hours': metadata.get('monthly_hours'),
        'country': metadata.get('country'),
        'city': metadata.get('city'),
        'start_date': metadata.get('start_date'),
        'end_date': metadata.get('end_date'),
        'permissions': perms,
        'role_permissions': sorted({perm.key for role in user.roles for perm in role.permissions}) if getattr(user, 'roles', None) else [],
        'permission_overrides': overrides,
        'generated_password': generated_password,
    }


@router.get('', tags=['Employees'])
def list_employees(
    db: Session = Depends(get_db),
    user=Depends(require_permissions('users.invite', 'reports.company')),
    limit: int | None = Query(None, ge=1, le=200),
    offset: int = Query(0, ge=0),
    q: str | None = Query(None, max_length=120),
    branch_id: str | None = Query(None),
    project_id: str | None = Query(None),
):
    items, total = service.list_employees(db, actor=user, limit=limit, offset=offset, q=q, branch_id=branch_id, project_id=project_id)
    return {'message': 'Employees fetched successfully', 'data': [serialize_user(item, db=db) for item in items], 'meta': {'limit': limit or total, 'offset': offset, 'total': total}}


@router.get('/organization', tags=['Employees'])
def organization(
    db: Session = Depends(get_db),
    user=Depends(require_permissions('org.view_self', 'org.view_team', 'org.view_company', 'settings.tenant', 'reports.company')),
    q: str | None = Query(None, max_length=120),
    project_id: str | None = Query(None),
):
    items = service.list_organization_people(db, actor=user, q=q, project_id=project_id)
    return {'message': 'Organization hierarchy fetched successfully', 'data': [serialize_user(item, db=db) for item in items]}


@router.post('/bulk', tags=['Employees'])
def create_bulk(payload: BulkEmployeeCreateRequest, request: Request, db: Session = Depends(get_db), user=Depends(require_permissions('users.invite'))):
    _, current_total = service.list_employees(db, actor=user, limit=1, offset=0)
    assert_limit_available(str(user.company_id), 'employees', current_total, len(payload.users or []))
    results = []
    for item in payload.users:
        try:
            created, generated_password = service.register_employee(db, actor=user, payload=item, request_meta=req_meta(request))
            results.append({'email': created.email, 'status': 'created', 'user_id': str(created.id), 'employee_code': created.employee_code, 'generated_password': generated_password})
        except Exception as exc:
            db.rollback()
            results.append({'email': item.email, 'status': 'failed', 'reason': str(exc)})
    return {'message': 'Bulk registration completed', 'data': results}


@router.post('/import', tags=['Employees'])
async def import_employees(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db), user=Depends(require_permissions('users.invite'))):
    raw = await file.read()
    csv_lines = [line for line in raw.decode('utf-8', errors='ignore').splitlines()[1:] if line.strip()]
    _, current_total = service.list_employees(db, actor=user, limit=1, offset=0)
    assert_limit_available(str(user.company_id), 'employees', current_total, len(csv_lines))
    results = service.import_employees(db, actor=user, filename=file.filename, raw_bytes=raw, request_meta=req_meta(request))
    return {'message': 'Employee import completed', 'data': results}


@router.get('/import/template', tags=['Employees'])
def import_template(user=Depends(require_permissions('users.invite'))):
    path = Path(__file__).resolve().parents[3] / 'templates' / 'employee-import-template.csv'
    return FileResponse(path, media_type='text/csv', filename='employee-import-template.csv')


@router.post('', tags=['Employees'])
def create_employee(payload: EmployeeCreateRequest, request: Request, db: Session = Depends(get_db), user=Depends(require_permissions('users.invite'))):
    _, current_total = service.list_employees(db, actor=user, limit=1, offset=0)
    assert_limit_available(str(user.company_id), 'employees', current_total, 1)
    item, generated_password = service.register_employee(db, actor=user, payload=payload, request_meta=req_meta(request))
    return {'message': 'Employee registered successfully', 'data': serialize_user(item, generated_password)}


@router.patch('/{user_id}', tags=['Employees'])
def update_employee(user_id: str, payload: EmployeeUpdateRequest, request: Request, db: Session = Depends(get_db), user=Depends(require_permissions('users.invite'))):
    item = service.update_employee(db, actor=user, user_id=user_id, payload=payload, request_meta=req_meta(request))
    return {'message': 'Employee updated successfully', 'data': serialize_user(item)}


@router.post('/{user_id}/status', tags=['Employees'])
def update_employee_status(user_id: str, payload: EmployeeStatusRequest, request: Request, db: Session = Depends(get_db), user=Depends(require_permissions('users.invite'))):
    item = service.update_employee_status(db, actor=user, user_id=user_id, status=payload.status, request_meta=req_meta(request))
    return {'message': f'Employee {payload.status}', 'data': serialize_user(item)}


@router.delete('/{user_id}', tags=['Employees'])
def delete_employee(user_id: str, request: Request, db: Session = Depends(get_db), user=Depends(require_permissions('users.invite'))):
    service.delete_employee(db, actor=user, user_id=user_id, request_meta=req_meta(request))
    return {'message': 'Employee removed successfully'}


@router.get('/{user_id}', tags=['Employees'])
def get_employee(user_id: str, db: Session = Depends(get_db), user=Depends(require_permissions('users.invite', 'reports.company'))):
    item = service.get_employee(db, actor=user, user_id=user_id)
    return {'message': 'Employee fetched successfully', 'data': serialize_user(item)}
