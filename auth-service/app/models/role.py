import uuid
from sqlalchemy import String, Boolean, ForeignKey, Uuid, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.associations import RolePermission, UserRole


class Role(Base):
    __tablename__ = 'roles'
    __table_args__ = (UniqueConstraint('key', 'company_id', name='roles_key_company_uq'),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))
    company_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey('companies.id', ondelete='CASCADE'))
    is_system: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    permissions = relationship('Permission', secondary=RolePermission.__table__, back_populates='roles')
    users = relationship('User', secondary=UserRole.__table__, back_populates='roles')
