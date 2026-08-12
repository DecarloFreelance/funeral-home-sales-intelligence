from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RefreshObservation:
    subject_type: str
    subject_key: str
    semantic_fingerprint: str
    reference_id: int | None = None
    metadata_json: str = "{}"
