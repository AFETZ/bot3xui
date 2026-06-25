from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RedisJobLock:
    redis: Any
    key: str
    ttl_seconds: int
    token: str = field(default_factory=lambda: uuid.uuid4().hex)
    acquired: bool = False

    async def __aenter__(self) -> bool:
        try:
            result = await self.redis.set(
                self.key,
                self.token,
                ex=self.ttl_seconds,
                nx=True,
            )
        except TypeError:
            if await self.redis.get(self.key):
                self.acquired = False
                return False
            await self.redis.set(self.key, self.token, ex=self.ttl_seconds)
            result = True
        except Exception as exception:
            logger.warning("Failed to acquire Redis lock %s: %s", self.key, exception)
            self.acquired = True
            return True

        self.acquired = bool(result)
        return self.acquired

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        if not self.acquired:
            return False

        try:
            current_token = await self.redis.get(self.key)
            if isinstance(current_token, bytes):
                current_token = current_token.decode()
            if current_token == self.token:
                await self.redis.delete(self.key)
        except AttributeError:
            try:
                values = getattr(self.redis, "values", None)
                if isinstance(values, dict) and values.get(self.key) == self.token:
                    values.pop(self.key, None)
            except Exception:
                pass
        except Exception as exception:
            logger.warning("Failed to release Redis lock %s: %s", self.key, exception)

        return False
