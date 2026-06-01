import uuid
from datetime import datetime
from sqlalchemy import DateTime, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from app.db.session import Base


class NotificationDeliveryView(Base):
    __tablename__ = "notification_delivery_views"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    cleared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
