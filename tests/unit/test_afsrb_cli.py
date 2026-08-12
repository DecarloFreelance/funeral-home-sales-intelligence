from __future__ import annotations

import json
from pathlib import Path

import pytest

from canada_funeral_intel.cli import build_parser
from canada_funeral_intel.collectors.afsrb import EstablishmentType
from canada_funeral_intel.collectors.afsrb_cli import (
    AFSRB_SOURCE_NAME,
    AfsrbProbeCommandError,
    run_afsrb_probe,
)


class FakeAfsrbClient:
    def establishment_types(self) -> tuple[EstablishmentType, ...]:
        return (
            EstablishmentType("FUN", "Funeral Home"),
            EstablishmentType("BOTH", "Funeral Home/Crematory"),
        )


def _registry(tmp_path: Path, *, enabled: bool = True) -> Path:
    path = tmp_path / "sources.json"
    path.write_text(
        json.dumps(
            [
                {
                    "name": AFSRB_SOURCE_NAME,
                    "source_type": "regulator",
                    "source_format": "html",
                    "trust_level": "authoritative",
                    "coverage": ["AB"],
                    "refresh_interval_days": 30,
                    "enabled": enabled,
                    "source_url": "https://www.afsrb.ab.ca/",
                }
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_afsrb_probe_returns_read_only_metadata(tmp_path: Path) -> None:
    payload = run_afsrb_probe(
        _registry(tmp_path),
        client=FakeAfsrbClient(),
    )

    assert payload["source"] == AFSRB_SOURCE_NAME
    assert payload["collector"] == "afsrb"
    assert payload["mode"] == "metadata_only"
    assert payload["database_write"] is False
    assert payload["search_automated"] is False
    assert payload["establishment_types"] == [
        {"code": "FUN", "description": "Funeral Home"},
        {"code": "BOTH", "description": "Funeral Home/Crematory"},
    ]


def test_afsrb_probe_rejects_disabled_source(tmp_path: Path) -> None:
    with pytest.raises(AfsrbProbeCommandError, match="Source is disabled"):
        run_afsrb_probe(
            _registry(tmp_path, enabled=False),
            client=FakeAfsrbClient(),
        )


def test_parser_accepts_sources_probe() -> None:
    args = build_parser().parse_args(["sources", "probe"])
    assert args.command == "sources"
    assert args.sources_command == "probe"
    assert args.name == AFSRB_SOURCE_NAME
