import time
from collections import defaultdict, deque
from typing import Deque

from fastapi import HTTPException, Request


class InMemoryRateLimiter:
    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self._hits: dict[str, Deque[float]] = defaultdict(deque)

    async def check(self, request: Request) -> None:
        client = request.client.host if request.client else "unknown"
        now = time.time()
        bucket = self._hits[client]
        while bucket and now - bucket[0] > 60:
            bucket.popleft()
        if len(bucket) >= self.per_minute:
            raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")
        bucket.append(now)
