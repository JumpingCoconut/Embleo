"""Bounded operational counters; never include client values or exception text."""

import logging
import threading
import time


class Diagnostics:
    def __init__(self, component):
        self.logger = logging.getLogger('embleo.raid.' + component)
        self.lock = threading.Lock()
        self.counts = {}
        self.last_logged = {}

    def record(self, reason, operation='transport'):
        # Call sites provide fixed labels only. Cardinality and warning volume
        # remain bounded even during malformed-client or reconnect storms.
        key = (reason, operation)
        with self.lock:
            if key not in self.counts and len(self.counts) >= 64:
                return
            count = self.counts[key] = min(self.counts.get(key, 0) + 1, 2**31 - 1)
            now = time.monotonic()
            if key in self.last_logged and now - self.last_logged[key] < 30:
                return
            self.last_logged[key] = now
        self.logger.warning('raid_event reason=%s operation=%s count=%d',
                            reason, operation, count)
