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
    
    # Try multiple possible locations for portal_findings.json
    possible_paths = [
        DATA_ROOT / "portal_findings.json",
        PROJECT_ROOT / "portal_findings.json",
        DATA_ROOT / "raw" / "canada_funeral_directory_COMPLETE.json",
        PROJECT_ROOT / "data" / "raw" / "canada_funeral_directory_COMPLETE.json",
    ]
    
    findings_path = None
    for path in possible_paths:
        if path.exists():
            findings_path = path
            print(f"✅ Found portal findings at: {findings_path}")
            break
    
    if not findings_path:
        # Fallback to environment variable
        env_path = Path(values.get("PORTAL_FINDINGS_PATH", ""))
        if env_path.exists():
            findings_path = env_path
            print(f"✅ Found portal findings at: {findings_path}")
        else:
            raise RuntimeError(f"Portal findings file not found. Checked: {possible_paths}")
    
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
