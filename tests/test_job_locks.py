from app.bot.services.job_locks import RedisJobLock


class FakeRedis:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.deleted = []

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def delete(self, key):
        self.deleted.append(key)
        self.values.pop(key, None)


async def test_redis_job_lock_acquires_and_releases():
    redis = FakeRedis()

    async with RedisJobLock(redis, "job:test", 60) as acquired:
        assert acquired is True
        assert "job:test" in redis.values

    assert "job:test" not in redis.values
    assert redis.deleted == ["job:test"]


async def test_redis_job_lock_skips_when_key_exists():
    redis = FakeRedis({"job:test": "other-token"})

    async with RedisJobLock(redis, "job:test", 60) as acquired:
        assert acquired is False

    assert redis.values["job:test"] == "other-token"
    assert redis.deleted == []
