import uuid
from sqlalchemy import String, Integer, JSON, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class Company(Base):
    __tablename__ = 'companies'

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    domain: Mapped[str | None] = mapped_column(String(150), unique=True)
    status: Mapped[str] = mapped_column(String(20), default='active')
    employee_sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    employee_code_prefix: Mapped[str] = mapped_column(String(20), default='EMP', nullable=False)
    metadata_json: Mapped[dict] = mapped_column('metadata', JSON, default=dict)

    users = relationship('User', back_populates='company')
