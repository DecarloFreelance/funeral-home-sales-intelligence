from __future__ import annotations

import os
from pathlib import Path

from operator_ui.app import create_app
from operator_ui.auth import AuthStore


def _required(values, name):
    value = str(values.get(name, "")).strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value

def production_app(environment=None):
    values = os.environ if environment is None else environment
    PROJECT_ROOT = Path(__file__).resolve().parents[1]
    DATA_ROOT = PROJECT_ROOT / "data"

    findings_path = Path(_required(values, "PORTAL_FINDINGS_PATH"))
    if not findings_path.is_file():
        raise RuntimeError(f"Portal findings file not found: {findings_path}")
    secret_key = _required(values, "OPERATOR_UI_SECRET_KEY")
    bootstrap_password = _required(values, "OPERATOR_UI_BOOTSTRAP_PASSWORD")
    auth_path = Path(values.get("OPERATOR_UI_AUTH_DB", str(PROJECT_ROOT / "instance" / "operator_auth.sqlite")))
    AuthStore(auth_path).initialize(bootstrap_password)
    
    return create_app({
        "SECRET_KEY": secret_key,
        "AUTH_DB": auth_path,
        "AUTH_REQUIRED": True,
        "FINDINGS_PATH": findings_path,
        "DATA_ROOT": DATA_ROOT,
        "SESSION_COOKIE_SECURE": True,
    })

app = production_app()
