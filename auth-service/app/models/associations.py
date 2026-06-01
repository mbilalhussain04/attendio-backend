import uuid
from sqlalchemy import ForeignKey, String, Uuid, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class UserRole(Base):
    __tablename__ = 'user_roles'
    __table_args__ = (UniqueConstraint('user_id', 'role_id', name='user_role_uq'),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    role_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('roles.id', ondelete='CASCADE'), nullable=False)


class RolePermission(Base):
    __tablename__ = 'role_permissions'
    __table_args__ = (UniqueConstraint('role_id', 'permission_id', name='role_permission_uq'),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    role_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('roles.id', ondelete='CASCADE'), nullable=False)
    permission_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('permissions.id', ondelete='CASCADE'), nullable=False)


class UserPermissionOverride(Base):
    __tablename__ = 'user_permission_overrides'
    __table_args__ = (UniqueConstraint('user_id', 'permission_id', name='user_permission_override_uq'),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    permission_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('permissions.id', ondelete='CASCADE'), nullable=False)
    effect: Mapped[str] = mapped_column(String(10), default='allow', nullable=False)
