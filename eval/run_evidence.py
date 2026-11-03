"""What a run retrieved and what its answer claims, read from its determination and events.

Shared by the agent evaluation (eval/agent_sut.py) and live scoring (eval/live_scorer.py), so both
judge a run the same way. Kept free of HTTP and agent imports so the live scorer can run in the
retrieval image.
"""
from __future__ import annotations

import re
from typing import List

from .metrics import split_claims

_CITE_TAG = re.compile(r"\s*\[c\d+\]")


def retrieved_passages(events: List[dict]) -> List[dict]:
    """Passages the run retrieved, in order, de-duplicated by chunk_id."""
    seen, out = set(), []
    for event in events:
        if event.get("kind") != "tool_call":
            continue
        for p in (event.get("payload") or {}).get("passages") or []:
            cid = p.get("chunk_id")
            if cid in seen:
                continue
            seen.add(cid)
            out.append(p)
    return out


def contexts_from_events(events: List[dict]) -> List[str]:
    """Passage texts the run retrieved, in order, de-duplicated by chunk_id."""
    return [p["text"] for p in retrieved_passages(events) if p.get("text")]


def claims_from_determination(det: dict) -> List[str]:
    """An answer's claims are the sentences of its basis; escalations and failures assert nothing."""
    if (det or {}).get("status") != "completed":
        return []
    return split_claims(_CITE_TAG.sub("", det.get("basis") or ""))
