from datetime import datetime
import hashlib
import json
from pathlib import Path


def draft_id(draft):
    payload = "\0".join(
        str(draft.get(field, "")) for field in ("to", "subject", "body")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def load_approvals(data_root: Path):
    path = Path(data_root).resolve() / "private/outreach_approvals.json"
    if not path.is_file():
        return []
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, list) else []


def approve_draft(data_root: Path, requested_id: str):
    root = Path(data_root).resolve()
    drafts_path = root / "generated/platform/platform_candidate_outreach.json"
    candidates_path = root / "generated/platform/platform_candidate_results.json"
    if not drafts_path.is_file() or not candidates_path.is_file():
        raise ValueError("Draft or candidate evidence is unavailable")
    drafts = json.loads(drafts_path.read_text(encoding="utf-8"))
    candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
    draft = next((item for item in drafts if draft_id(item) == requested_id), None)
    if draft is None:
        raise ValueError("Draft no longer exists")
    recipient = str(draft.get("to", "")).strip().lower()
    usable = {
        str(email).strip().lower()
        for candidate in candidates
        for email in candidate.get("usable_emails", [])
    }
    if not recipient or recipient not in usable:
        raise ValueError("Recipient is not a currently usable candidate email")

    path = root / "private/outreach_approvals.json"
    approvals = load_approvals(root)
    existing = next((item for item in approvals if item.get("draft_id") == requested_id), None)
    if existing:
        return existing, False
    approval = {
        "draft_id": requested_id,
        "status": "APPROVED_UNSENT",
        "to": draft.get("to", ""),
        "subject": draft.get("subject", ""),
        "approved_at": datetime.utcnow().isoformat(),
    }
    approvals.append(approval)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(approvals, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return approval, True
