import logging
from datetime import datetime
from typing import Self

from sqlalchemy import *
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship, selectinload

from app.bot.utils.misc import generate_code

from . import Base

logger = logging.getLogger(__name__)


class PromocodeActivation(Base):
    __tablename__ = "promocode_activations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    promocode_id: Mapped[int] = mapped_column(ForeignKey("promocodes.id", ondelete="CASCADE"), nullable=False)
    user_tg_id: Mapped[int] = mapped_column(ForeignKey("users.tg_id"), nullable=False)
    activated_at: Mapped[datetime] = mapped_column(default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("promocode_id", "user_tg_id", name="uq_promocode_activation_user"),
    )


class Promocode(Base):
    __tablename__ = "promocodes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(length=32), unique=True, nullable=False)
    duration: Mapped[int] = mapped_column(nullable=False)
    max_activations: Mapped[int] = mapped_column(default=1, server_default="1", nullable=False)
    is_activated: Mapped[bool] = mapped_column(default=False, nullable=False)
    activated_by: Mapped[int | None] = mapped_column(ForeignKey("users.tg_id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now(), nullable=False)
    activated_user: Mapped["User | None"] = relationship(  # type: ignore
        "User", back_populates="activated_promocodes"
    )
    activations: Mapped[list["PromocodeActivation"]] = relationship(
        "PromocodeActivation", cascade="all, delete-orphan", lazy="selectin",
    )

    @property
    def is_multi_use(self) -> bool:
        return self.max_activations != 1

    @property
    def activation_count(self) -> int:
        return len(self.activations) if self.activations else 0

    def can_activate(self, user_id: int) -> bool:
        if self.is_multi_use:
            if any(a.user_tg_id == user_id for a in self.activations):
                return False
            if self.max_activations == 0:
                return True
            return self.activation_count < self.max_activations
        return not self.is_activated

    def __repr__(self) -> str:
        return (
            f"<Promocode(id={self.id}, code='{self.code}', duration={self.duration}, "
            f"max_activations={self.max_activations}, "
            f"is_activated={self.is_activated}, activated_by={self.activated_by}, "
            f"created_at={self.created_at})>"
        )

    @classmethod
    async def get(cls, session: AsyncSession, code: str) -> Self | None:
        filter = [Promocode.code == code]
        query = await session.execute(
            select(Promocode)
            .options(selectinload(Promocode.activated_user), selectinload(Promocode.activations))
            .where(*filter)
        )
        return query.scalar_one_or_none()

    @classmethod
    async def create(cls, session: AsyncSession, **kwargs: Any) -> Self | None:
        while True:
            code = generate_code()
            promocode = await Promocode.get(session=session, code=code)
            if not promocode:
                break

        promocode = Promocode(code=code, **kwargs)
        session.add(promocode)

        try:
            await session.commit()
            logger.info(f"Promocode {promocode.code} created.")
            return promocode
        except IntegrityError as exception:
            await session.rollback()
            logger.error(f"Error occurred while creating promocode {promocode.code}: {exception}")
            return None

    @classmethod
    async def update(cls, session: AsyncSession, code: str, **kwargs: Any) -> Self | None:
        promocode = await Promocode.get(session=session, code=code)

        if not promocode:
            logger.warning(f"Promocode {code} not found for update.")
            return None

        filter = [Promocode.code == code]
        await session.execute(update(Promocode).where(*filter).values(**kwargs))
        await session.commit()
        logger.info(f"Promocode {code} updated.")
        return promocode

    @classmethod
    async def delete(cls, session: AsyncSession, code: str) -> bool:
        promocode = await Promocode.get(session=session, code=code)

        if promocode:
            await session.delete(promocode)
            await session.commit()
            logger.info(f"Promocode {code} deleted.")
            return True

        logger.warning(f"Promocode {code} not found for deletion.")
        return False

    @classmethod
    async def set_activated(cls, session: AsyncSession, code: str, user_id: int) -> bool:
        promocode = await Promocode.get(session=session, code=code)

        if not promocode:
            logger.warning(f"Promocode {code} not found for activation.")
            return False

        if not promocode.can_activate(user_id):
            logger.warning(f"Promocode {code} cannot be activated by user {user_id}.")
            return False

        if promocode.is_multi_use:
            activation = PromocodeActivation(promocode_id=promocode.id, user_tg_id=user_id)
            session.add(activation)
            if promocode.max_activations > 0 and (promocode.activation_count + 1) >= promocode.max_activations:
                await session.execute(
                    update(Promocode).where(Promocode.code == code).values(is_activated=True)
                )
            await session.commit()
            logger.info(f"Multi-use promocode {code} activated by user {user_id}.")
            return True

        await Promocode.update(session=session, code=code, is_activated=True, activated_by=user_id)
        return True

    @classmethod
    async def set_deactivated(cls, session: AsyncSession, code: str, user_id: int | None = None) -> bool:
        promocode = await Promocode.get(session=session, code=code)

        if not promocode:
            logger.warning(f"Promocode {code} not found for deactivation.")
            return False

        if promocode.is_multi_use and user_id:
            activation = next((a for a in promocode.activations if a.user_tg_id == user_id), None)
            if activation:
                await session.delete(activation)
                if promocode.is_activated:
                    await session.execute(
                        update(Promocode).where(Promocode.code == code).values(is_activated=False)
                    )
                await session.commit()
                logger.info(f"Multi-use promocode {code} deactivated for user {user_id}.")
                return True
            return False

        if not promocode.is_activated:
            logger.warning(f"Promocode {code} is already deactivated.")
            return False

        await Promocode.update(session=session, code=code, is_activated=False, activated_by=None)
        return True
