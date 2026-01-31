import time

from sqlalchemy import BigInteger, Column


class TimestampMixin:
    created_at = Column(BigInteger, nullable=False, default=lambda: int(time.time()))
    updated_at = Column(
        BigInteger,
        nullable=False,
        default=lambda: int(time.time()),
        onupdate=lambda: int(time.time()),
    )


class SoftDeleteMixin:
    deleted_at = Column(BigInteger, nullable=True)
