"""Per-job port allocation.

A port is handed out only if it is both unreserved by this allocator and actually
bindable on localhost right now. Reservations are in-memory; on startup the caller
seeds them from the store (``reserve``) so ports of jobs that survived a restart are
never handed out again.
"""

from __future__ import annotations

import socket
import threading
from collections.abc import Iterable


class NoFreePort(RuntimeError):
    pass


def is_bindable(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return False
        return True


class PortAllocator:
    def __init__(self, start: int = 8100, end: int = 8999) -> None:
        if not (1024 <= start <= end <= 65535):
            raise ValueError(f"invalid port range {start}-{end}")
        self.start = start
        self.end = end
        self._reserved: set[int] = set()
        self._lock = threading.Lock()

    @property
    def reserved(self) -> frozenset[int]:
        with self._lock:
            return frozenset(self._reserved)

    def reserve(self, ports: Iterable[int]) -> None:
        """Mark ports as taken without checking them (used to seed from persisted jobs)."""
        with self._lock:
            self._reserved.update(ports)

    def allocate(self) -> int:
        with self._lock:
            for port in range(self.start, self.end + 1):
                if port in self._reserved:
                    continue
                if is_bindable(port):
                    self._reserved.add(port)
                    return port
        raise NoFreePort(f"no free port in {self.start}-{self.end}")

    def release(self, port: int | None) -> None:
        if port is None:
            return
        with self._lock:
            self._reserved.discard(port)
