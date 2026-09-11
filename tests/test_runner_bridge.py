import json
from pathlib import Path

from automation.runner_bridge import coordinated_run
from automation.task_coordinator import TaskCoordinator
from run_enrichment import run_coordinated as run_enrichment_coordinated
from run_research_resolution import run_coordinated as run_research_coordinated


def _manifest(path):
    path.write_text(json.dumps({
        "schema_version": 2,
        "tasks": [{
            "id": "AUTOMATION-TEST", "task_version": 1, "title": "Test runner",
            "owner": None, "declared_status": "ACTIVE", "depends_on": [],
            "requires_review": True, "audit_refs": [],
        }],
    }), encoding="utf-8")


def test_runner_claims_reconciles_review_and_reuses_unchanged_input(tmp_path):
    manifest = tmp_path / "manifest.json"
    state = tmp_path / "state.json"
    input_path, output_path = tmp_path / "input.json", tmp_path / "output.json"
    input_path.write_text('{"input": 1}', encoding="utf-8")
    _manifest(manifest)
    calls = []

    def run():
        calls.append("run")
        output_path.write_text('{"output": 1}', encoding="utf-8")
        return {"needs_review": 1}

    first = coordinated_run(TaskCoordinator(manifest, state), "AUTOMATION-TEST", "worker", [input_path], [output_path], run)
    second = coordinated_run(TaskCoordinator(manifest, state), "AUTOMATION-TEST", "worker", [input_path], [output_path], run)
    assert first == second == {"needs_review": 1}
    assert calls == ["run"]
    saved = json.loads(state.read_text(encoding="utf-8"))
    assert saved["tasks"]["AUTOMATION-TEST"]["execution_status"] == "COMPLETED"
    assert saved["tasks"]["AUTOMATION-TEST"]["review_status"] == "REVIEW"


def test_runner_failure_is_reconciled_as_retryable_execution(tmp_path):
    manifest = tmp_path / "manifest.json"
    state = tmp_path / "state.json"
    input_path, output_path = tmp_path / "input.json", tmp_path / "output.json"
    input_path.write_text('{"input": 1}', encoding="utf-8")
    _manifest(manifest)

    def run():
        raise RuntimeError("bounded failure")

    try:
        coordinated_run(TaskCoordinator(manifest, state), "AUTOMATION-TEST", "worker", [input_path], [output_path], run)
    except RuntimeError:
        pass
    else:
        raise AssertionError("runner failure was swallowed")
    saved = json.loads(state.read_text(encoding="utf-8"))
    assert saved["tasks"]["AUTOMATION-TEST"]["execution_status"] == "FAILED"
    assert [item["id"] for item in TaskCoordinator(manifest, state).list_ready_tasks()] == ["AUTOMATION-TEST"]


def test_enrichment_runner_enters_governed_path(tmp_path):
    pages = tmp_path / "pages.json"
    results = tmp_path / "results.json"
    output, state, audit, review = (tmp_path / name for name in ("output.json", "state.json", "audit.json", "review.json"))
    pages.write_text(json.dumps([{
        "url": "https://example.ca/", "markdown": "Funeral services.", "html": "",
        "metadata": {}, "discovery": {"queue_domain": "example.ca"},
    }]), encoding="utf-8")
    results.write_text(json.dumps([{
        "domain": "example.ca", "business_profile": {"company": "Example"},
        "contact_intelligence": {"emails": [], "phones": [], "people": []},
    }]), encoding="utf-8")
    summary = run_enrichment_coordinated(
        pages, results, output, state, audit, review,
        Path("automation/task_manifest.json"), tmp_path / "coordinator.json", "enrichment-test",
    )
    assert summary["records"] == 1
    coordinator_state = json.loads((tmp_path / "coordinator.json").read_text(encoding="utf-8"))
    assert coordinator_state["tasks"]["AUTOMATION-ENRICHMENT"]["execution_status"] == "COMPLETED"
    assert coordinator_state["tasks"]["AUTOMATION-ENRICHMENT"]["review_status"] == "REVIEW"


def test_research_runner_enters_governed_path_without_resolution_approval(tmp_path):
    research = tmp_path / "research.json"
    review = tmp_path / "review.json"
    output, queue, state, audit = (tmp_path / name for name in ("output.json", "queue.json", "state.json", "audit.json"))
    research.write_text(json.dumps([{"domain": "branch.example", "company": "Branch", "attempts": [], "locations": []}]), encoding="utf-8")
    review.write_text(json.dumps([{"domain": "branch.example", "findings": [{"id": "f1", "code": "NO_USABLE_WEBSITE_EVIDENCE", "evidence": {}}]}]), encoding="utf-8")
    summary = run_research_coordinated(
        research, review, output, queue, state, audit,
        Path("automation/task_manifest.json"), tmp_path / "coordinator.json", "research-test",
    )
    assert summary["ambiguous"] == 1
    coordinator_state = json.loads((tmp_path / "coordinator.json").read_text(encoding="utf-8"))
    assert coordinator_state["tasks"]["AUTOMATION-RESEARCH-RESOLUTION"]["execution_status"] == "COMPLETED"
    assert coordinator_state["tasks"]["AUTOMATION-RESEARCH-RESOLUTION"]["review_status"] == "REVIEW"
