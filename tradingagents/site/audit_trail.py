"""What the record can prove about itself.

Each run appends its steps to a hash-chained ledger and stores the chain head
with the run. Publishing those heads is what separates a track record from a
screenshot: a row edited after the fact no longer matches the hash that was
written the morning it ran, and every later run's hash depends on it.

This module only reads what was already stored. It never writes.
"""

from __future__ import annotations

from typing import Any, Mapping

GENESIS_HASH = "0" * 64


def _metadata(run: Mapping[str, Any]) -> dict[str, Any]:
    value = run.get("metadata") or run.get("metadata_json") or {}
    return dict(value) if isinstance(value, Mapping) else {}


def build_audit_payload(runs: list[Mapping[str, Any]] | None, *, limit: int = 12) -> dict[str, Any]:
    """The most recent runs with their sequence range and chain head."""

    entries = []
    for run in runs or []:
        metadata = _metadata(run)
        head = str(metadata.get("audit_head_hash") or "").strip()
        start = run.get("audit_sequence_start")
        end = run.get("audit_sequence_end")
        if not head and start is None and end is None:
            continue
        entries.append(
            {
                "run_id": str(run.get("id") or ""),
                "as_of_date": str(run.get("as_of_date") or ""),
                "broker": run.get("broker"),
                "sequence_start": start,
                "sequence_end": end,
                "step_count": (int(end) - int(start) + 1) if (start is not None and end is not None) else None,
                "head_hash": head,
                "head_short": f"{head[:12]}…{head[-6:]}" if len(head) > 20 else head,
                "detail_path": f"/harness/{run.get('id')}" if run.get("id") else None,
            }
        )
    entries.sort(key=lambda item: (item["as_of_date"], item.get("sequence_end") or 0), reverse=True)
    covered = [item for item in entries if item["head_hash"]]
    return {
        "status": "available" if entries else "empty",
        "entries": entries[:limit],
        "summary": {
            "run_count": len(entries),
            "hashed_count": len(covered),
            "latest_hash": covered[0]["head_hash"] if covered else None,
            "latest_date": covered[0]["as_of_date"] if covered else None,
        },
    }
