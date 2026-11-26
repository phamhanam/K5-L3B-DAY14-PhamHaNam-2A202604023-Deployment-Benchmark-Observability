"""
Rate limiting (tiêu chí 7) — Sliding window 60s bằng Redis sorted set.
"""
import hashlib
import time
import uuid
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r


def check_rate_limit(key: str) -> None:
    now = time.time()
    window_seconds = 60
    limit = settings.rate_limit_per_minute

    key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    redis_key = f"rate_limit:{key_hash}"

    try:
        pipe = r.pipeline()
        pipe.zremrangebyscore(redis_key, 0, now - window_seconds)
        pipe.zcard(redis_key)
        _, current_count = pipe.execute()

        if current_count >= limit:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={"Retry-After": str(window_seconds)},
            )

        member = f"{now}:{uuid.uuid4().hex}"
        pipe = r.pipeline()
        pipe.zadd(redis_key, {member: now})
        pipe.expire(redis_key, window_seconds + 1)
        pipe.execute()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Rate limiter unavailable: {exc}")
