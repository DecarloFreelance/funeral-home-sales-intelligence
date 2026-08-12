from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from canada_funeral_intel.collectors.afsrb import (
    AfsrbError,
    AfsrbPublicDirectoryClient,
    EstablishmentType,
)
from canada_funeral_intel.collectors.source_registry import (
    SourceDefinition,
    load_source_registry,
)

AFSRB_SOURCE_NAME = "Alberta Funeral Services Regulatory Board"


class AfsrbMetadataClient(Protocol):
    def establishment_types(self) -> tuple[EstablishmentType, ...]: ...


class AfsrbProbeCommandError(RuntimeError):
    """Raised when the read-only AFSRB metadata probe cannot be completed."""


def run_afsrb_probe(
    registry_path: Path,
    *,
    client: AfsrbMetadataClient | None = None,
    source_name: str = AFSRB_SOURCE_NAME,
) -> dict[str, object]:
    registry = load_source_registry(registry_path)
    requested = source_name.casefold()
    definition: SourceDefinition | None = next(
        (item for item in registry if item.name.casefold() == requested),
        None,
    )

    if definition is None:
        raise AfsrbProbeCommandError(f"Source not found: {source_name}")
    if definition.name != AFSRB_SOURCE_NAME:
        raise AfsrbProbeCommandError(
            f"No live collector is registered for source: {definition.name}"
        )
    if not definition.enabled:
        raise AfsrbProbeCommandError(f"Source is disabled: {definition.name}")

    live_client = client or AfsrbPublicDirectoryClient()

    try:
        establishment_types = live_client.establishment_types()
    except AfsrbError as exc:
        raise AfsrbProbeCommandError(str(exc)) from exc

    return {
        "source": definition.name,
        "collector": "afsrb",
        "mode": "metadata_only",
        "database_write": False,
        "search_automated": False,
        "establishment_types": [
            {
                "code": item.code,
                "description": item.description,
            }
            for item in establishment_types
        ],
    }


def print_afsrb_probe_result(payload: dict[str, object]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))
