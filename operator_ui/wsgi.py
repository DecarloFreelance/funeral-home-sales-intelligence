from __future__ import annotations

import os
from pathlib import Path

from operator_ui.app import create_app
from operator_ui.auth import AuthStore


def production_app(environment=None):
    values = environment or os.environ
    required = ("OPERATOR_UI_SECRET_KEY", "OPERATOR_UI_BOOTSTRAP_PASSWORD", "PORTAL_FINDINGS_PATH")
    missing = [key for key in required if not values.get(key)]
    if missing:
        raise RuntimeError("Missing required portal configuration: " + ", ".join(missing))
    findings_path = Path(values["PORTAL_FINDINGS_PATH"]).resolve()
    if not findings_path.is_file():
        raise RuntimeError(f"Portal findings secret file is missing: {findings_path}")
    auth_path = Path(values.get("OPERATOR_UI_AUTH_DB", "/tmp/operator_auth.sqlite"))
    AuthStore(auth_path).initialize(values["OPERATOR_UI_BOOTSTRAP_PASSWORD"])
    return create_app({
        "SECRET_KEY": values["OPERATOR_UI_SECRET_KEY"], "AUTH_DB": auth_path,
        "AUTH_REQUIRED": True, "FINDINGS_PATH": findings_path,
        "SESSION_COOKIE_SECURE": True,
    })


app = production_app()
