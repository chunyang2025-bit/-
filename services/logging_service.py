import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

from app.config import Settings


class ComplianceLogger:
    def __init__(self, settings: Settings):
        self.settings = settings

    def write(self, event: str, payload: Dict[str, Any]) -> None:
        now = datetime.now(timezone.utc)
        path = self.settings.logs_dir / f"api-{now.strftime('%Y-%m')}.jsonl"
        record = {
            "ts": now.isoformat(),
            "event": event,
            "payload": payload,
        }
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def cleanup_old_logs(self) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.settings.log_retention_days)
        for path in self.settings.logs_dir.glob("api-*.jsonl"):
            if self._mtime(path) < cutoff:
                path.unlink(missing_ok=True)

    @staticmethod
    def _mtime(path: Path) -> datetime:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
