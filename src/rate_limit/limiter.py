import time
import threading
import yaml
from pathlib import Path
from contextlib import contextmanager

CONFIG_PATH = Path("configs/rate_limits.yaml")

class SlidingWindowLimiter:
    def __init__(self, rate_per_sec: float, burst: int):
        self.rate = rate_per_sec
        self.capacity = burst
        self.tokens = burst
        self.lock = threading.Lock()
        self.last = time.monotonic()

    @contextmanager
    def __call__(self):
        with self.lock:
            now = time.monotonic()
            elapsed = now - self.last
            self.last = now
            # refill
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            if self.tokens < 1:
                # wait until we have at least 1 token
                needed = 1 - self.tokens
                time.sleep(needed / self.rate)
                self.tokens = 1
                self.last = time.monotonic()
            # consume
            self.tokens -= 1
        yield

def _load_config():
    if not CONFIG_PATH.exists():
        return {}
    return yaml.safe_load(CONFIG_PATH.read_text()) or {}

_limiters = {}

def get_limiter(channel: str) -> SlidingWindowLimiter:
    cfg = _load_config().get(channel, {"rate_per_sec": 2, "burst": 5})
    key = f"{channel}:{cfg['rate_per_sec']}:{cfg['burst']}"
    if key not in _limiters:
        _limiters[key] = SlidingWindowLimiter(cfg["rate_per_sec"], cfg["burst"])
    return _limiters[key]
