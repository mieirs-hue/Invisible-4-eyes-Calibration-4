import time
import logging

logger = logging.getLogger(__name__)

class HeartbeatMonitor:
    def __init__(self, timeout_sec=10):
        self.last_seen = {}
        self.timeout_sec = timeout_sec

    def update(self, node_name):
        self.last_seen[node_name] = time.time()

    def check_health(self):
        now = time.time()
        for node, last_time in self.last_seen.items():
            if now - last_time > self.timeout_sec:
                logger.warning(f"{node} sensor offline (no heartbeat for {now - last_time:.1f}s)")