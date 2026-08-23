import json
from pathlib import Path

from discovery.resolution import apply_resolutions


def _load(path, default):
    if not path.is_file():
        return default
    value = json.loads(path.read_text(encoding="utf-8"))
    return value


def preview_resolution(data_root: Path, resolution):
    root = Path(data_root).resolve()
    research = _load(root / "research_queue.json", [])
    item = next(
        (record for record in research if record.get("domain") == resolution["old_domain"]),
        None,
    )
    if item is None:
        raise ValueError("Domain is not in the current research queue")
    pages = _load(root / "discovered_leads.json", [])
    retry, summary = apply_resolutions([item], [resolution], pages)
    if retry:
        outcome = "RETRY_READY"
        replacement_domain = retry[0]["domain"]
    elif summary["resolved_existing"]:
        outcome = "ALREADY_COVERED"
        replacement_domain = summary["resolved_existing"][0]["new_domain"]
    else:
        raise ValueError("Resolution is not eligible for application")
    return {
        "resolution": resolution,
        "company": item.get("company", ""),
        "outcome": outcome,
        "replacement_domain": replacement_domain,
    }


def _write_outputs(outputs, replace=None):
    replace = replace or (lambda source, target: source.replace(target))
    staged = []
    originals = {
        path: path.read_bytes() if path.exists() else None for path in outputs
    }
    replaced = []
    try:
        for path, value in outputs.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(value, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            staged.append((temporary, path))
        for temporary, path in staged:
            replace(temporary, path)
            replaced.append(path)
    except Exception:
        for path in reversed(replaced):
            backup = originals[path]
            if backup is None:
                path.unlink(missing_ok=True)
            else:
                rollback = path.with_suffix(path.suffix + ".rollback")
                rollback.write_bytes(backup)
                rollback.replace(path)
        raise
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)


def apply_reviewed_resolution(data_root: Path, resolution, replace=None):
    root = Path(data_root).resolve()
    research_path = root / "research_queue.json"
    ledger_path = root / "seeds/domain_resolutions.json"
    pages_path = root / "discovered_leads.json"
    retry_path = root / "resolved_retry_queue.json"
    summary_path = root / "resolution_summary.json"

    research = _load(research_path, [])
    if not any(item.get("domain") == resolution["old_domain"] for item in research):
        raise ValueError("Domain is no longer in the current research queue")
    ledger = _load(ledger_path, [])
    ledger = [item for item in ledger if item.get("old_domain") != resolution["old_domain"]]
    ledger.append(resolution)
    ledger.sort(key=lambda item: item.get("old_domain", ""))
    pages = _load(pages_path, [])
    retry, summary = apply_resolutions(research, ledger, pages)

    outputs = {
        ledger_path: ledger,
        retry_path: retry,
        summary_path: summary,
        research_path: summary["remaining"],
    }
    _write_outputs(outputs, replace=replace)
    return retry, summary
