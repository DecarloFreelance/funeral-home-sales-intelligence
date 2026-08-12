from __future__ import annotations

import json
from dataclasses import dataclass
from http.cookiejar import CookieJar
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener

DEFAULT_BASE_URL = "https://services.afsrb.ab.ca"
DEFAULT_USER_AGENT = "CanadaFuneralIntel/0.1 (+public-business-data-research)"
VERIFY_ESTABLISHMENT_CODE_CLASS = "VERIFY_EST_TYPE"


class AfsrbError(RuntimeError):
    """Base error for AFSRB public-directory access."""


class AfsrbTransportError(AfsrbError):
    """Raised when the public AFSRB service cannot be reached."""


class AfsrbProtocolError(AfsrbError):
    """Raised when the public AFSRB service returns an unexpected response."""


class AfsrbCaptchaRequired(AfsrbError):
    """Raised for search operations protected by the public-site CAPTCHA."""


@dataclass(frozen=True, slots=True)
class EstablishmentType:
    code: str
    description: str


class AfsrbPublicDirectoryClient:
    """Session-aware client for non-CAPTCHA AFSRB public-directory metadata."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout_seconds: float = 20.0,
        opener: Any | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent
        self.timeout_seconds = timeout_seconds
        self._opener = opener or build_opener(HTTPCookieProcessor(CookieJar()))
        self._session_ready = False

    @property
    def verify_url(self) -> str:
        return f"{self.base_url}/verify/"

    def _request_text(
        self,
        url: str,
        *,
        referer: str | None = None,
    ) -> tuple[str, str]:
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
        }
        if referer is not None:
            headers["Referer"] = referer

        request = Request(url, headers=headers, method="GET")

        try:
            with self._opener.open(
                request,
                timeout=self.timeout_seconds,
            ) as response:
                content_type = response.headers.get_content_type()
                body = response.read().decode("utf-8", errors="replace")
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise AfsrbTransportError(f"AFSRB request failed for {url}: {exc}") from exc

        return content_type, body

    def establish_session(self) -> None:
        content_type, body = self._request_text(self.verify_url)

        if content_type != "text/html":
            raise AfsrbProtocolError("AFSRB verify page did not return HTML")

        if 'name="action"' not in body or 'value="verifySearch"' not in body:
            raise AfsrbProtocolError(
                "AFSRB verify page does not contain expected search contract"
            )

        self._session_ready = True

    def establishment_types(self) -> tuple[EstablishmentType, ...]:
        if not self._session_ready:
            self.establish_session()

        url = f"{self.base_url}/api/?CodeClass/{VERIFY_ESTABLISHMENT_CODE_CLASS}"
        content_type, body = self._request_text(
            url,
            referer=self.verify_url,
        )

        if content_type != "application/json":
            raise AfsrbProtocolError(
                "AFSRB establishment-type endpoint did not return JSON"
            )

        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise AfsrbProtocolError(
                "AFSRB establishment-type response was invalid JSON"
            ) from exc

        if payload.get("CODE_CLASS") != VERIFY_ESTABLISHMENT_CODE_CLASS:
            raise AfsrbProtocolError(
                "AFSRB establishment-type response has unexpected code class"
            )

        values = payload.get("CodeValues")
        if not isinstance(values, list):
            raise AfsrbProtocolError(
                "AFSRB establishment-type response has no CodeValues list"
            )

        result: list[EstablishmentType] = []

        for row in values:
            if not isinstance(row, dict):
                continue
            if row.get("INACTIVE") != "N":
                continue

            code = row.get("CODE_VALUE")
            description = row.get("CODE_VALUE_DESC")

            if not isinstance(code, str) or not isinstance(description, str):
                continue

            result.append(
                EstablishmentType(
                    code=code,
                    description=description,
                )
            )

        return tuple(result)

    def search_establishments(self, **_: object) -> None:
        raise AfsrbCaptchaRequired(
            "AFSRB establishment search is CAPTCHA-protected and is not "
            "automated by this client."
        )
