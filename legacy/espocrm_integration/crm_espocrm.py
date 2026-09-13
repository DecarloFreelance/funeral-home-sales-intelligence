import time
from urllib.parse import quote, urljoin, urlparse

import requests

from crm.backends import CRMBackend


class EspoCRMError(RuntimeError):
    pass


class EspoCRMBackend(CRMBackend):
    """Minimal EspoCRM Account client using a least-privilege API key."""

    def __init__(self, site_url, api_key, session=None, timeout=10, retries=2):
        if not site_url or not api_key:
            raise ValueError("EspoCRM site URL and API key are required")
        parsed_url = urlparse(str(site_url))
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname:
            raise ValueError("EspoCRM site URL must use HTTP or HTTPS")
        if parsed_url.scheme != "https" and parsed_url.hostname not in {
            "localhost", "127.0.0.1", "::1",
        }:
            raise ValueError("EspoCRM API keys require HTTPS except on localhost")
        self.base_url = str(site_url).rstrip("/") + "/api/v1/"
        self.api_key = api_key
        self.session = session or requests.Session()
        self.timeout = timeout
        self.retries = max(0, int(retries))

    def _request(self, method, path, **kwargs):
        headers = {"X-Api-Key": self.api_key, "Content-Type": "application/json"}
        for attempt in range(self.retries + 1):
            try:
                response = self.session.request(
                    method, urljoin(self.base_url, path), headers=headers,
                    timeout=self.timeout, **kwargs,
                )
                if response.status_code not in {429, 500, 502, 503, 504}:
                    response.raise_for_status()
                    return response.json()
            except (requests.RequestException, ValueError) as error:
                if attempt >= self.retries:
                    raise EspoCRMError("EspoCRM request failed") from error
            if attempt >= self.retries:
                raise EspoCRMError("EspoCRM request failed after bounded retries")
            time.sleep(min(2 ** attempt, 4))

    def upsert_account(self, domain, payload, remote_id=None):
        remote_id = remote_id or self._find_account(domain)
        if remote_id:
            result = self._request(
                "PUT", f"Account/{quote(str(remote_id), safe='')}", json=payload,
            )
        else:
            result = self._request("POST", "Account", json=payload)
        response_id = result.get("id") if isinstance(result, dict) else None
        identifier = str(response_id or remote_id or "").strip()
        if not identifier:
            raise EspoCRMError("EspoCRM response did not include a record ID")
        return identifier

    def _find_account(self, domain):
        result = self._request("GET", "Account", params={
            "select": "id,website",
            "maxSize": 2,
            "where[0][type]": "equals",
            "where[0][attribute]": "website",
            "where[0][value]": f"https://{domain}",
        })
        if not isinstance(result, dict):
            raise EspoCRMError("EspoCRM search returned an invalid response")
        records = result.get("list", [])
        if len(records) > 1:
            raise EspoCRMError("Multiple EspoCRM accounts match the local domain")
        return str(records[0].get("id") or "") if records else None

    def get_account(self, remote_id):
        result = self._request(
            "GET", f"Account/{quote(str(remote_id), safe='')}",
        )
        if not isinstance(result, dict):
            raise EspoCRMError("EspoCRM account read returned an invalid response")
        return result
