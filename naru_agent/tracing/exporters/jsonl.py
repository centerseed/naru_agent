from __future__ import annotations

import threading

from naru_agent.tracing.exporters.base import BaseTraceExporter
from naru_agent.tracing.trace import Trace


class JSONLTraceExporter(BaseTraceExporter):
    """將 trace 以 JSONL 格式寫入檔案，用於 offline 分析。"""

    def __init__(self, filepath: str, append: bool = True) -> None:
        self.filepath = filepath
        self.append = append
        self._lock = threading.Lock()

    def export(self, trace: Trace) -> None:
        line = trace.to_json() + "\n"
        mode = "a" if self.append else "w"
        with self._lock:
            with open(self.filepath, mode, encoding="utf-8") as f:
                f.write(line)
