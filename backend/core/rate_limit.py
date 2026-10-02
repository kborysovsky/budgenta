"""Bounded, process-local rate limits for the single-worker deployment."""
from collections import OrderedDict
from threading import Lock
from time import monotonic


class RateLimiter:
    def __init__(self, max_keys=10000):
        self.max_keys = max_keys
        self.buckets = OrderedDict()
        self.lock = Lock()

    def allow(self, key, limit, window=60):
        current = monotonic()
        with self.lock:
            # Expire oldest buckets; reject new keys at capacity rather than
            # allowing attackers to evict someone else's active limit.
            while self.buckets and next(iter(self.buckets.values()))[0] <= current:
                self.buckets.popitem(last=False)
            expires, count = self.buckets.get(key, (current + window, 0))
            if expires <= current:
                del self.buckets[key]
                expires, count = current + window, 0
            if key not in self.buckets and len(self.buckets) >= self.max_keys:
                return False
            if count >= limit:
                return False
            self.buckets[key] = (expires, count + 1)
            return True

    def clear(self):
        with self.lock:
            self.buckets.clear()
