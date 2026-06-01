from datetime import datetime, timedelta, timezone
import io
import uuid
import pandas as pd
import phonenumbers
from fastapi import HTTPException
from sqlalchemy import func, select, or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, object_session, selectinload

from app.core.config import settings
from app.core.exceptions import bad_request, conflict, not_found, unauthorized, forbidden
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
    token_hash,
    random_password,
    random_secret,
    slugify_name,
)
from app.models.company import Company
from app.models.user import User
from app.models.role import Role
from app.models.permission import Permission
from app.models.associations import UserPermissionOverride
from app.models.refresh_session import RefreshSession
from app.models.verification_token import VerificationToken
from app.models.login_history import LoginHistory
from app.models.api_key import ApiKey
from app.services.audit import log_audit
from app.services.email import EmailDeliveryError, send_email_verification, send_password_reset  # Backward-compatible imports for legacy tests/integrations.
from app.services import mfa as mfa_service
from app.integrations.events import publish_event


def normalize_phone_number(value: str | None, country: str | None = None) -> str | None:
    if not value:
        return None
    try:
        parsed = phonenumbers.parse(str(value), country or None)
    except phonenumbers.NumberParseException:
        bad_request('Invalid phone number')
    if not phonenumbers.is_valid_number(parsed):
        bad_request('Invalid phone number')
    if country and phonenumbers.region_code_for_number(parsed) != country:
        bad_request('Phone number does not match selected country')
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL)


