from __future__ import annotations

from email.message import Message
from io import BytesIO
from typing import Self

import pytest

from canada_funeral_intel.collectors.afsrb import (
    AfsrbCaptchaRequired,
    AfsrbProtocolError,
    AfsrbPublicDirectoryClient,
    EstablishmentType,
)


class FakeResponse:
    def __init__(self, body: str, content_type: str) -> None:
        self._body = BytesIO(body.encode("utf-8"))
        self.headers = Message()
        self.headers["Content-Type"] = content_type

    def read(self) -> bytes:
        return self._body.read()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class FakeOpener:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.requests = []

    def open(self, request, timeout: float):
        self.requests.append((request, timeout))
        return self.responses.pop(0)


def test_establishment_types_uses_verify_session_and_referer() -> None:
    verify_html = """
    <html>
      <form id="form">
        <input name="action" value="verifySearch">
      </form>
    </html>
    """
    types_json = """
    {
      "CODE_CLASS": "VERIFY_EST_TYPE",
      "CodeValues": [
        {
          "CODE_VALUE": "FUN",
          "CODE_VALUE_DESC": "Funeral Home",
          "INACTIVE": "N"
        },
        {
          "CODE_VALUE": "BOTH",
          "CODE_VALUE_DESC": "Funeral Home/Crematory",
          "INACTIVE": "N"
        },
        {
          "CODE_VALUE": "OLD",
          "CODE_VALUE_DESC": "Inactive",
          "INACTIVE": "Y"
        }
      ]
    }
    """

    opener = FakeOpener(
        [
            FakeResponse(verify_html, "text/html; charset=utf-8"),
            FakeResponse(types_json, "application/json; charset=utf-8"),
        ]
    )
    client = AfsrbPublicDirectoryClient(opener=opener)

    result = client.establishment_types()

    assert result == (
        EstablishmentType("FUN", "Funeral Home"),
        EstablishmentType("BOTH", "Funeral Home/Crematory"),
    )
    assert len(opener.requests) == 2

    verify_request, verify_timeout = opener.requests[0]
    api_request, api_timeout = opener.requests[1]

    assert verify_request.full_url.endswith("/verify/")
    assert verify_request.get_header("Referer") is None
    assert verify_timeout == 20.0

    assert api_request.full_url.endswith("/api/?CodeClass/VERIFY_EST_TYPE")
    assert api_request.get_header("Referer") == client.verify_url
    assert api_timeout == 20.0


def test_session_rejects_unexpected_verify_page() -> None:
    opener = FakeOpener([FakeResponse("<html>unexpected</html>", "text/html")])
    client = AfsrbPublicDirectoryClient(opener=opener)

    with pytest.raises(AfsrbProtocolError):
        client.establish_session()


def test_search_is_explicitly_not_automated() -> None:
    client = AfsrbPublicDirectoryClient(opener=FakeOpener([]))

    with pytest.raises(AfsrbCaptchaRequired):
        client.search_establishments()
