from fastapi import APIRouter, Depends, Request, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps.auth import require_permissions
from app.schemas.employee import BranchRequest, CompanySettingsRequest, ProjectRequest, RoleCreateRequest, RoleUpdateRequest, UserPermissionOverrideRequest, UserRoleAssignmentRequest
from app.services.auth import service
from app.services.billing_policy import assert_limit_available

router = APIRouter()


def req_meta(request: Request):
    return {'ip_address': request.client.host if request.client else None, 'user_agent': request.headers.get('user-agent')}


@router.get('/permissions', tags=['Roles & Permissions'])
def permissions(db: Session = Depends(get_db), user=Depends(require_permissions('roles.manage', 'settings.tenant'))):
    items = service.list_permissions(db)
    return {'message': 'Permissions fetched successfully', 'data': [{'id': str(item.id), 'key': item.key, 'name': item.name, 'description': item.description} for item in items]}


@router.get('/roles', tags=['Roles & Permissions'])
def roles(db: Session = Depends(get_db), user=Depends(require_permissions('roles.manage', 'settings.tenant'))):
    items = service.list_roles(db, actor=user)
    return {'message': 'Roles fetched successfully', 'data': [{'id': str(item.id), 'key': item.key, 'name': item.name, 'description': item.description, 'company_id': str(item.company_id) if item.company_id else None, 'is_system': item.is_system, 'permissions': [perm.key for perm in item.permissions]} for item in items]}


@router.post('/roles', tags=['Roles & Permissions'])
def create_role(payload: RoleCreateRequest, request: Request, db: Session = Depends(get_db), user=Depends(require_permissions('roles.manage', 'settings.tenant'))):
    item = service.create_role(db, actor=user, key=payload.key, name=payload.name, description=payload.description, permission_keys=payload.permission_keys, request_meta=req_meta(request))
    return {'message': 'Role created successfully', 'data': {'id': str(item.id), 'key': item.key, 'name': item.name}}


@router.patch('/roles/{role_id}', tags=['Roles & Permissions'])
def update_role(role_id: str, payload: RoleUpdateRequest, request: Request, db: Session = Depends(get_db), user=Depends(require_permissions('roles.manage', 'settings.tenant'))):
    item = service.update_role(db, actor=user, role_id=role_id, name=payload.name, description=payload.description, permission_keys=payload.permission_keys, request_meta=req_meta(request))
    return {'message': 'Role updated successfully', 'data': {'id': str(item.id), 'key': item.key, 'name': item.name, 'permissions': [perm.key for perm in item.permissions]}}


@router.put('/employees/{user_id}/roles', tags=['Roles & Permissions'])
def assign_user_roles(user_id: str, payload: UserRoleAssignmentRequest, request: Request, db: Session = Depends(get_db), user=Depends(require_permissions('roles.manage', 'settings.tenant'))):
    item = service.assign_user_roles(db, actor=user, user_id=user_id, role_keys=payload.role_keys, request_meta=req_meta(request))
    return {'message': 'User roles updated successfully', 'data': {'id': str(item.id), 'role_keys': [role.key for role in item.roles], 'permissions': service.permission_keys_for_user(db, item)}}


@router.put('/employees/{user_id}/permission-overrides', tags=['Roles & Permissions'])
def set_user_permission_overrides(user_id: str, payload: UserPermissionOverrideRequest, request: Request, db: Session = Depends(get_db), user=Depends(require_permissions('roles.manage', 'settings.tenant'))):
    return {'message': 'User permission overrides updated successfully', 'data': service.set_user_permission_overrides(db, actor=user, user_id=user_id, allow=payload.allow, deny=payload.deny, request_meta=req_meta(request))}


@router.get('/company-settings', tags=['Company'])
def company_settings(user=Depends(require_permissions('settings.tenant', 'reports.company'))):
    return {'message': 'Company settings fetched successfully', 'data': service.get_company_settings(actor=user)}


@router.patch('/company-settings', tags=['Company'])
def update_company_settings(payload: CompanySettingsRequest, request: Request, db: Session = Depends(get_db), user=Depends(require_permissions('settings.tenant'))):
    return {'message': 'Company settings saved successfully', 'data': service.update_company_settings(db, actor=user, payload=payload, request_meta=req_meta(request))}