class AuthService:
    suggested_role_names = {
        'employee': 'Employee',
        'team_lead': 'Team lead',
        'manager': 'Manager',
        'department_head': 'Department head',
        'project_manager': 'Project manager',
        'recruiter': 'Recruiter',
        'hr_admin': 'HR admin',
        'finance_admin': 'Finance admin',
        'it_admin': 'IT admin',
        'auditor': 'Auditor',
        'read_only': 'Read-only',
        'company_owner': 'Company owner',
    }

    def resolve_role(self, db: Session, *, actor: User, role_key: str) -> Role | None:
        role = db.scalar(select(Role).where(Role.key == role_key).where(or_(Role.company_id.is_(None), Role.company_id == actor.company_id)))
        if role or role_key not in self.suggested_role_names:
            return role
        role = Role(key=role_key, name=self.suggested_role_names[role_key], description='Directory access role', company_id=actor.company_id, is_system=False)
        db.add(role)
        db.flush()
        return role

    def has_role_key(self, user: User, role_key: str) -> bool:
        return any(role.key == role_key for role in (user.roles or []))

    def permission_keys_for_user(self, db: Session, user: User) -> list[str]:
        keys = {perm.key for role in (user.roles or []) for perm in role.permissions}
        if db is None:
            return sorted(keys)
        try:
            overrides = db.execute(
                select(UserPermissionOverride.effect, Permission.key)
                .join(Permission, Permission.id == UserPermissionOverride.permission_id)
                .where(UserPermissionOverride.user_id == user.id)
            ).all()
        except SQLAlchemyError:
            db.rollback()
            return sorted(keys)
        denied = {key for effect, key in overrides if effect == 'deny'}
        allowed = {key for effect, key in overrides if effect == 'allow'}
        return sorted((keys | allowed) - denied)

    def has_permission_key(self, db: Session, user: User, permission: str) -> bool:
        return permission in set(self.permission_keys_for_user(db, user))

    def assert_assignable_employee_role(self, role_key: str | None):
        if role_key == 'company_owner':
            bad_request('Company owner cannot be assigned to an employee')

    def normalize_company_owner_role(self, db: Session, *, company: Company, current_user: User | None = None):
        owner_role = db.scalar(select(Role).where(Role.key == 'company_owner', Role.company_id.is_(None)))
        if not owner_role:
            return
        owners = db.execute(
            select(User)
            .join(User.roles)
            .options(selectinload(User.roles).selectinload(Role.permissions))
            .where(User.company_id == company.id, Role.key == 'company_owner', User.status != 'deleted')
        ).scalars().unique().all()
        if not owners:
            return
        metadata = dict(company.metadata_json or {})
        owner_user_id = metadata.get('owner_user_id')
        owner = next((item for item in owners if str(item.id) == str(owner_user_id)), None)
        if not owner:
            owners.sort(key=lambda item: item.created_at or datetime.min)
            owner = owners[0]
            metadata['owner_user_id'] = str(owner.id)
            company.metadata_json = metadata
            db.add(company)
        employee_role = db.scalar(select(Role).where(Role.key == 'employee', Role.company_id.is_(None)))
        for item in owners:
            if item.id == owner.id:
                continue
            item.roles = [role for role in item.roles if role.key != 'company_owner']
            if not item.roles and employee_role:
                item.roles.append(employee_role)
            db.add(item)
            if current_user and item.id == current_user.id:
                current_user.roles = item.roles
        db.flush()

    def user_has_sso_link(self, user: User) -> bool:
        metadata = user.metadata_json or {}
        return isinstance(metadata, dict) and isinstance(metadata.get('sso'), dict)

    def is_expired(self, expires_at: datetime) -> bool:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return expires_at < datetime.now(timezone.utc)

    def format_employee_code(self, prefix: str, sequence: int) -> str:
        return f'{prefix}-{sequence:06d}'

    def build_tenant_base_url(self, company: Company) -> str:
        return f'http://{company.domain or f"{company.slug}.{settings.DEFAULT_ROOT_DOMAIN}"}'

    def list_branches(self, *, actor: User):
        metadata = actor.company.metadata_json or {}
        return metadata.get('branches') or []

    def get_company_settings(self, *, actor: User):
        metadata = actor.company.metadata_json or {}
        return {
            'id': str(actor.company.id),
            'name': actor.company.name,
            'slug': actor.company.slug,
            'domain': actor.company.domain,
            'status': actor.company.status,
            'employee_code_prefix': actor.company.employee_code_prefix,
            'logo_url': metadata.get('logo_url'),
            'legal_name': metadata.get('legal_name'),
            'company_size': metadata.get('company_size'),
            'industry': metadata.get('industry'),
            'registration_number': metadata.get('registration_number'),
            'vat_id': metadata.get('vat_id'),
            'address_line': metadata.get('address_line'),
            'country': metadata.get('country'),
            'city': metadata.get('city'),
            'timezone': metadata.get('timezone'),
            'website': metadata.get('website'),
            'language': metadata.get('language'),
            'operating_model': metadata.get('operating_model'),
            'onboarding_completed': metadata.get('onboarding_completed'),
            'enabled_modules': metadata.get('enabled_modules') or [],
            'terminology': metadata.get('terminology') or {},
            'integrations': metadata.get('integrations') or {},
        }

    def update_company_settings(self, db: Session, *, actor: User, payload, request_meta: dict):
        metadata = dict(actor.company.metadata_json or {})
        data = payload.model_dump(exclude_unset=True)
        if data.get('name'):
            actor.company.name = data['name'].strip()
        for key in ('logo_url', 'legal_name', 'company_size', 'industry', 'registration_number', 'vat_id', 'address_line', 'country', 'city', 'timezone', 'website', 'language', 'operating_model', 'onboarding_completed', 'enabled_modules', 'terminology', 'integrations'):
            if key in data:
                if key == 'enabled_modules' and data[key] is not None:
                    metadata[key] = [str(item).strip() for item in data[key] if str(item).strip()]
                elif key == 'terminology' and data[key] is not None:
                    metadata[key] = {str(term_key).strip(): str(term_value).strip() for term_key, term_value in data[key].items() if str(term_key).strip() and str(term_value).strip()}
                elif key == 'integrations' and data[key] is not None:
                    metadata[key] = data[key]
                else:
                    metadata[key] = data[key].strip() if isinstance(data[key], str) and data[key] else data[key]
        actor.company.metadata_json = metadata
        db.add(actor.company)
        db.commit()
        log_audit(db, company_id=actor.company_id, actor_user_id=actor.id, action='company.settings_updated', entity_type='company', entity_id=actor.company_id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={key: data.get(key) for key in data.keys() if key != 'logo_url'})
        return self.get_company_settings(actor=actor)

    def get_branch(self, *, actor: User, branch_id: str | None):
        if not branch_id:
            return None
        return next((item for item in self.list_branches(actor=actor) if str(item.get('id')) == str(branch_id)), None)

    def upsert_branch(self, db: Session, *, actor: User, payload, request_meta: dict):
        metadata = dict(actor.company.metadata_json or {})
        branches = list(metadata.get('branches') or [])
        branch_id = payload.id or str(uuid.uuid4())
        next_branch = {
            'id': branch_id,
            'name': payload.name.strip(),
            'city': payload.city.strip() if payload.city else None,
            'country': payload.country.strip() if payload.country else None,
            'timezone': payload.timezone.strip() if payload.timezone else None,
            'status': payload.status,
        }
        updated = False
        for index, branch in enumerate(branches):
            if str(branch.get('id')) == branch_id:
                branches[index] = {**branch, **next_branch}
                updated = True
                break
        if not updated:
            branches.append(next_branch)
        metadata['branches'] = branches
        actor.company.metadata_json = metadata
        db.add(actor.company)
        db.commit()
        log_audit(db, company_id=actor.company_id, actor_user_id=actor.id, action='company.branch_upserted', entity_type='branch', entity_id=branch_id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload=next_branch)
        return next_branch

    def delete_branch(self, db: Session, *, actor: User, branch_id: str, request_meta: dict):
        metadata = dict(actor.company.metadata_json or {})
        branches = list(metadata.get('branches') or [])
        next_branches = [branch for branch in branches if str(branch.get('id')) != str(branch_id)]
        if len(next_branches) == len(branches):
            not_found('Branch not found')
        metadata['branches'] = next_branches
        actor.company.metadata_json = metadata
        db.add(actor.company)
        users = db.execute(select(User).where(User.company_id == actor.company_id)).scalars().all()
        for user in users:
            user_metadata = dict(user.metadata_json or {})
            if str(user_metadata.get('branch_id')) == str(branch_id):
                user_metadata['branch_id'] = None
                user_metadata['branch_name'] = None
                user.metadata_json = user_metadata
                db.add(user)
        db.commit()
        log_audit(db, company_id=actor.company_id, actor_user_id=actor.id, action='company.branch_deleted', entity_type='branch', entity_id=branch_id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={})
        return {'id': branch_id, 'deleted': True}

    def list_projects(self, *, actor: User, limit: int | None = None, offset: int = 0, q: str | None = None, branch_id: str | None = None):
        metadata = actor.company.metadata_json or {}
        projects = list(metadata.get('projects') or [])
        if q:
            needle = q.strip().lower()
            projects = [
                project for project in projects
                if needle in ' '.join(str(project.get(key) or '') for key in ('name', 'code', 'client', 'branch_name', 'status')).lower()
            ]
        if branch_id:
            projects = [project for project in projects if str(project.get('branch_id') or '') == str(branch_id)]
        total = len(projects)
        if limit is None:
            return projects
        limit = max(1, min(int(limit or 50), 200))
        offset = max(0, int(offset or 0))
        return projects[offset:offset + limit], total

    def get_project(self, *, actor: User, project_id: str | None):
        if not project_id:
            return None
        return next((item for item in self.list_projects(actor=actor) if str(item.get('id')) == str(project_id)), None)

    def resolve_projects(self, *, actor: User, project_ids: list[str] | None):
        if not project_ids:
            return []
        wanted = {str(item) for item in project_ids if item}
        return [project for project in self.list_projects(actor=actor) if str(project.get('id')) in wanted]

    def resolve_manager(self, db: Session, *, actor: User, manager_id: str | None):
        identifier = str(manager_id or '').strip()
        if not identifier:
            return None
        filters = [User.employee_code == identifier, User.email == identifier.lower()]
        try:
            filters.append(User.id == uuid.UUID(identifier))
        except ValueError:
            pass
        manager = db.scalar(select(User).where(User.company_id == actor.company_id, User.status != 'deleted').where(or_(*filters)))
        if not manager:
            bad_request('Invalid manager')
        return manager

    def upsert_project(self, db: Session, *, actor: User, payload, request_meta: dict):
        metadata = dict(actor.company.metadata_json or {})
        projects = list(metadata.get('projects') or [])
        project_id = payload.id or str(uuid.uuid4())
        branch = self.get_branch(actor=actor, branch_id=payload.branch_id)
        next_project = {
            'id': project_id,
            'name': payload.name.strip(),
            'code': payload.code.strip().upper() if payload.code else None,
            'client': payload.client.strip() if payload.client else None,
            'branch_id': branch.get('id') if branch else None,
            'branch_name': branch.get('name') if branch else None,
            'status': payload.status,
            'start_date': payload.start_date,
            'end_date': payload.end_date,
        }
        updated = False
        for index, project in enumerate(projects):
            if str(project.get('id')) == project_id:
                projects[index] = {**project, **next_project}
                updated = True
                break
        if not updated:
            projects.append(next_project)
        metadata['projects'] = projects
        actor.company.metadata_json = metadata
        db.add(actor.company)
        db.commit()
        log_audit(db, company_id=actor.company_id, actor_user_id=actor.id, action='company.project_upserted', entity_type='project', entity_id=project_id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload=next_project)
        return next_project

    def delete_project(self, db: Session, *, actor: User, project_id: str, request_meta: dict):
        metadata = dict(actor.company.metadata_json or {})
        projects = list(metadata.get('projects') or [])
        next_projects = [project for project in projects if str(project.get('id')) != str(project_id)]
        if len(next_projects) == len(projects):
            not_found('Project not found')
        metadata['projects'] = next_projects
        actor.company.metadata_json = metadata
        db.add(actor.company)
        users = db.execute(select(User).where(User.company_id == actor.company_id)).scalars().all()
        for user in users:
            user_metadata = dict(user.metadata_json or {})
            project_ids = [str(item) for item in (user_metadata.get('project_ids') or []) if str(item) != str(project_id)]
            if project_ids != (user_metadata.get('project_ids') or []):
                project_rows = self.resolve_projects(actor=actor, project_ids=project_ids)
                user_metadata['project_ids'] = [item.get('id') for item in project_rows]
                user_metadata['project_names'] = [item.get('name') for item in project_rows]
                user.metadata_json = user_metadata
                db.add(user)
        db.commit()
        log_audit(db, company_id=actor.company_id, actor_user_id=actor.id, action='company.project_deleted', entity_type='project', entity_id=project_id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={})
        return {'id': project_id, 'deleted': True}

    def create_company_for_sso_signup(self, db: Session, *, email: str, userinfo: dict, provider: str | None = None) -> Company:
        domain_part = email.split('@')[-1].split('.')[0]
        display_name = userinfo.get('hd') or domain_part or email.split('@')[0]
        base_slug = slugify_name(display_name) or f'sso-{uuid.uuid4().hex[:8]}'
        slug = base_slug
        counter = 1
        while db.scalar(select(Company).where(Company.slug == slug)):
            counter += 1
            slug = f'{base_slug}-{counter}'
        company = Company(
            name=display_name.replace('-', ' ').title(),
            slug=slug,
            domain=f'{slug}.{settings.DEFAULT_ROOT_DOMAIN}',
            employee_sequence=0,
            employee_code_prefix='EMP',
            metadata_json={'created_by': 'sso_signup', 'signup_provider': provider, 'onboarding_completed': False},
        )
        db.add(company)
        db.flush()
        return company

    def issue_payload(self, user: User, company: Company) -> dict:
        roles = [role.key for role in user.roles]
        permissions = self.permission_keys_for_user(object_session(user), user)
        return {
            'sub': str(user.id),
            'email': user.email,
            'company_id': str(company.id),
            'company_slug': company.slug,
            'roles': roles,
            'permissions': permissions,
        }

    def issue_login_tokens(self, db: Session, *, user: User, company: Company, provider: str, request_meta: dict):
        device_id = request_meta.get('device_id')
        prior_sessions = db.execute(select(RefreshSession).where(RefreshSession.user_id == user.id)).scalars().all()
        known_device = bool(device_id and any((item.device_info or {}).get('device_id') == device_id for item in prior_sessions))
        self.normalize_company_owner_role(db, company=company, current_user=user)
        user.login_attempts = 0
        user.locked_until = None
        user.status = 'active'
        user.last_login_at = datetime.now(timezone.utc)
        db.add(user)
        payload = self.issue_payload(user, company)
        access_token = create_access_token(payload)
        policy = self.get_security_policy(actor=user)
        refresh_token = create_refresh_token(payload, policy['session_ttl_days'])
        session = RefreshSession(
            user_id=user.id,
            token_hash=token_hash(refresh_token),
            expires_at=datetime.now(timezone.utc) + timedelta(days=policy['session_ttl_days']),
            last_used_at=datetime.now(timezone.utc),
            ip_address=request_meta.get('ip_address'),
            user_agent=request_meta.get('user_agent'),
            device_info={'user_agent': request_meta.get('user_agent'), 'provider': provider, 'geo_country': request_meta.get('geo_country'), 'geo_city': request_meta.get('geo_city'), 'device_id': request_meta.get('device_id')},
        )
        db.add(session)
        db.add(LoginHistory(user_id=user.id, email=user.email, company_slug=company.slug, provider=provider, status='success', ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent')))
        db.commit()
        log_audit(db, company_id=company.id, actor_user_id=user.id, action='auth.login', entity_type='session', entity_id=user.id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={'provider': provider})
        if not known_device:
            self.send_security_notification_if_enabled(user, title='New device sign-in', preview='A new browser or device signed in to your Attendio account.')
        return {
            'user': user,
            'company': company,
            'access_token': access_token,
            'refresh_token': refresh_token,
            'tenant_base_url': self.build_tenant_base_url(company),
            'redirect_url': f'{self.build_tenant_base_url(company)}{settings.FRONTEND_AFTER_LOGIN}',
            'display_message': f'Login successful. Welcome, {user.first_name} {user.last_name}',
            'device_id': request_meta.get('device_id'),
        }

    def allocate_employee_code(self, db: Session, company: Company) -> str:
        company.employee_sequence += 1
        db.add(company)
        db.flush()
        return self.format_employee_code(company.employee_code_prefix, company.employee_sequence)

    def resolve_company_for_login(self, db: Session, *, email: str, tenant: Company | None) -> Company:
        if tenant:
            return tenant
        stmt = select(User).options(selectinload(User.company)).where(User.email == email.lower())
        matches = db.execute(stmt).scalars().all()
        active_users = [user for user in matches if user.company and user.company.status == 'active']
        if not active_users:
            unauthorized('Invalid credentials')
        active_users.sort(key=lambda item: item.last_login_at or item.created_at or datetime.min, reverse=True)
        return active_users[0].company

    def resolve_company_by_slug(self, db: Session, *, slug: str | None) -> Company | None:
        value = (slug or '').strip().lower()
        if not value:
            return None
        company = db.scalar(select(Company).where(Company.slug == value, Company.status == 'active'))
        return company

    def resolve_local_user_for_login(self, db: Session, *, email: str, password: str, tenant: Company | None, request_meta: dict) -> tuple[Company, User]:
        email = email.lower()
        if tenant:
            company = tenant
            stmt = (
                select(User)
                .options(selectinload(User.roles).selectinload(Role.permissions), selectinload(User.company))
                .where(User.company_id == company.id, User.email == email)
            )
            user = db.execute(stmt).scalar_one_or_none()
            if user and not settings.ALLOW_EMAIL_LOGIN_FALLBACK and (user.provider != 'local' or self.user_has_sso_link(user)):
                unauthorized('Use SSO to sign in')
            if not user or not verify_password(password, user.password_hash):
                if user:
                    user.login_attempts += 1
                    if user.login_attempts >= settings.LOGIN_MAX_ATTEMPTS:
                        user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=settings.LOGIN_LOCK_MINUTES)
                        user.status = 'locked'
                    db.add(user)
                    db.commit()
                db.add(LoginHistory(user_id=user.id if user else None, email=email, company_slug=company.slug, provider='local', status='failed', ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), failure_reason='invalid_password'))
                db.commit()
                unauthorized('Invalid credentials')
            return company, user

        stmt = (
            select(User)
            .options(selectinload(User.roles).selectinload(Role.permissions), selectinload(User.company))
            .where(User.email == email)
        )
        candidates = [
            user for user in db.execute(stmt).scalars().all()
            if user.company and user.company.status == 'active'
        ]
        candidates = [
            user for user in candidates
            if settings.ALLOW_EMAIL_LOGIN_FALLBACK or (user.provider == 'local' and not self.user_has_sso_link(user))
        ]
        if not candidates:
            unauthorized('Invalid credentials')
        valid_users = [user for user in candidates if verify_password(password, user.password_hash)]
        if len(valid_users) == 1:
            user = valid_users[0]
            return user.company, user
        if len(valid_users) > 1:
            non_owner_users = [user for user in valid_users if not self.has_role_key(user, 'company_owner')]
            if len(non_owner_users) == 1:
                user = non_owner_users[0]
                return user.company, user
            conflict('This email belongs to more than one workspace. Open the exact tenant link to continue.')

        for user in candidates:
            user.login_attempts += 1
            if user.login_attempts >= settings.LOGIN_MAX_ATTEMPTS:
                user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=settings.LOGIN_LOCK_MINUTES)
                user.status = 'locked'
            db.add(user)
            db.add(LoginHistory(user_id=user.id, email=email, company_slug=user.company.slug if user.company else None, provider='local', status='failed', ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), failure_reason='invalid_password'))
        db.commit()
        unauthorized('Invalid credentials')

    def bootstrap_company(self, db: Session, payload, request_meta: dict):
        base_slug = slugify_name(payload.company_name)
        slug = base_slug
        counter = 1
        while db.scalar(select(Company).where(Company.slug == slug)):
            counter += 1
            slug = f'{base_slug}-{counter}'
        domain = f'{slug}.{settings.DEFAULT_ROOT_DOMAIN}'
        owner_email = payload.owner_email.lower()
        company = Company(name=payload.company_name, slug=slug, domain=domain, employee_sequence=0, employee_code_prefix='EMP', metadata_json={'onboarding_completed': False})
        db.add(company)
        db.flush()
        owner_code = self.allocate_employee_code(db, company)
        owner = User(
            company_id=company.id,
            employee_code=owner_code,
            first_name=payload.owner_first_name,
            last_name=payload.owner_last_name,
            email=owner_email,
            password_hash=hash_password(payload.owner_password),
            provider='local',
            status='active',
            email_verified=False,
        )
        owner_role = db.scalar(select(Role).where(Role.key == 'company_owner', Role.company_id.is_(None)))
        if not owner_role:
            raise RuntimeError('Seed roles missing')
        owner.roles.append(owner_role)
        db.add(owner)
        db.flush()
        company_metadata = dict(company.metadata_json or {})
        company_metadata['owner_user_id'] = str(owner.id)
        company.metadata_json = company_metadata
        db.add(company)
        db.commit()
        db.refresh(company)
        db.refresh(owner)
        delivery = self.send_email_verification(db, user=owner, request_meta=request_meta)
        log_audit(db, company_id=company.id, actor_user_id=owner.id, action='company.bootstrap', entity_type='company', entity_id=company.id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={'slug': company.slug, 'domain': company.domain, 'owner_email': owner.email})
        return company, owner, delivery

    def load_user_for_session(self, db: Session, *, user_id: uuid.UUID | str):
        stmt = (
            select(User)
            .options(selectinload(User.roles).selectinload(Role.permissions), selectinload(User.company))
            .where(User.id == user_id)
        )
        return db.execute(stmt).scalar_one_or_none()

    def login(self, db: Session, *, email: str, password: str, mfa_token: str | None, tenant: Company | None, request_meta: dict):
        company, user = self.resolve_local_user_for_login(db, email=email, password=password, tenant=tenant, request_meta=request_meta)
        if user.locked_until and user.locked_until > datetime.now(timezone.utc):
            unauthorized('Account temporarily locked')
        if not user.email_verified:
            self.send_email_verification(db, user=user, request_meta=request_meta)
            db.add(LoginHistory(user_id=user.id, email=email.lower(), company_slug=company.slug, provider='local', status='failed', ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), failure_reason='email_not_verified'))
            db.commit()
            forbidden('Email verification required. We sent a fresh verification link to your email.')
        policy = self.get_security_policy(actor=user)
        enforcement_at = policy.get('mfa_enforcement_at')
        if policy.get('require_mfa') and not user.mfa_enabled and enforcement_at:
            deadline = datetime.fromisoformat(enforcement_at)
            if deadline <= datetime.now(timezone.utc):
                forbidden('MFA enrollment is required by your company before sign-in')
        if user.mfa_enabled:
            if not mfa_token:
                unauthorized('MFA token is required')
            mfa_service.verify_login(db, user, mfa_token)
        return self.issue_login_tokens(db, user=user, company=company, provider='local', request_meta=request_meta)

    def discover_sso_provider(self, db: Session, *, email: str, tenant: Company | None = None):
        company = self.resolve_company_for_login(db, email=email, tenant=tenant)
        email_domain = email.lower().split('@')[-1]
        metadata = company.metadata_json or {}
        sso = metadata.get('sso') if isinstance(metadata, dict) else None
        provider = None
        if isinstance(sso, dict):
            provider = sso.get('provider')
        if not provider:
            users = db.execute(select(User.provider).where(User.company_id == company.id, User.email == email.lower())).scalars().all()
            if 'microsoft' in users:
                provider = 'microsoft'
            elif 'google' in users:
                provider = 'google'
        provider = provider or ('microsoft' if email_domain in {'outlook.com', 'hotmail.com', 'live.com'} else 'google')
        if provider not in {'google', 'microsoft'}:
            bad_request('Unsupported SSO provider')
        return {
            'provider': provider,
            'company': company,
            'login_url': f'{settings.API_V1_PREFIX}/auth/sso/{provider}?email={email.lower()}',
        }

    def sso_login(self, db: Session, *, provider: str, userinfo: dict, tenant: Company | None, email_hint: str | None, request_meta: dict):
        email = (userinfo.get('email') or userinfo.get('preferred_username') or email_hint or '').lower()
        if not email:
            unauthorized('SSO provider did not return an email address')
        if provider == 'google' and userinfo.get('email_verified') is False:
            unauthorized('Google account email is not verified')
        provider_subject = userinfo.get('sub') or userinfo.get('oid')
        company = None
        user = None
        if tenant:
            company = tenant
        else:
            matches = [
                candidate for candidate in db.execute(
                    select(User)
                    .options(selectinload(User.roles).selectinload(Role.permissions), selectinload(User.company))
                    .where(User.email == email)
                ).scalars().all()
                if candidate.company and candidate.company.status == 'active' and candidate.status in {'active', 'invited'}
            ]
            exact_provider_matches = []
            reusable_local_users = []
            for candidate in matches:
                metadata = candidate.metadata_json or {}
                existing_sso = metadata.get('sso') if isinstance(metadata, dict) else None
                existing_provider = existing_sso.get('provider') if isinstance(existing_sso, dict) else None
                existing_subject = existing_sso.get('sub') if isinstance(existing_sso, dict) else None
                provider_matches = candidate.provider == provider or existing_provider == provider
                subject_matches = not existing_subject or not provider_subject or existing_subject == provider_subject
                if provider_matches and subject_matches:
                    exact_provider_matches.append(candidate)
                elif candidate.provider == 'local' and not existing_sso:
                    reusable_local_users.append(candidate)
            if exact_provider_matches:
                exact_provider_matches.sort(key=lambda item: item.last_login_at or item.created_at or datetime.min, reverse=True)
                user = exact_provider_matches[0]
                company = user.company
            elif len(reusable_local_users) == 1:
                user = reusable_local_users[0]
                company = user.company
        if company and not user:
            stmt = (
                select(User)
                .options(selectinload(User.roles).selectinload(Role.permissions), selectinload(User.company))
                .where(User.company_id == company.id, User.email == email)
            )
            user = db.execute(stmt).scalar_one_or_none()
        if not user:
            if company is not None and not settings.SSO_AUTO_PROVISION:
                db.add(LoginHistory(email=email, company_slug=company.slug if company else None, provider=provider, status='failed', ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), failure_reason='sso_user_not_invited'))
                db.commit()
                unauthorized('SSO user is not invited to this company')
            if company is None:
                company = self.create_company_for_sso_signup(db, email=email, userinfo=userinfo, provider=provider)
                role_key = 'company_owner'
            else:
                role_key = settings.SSO_DEFAULT_ROLE
            role = db.scalar(select(Role).where(Role.key == role_key, Role.company_id.is_(None)))
            if not role:
                raise RuntimeError('Seed roles missing')
            full_name = userinfo.get('name') or email.split('@')[0]
            parts = full_name.split(' ', 1)
            provider_avatar_url = userinfo.get('picture')
            metadata = {'sso': {'provider': provider, 'sub': userinfo.get('sub') or userinfo.get('oid')}}
            if provider_avatar_url:
                metadata.update({
                    'provider_avatar_url': provider_avatar_url,
                    'profile_picture_url': provider_avatar_url,
                    'profile_picture_source': 'sso_seed',
                })
            user = User(
                company_id=company.id,
                employee_code=self.allocate_employee_code(db, company),
                first_name=userinfo.get('given_name') or parts[0] or 'SSO',
                last_name=userinfo.get('family_name') or (parts[1] if len(parts) > 1 else 'User'),
                email=email,
                password_hash=None,
                provider=provider,
                status='active',
                email_verified=True,
                metadata_json=metadata,
            )
            user.roles.append(role)
            db.add(user)
            db.flush()
            if role_key == 'company_owner':
                company_metadata = dict(company.metadata_json or {})
                company_metadata['owner_user_id'] = str(user.id)
                company.metadata_json = company_metadata
                db.add(company)
        else:
            metadata = dict(user.metadata_json or {})
            existing_sso = metadata.get('sso') if isinstance(metadata, dict) else None
            existing_sso_provider = existing_sso.get('provider') if isinstance(existing_sso, dict) else None
            if user.provider not in {'local', provider} or (existing_sso_provider and existing_sso_provider != provider):
                db.add(LoginHistory(user_id=user.id, email=email, company_slug=company.slug, provider=provider, status='failed', ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), failure_reason='sso_provider_mismatch'))
                db.commit()
                unauthorized('This account is linked to a different SSO provider')
        if user.status not in {'active', 'invited'}:
            unauthorized('Account is not active')
        if user.status == 'invited':
            user.status = 'active'
        if user.provider != 'local':
            user.provider = provider
        user.email_verified = True
        metadata = dict(user.metadata_json or {})
        metadata['sso'] = {'provider': provider, 'sub': userinfo.get('sub') or userinfo.get('oid'), 'last_email': email}
        provider_avatar_url = userinfo.get('picture')
        if provider_avatar_url:
            metadata['provider_avatar_url'] = provider_avatar_url
            if not metadata.get('profile_picture_url') and not metadata.get('profile_picture_source'):
                metadata['profile_picture_url'] = provider_avatar_url
                metadata['profile_picture_source'] = 'sso_seed'
        user.metadata_json = metadata
        return self.issue_login_tokens(db, user=user, company=company, provider=provider, request_meta=request_meta)

    def update_profile(self, db: Session, *, actor: User, payload, request_meta: dict):
        metadata = dict(actor.metadata_json or {})
        data = payload.model_dump(exclude_unset=True)
        if 'first_name' in data and data['first_name']:
            actor.first_name = data['first_name'].strip()
        if 'last_name' in data and data['last_name']:
            actor.last_name = data['last_name'].strip()
        if 'phone' in data:
            profile_country = data.get('country') or metadata.get('country')
            region = profile_country if isinstance(profile_country, str) and len(profile_country) == 2 else None
            actor.phone = normalize_phone_number(data['phone'], region)
        for key in ('country', 'city', 'language'):
            if key in data:
                metadata[key] = data[key].strip() if data[key] else None
        if 'notification_preferences' in data:
            metadata['notification_preferences'] = data['notification_preferences'] or {}
        if 'profile_picture_url' in data:
            metadata['profile_picture_url'] = data['profile_picture_url']
            metadata['profile_picture_source'] = 'user_upload' if data['profile_picture_url'] else 'user_removed'
        actor.metadata_json = metadata
        db.add(actor)
        db.commit()
        db.refresh(actor)
        log_audit(db, company_id=actor.company_id, actor_user_id=actor.id, action='user.profile_updated', entity_type='user', entity_id=actor.id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={'profile_picture_changed': True})
        publish_event('auth.user.profile_updated', str(actor.company_id), {'user_id': str(actor.id)})
        return actor

    def refresh(self, db: Session, *, refresh_token: str):
        payload = decode_token(refresh_token)
        session = db.scalar(select(RefreshSession).where(RefreshSession.token_hash == token_hash(refresh_token), RefreshSession.revoked_at.is_(None)))
        if not session:
            unauthorized('Refresh session not found')
        user = self.load_user_for_session(db, user_id=payload['sub'])
        if not user:
            unauthorized('User not found')
        self.normalize_company_owner_role(db, company=user.company, current_user=user)
        session.last_used_at = datetime.now(timezone.utc)
        new_payload = self.issue_payload(user, user.company)
        new_refresh_token = create_refresh_token(new_payload, self.get_security_policy(actor=user)['session_ttl_days'])
        session.token_hash = token_hash(new_refresh_token)
        db.add(session)
        db.commit()
        return {'access_token': create_access_token(new_payload), 'refresh_token': new_refresh_token, 'company': user.company, 'device_id': (session.device_info or {}).get('device_id')}

    def logout(self, db: Session, refresh_token: str | None):
        if not refresh_token:
            return
        session = db.scalar(select(RefreshSession).where(RefreshSession.token_hash == token_hash(refresh_token), RefreshSession.revoked_at.is_(None)))
        if session:
            session.revoked_at = datetime.now(timezone.utc)
            db.add(session)
            db.commit()

    def register_employee(self, db: Session, *, actor: User, payload, request_meta: dict):
        self.assert_assignable_employee_role(payload.role_key)
        role = self.resolve_role(db, actor=actor, role_key=payload.role_key)
        if not role:
            bad_request('Invalid role')
        email = payload.email.lower()
        normalized_phone = normalize_phone_number(payload.phone, getattr(payload, 'country', None))
        existing_filters = [User.email == email]
        if payload.employee_code:
            existing_filters.append(User.employee_code == payload.employee_code)
        if payload.external_employee_id:
            existing_filters.append(User.external_employee_id == payload.external_employee_id)
        if payload.payroll_employee_id:
            existing_filters.append(User.payroll_employee_id == payload.payroll_employee_id)
        existing = db.scalar(select(User).where(User.company_id == actor.company_id).where(or_(*existing_filters)))
        if existing:
            if existing.status != 'deleted':
                conflict('User, email, or employee identifier already exists in this company')
            generated_password = payload.password or (random_password() if payload.provider == 'local' else None)
            existing.employee_code = payload.employee_code or existing.employee_code or self.allocate_employee_code(db, actor.company)
            existing.external_employee_id = payload.external_employee_id
            existing.payroll_employee_id = payload.payroll_employee_id
            existing.first_name = payload.first_name
            existing.last_name = payload.last_name
            existing.email = email
            existing.phone = normalized_phone
            existing.password_hash = hash_password(generated_password) if generated_password else existing.password_hash
            existing.provider = payload.provider
            existing.status = 'active' if generated_password else 'invited'
            existing.email_verified = False
            branch = self.get_branch(actor=actor, branch_id=getattr(payload, 'branch_id', None))
            project_rows = self.resolve_projects(actor=actor, project_ids=getattr(payload, 'project_ids', None))
            manager = self.resolve_manager(db, actor=actor, manager_id=getattr(payload, 'manager_id', None))
            if manager and manager.id == existing.id:
                bad_request('Employee cannot be their own manager')
            existing.metadata_json = {
                'job_title': getattr(payload, 'job_title', None),
                'department': getattr(payload, 'department', None),
                'manager_id': str(manager.id) if manager else None,
                'manager_name': f'{manager.first_name or ""} {manager.last_name or ""}'.strip() if manager else None,
                'branch_id': branch.get('id') if branch else None,
                'branch_name': branch.get('name') if branch else None,
                'project_ids': [item.get('id') for item in project_rows],
                'project_names': [item.get('name') for item in project_rows],
                'contract_type': getattr(payload, 'contract_type', None),
                'employment_type': getattr(payload, 'employment_type', None),
                'expected_hours_period': getattr(payload, 'expected_hours_period', 'weekly'),
                'expected_hours': getattr(payload, 'expected_hours', None),
                'weekly_hours': getattr(payload, 'weekly_hours', None),
                'monthly_hours': getattr(payload, 'monthly_hours', None),
                'country': getattr(payload, 'country', None),
                'city': getattr(payload, 'city', None),
                'start_date': getattr(payload, 'start_date', None),
                'end_date': getattr(payload, 'end_date', None),
            }
            existing.roles.clear()
            existing.roles.append(role)
            db.commit()
            db.refresh(existing)
            log_audit(db, company_id=actor.company_id, actor_user_id=actor.id, action='user.restored', entity_type='user', entity_id=existing.id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={'email': existing.email, 'employee_code': existing.employee_code, 'role': role.key})
            publish_event('auth.employee.registered', str(actor.company_id), {
                'user_id': str(existing.id),
                'first_name': existing.first_name,
                'last_name': existing.last_name,
                'email': existing.email,
                'employee_code': existing.employee_code,
                'contract_type': (existing.metadata_json or {}).get('contract_type'),
                'employment_type': (existing.metadata_json or {}).get('employment_type'),
            })
            return existing, (None if payload.password else generated_password)
        company = actor.company
        employee_code = payload.employee_code or self.allocate_employee_code(db, company)
        generated_password = payload.password or (random_password() if payload.provider == 'local' else None)
        branch = self.get_branch(actor=actor, branch_id=getattr(payload, 'branch_id', None))
        project_rows = self.resolve_projects(actor=actor, project_ids=getattr(payload, 'project_ids', None))
        manager = self.resolve_manager(db, actor=actor, manager_id=getattr(payload, 'manager_id', None))
        user = User(
            company_id=actor.company_id,
            employee_code=employee_code,
            external_employee_id=payload.external_employee_id,
            payroll_employee_id=payload.payroll_employee_id,
            first_name=payload.first_name,
            last_name=payload.last_name,
            email=email,
            phone=normalized_phone,
            password_hash=hash_password(generated_password) if generated_password else None,
            provider=payload.provider,
            status='active' if generated_password else 'invited',
            email_verified=False,
            metadata_json={
                'job_title': getattr(payload, 'job_title', None),
                'department': getattr(payload, 'department', None),
                'manager_id': str(manager.id) if manager else None,
                'manager_name': f'{manager.first_name or ""} {manager.last_name or ""}'.strip() if manager else None,
                'branch_id': branch.get('id') if branch else None,
                'branch_name': branch.get('name') if branch else None,
                'project_ids': [item.get('id') for item in project_rows],
                'project_names': [item.get('name') for item in project_rows],
                'contract_type': getattr(payload, 'contract_type', None),
                'employment_type': getattr(payload, 'employment_type', None),
                'expected_hours_period': getattr(payload, 'expected_hours_period', 'weekly'),
                'expected_hours': getattr(payload, 'expected_hours', None),
                'weekly_hours': getattr(payload, 'weekly_hours', None),
                'monthly_hours': getattr(payload, 'monthly_hours', None),
                'country': getattr(payload, 'country', None),
                'city': getattr(payload, 'city', None),
                'start_date': getattr(payload, 'start_date', None),
                'end_date': getattr(payload, 'end_date', None),
            },
        )
        user.roles.append(role)
        db.add(user)
        db.commit()
        db.refresh(user)
        log_audit(db, company_id=actor.company_id, actor_user_id=actor.id, action='user.registered', entity_type='user', entity_id=user.id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={'email': user.email, 'employee_code': user.employee_code, 'role': role.key})
        publish_event('auth.employee.registered', str(actor.company_id), {
            'user_id': str(user.id),
            'first_name': user.first_name,
            'last_name': user.last_name,
            'email': user.email,
            'employee_code': user.employee_code,
            'contract_type': (user.metadata_json or {}).get('contract_type'),
            'employment_type': (user.metadata_json or {}).get('employment_type'),
        })
        return user, (None if payload.password else generated_password)

    def import_employees(self, db: Session, *, actor: User, filename: str, raw_bytes: bytes, request_meta: dict):
        ext = filename.rsplit('.', 1)[-1].lower()
        if ext == 'csv':
            frame = pd.read_csv(io.BytesIO(raw_bytes))
        elif ext in {'xlsx', 'xls'}:
            frame = pd.read_excel(io.BytesIO(raw_bytes))
        else:
            bad_request('Only csv, xlsx, and xls files are supported')
        aliases = {
            'employee_code': {'employeecode', 'employeeid', 'code'},
            'external_employee_id': {'externalemployeeid', 'externalid'},
            'payroll_employee_id': {'payrollemployeeid', 'payrollid'},
            'first_name': {'firstname', 'first'},
            'last_name': {'lastname', 'last'},
            'email': {'email', 'emailaddress', 'workemail'},
            'phone': {'phone', 'phonenumber', 'mobile'},
            'role_key': {'rolekey', 'accessrole'},
            'job_title': {'jobtitle', 'title', 'position', 'role'},
            'department': {'department', 'team'},
            'manager_id': {'managerid', 'manager', 'reports_to', 'reportsto', 'supervisor'},
            'branch_id': {'branchid', 'branch'},
            'project_ids': {'projectids', 'projects', 'project'},
            'contract_type': {'contracttype', 'contract'},
            'employment_type': {'employmenttype', 'employment'},
            'expected_hours_period': {'expectedhoursperiod', 'hoursbasis', 'hourbasis', 'period'},
            'expected_hours': {'expectedhours', 'contracthours', 'weeklyhours', 'weekhours', 'hoursperweek', 'monthlyhours', 'monthhours', 'hourspermonth'},
            'weekly_hours': {'weeklyhours', 'weekhours', 'hoursperweek'},
            'monthly_hours': {'monthlyhours', 'monthhours', 'hourspermonth'},
            'country': {'country'},
            'city': {'city'},
            'start_date': {'startdate', 'joiningdate', 'hiredate'},
            'end_date': {'enddate', 'contractenddate', 'leavingdate'},
            'password': {'password', 'temppassword', 'temporarypassword'},
            'provider': {'provider'},
        }
        def column_key(value):
            normalized = ''.join(ch for ch in str(value).strip().lower() if ch.isalnum())
            for canonical, options in aliases.items():
                if normalized in options:
                    return canonical
            return None
        column_map = {column: column_key(column) for column in frame.columns}
        normalized_columns = {canonical for canonical in column_map.values() if canonical}
        missing_columns = {'first_name', 'last_name', 'email'} - normalized_columns
        if missing_columns:
            bad_request(f"Import file is missing required columns: {', '.join(sorted(missing_columns))}")
        results = []
        for row in frame.fillna('').to_dict(orient='records'):
            normalized_row = {canonical: row.get(original) for original, canonical in column_map.items() if canonical}
            class Payload: ...
            payload = Payload()
            payload.employee_code = normalized_row.get('employee_code') or None
            payload.external_employee_id = normalized_row.get('external_employee_id') or None
            payload.payroll_employee_id = normalized_row.get('payroll_employee_id') or None
            payload.first_name = normalized_row.get('first_name')
            payload.last_name = normalized_row.get('last_name')
            payload.email = normalized_row.get('email')
            payload.phone = normalized_row.get('phone') or None
            payload.job_title = normalized_row.get('job_title') or None
            payload.department = normalized_row.get('department') or None
            payload.manager_id = normalized_row.get('manager_id') or None
            payload.branch_id = normalized_row.get('branch_id') or None
            raw_project_ids = normalized_row.get('project_ids') or ''
            payload.project_ids = [item.strip() for item in str(raw_project_ids).replace(';', ',').split(',') if item.strip()]
            payload.contract_type = normalized_row.get('contract_type') or None
            payload.employment_type = normalized_row.get('employment_type') or None
            payload.expected_hours_period = normalized_row.get('expected_hours_period') or ('monthly' if normalized_row.get('monthly_hours') else 'weekly')
            payload.expected_hours = float(normalized_row.get('expected_hours')) if normalized_row.get('expected_hours') else None
            payload.weekly_hours = payload.expected_hours if payload.expected_hours_period == 'weekly' else None
            payload.monthly_hours = payload.expected_hours if payload.expected_hours_period == 'monthly' else None
            payload.country = normalized_row.get('country') or None
            payload.city = normalized_row.get('city') or None
            payload.start_date = normalized_row.get('start_date') or None
            payload.end_date = normalized_row.get('end_date') or None
            payload.password = normalized_row.get('password') or None
            payload.role_key = normalized_row.get('role_key') or 'employee'
            payload.provider = normalized_row.get('provider') or 'local'
            try:
                self.assert_assignable_employee_role(payload.role_key)
                payload.phone = normalize_phone_number(payload.phone, payload.country)
                existing = db.scalar(select(User).options(selectinload(User.roles)).where(User.company_id == actor.company_id, User.email == str(payload.email).lower(), User.status != 'deleted'))
                if existing:
                    role = self.resolve_role(db, actor=actor, role_key=payload.role_key)
                    if not role:
                        bad_request('Invalid role')
                    existing.employee_code = payload.employee_code or existing.employee_code
                    existing.external_employee_id = payload.external_employee_id or existing.external_employee_id
                    existing.payroll_employee_id = payload.payroll_employee_id or existing.payroll_employee_id
                    existing.first_name = payload.first_name or existing.first_name
                    existing.last_name = payload.last_name or existing.last_name
                    existing.phone = payload.phone
                    if payload.password:
                        existing.password_hash = hash_password(payload.password)
                        existing.provider = 'local'
                    existing.roles = [role]
                    branch = self.get_branch(actor=actor, branch_id=payload.branch_id)
                    project_rows = self.resolve_projects(actor=actor, project_ids=payload.project_ids)
                    manager = self.resolve_manager(db, actor=actor, manager_id=payload.manager_id)
                    if manager and manager.id == existing.id:
                        bad_request('Employee cannot be their own manager')
                    existing.metadata_json = {
                        **(existing.metadata_json or {}),
                        'job_title': payload.job_title,
                        'department': payload.department,
                        'manager_id': str(manager.id) if manager else None,
                        'manager_name': f'{manager.first_name or ""} {manager.last_name or ""}'.strip() if manager else None,
                        'branch_id': branch.get('id') if branch else None,
                        'branch_name': branch.get('name') if branch else None,
                        'project_ids': [item.get('id') for item in project_rows],
                        'project_names': [item.get('name') for item in project_rows],
                        'contract_type': payload.contract_type,
                        'employment_type': payload.employment_type,
                        'expected_hours_period': payload.expected_hours_period,
                        'expected_hours': payload.expected_hours,
                        'weekly_hours': payload.weekly_hours,
                        'monthly_hours': payload.monthly_hours,
                        'country': payload.country,
                        'city': payload.city,
                        'start_date': payload.start_date,
                        'end_date': payload.end_date,
                    }
                    db.add(existing)
                    db.commit()
                    db.refresh(existing)
                    log_audit(db, company_id=actor.company_id, actor_user_id=actor.id, action='user.import_updated', entity_type='user', entity_id=existing.id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={'email': existing.email, 'employee_code': existing.employee_code, 'role': role.key})
                    results.append({'email': existing.email, 'status': 'updated', 'user_id': str(existing.id), 'employee_code': existing.employee_code})
                    continue
                user, generated_password = self.register_employee(db, actor=actor, payload=payload, request_meta=request_meta)
                results.append({'email': user.email, 'status': 'created', 'user_id': str(user.id), 'employee_code': user.employee_code, 'generated_password': generated_password})
            except HTTPException as exc:
                db.rollback()
                status = 'skipped' if exc.status_code == 409 else 'failed'
                results.append({'email': payload.email, 'status': status, 'reason': exc.detail})
            except Exception as exc:
                db.rollback()
                results.append({'email': payload.email, 'status': 'failed', 'reason': str(exc)})
        return results

    def issue_verification_token(self, db: Session, *, user: User, token_type: str):
        raw = random_secret(32)
        expires = datetime.now(timezone.utc) + (timedelta(minutes=settings.PASSWORD_RESET_EXPIRE_MINUTES) if token_type == 'password_reset' else timedelta(hours=settings.EMAIL_VERIFICATION_EXPIRE_HOURS))
        item = VerificationToken(user_id=user.id, company_id=user.company_id, type=token_type, token_hash=token_hash(raw), expires_at=expires, metadata_json={'email': user.email})
        db.add(item)
        db.commit()
        return raw

    def _development_delivery_payload(self, *, token: str, path: str, delivered: bool, error: str | None = None):
        payload = {'sent': delivered}
        if error and settings.APP_ENV == 'development':
            payload['delivery_error'] = error
        if not delivered and settings.APP_ENV == 'development':
            payload['development_link'] = f"{settings.FRONTEND_BASE_URL.rstrip('/')}{path}?token={token}"
        return payload

    def send_email_verification(self, db: Session, *, user: User, request_meta: dict):
        token = self.issue_verification_token(db, user=user, token_type='email_verification')
        delivered = self.publish_email_event(user=user, template_key='email_verification', metadata={'token': token})
        error = None if delivered else 'Notification event was not accepted'
        log_audit(db, company_id=user.company_id, actor_user_id=user.id, action='auth.email_verification_requested', entity_type='user', entity_id=user.id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={'delivered': delivered, 'delivery_error': error})
        return self._development_delivery_payload(token=token, path='/verify-email', delivered=delivered, error=error)

    def request_email_verification(self, db: Session, *, actor: User, request_meta: dict):
        if actor.email_verified:
            return {'sent': False, 'already_verified': True}
        return self.send_email_verification(db, user=actor, request_meta=request_meta)

    def resend_email_verification_from_token(self, db: Session, *, token: str, request_meta: dict):
        record = db.scalar(select(VerificationToken).where(VerificationToken.token_hash == token_hash(token), VerificationToken.type == 'email_verification'))
        if not record:
            bad_request('Verification link is invalid. Please sign in to request a fresh verification email.')
        user = db.scalar(select(User).where(User.id == record.user_id))
        if not user:
            bad_request('Verification link is invalid. Please sign in to request a fresh verification email.')
        if user.email_verified:
            return {'sent': False, 'already_verified': True}
        record.consumed_at = record.consumed_at or datetime.now(timezone.utc)
        db.add(record)
        db.commit()
        return self.send_email_verification(db, user=user, request_meta=request_meta)

    def verify_email(self, db: Session, *, token: str, request_meta: dict):
        record = db.scalar(select(VerificationToken).where(VerificationToken.token_hash == token_hash(token), VerificationToken.type == 'email_verification', VerificationToken.consumed_at.is_(None)))
        if not record or self.is_expired(record.expires_at):
            bad_request('Invalid or expired verification token')
        user = db.scalar(select(User).where(User.id == record.user_id))
        record.consumed_at = datetime.now(timezone.utc)
        user.email_verified = True
        db.add(record)
        db.add(user)
        db.commit()
        log_audit(db, company_id=user.company_id, actor_user_id=user.id, action='auth.email_verified', entity_type='user', entity_id=user.id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={})

    def forgot_password(self, db: Session, *, email: str, request_meta: dict):
        user = db.scalar(select(User).where(User.email == email.lower()))
        if not user:
            return {'sent': True}
        if not settings.ALLOW_EMAIL_LOGIN_FALLBACK and (user.provider != 'local' or self.user_has_sso_link(user)):
            log_audit(db, company_id=user.company_id, actor_user_id=user.id, action='auth.password_reset_skipped_sso', entity_type='user', entity_id=user.id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={'provider': user.provider})
            return {'sent': True}
        token = self.issue_verification_token(db, user=user, token_type='password_reset')
        delivered = self.publish_email_event(user=user, template_key='password_reset', metadata={'token': token})
        error = None if delivered else 'Notification event was not accepted'
        log_audit(db, company_id=user.company_id, actor_user_id=user.id, action='auth.password_reset_requested', entity_type='user', entity_id=user.id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={'delivered': delivered, 'delivery_error': error})
        if settings.APP_ENV == 'development':
            return self._development_delivery_payload(token=token, path='/reset-password', delivered=delivered, error=error)
        return {'sent': True}

    def reset_password(self, db: Session, *, token: str, password: str, request_meta: dict):
        record = db.scalar(select(VerificationToken).where(VerificationToken.token_hash == token_hash(token), VerificationToken.type == 'password_reset', VerificationToken.consumed_at.is_(None)))
        if not record or self.is_expired(record.expires_at):
            bad_request('Invalid or expired reset token')
        user = db.scalar(select(User).where(User.id == record.user_id))
        if not settings.ALLOW_EMAIL_LOGIN_FALLBACK and (user.provider != 'local' or self.user_has_sso_link(user)):
            bad_request('Password reset is disabled for SSO accounts')
        record.consumed_at = datetime.now(timezone.utc)
        user.password_hash = hash_password(password)
        user.status = 'active'
        user.login_attempts = 0
        user.locked_until = None
        db.add(record)
        db.add(user)
        db.commit()
        log_audit(db, company_id=user.company_id, actor_user_id=user.id, action='auth.password_reset_completed', entity_type='user', entity_id=user.id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={})

    def change_password(self, db: Session, *, actor: User, payload, current_refresh_token: str | None, request_meta: dict):
        if not actor.password_hash:
            bad_request('No local password is set. Use forgot password first.')
        if not verify_password(payload.old_password, actor.password_hash):
            bad_request('Current password is incorrect')
        if verify_password(payload.new_password, actor.password_hash):
            bad_request('New password must be different from current password')
        policy = self.get_security_policy(actor=actor)
        if len(payload.new_password) < policy['password_min_length']:
            bad_request(f"Password must be at least {policy['password_min_length']} characters")
        actor.password_hash = hash_password(payload.new_password)
        actor.login_attempts = 0
        actor.locked_until = None
        db.add(actor)
        if payload.revoke_other_sessions:
            current_hash = token_hash(current_refresh_token) if current_refresh_token else None
            sessions = db.execute(select(RefreshSession).where(RefreshSession.user_id == actor.id, RefreshSession.revoked_at.is_(None))).scalars().all()
            for session in sessions:
                if current_hash and session.token_hash == current_hash:
                    continue
                session.revoked_at = datetime.now(timezone.utc)
                db.add(session)
        db.commit()
        log_audit(db, company_id=actor.company_id, actor_user_id=actor.id, action='auth.password_changed', entity_type='user', entity_id=actor.id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={})
        publish_event('auth.user.password_changed', str(actor.company_id), {'user_id': str(actor.id)})
        self.send_security_notification_if_enabled(actor, title='Password changed', preview='Your Attendio password was changed successfully.')

    def list_sessions(self, db: Session, *, actor: User):
        return db.execute(select(RefreshSession).where(RefreshSession.user_id == actor.id).order_by(RefreshSession.created_at.desc())).scalars().all()

    def revoke_session(self, db: Session, *, actor: User, session_id: uuid.UUID):
        session = db.scalar(select(RefreshSession).where(RefreshSession.id == session_id, RefreshSession.user_id == actor.id, RefreshSession.revoked_at.is_(None)))
        if not session:
            not_found('Session not found')
        session.revoked_at = datetime.now(timezone.utc)
        db.add(session)
        db.commit()

    def revoke_all_sessions(self, db: Session, *, actor: User):
        sessions = db.execute(select(RefreshSession).where(RefreshSession.user_id == actor.id, RefreshSession.revoked_at.is_(None))).scalars().all()
        for session in sessions:
            session.revoked_at = datetime.now(timezone.utc)
            db.add(session)
        db.commit()

    def create_api_key(self, db: Session, *, actor: User, name: str, scopes: list[str], request_meta: dict):
        secret = random_secret(32)
        value = f'ak_{secret}'
        record = ApiKey(company_id=actor.company_id, created_by_user_id=actor.id, name=name, scopes=scopes, prefix=value[:12], key_hash=token_hash(value))
        db.add(record)
        db.commit()
        db.refresh(record)
        log_audit(db, company_id=actor.company_id, actor_user_id=actor.id, action='api_key.created', entity_type='api_key', entity_id=record.id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={'name': name, 'scopes': scopes})
        return value, record

    def list_api_keys(self, db: Session, *, actor: User):
        return db.execute(select(ApiKey).where(ApiKey.company_id == actor.company_id).order_by(ApiKey.created_at.desc())).scalars().all()

    def revoke_api_key(self, db: Session, *, actor: User, api_key_id: uuid.UUID, request_meta: dict):
        record = db.scalar(select(ApiKey).where(ApiKey.id == api_key_id, ApiKey.company_id == actor.company_id, ApiKey.revoked_at.is_(None)))
        if not record:
            not_found('API key not found')
        record.revoked_at = datetime.now(timezone.utc)
        db.add(record)
        db.commit()
        log_audit(db, company_id=actor.company_id, actor_user_id=actor.id, action='api_key.revoked', entity_type='api_key', entity_id=record.id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={})

    def impersonate(self, db: Session, *, actor: User, target_user_id: uuid.UUID, request_meta: dict):
        perms = {perm.key for role in actor.roles for perm in role.permissions}
        if 'users.impersonate' not in perms and 'settings.tenant' not in perms:
            forbidden('Insufficient permissions')
        target = self.load_user_for_session(db, user_id=target_user_id)
        if not target or target.company_id != actor.company_id:
            not_found('Target user not found')
        payload = self.issue_payload(target, target.company)
        payload['impersonated_by'] = str(actor.id)
        access = create_access_token(payload)
        refresh = create_refresh_token(payload)
        db.add(RefreshSession(user_id=target.id, token_hash=token_hash(refresh), expires_at=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS), last_used_at=datetime.now(timezone.utc), ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), device_info={'user_agent': request_meta.get('user_agent')}))
        db.commit()
        log_audit(db, company_id=actor.company_id, actor_user_id=actor.id, action='auth.impersonation_started', entity_type='user', entity_id=target.id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={'target_email': target.email})
        return {'target': target, 'company': target.company, 'access_token': access, 'refresh_token': refresh}

    def set_kiosk_pin(self, db: Session, *, actor: User, target_user_id: uuid.UUID, pin: str, request_meta: dict):
        target = db.scalar(select(User).where(User.id == target_user_id, User.company_id == actor.company_id))
        if not target:
            not_found('Target user not found')
        metadata = dict(target.metadata_json or {})
        metadata['kiosk_pin_hash'] = token_hash(pin)
        metadata['kiosk_pin_updated_at'] = datetime.now(timezone.utc).isoformat()
        target.metadata_json = metadata
        db.add(target)
        db.commit()
        log_audit(db, company_id=actor.company_id, actor_user_id=actor.id, action='kiosk.pin_set', entity_type='user', entity_id=target.id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={})

    def kiosk_login(self, db: Session, *, actor_tenant: Company | None, employee_code: str, pin: str, request_meta: dict):
        if not actor_tenant:
            matches = db.execute(
                select(User)
                .join(Company, Company.id == User.company_id)
                .where(User.employee_code == employee_code, Company.status == 'active')
                .limit(2)
            ).scalars().all()
            if len(matches) > 1:
                conflict('This employee code exists in more than one company. Open the kiosk from your tenant domain.')
            if not matches:
                unauthorized('Invalid kiosk credentials')
            actor_tenant = db.scalar(select(Company).where(Company.id == matches[0].company_id, Company.status == 'active'))
            if not actor_tenant:
                unauthorized('Invalid kiosk credentials')
        user = self.load_user_for_session(db, user_id=(db.scalar(select(User.id).where(User.company_id == actor_tenant.id, User.employee_code == employee_code))))
        if not user:
            unauthorized('Invalid kiosk credentials')
        pin_hash = (user.metadata_json or {}).get('kiosk_pin_hash')
        if not pin_hash or pin_hash != token_hash(pin):
            unauthorized('Invalid kiosk credentials')
        payload = self.issue_payload(user, actor_tenant)
        payload['kiosk'] = True
        access = create_access_token(payload)
        refresh = create_refresh_token(payload)
        db.add(RefreshSession(user_id=user.id, token_hash=token_hash(refresh), expires_at=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS), last_used_at=datetime.now(timezone.utc), ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), device_info={'user_agent': request_meta.get('user_agent')}))
        db.commit()
        log_audit(db, company_id=actor_tenant.id, actor_user_id=user.id, action='kiosk.login', entity_type='session', entity_id=user.id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={'employee_code': employee_code})
        return {'user': user, 'company': actor_tenant, 'access_token': access, 'refresh_token': refresh, 'redirect_url': f'{self.build_tenant_base_url(actor_tenant)}/kiosk'}

    def list_permissions(self, db: Session):
        return db.execute(select(Permission).order_by(Permission.key.asc())).scalars().all()

    def list_roles(self, db: Session, *, actor: User):
        return db.execute(select(Role).options(selectinload(Role.permissions)).where(or_(Role.company_id.is_(None), Role.company_id == actor.company_id)).order_by(Role.key.asc())).scalars().all()

    def create_role(self, db: Session, *, actor: User, key: str, name: str, description: str | None, permission_keys: list[str], request_meta: dict):
        if key == 'company_owner':
            bad_request('Company owner is reserved for workspace ownership')
        existing = db.scalar(select(Role).where(Role.key == key, Role.company_id == actor.company_id))
        if existing:
            conflict('Role key already exists for this company')
        perms = db.execute(select(Permission).where(Permission.key.in_(permission_keys))).scalars().all() if permission_keys else []
        role = Role(key=key, name=name, description=description, company_id=actor.company_id, is_system=False)
        role.permissions = perms
        db.add(role)
        db.commit()
        db.refresh(role)
        log_audit(db, company_id=actor.company_id, actor_user_id=actor.id, action='role.created', entity_type='role', entity_id=role.id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={'key': key, 'permission_keys': permission_keys})
        return role

    def update_role(self, db: Session, *, actor: User, role_id: str, name: str | None, description: str | None, permission_keys: list[str] | None, request_meta: dict):
        role = db.get(Role, uuid.UUID(str(role_id)))
        if not role or role.company_id != actor.company_id:
            not_found('Role not found')
        if role.key == 'company_owner':
            bad_request('Company owner role cannot be edited')
        if name is not None:
            role.name = name
        if description is not None:
            role.description = description
        if permission_keys is not None:
            role.permissions = db.execute(select(Permission).where(Permission.key.in_(permission_keys))).scalars().all() if permission_keys else []
        db.add(role)
        db.commit()
        db.refresh(role)
        log_audit(db, company_id=actor.company_id, actor_user_id=actor.id, action='role.updated', entity_type='role', entity_id=role.id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={'key': role.key, 'permission_keys': permission_keys})
        return role

    def assign_user_roles(self, db: Session, *, actor: User, user_id: str, role_keys: list[str], request_meta: dict):
        user = self.get_employee(db, actor=actor, user_id=uuid.UUID(str(user_id)))
        metadata = dict(actor.company.metadata_json or {})
        owner_user_id = str(metadata.get('owner_user_id') or '')
        if 'company_owner' in role_keys and str(user.id) != owner_user_id:
            bad_request('Company owner can only belong to the workspace owner')
        roles = []
        for key in dict.fromkeys(role_keys):
            if key == 'company_owner' and str(user.id) != owner_user_id:
                continue
            role = self.resolve_role(db, actor=actor, role_key=key)
            if not role:
                bad_request(f'Invalid role: {key}')
            roles.append(role)
        if not roles:
            role = db.scalar(select(Role).where(Role.key == 'employee', Role.company_id.is_(None)))
            if role:
                roles.append(role)
        user.roles = roles
        db.add(user)
        db.commit()
        db.refresh(user)
        log_audit(db, company_id=actor.company_id, actor_user_id=actor.id, action='user.roles_assigned', entity_type='user', entity_id=user.id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={'role_keys': [role.key for role in roles]})
        return user

    def set_user_permission_overrides(self, db: Session, *, actor: User, user_id: str, allow: list[str], deny: list[str], request_meta: dict):
        user = self.get_employee(db, actor=actor, user_id=uuid.UUID(str(user_id)))
        db.query(UserPermissionOverride).filter(UserPermissionOverride.user_id == user.id).delete(synchronize_session=False)
        allow_set = set(allow or [])
        deny_set = set(deny or [])
        permissions = db.execute(select(Permission).where(Permission.key.in_(allow_set | deny_set))).scalars().all()
        permission_by_key = {item.key: item for item in permissions}
        missing = sorted((allow_set | deny_set) - set(permission_by_key))
        if missing:
            bad_request(f'Invalid permission(s): {", ".join(missing)}')
        for key in sorted(allow_set - deny_set):
            db.add(UserPermissionOverride(user_id=user.id, permission_id=permission_by_key[key].id, effect='allow'))
        for key in sorted(deny_set):
            db.add(UserPermissionOverride(user_id=user.id, permission_id=permission_by_key[key].id, effect='deny'))
        db.commit()
        log_audit(db, company_id=actor.company_id, actor_user_id=actor.id, action='user.permission_overrides_set', entity_type='user', entity_id=user.id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={'allow': sorted(allow_set - deny_set), 'deny': sorted(deny_set)})
        return {'allow': sorted(allow_set - deny_set), 'deny': sorted(deny_set), 'effective_permissions': self.permission_keys_for_user(db, user)}

    def list_employees(self, db: Session, *, actor: User, limit: int | None = None, offset: int = 0, q: str | None = None, branch_id: str | None = None, project_id: str | None = None):
        offset = max(0, int(offset or 0))
        stmt = select(User).where(User.company_id == actor.company_id, User.status != 'deleted')
        if q:
            needle = f"%{q.strip()}%"
            stmt = stmt.where(or_(
                User.employee_code.ilike(needle),
                User.email.ilike(needle),
                User.first_name.ilike(needle),
                User.last_name.ilike(needle),
            ))
        if branch_id:
            stmt = stmt.where(User.metadata_json['branch_id'].as_string() == str(branch_id))
        if project_id:
            stmt = stmt.where(User.metadata_json['project_ids'].contains([str(project_id)]))
        total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        stmt = stmt.options(selectinload(User.roles).selectinload(Role.permissions)).order_by(User.created_at.desc())
        if limit is not None:
            limit = max(1, min(int(limit or 50), 200))
            stmt = stmt.offset(offset).limit(limit)
        items = db.execute(stmt).scalars().all()
        return items, total

    def direct_and_indirect_report_ids(self, db: Session, *, actor: User) -> set[str]:
        rows = db.execute(select(User.id, User.metadata_json).where(User.company_id == actor.company_id, User.status != 'deleted')).all()
        children = {}
        for user_id, metadata in rows:
            manager_id = str((metadata or {}).get('manager_id') or '')
            if manager_id:
                children.setdefault(manager_id, set()).add(str(user_id))
        visible = {str(actor.id)}
        stack = list(children.get(str(actor.id), set()))
        while stack:
            next_id = stack.pop()
            if next_id in visible:
                continue
            visible.add(next_id)
            stack.extend(children.get(next_id, set()))
        return visible

    def list_organization_people(self, db: Session, *, actor: User, q: str | None = None, project_id: str | None = None):
        permissions = set(self.permission_keys_for_user(db, actor))
        stmt = select(User).options(selectinload(User.roles).selectinload(Role.permissions)).where(User.company_id == actor.company_id, User.status != 'deleted')
        if 'org.view_company' not in permissions and 'settings.tenant' not in permissions and 'reports.company' not in permissions:
            allowed_ids = self.direct_and_indirect_report_ids(db, actor=actor) if 'org.view_team' in permissions else {str(actor.id)}
            actor_metadata = actor.metadata_json or {}
            actor_branch_id = str(actor_metadata.get('branch_id') or '')
            actor_project_ids = {str(item) for item in (actor_metadata.get('project_ids') or []) if item}
            if actor_branch_id or actor_project_ids:
                peers = db.execute(
                    select(User.id, User.metadata_json).where(User.company_id == actor.company_id, User.status != 'deleted')
                ).all()
                for peer_id, peer_metadata in peers:
                    peer_metadata = peer_metadata or {}
                    peer_branch_id = str(peer_metadata.get('branch_id') or '')
                    peer_project_ids = {str(item) for item in (peer_metadata.get('project_ids') or []) if item}
                    if (actor_branch_id and peer_branch_id == actor_branch_id) or (actor_project_ids and actor_project_ids.intersection(peer_project_ids)):
                        allowed_ids.add(str(peer_id))
            manager_id = str(actor_metadata.get('manager_id') or '')
            guard = {str(actor.id)}
            while manager_id and manager_id not in guard:
                try:
                    manager_uuid = uuid.UUID(manager_id)
                except ValueError:
                    break
                manager = db.scalar(select(User).where(User.company_id == actor.company_id, User.id == manager_uuid, User.status != 'deleted'))
                if not manager:
                    break
                allowed_ids.add(str(manager.id))
                guard.add(manager_id)
                manager_id = str((manager.metadata_json or {}).get('manager_id') or '')
            stmt = stmt.where(User.id.in_([uuid.UUID(item) for item in allowed_ids]))
        if q:
            needle = f"%{q.strip()}%"
            stmt = stmt.where(or_(User.employee_code.ilike(needle), User.email.ilike(needle), User.first_name.ilike(needle), User.last_name.ilike(needle)))
        items = db.execute(stmt.order_by(User.created_at.asc())).scalars().all()
        if project_id:
            items = [item for item in items if str(project_id) in [str(value) for value in ((item.metadata_json or {}).get('project_ids') or [])]]
        return items

    def get_employee(self, db: Session, *, actor: User, user_id: uuid.UUID):
        stmt = select(User).options(selectinload(User.roles).selectinload(Role.permissions)).where(User.company_id == actor.company_id, User.id == user_id)
        user = db.execute(stmt).scalar_one_or_none()
        if not user:
            not_found('Employee not found')
        return user

    def update_employee(self, db: Session, *, actor: User, user_id: uuid.UUID, payload, request_meta: dict):
        user = self.get_employee(db, actor=actor, user_id=user_id)
        data = payload.model_dump(exclude_unset=True)
        role_key = data.pop('role_key', None)
        metadata_keys = {'job_title', 'department', 'manager_id', 'branch_id', 'project_ids', 'contract_type', 'employment_type', 'expected_hours_period', 'expected_hours', 'weekly_hours', 'monthly_hours', 'country', 'city', 'start_date', 'end_date'}
        metadata = dict(user.metadata_json or {})
        for key in list(data.keys()):
            if key in metadata_keys:
                value = data.pop(key)
                if key == 'branch_id':
                    branch = self.get_branch(actor=actor, branch_id=value)
                    metadata['branch_id'] = branch.get('id') if branch else None
                    metadata['branch_name'] = branch.get('name') if branch else None
                elif key == 'project_ids':
                    project_rows = self.resolve_projects(actor=actor, project_ids=value)
                    metadata['project_ids'] = [item.get('id') for item in project_rows]
                    metadata['project_names'] = [item.get('name') for item in project_rows]
                elif key == 'manager_id':
                    manager = self.resolve_manager(db, actor=actor, manager_id=value)
                    if manager and manager.id == user.id:
                        bad_request('Employee cannot be their own manager')
                    metadata['manager_id'] = str(manager.id) if manager else None
                    metadata['manager_name'] = f'{manager.first_name or ""} {manager.last_name or ""}'.strip() if manager else None
                else:
                    metadata[key] = value
        if 'email' in data and data['email']:
            data['email'] = data['email'].lower()
        if 'phone' in data:
            data['phone'] = normalize_phone_number(data['phone'], metadata.get('country'))
        elif 'country' in metadata and user.phone:
            normalize_phone_number(user.phone, metadata.get('country'))
        for key, value in data.items():
            setattr(user, key, value)
        if role_key:
            self.assert_assignable_employee_role(role_key)
            role = self.resolve_role(db, actor=actor, role_key=role_key)
            if not role:
                bad_request('Invalid role')
            user.roles = [role]
        user.metadata_json = metadata
        db.add(user)
        db.commit()
        db.refresh(user)
        log_audit(db, company_id=actor.company_id, actor_user_id=actor.id, action='user.updated', entity_type='user', entity_id=user.id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={'email': user.email})
        return user

    def update_employee_status(self, db: Session, *, actor: User, user_id: uuid.UUID, status: str, request_meta: dict):
        user = self.get_employee(db, actor=actor, user_id=user_id)
        if str(user.id) == str(actor.id) and status != 'active':
            bad_request('You cannot deactivate your own account')
        user.status = status
        db.add(user)
        db.commit()
        db.refresh(user)
        log_audit(db, company_id=actor.company_id, actor_user_id=actor.id, action='user.status_updated', entity_type='user', entity_id=user.id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={'status': status})
        return user

    def delete_employee(self, db: Session, *, actor: User, user_id: uuid.UUID, request_meta: dict):
        user = self.get_employee(db, actor=actor, user_id=user_id)
        if str(user.id) == str(actor.id):
            bad_request('You cannot delete your own account')
        user.status = 'deleted'
        db.add(user)
        db.commit()
        log_audit(db, company_id=actor.company_id, actor_user_id=actor.id, action='user.deleted', entity_type='user', entity_id=user.id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={'email': user.email})

    def list_audit_logs(self, db: Session, *, actor: User):
        from app.models.audit_log import AuditLog
        return db.execute(select(AuditLog).where(AuditLog.company_id == actor.company_id).order_by(AuditLog.created_at.desc()).limit(200)).scalars().all()

    def list_own_activity(self, db: Session, *, actor: User):
        from app.models.audit_log import AuditLog
        return db.execute(
            select(AuditLog)
            .where(AuditLog.company_id == actor.company_id, AuditLog.actor_user_id == actor.id)
            .order_by(AuditLog.created_at.desc())
            .limit(100)
        ).scalars().all()

    def get_security_policy(self, *, actor: User):
        metadata = actor.company.metadata_json or {}
        return {
            'password_min_length': 12,
            'require_mfa': False,
            'session_ttl_days': 7,
            'mfa_grace_period_days': 14,
            **(metadata.get('security_policy') or {}),
        }

    def update_security_policy(self, db: Session, *, actor: User, payload, request_meta: dict):
        metadata = dict(actor.company.metadata_json or {})
        previous = metadata.get('security_policy') or {}
        next_policy = payload.model_dump()
        if next_policy['require_mfa'] and not previous.get('require_mfa'):
            next_policy['mfa_enforcement_at'] = (datetime.now(timezone.utc) + timedelta(days=next_policy['mfa_grace_period_days'])).isoformat()
        elif previous.get('mfa_enforcement_at'):
            next_policy['mfa_enforcement_at'] = previous['mfa_enforcement_at']
        metadata['security_policy'] = next_policy
        actor.company.metadata_json = metadata
        db.add(actor.company)
        db.commit()
        log_audit(db, company_id=actor.company_id, actor_user_id=actor.id, action='company.security_policy_updated', entity_type='company', entity_id=actor.company_id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload=metadata['security_policy'])
        return metadata['security_policy']

    def send_test_email(self, db: Session, *, actor: User, request_meta: dict):
        self.create_notification(None, user=actor, kind='test', title='Email delivery test', body='Your Attendio email delivery configuration is working.', metadata={}, template_key='test', channels=['email'], preference_key='test')
        log_audit(db, company_id=actor.company_id, actor_user_id=actor.id, action='auth.test_email_sent', entity_type='user', entity_id=actor.id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={'delivered': True})
        return {'queued': True}

    def send_security_notification_if_enabled(self, actor: User, *, title: str, preview: str):
        self.create_notification(None, user=actor, kind='security', title=title, body=preview, template_key='security', channels=['in_app', 'email'], preference_key='security')

    def create_notification(self, db: Session | None, *, user: User, kind: str, title: str, body: str, metadata: dict | None = None, template_key: str | None = None, channels: list[str] | None = None, preference_key: str = 'security'):
        return publish_event('notification.requested', str(user.company_id), {'user_id': str(user.id), 'email': user.email, 'first_name': user.first_name, 'kind': kind, 'title': title, 'body': body, 'metadata': {**(metadata or {}), 'email': user.email, 'first_name': user.first_name, 'template_key': template_key}, 'template_key': template_key, 'channels': channels or ['in_app'], 'preference_key': preference_key, 'preferences': (user.metadata_json or {}).get('notification_preferences') or {}})

    def publish_email_event(self, *, user: User, template_key: str, metadata: dict):
        return self.create_notification(None, user=user, kind=template_key, title=template_key, body='', metadata=metadata, template_key=template_key, channels=['email'], preference_key=template_key)

    def list_users_missing_mfa(self, db: Session, *, actor: User, query: str = '', limit: int = 20, offset: int = 0):
        stmt = select(User).where(User.company_id == actor.company_id, User.status == 'active', User.mfa_enabled.is_(False))
        if query:
            pattern = f'%{query.lower()}%'
            stmt = stmt.where(or_(func.lower(User.first_name).like(pattern), func.lower(User.last_name).like(pattern), func.lower(User.email).like(pattern)))
        total = db.scalar(select(func.count()).select_from(stmt.subquery()))
        items = db.execute(stmt.order_by(User.first_name.asc(), User.last_name.asc()).offset(offset).limit(limit)).scalars().all()
        return items, total

    def send_mfa_reminders(self, db: Session, *, actor: User, user_ids: list[uuid.UUID], send_to_all_missing: bool, request_meta: dict):
        stmt = select(User).where(User.company_id == actor.company_id, User.status == 'active', User.mfa_enabled.is_(False))
        if not send_to_all_missing:
            stmt = stmt.where(User.id.in_(user_ids))
        users = db.execute(stmt).scalars().all()
        deadline = self.get_security_policy(actor=actor).get('mfa_enforcement_at')
        sent = []
        failed = []
        for user in users:
            accepted = self.create_notification(db, user=user, kind='mfa', title='Set up MFA', body='Your company asks you to protect your account with multi-factor authentication.', metadata={'deadline': deadline}, template_key='mfa_reminder', channels=['in_app', 'email'], preference_key='mfa_reminders')
            (sent if accepted else failed).append(str(user.id))
        self.create_notification(db, user=actor, kind='mfa_admin', title='MFA reminders queued', body=f'{len(sent)} employee reminder(s) queued successfully.', channels=['in_app'], preference_key='security')
        log_audit(db, company_id=actor.company_id, actor_user_id=actor.id, action='company.mfa_reminders_sent', entity_type='company', entity_id=actor.company_id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={'sent_count': len(sent), 'failed_count': len(failed), 'send_to_all_missing': send_to_all_missing, 'recipient_ids': sent})
        return {'sent_count': len(sent), 'failed_count': len(failed), 'failed': failed}

    def send_scheduled_mfa_reminders(self, db: Session):
        companies = db.execute(select(Company)).scalars().all()
        for company in companies:
            policy = (company.metadata_json or {}).get('security_policy') or {}
            deadline = policy.get('mfa_enforcement_at')
            if not policy.get('require_mfa') or not deadline:
                continue
            days_left = (datetime.fromisoformat(deadline) - datetime.now(timezone.utc)).days
            if days_left not in {7, 3, 1}:
                continue
            users = db.execute(select(User).where(User.company_id == company.id, User.status == 'active', User.mfa_enabled.is_(False))).scalars().all()
            for user in users:
                marker = f'mfa-reminder-{days_left}'
                self.create_notification(db, user=user, kind=marker, title='MFA deadline approaching', body=f'Set up MFA before {deadline}.', metadata={'deadline': deadline}, template_key='mfa_reminder', channels=['in_app', 'email'], preference_key='mfa_reminders')

    def list_mfa_reminder_history(self, db: Session, *, actor: User):
        from app.models.audit_log import AuditLog
        cleared_at = db.scalar(
            select(func.max(AuditLog.created_at))
            .where(
                AuditLog.company_id == actor.company_id,
                AuditLog.actor_user_id == actor.id,
                AuditLog.action == 'company.mfa_reminder_history_cleared',
            )
        )
        filters = [AuditLog.company_id == actor.company_id, AuditLog.action == 'company.mfa_reminders_sent']
        if cleared_at:
            filters.append(AuditLog.created_at > cleared_at)
        return db.execute(
            select(AuditLog)
            .where(*filters)
            .order_by(AuditLog.created_at.desc())
            .limit(50)
        ).scalars().all()

    def clear_mfa_reminder_history(self, db: Session, *, actor: User, request_meta: dict):
        log_audit(db, company_id=actor.company_id, actor_user_id=actor.id, action='company.mfa_reminder_history_cleared', entity_type='company', entity_id=actor.company_id, ip_address=request_meta.get('ip_address'), user_agent=request_meta.get('user_agent'), payload={})
        return {'cleared': True}

service = AuthService()
