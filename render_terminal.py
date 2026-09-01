#!/usr/bin/env python3
"""Small, explicit Render API helper for terminal operations."""

import argparse
import getpass
import json
import os
import stat
import sys
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parent
SECRETS = ROOT / ".render.env"
API = "https://api.render.com/v1"


def read_key():
    value = os.environ.get("RENDER_API_KEY", "").strip()
    if value:
        return value
    if SECRETS.exists():
        for line in SECRETS.read_text(encoding="utf-8").splitlines():
            if line.startswith("RENDER_API_KEY="):
                return line.split("=", 1)[1].strip()
    return ""


def request(path, key, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = Request(API + path, data=data, method=method, headers={
        "Accept": "application/json", "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    })
    try:
        with urlopen(req, timeout=30) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else {}
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Render API returned HTTP {error.code}: {detail[:500]}")
    except URLError as error:
        raise SystemExit(f"Could not reach Render API: {error.reason}")


def setup():
    print("Render API keys are secret; they will not be printed or committed.")
    key = getpass.getpass("Render API key: ").strip()
    if not key:
        raise SystemExit("No API key entered")
    SECRETS.write_text(f"RENDER_API_KEY={key}\n", encoding="utf-8")
    SECRETS.chmod(stat.S_IRUSR | stat.S_IWUSR)
    status, payload = request("/services?limit=1", key)
    print(json.dumps({"authenticated": status == 200, "services_returned": len(payload) if isinstance(payload, list) else len(payload.get("items", []))}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("setup", help="prompt for key, store locally, and validate it")
    sub.add_parser("services", help="list Render services")
    deploy = sub.add_parser("deploy", help="explicitly trigger a service deploy")
    deploy.add_argument("service_id")
    deploy.add_argument("--commit", dest="commit_id")
    deploy.add_argument("--clear-cache", action="store_true")
    args = parser.parse_args()
    if args.command == "setup":
        setup(); return
    key = read_key()
    if not key:
        raise SystemExit("No Render key configured. Run: python render_terminal.py setup")
    if args.command == "services":
        _status, payload = request("/services?limit=100", key)
        print(json.dumps(payload, indent=2))
    else:
        body = {}
        if args.commit_id: body["commitId"] = args.commit_id
        if args.clear_cache: body["clearCache"] = "clear"
        _status, payload = request(f"/services/{args.service_id}/deploys", key, "POST", body)
        print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
