from __future__ import annotations

import json

import pytest

from canada_funeral_intel.collectors.quebec import (
    QuebecCollectorError,
    parse_directory,
    records_as_parse_result,
)


def sample_text() -> str:
    return """
Liste des ESF avec les services
Dénomination sociale : EXEMPLE FUNÉRAIRE INC.
Numéro de permis : 19FUN0001
Nom directeur des services funéraires : Jeanne Exemple
État du permis : Actif
Téléphone : (418) 555-0100
10, rue Principale , Québec 03 - Capitale-Nationale
20, rue du Lac , Lévis 12 - Chaudière-Appalaches
Dénomination sociale : ENTREPRISE FERMÉE INC.
Numéro de permis : 19FUN0002
État du permis : Suspendu
10, rue Fermée , Québec 03 - Capitale-Nationale
"""


def test_parse_directory_expands_active_facilities() -> None:
    records = parse_directory(sample_text())

    assert len(records) == 2
    assert records[0].permit_number == "19FUN0001"
    assert records[0].city == "Québec"
    assert records[1].city == "Lévis"
    assert all(record.status == "Actif" for record in records)


def test_parse_result_preserves_permit_provenance() -> None:
    parsed = records_as_parse_result(parse_directory(sample_text()))

    payload = json.loads(parsed.rows[0].raw_payload)
    assert payload["permit_number"] == "19FUN0001"
    assert payload["province"] == "QC"
    assert parsed.rows[1].external_record_id == "QC-19FUN0001-002"


def test_parse_directory_fails_without_active_facilities() -> None:
    with pytest.raises(QuebecCollectorError, match="no active"):
        parse_directory(
            "Dénomination sociale : X\n"
            "Numéro de permis : 19FUN9999\n"
            "État du permis : Suspendu"
        )
