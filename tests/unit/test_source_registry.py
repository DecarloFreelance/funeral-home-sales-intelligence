from __future__ import annotations

import json
from pathlib import Path

import pytest

from canada_funeral_intel.collectors.source_registry import (
    SourceDefinition,
    SourceFormat,
    SourceRegistryError,
    SourceType,
    TrustLevel,
    load_source_registry,
    source_definition_from_mapping,
)


def valid_payload() -> dict[str, object]:
    return {
        "name": "Example Registry",
        "source_type": "regulator",
        "source_format": "html",
        "trust_level": "authoritative",
        "coverage": ["AB"],
        "refresh_interval_days": 30,
        "enabled": True,
        "source_url": "https://example.test/source",
        "publisher": "Example Publisher",
        "jurisdiction": "AB",
    }


def test_source_definition_accepts_valid_metadata() -> None:
    definition = source_definition_from_mapping(valid_payload())

    assert definition.name == "Example Registry"
    assert definition.source_type is SourceType.REGULATOR
    assert definition.source_format is SourceFormat.HTML
    assert definition.trust_level is TrustLevel.AUTHORITATIVE
    assert definition.coverage == ("AB",)
    assert definition.refresh_interval_days == 30
    assert definition.enabled is True


def test_source_definition_rejects_empty_name() -> None:
    payload = valid_payload()
    payload["name"] = " "

    with pytest.raises(SourceRegistryError, match="name must not be empty"):
        source_definition_from_mapping(payload)


def test_source_definition_rejects_invalid_refresh_interval() -> None:
    payload = valid_payload()
    payload["refresh_interval_days"] = 0

    with pytest.raises(SourceRegistryError, match="must be at least 1"):
        source_definition_from_mapping(payload)


def test_source_definition_rejects_empty_coverage() -> None:
    payload = valid_payload()
    payload["coverage"] = []

    with pytest.raises(SourceRegistryError, match="at least one jurisdiction"):
        source_definition_from_mapping(payload)


def test_source_definition_rejects_duplicate_coverage() -> None:
    payload = valid_payload()
    payload["coverage"] = ["AB", "ab"]

    with pytest.raises(SourceRegistryError, match="duplicate jurisdictions"):
        source_definition_from_mapping(payload)


def test_source_definition_rejects_invalid_url() -> None:
    payload = valid_payload()
    payload["source_url"] = "example.test/no-scheme"

    with pytest.raises(SourceRegistryError, match="absolute HTTP"):
        source_definition_from_mapping(payload)


def test_source_definition_rejects_unknown_enum_value() -> None:
    payload = valid_payload()
    payload["trust_level"] = "magic"

    with pytest.raises(SourceRegistryError, match="Invalid source registry value"):
        source_definition_from_mapping(payload)


def test_source_definition_record_is_deterministic() -> None:
    definition = SourceDefinition(
        name="Example",
        source_type=SourceType.GOVERNMENT,
        source_format=SourceFormat.JSON,
        trust_level=TrustLevel.HIGH,
        coverage=("ON", "QC"),
        refresh_interval_days=14,
    )

    first = definition.as_record()
    second = definition.as_record()

    assert first == second
    assert first["coverage"] == '["ON","QC"]'


def test_load_registry_sorts_entries_deterministically(tmp_path: Path) -> None:
    path = tmp_path / "sources.json"

    first = valid_payload()
    first["name"] = "Zulu"

    second = valid_payload()
    second["name"] = "Alpha"

    path.write_text(
        json.dumps([first, second]),
        encoding="utf-8",
    )

    registry = load_source_registry(path)

    assert [item.name for item in registry] == ["Alpha", "Zulu"]


def test_load_registry_rejects_duplicate_names(tmp_path: Path) -> None:
    path = tmp_path / "sources.json"

    first = valid_payload()
    second = valid_payload()

    path.write_text(
        json.dumps([first, second]),
        encoding="utf-8",
    )

    with pytest.raises(SourceRegistryError, match="duplicate names"):
        load_source_registry(path)


def test_load_project_seed_registry() -> None:
    path = Path("config/sources.json")
    registry = load_source_registry(path)

    assert registry
    assert [item.name for item in registry] == sorted(
        (item.name for item in registry),
        key=str.casefold,
    )

    for definition in registry:
        definition.validate()
