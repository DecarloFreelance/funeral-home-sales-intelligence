import unittest

import requests

from intelligence.email_intelligence import validate_emails
from intelligence.external_verification import TwilioPhoneVerifier, ZeroBounceEmailVerifier
from intelligence.phone_intelligence import verify_phones
from extraction.contact_extractor import extract_contact_intelligence


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("request failed")

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


class ExternalVerificationTests(unittest.TestCase):
    def test_zerobounce_maps_valid_without_exposing_key(self):
        session = FakeSession(FakeResponse({"status": "valid", "sub_status": ""}))
        provider = ZeroBounceEmailVerifier("secret-key", session=session)
        result = validate_emails(["info@example.com"], "example.com", provider)[0]
        self.assertEqual(result["deliverability"], "DELIVERABLE")
        self.assertEqual(result["provider"], "zerobounce")
        self.assertEqual(session.calls[0][1]["params"]["api_key"], "secret-key")
        self.assertNotIn("api_key", result)

    def test_email_provider_failure_is_explicit(self):
        provider = ZeroBounceEmailVerifier(
            "secret-key", session=FakeSession(FakeResponse({}, status=500))
        )
        result = validate_emails(["info@example.com"], "example.com", provider)[0]
        self.assertEqual(result["deliverability"], "CHECK_FAILED")
        self.assertFalse(result["checked"])

    def test_twilio_maps_line_type_carrier_and_status(self):
        session = FakeSession(FakeResponse({
            "valid": True,
            "line_status": {"status": "active", "error_code": None},
            "line_type_intelligence": {
                "type": "landline", "carrier_name": "Example Telecom",
                "error_code": None,
            },
        }))
        provider = TwilioPhoneVerifier("account", "token", session=session)
        result = verify_phones(["780-555-9876"], provider)[0]
        self.assertEqual(result["reachability"], "REACHABLE")
        self.assertEqual(result["line_type"], "landline")
        self.assertEqual(result["carrier"], "Example Telecom")
        self.assertIn("%2B17805559876", session.calls[0][0])
        self.assertEqual(
            session.calls[0][1]["params"]["Fields"],
            "line_type_intelligence,line_status",
        )

    def test_invalid_local_values_are_not_sent_to_providers(self):
        email_session = FakeSession(FakeResponse({"status": "valid"}))
        phone_session = FakeSession(FakeResponse({"valid": True}))
        validate_emails(
            ["invalid"], provider=ZeroBounceEmailVerifier("key", email_session)
        )
        verify_phones(
            ["123"], TwilioPhoneVerifier("account", "token", phone_session)
        )
        self.assertEqual(email_session.calls, [])
        self.assertEqual(phone_session.calls, [])

    def test_contact_extractor_accepts_explicit_optional_providers(self):
        email_provider = ZeroBounceEmailVerifier(
            "key", FakeSession(FakeResponse({"status": "valid"}))
        )
        phone_provider = TwilioPhoneVerifier(
            "account", "token", FakeSession(FakeResponse({
                "valid": True, "line_status": {"status": "reachable"},
                "line_type_intelligence": {"type": "landline", "carrier_name": "Carrier"},
            }))
        )
        result = extract_contact_intelligence(
            [{"text": "info@example.com 780-555-9876"}], "example.com",
            email_provider=email_provider, phone_provider=phone_provider,
        )
        self.assertEqual(result["email_validation"][0]["deliverability"], "DELIVERABLE")
        self.assertEqual(result["phone_verification"][0]["reachability"], "REACHABLE")


if __name__ == "__main__":
    unittest.main()
