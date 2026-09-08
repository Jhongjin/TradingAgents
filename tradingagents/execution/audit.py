"""Hash-chained audit ledger for decisions, gates, and orders.

Modelled on Vibe-Trading's ``audit.jsonl`` hash chain and Binance-Agent's
``events.jsonl``. Every pipeline cycle appends one JSON line, even when no
trade happens, so operators can prove the system was evaluating. Each record
stores the SHA-256 of the previous record; ``verify_chain`` detects tampering
or truncation.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping


GENESIS_HASH = "0" * 64


@dataclass(frozen=True)
class AuditRecord:
    sequence: int
    timestamp: str
    event_type: str
    payload: dict[str, Any]
    previous_hash: str
    hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "payload": self.payload,
            "previous_hash": self.previous_hash,
            "hash": self.hash,
        }


class AuditLedger:
    """Append-only JSONL ledger with a SHA-256 hash chain."""

    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path)
        self._last_hash = GENESIS_HASH
        self._sequence = 0
        if self.path.exists():
            for record in self.iter_records():
                self._last_hash = record.hash
                self._sequence = record.sequence

    @classmethod
    def from_env(cls, default: str | None = None) -> "AuditLedger":
        configured = os.getenv("TRADINGAGENTS_AUDIT_LOG_PATH") or default
        if not configured:
            configured = os.path.join(os.path.expanduser("~"), ".tradingagents", "audit", "audit.jsonl")
        return cls(configured)

    @property
    def last_hash(self) -> str:
        return self._last_hash

    @property
    def sequence(self) -> int:
        return self._sequence

    def append(self, event_type: str, payload: Mapping[str, Any], *, timestamp: datetime | None = None) -> AuditRecord:
        if not event_type or not event_type.strip():
            raise ValueError("event_type cannot be empty")
        stamp = (timestamp or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        sequence = self._sequence + 1
        body = {
            "sequence": sequence,
            "timestamp": stamp,
            "event_type": event_type,
            "payload": _json_safe(dict(payload)),
            "previous_hash": self._last_hash,
        }
        digest = compute_record_hash(body)
        record = AuditRecord(hash=digest, **body)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.as_dict(), ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                pass
        self._last_hash = digest
        self._sequence = sequence
        return record

    def iter_records(self) -> Iterator[AuditRecord]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                yield AuditRecord(
                    sequence=int(data["sequence"]),
                    timestamp=str(data["timestamp"]),
                    event_type=str(data["event_type"]),
                    payload=dict(data.get("payload") or {}),
                    previous_hash=str(data["previous_hash"]),
                    hash=str(data["hash"]),
                )

    def verify_chain(self) -> tuple[bool, str | None]:
        """Return (ok, error). Re-hashes every record and checks the links."""

        previous = GENESIS_HASH
        expected_sequence = 0
        for record in self.iter_records():
            expected_sequence += 1
            if record.sequence != expected_sequence:
                return False, f"sequence gap at {record.sequence} (expected {expected_sequence})"
            if record.previous_hash != previous:
                return False, f"broken link at sequence {record.sequence}"
            body = {
                "sequence": record.sequence,
                "timestamp": record.timestamp,
                "event_type": record.event_type,
                "payload": record.payload,
                "previous_hash": record.previous_hash,
            }
            if compute_record_hash(body) != record.hash:
                return False, f"hash mismatch at sequence {record.sequence}"
            previous = record.hash
        return True, None


def compute_record_hash(body: Mapping[str, Any]) -> str:
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "as_dict"):
        return _json_safe(value.as_dict())
    return str(value)
