"""per-session asyncio.Lock registry。

取代以全域 `threading.Lock` 序列化 session 的舊作法（跨 session 過度序列化、競爭時還卡
event loop）。改用「同 key 序列、不同 key 並行」的 per-session asyncio.Lock：同一 session
的 turn 排隊（對話本來就序列），不同 session 的 turn 在單一 event loop 上並行。

回收用 bounded LRU（容量上限），不做「檢查無 waiter + 移除」的非原子回收（那會把 waiter
手上的 lock 換掉 → 序列化失效）。LRU 容量足夠大時，in-flight session 不會被淘汰。
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict


class SessionLockRegistry:
    """per-session asyncio.Lock。同 key 序列、不同 key 並行；bounded LRU 回收。"""

    def __init__(self, maxsize: int = 2048):
        self._locks: "OrderedDict[str, asyncio.Lock]" = OrderedDict()
        self._maxsize = maxsize

    def get(self, key: str) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
            if len(self._locks) > self._maxsize:
                self._locks.popitem(last=False)  # 淘汰最舊
        else:
            self._locks.move_to_end(key)
        return lock


session_lock_registry = SessionLockRegistry()
