from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Column, Numeric, UniqueConstraint
from sqlmodel import Field, SQLModel


class UsageBucket(SQLModel, table=True):
    __tablename__ = "proxy_usage"
    __table_args__ = (UniqueConstraint("user_id", "hour", "model"),)

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="proxy_user.id", ondelete="CASCADE", index=True)
    hour: datetime = Field(index=True)
    model: str
    calls: int = Field(default=0, sa_type=BigInteger)
    completed: int = Field(default=0, sa_type=BigInteger)
    failed: int = Field(default=0, sa_type=BigInteger)
    interrupted: int = Field(default=0, sa_type=BigInteger)
    unknown_usage: int = Field(default=0, sa_type=BigInteger)
    unpriced: int = Field(default=0, sa_type=BigInteger)
    input_tokens: int = Field(default=0, sa_type=BigInteger)
    cached_tokens: int = Field(default=0, sa_type=BigInteger)
    output_tokens: int = Field(default=0, sa_type=BigInteger)
    cost_usd: Decimal = Field(default=Decimal(0), sa_column=Column(Numeric(24, 12), nullable=False))


class PriceCatalog(SQLModel, table=True):
    __tablename__ = "proxy_price_catalog"

    id: int = Field(default=1, primary_key=True)
    fetched_at: datetime
    prices_json: str
