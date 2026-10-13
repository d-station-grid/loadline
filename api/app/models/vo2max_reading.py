from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Vo2maxReading(Base):
    """Apple Watch が推定した VO2max の 1 回分。Health Auto Export の metrics から届く。"""

    __tablename__ = "vo2max_readings"
    # 同じ測定が何度届いても、二重に数えない
    __table_args__ = (UniqueConstraint("user_id", "measured_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # 小数 1 桁。例 45.7（ml/kg/min）
    value: Mapped[Decimal] = mapped_column(Numeric(4, 1))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
