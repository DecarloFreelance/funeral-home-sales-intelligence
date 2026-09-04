from __future__ import annotations

import os
from pathlib import Path

from operator_ui.app import create_app
from operator_ui.auth import AuthStore


def production_app(environment=None):
    values = environment or os.environ
    
    # Use the complete dataset directly from the data directory
    PROJECT_ROOT = Path(__file__).resolve().parents[1]
    DATA_ROOT = PROJECT_ROOT / "data"
    findings_path = DATA_ROOT / "portal_findings.json"
    
    # Check if the file exists
    if not findings_path.is_file():
        # Fallback to old path if new one doesn't exist
        findings_path = Path(values.get("PORTAL_FINDINGS_PATH", ""))
        if not findings_path.is_file():
            raise RuntimeError(f"Portal findings file not found at: {findings_path}")
    
    # Initialize auth
    auth_path = Path(values.get("OPERATOR_UI_AUTH_DB", "/tmp/operator_auth.sqlite"))
    AuthStore(auth_path).initialize(values.get("OPERATOR_UI_BOOTSTRAP_PASSWORD", "funeral"))
    
    return create_app({
        "SECRET_KEY": values.get("OPERATOR_UI_SECRET_KEY", "dev-secret-key"),
        "AUTH_DB": auth_path,
        "AUTH_REQUIRED": True,
        "FINDINGS_PATH": findings_path,
        "DATA_ROOT": DATA_ROOT,
        "SESSION_COOKIE_SECURE": True,
    })


app = production_app()
