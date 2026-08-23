from urllib.parse import quote

import requests


class VerificationError(RuntimeError):
    pass


class ZeroBounceEmailVerifier:
    endpoint = "https://api-us.zerobounce.net/v2/validate"

    def __init__(self, api_key, session=None, timeout=10):
        if not api_key:
            raise ValueError("ZeroBounce API key is required")
        self.api_key = api_key
        self.session = session or requests.Session()
        self.timeout = timeout

    def verify(self, email):
        try:
            response = self.session.get(
                self.endpoint,
                params={"api_key": self.api_key, "email": email, "timeout": self.timeout},
                timeout=self.timeout + 2,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as error:
            raise VerificationError("ZeroBounce verification failed") from error
        status = str(payload.get("status", "")).lower()
        deliverability = {
            "valid": "DELIVERABLE",
            "invalid": "UNDELIVERABLE",
            "catch-all": "UNKNOWN",
            "unknown": "UNKNOWN",
            "spamtrap": "UNDELIVERABLE",
            "abuse": "UNDELIVERABLE",
            "do_not_mail": "UNDELIVERABLE",
        }.get(status, "UNKNOWN")
        return {
            "deliverability": deliverability,
            "provider": "zerobounce",
            "provider_status": status.upper() or "UNKNOWN",
            "provider_sub_status": str(payload.get("sub_status", "")).upper(),
            "checked": True,
        }


class TwilioPhoneVerifier:
    endpoint = "https://lookups.twilio.com/v2/PhoneNumbers"

    def __init__(self, account_sid, auth_token, session=None, timeout=10):
        if not account_sid or not auth_token:
            raise ValueError("Twilio account SID and auth token are required")
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.session = session or requests.Session()
        self.timeout = timeout

    def verify(self, phone):
        url = f"{self.endpoint}/{quote(phone, safe='')}"
        try:
            response = self.session.get(
                url,
                params={"Fields": "line_type_intelligence,line_status"},
                auth=(self.account_sid, self.auth_token),
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as error:
            raise VerificationError("Twilio Lookup verification failed") from error
        line_type = payload.get("line_type_intelligence") or {}
        line_status = payload.get("line_status") or {}
        status = str(line_status.get("status", "")).lower()
        reachability = {
            "active": "REACHABLE", "reachable": "REACHABLE",
            "inactive": "UNREACHABLE", "unreachable": "UNREACHABLE",
            "unknown": "UNKNOWN",
        }.get(status, "UNKNOWN")
        return {
            "reachability": reachability,
            "line_type": str(line_type.get("type") or "UNKNOWN"),
            "carrier": str(line_type.get("carrier_name") or "UNKNOWN"),
            "provider": "twilio_lookup_v2",
            "provider_valid": payload.get("valid"),
            "provider_status": status.upper() or "UNKNOWN",
            "checked": True,
        }