@router.get('/branches', tags=['Branches'])
def branches(db: Session = Depends(get_db), user=Depends(require_permissions('settings.tenant', 'users.invite', 'reports.company', 'org.view_self', 'org.view_team', 'org.view_company', 'schedule.view_self', 'schedule.view_team', 'schedule.view_company'))):
    rows = service.list_branches(actor=user)
    permissions = set(service.permission_keys_for_user(db, user))
    if not {'settings.tenant', 'users.invite', 'reports.company', 'org.view_company', 'schedule.view_company'}.intersection(permissions):
        branch_id = str((user.metadata_json or {}).get('branch_id') or '')
        rows = [item for item in rows if branch_id and str(item.get('id')) == branch_id]
    return {'message': 'Branches fetched successfully', 'data': rows}


@router.post('/branches', tags=['Branches'])
def upsert_branch(payload: BranchRequest, request: Request, db: Session = Depends(get_db), user=Depends(require_permissions('settings.tenant'))):
    if not payload.id:
        assert_limit_available(str(user.company_id), 'branches', len(service.list_branches(actor=user)), 1)
    item = service.upsert_branch(db, actor=user, payload=payload, request_meta=req_meta(request))
    return {'message': 'Branch saved successfully', 'data': item}


@router.delete('/branches/{branch_id}', tags=['Branches'])
def delete_branch(branch_id: str, request: Request, db: Session = Depends(get_db), user=Depends(require_permissions('settings.tenant'))):
    return {'message': 'Branch deleted successfully', 'data': service.delete_branch(db, actor=user, branch_id=branch_id, request_meta=req_meta(request))}


@router.get('/projects', tags=['Projects'])
def projects(
    db: Session = Depends(get_db),
    user=Depends(require_permissions('settings.tenant', 'users.invite', 'reports.company', 'org.view_self', 'org.view_team', 'org.view_company', 'schedule.view_self', 'schedule.view_team', 'schedule.view_company')),
    limit: int | None = Query(None, ge=1, le=200),
    offset: int = Query(0, ge=0),
    q: str | None = Query(None, max_length=120),
    branch_id: str | None = Query(None),
):
    permissions = set(service.permission_keys_for_user(db, user))
    if not {'settings.tenant', 'users.invite', 'reports.company', 'org.view_company', 'schedule.view_company'}.intersection(permissions):
        metadata = user.metadata_json or {}
        allowed_project_ids = {str(item) for item in (metadata.get('project_ids') or []) if item}
        if branch_id and str(branch_id) != str(metadata.get('branch_id') or ''):
            return {'message': 'Projects fetched successfully', 'data': [], 'meta': {'limit': limit or 50, 'offset': offset, 'total': 0}}
        rows = service.list_projects(actor=user, q=q, branch_id=branch_id or metadata.get('branch_id'))
        rows = [item for item in rows if str(item.get('id')) in allowed_project_ids or str(item.get('branch_id') or '') == str(metadata.get('branch_id') or '')]
        total = len(rows)
        if limit is None and offset == 0:
            return {'message': 'Projects fetched successfully', 'data': rows}
        return {'message': 'Projects fetched successfully', 'data': rows[offset:offset + (limit or 50)], 'meta': {'limit': limit or 50, 'offset': offset, 'total': total}}
    if limit is None and not q and not branch_id and offset == 0:
        return {'message': 'Projects fetched successfully', 'data': service.list_projects(actor=user)}
    items, total = service.list_projects(actor=user, limit=limit or 50, offset=offset, q=q, branch_id=branch_id)
    return {'message': 'Projects fetched successfully', 'data': items, 'meta': {'limit': limit or 50, 'offset': offset, 'total': total}}


@router.post('/projects', tags=['Projects'])
def upsert_project(payload: ProjectRequest, request: Request, db: Session = Depends(get_db), user=Depends(require_permissions('settings.tenant'))):
    if not payload.id:
        assert_limit_available(str(user.company_id), 'projects', len(service.list_projects(actor=user)), 1)
    item = service.upsert_project(db, actor=user, payload=payload, request_meta=req_meta(request))
    return {'message': 'Project saved successfully', 'data': item}


@router.delete('/projects/{project_id}', tags=['Projects'])
def delete_project(project_id: str, request: Request, db: Session = Depends(get_db), user=Depends(require_permissions('settings.tenant'))):
    return {'message': 'Project deleted successfully', 'data': service.delete_project(db, actor=user, project_id=project_id, request_meta=req_meta(request))}
