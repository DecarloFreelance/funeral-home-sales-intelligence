import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

from discovery.autonomous import (
    DiscoveryBudget, DiscoveryCandidate, DiscoveryStore,
    NationalDiscoveryCoordinator, PlannedQuery, QueryPlanner, saturation_status,
    stable_id, verify_candidate,
)
from discovery_cli import main


def candidate(**changes):
    value = DiscoveryCandidate(
        "North Star Funeral Home", "https://northstar.example.ca",
        municipality="Calgary", province="AB", source_url="https://search.test/1",
        source_identity="result-1", **changes,
    )
    return value.__dict__.copy()


def good_evidence(final="https://northstar.example.ca/"):
    return {"reachable": True, "final_url": final, "title": "North Star Funeral Home",
            "text": "North Star Funeral Home serves Calgary, AB. Funeral and cremation services.",
            "identity_marker": True, "redirect_chain": ["https://northstar.example.ca/", final]}


def test_candidate_is_deterministic_and_retains_complete_provenance():
    one = DiscoveryCandidate.from_mapping({"company":"A Funeral Home","website":"https://a.ca","phone":"1","email":"x@a.ca","address":"1 Main","city":"Regina","province":"SK","postal_code":"S4P","source_url":"https://source/1"}, query="q", provider="fixture")
    two = DiscoveryCandidate.from_mapping(copy.deepcopy(one.raw_source_value), query="q", provider="fixture")
    assert one.candidate_id == two.candidate_id
    assert one.raw_source_value["phone"] == "1"
    assert one.detector_version and one.stale_after and one.normalized_url_candidate == "https://a.ca/"


@pytest.mark.parametrize("url", ["http://info@fostercmgarvey.com", "javascript:alert(1)", "https://localhost"])
def test_malformed_and_foster_userinfo_are_rejected(url):
    item = DiscoveryCandidate("Foster", url, source_identity=url)
    assert item.status == "REJECTED"
    assert item.rejection_reasons == ["MALFORMED_WEBSITE"]
    assert not item.normalized_url_candidate


def test_high_confidence_first_party_candidate_is_publishable(tmp_path):
    store = DiscoveryStore(tmp_path/"state.json")
    value = verify_candidate(candidate(), good_evidence(), store.data["organizations"])
    store.data["candidates"][value["candidate_id"]] = value
    assert value["status"] == "ENRICHMENT_READY" and value["confidence"] >= .85
    assert store.publish(value) == "PUBLISHED"
    assert len(store.data["organizations"]) == 1


def test_generic_directory_is_never_first_party_publishable():
    value = verify_candidate(candidate(), {"reachable":True,"final_url":"https://directory.ca","title":"Business directory","text":"Listings in Calgary","identity_marker":False}, {})
    assert value["status"] in {"REJECTED", "QUARANTINED"}
    assert value["status"] != "ENRICHMENT_READY"


def test_location_mismatch_parent_ambiguity_and_unrelated_redirect_fail_closed():
    mismatch = good_evidence(); mismatch["country_mismatch"] = True
    assert verify_candidate(candidate(), mismatch, {})["quarantine_reasons"] == ["CANADIAN_LOCATION_MISMATCH"]
    parent = good_evidence(); parent["parent_location_ambiguous"] = True
    assert verify_candidate(candidate(), parent, {})["status"] == "QUARANTINED"
    redirected = verify_candidate(candidate(), good_evidence("https://unrelated.ca/"), {})
    assert "REDIRECT_IDENTITY_AMBIGUITY" in redirected["quarantine_reasons"]


def test_canonical_equivalent_redirect_is_supported():
    value = candidate()
    evidence = good_evidence("https://northstar.example.ca/contact/")
    result = verify_candidate(value, evidence, {})
    assert result["status"] == "ENRICHMENT_READY"


def test_shared_domain_preserves_locations_without_duplicate_org_explosion(tmp_path):
    store = DiscoveryStore(tmp_path/"state.json")
    store.seed([{"domain":"northstar.example.ca","company":"North Star Group","locations":[{"city":"Calgary","province":"AB"},{"city":"Airdrie","province":"AB"}]}])
    value = verify_candidate(candidate(), good_evidence(), store.data["organizations"])
    assert value["status"] == "QUARANTINED"
    assert "SHARED_DOMAIN_AMBIGUITY" in value["quarantine_reasons"]
    assert len(store.data["organizations"]) == 1
    assert len(store.data["organizations"]["northstar.example.ca"]["locations"]) == 2


def test_existing_exact_organization_is_duplicate_not_new(tmp_path):
    class Provider:
        name="fixture"
        def search(self,q,**kw): return {"results":[{"company":"North Star Funeral Home","website":"https://northstar.example.ca","source_identity":"1","verification":good_evidence()}]}
    store=DiscoveryStore(tmp_path/"s.json"); store.seed([{"domain":"northstar.example.ca","company":"North Star Funeral Home","locations":[{"city":"Calgary","province":"AB"}]}])
    plan=[PlannedQuery("q","GEOGRAPHIC","AB","fixture",stable_id("q"))]
    result=NationalDiscoveryCoordinator(store,Provider(),lambda c:c["raw_source_value"]["verification"],DiscoveryBudget(max_queries=1)).run(plan)
    assert result["organizations_newly_published"] == 0 and len(store.data["organizations"]) == 1


def test_rejected_verification_is_reported(tmp_path):
    class Provider:
        name="fixture"
        def search(self,q,**kw): return {"results":[{"company":"Directory","website":"https://directory.ca","source_identity":"directory"}]}
    store=DiscoveryStore(tmp_path/"s.json")
    plan=[PlannedQuery("q","GEOGRAPHIC","AB","fixture",stable_id("rejected-q"))]
    result=NationalDiscoveryCoordinator(store,Provider(),lambda c:{"reachable":True,"final_url":"https://directory.ca","title":"Directory","text":"Business listings","identity_marker":False},DiscoveryBudget(max_queries=1)).run(plan)
    assert result["rejected"] == 1 and result["retryable_failures"] == 0


def test_query_planner_is_deterministic_gap_first_bilingual_and_suppresses_fresh_query():
    seed=[{"domain":"a.ca","locations":[{"city":"Montreal","province":"QC"}]}]
    planner=QueryPlanner("fixture")
    first=planner.plan(seed,{},limit=20); second=planner.plan(seed,{},limit=20)
    assert first == second and first[0].geography in {"BC","AB","MB","NB","NL","NS","NT","NU","ON","PE","SK","YT"}
    qc=planner.plan(seed,{},limit=200)
    assert any("funéraire" in x.query for x in qc)
    ledger={first[0].fingerprint:{"status":"COMPLETED","stale_after":"2099-01-01T00:00:00Z"}}
    assert first[0].fingerprint not in {x.fingerprint for x in planner.plan(seed,ledger,limit=20)}


def test_stale_query_becomes_eligible():
    planner=QueryPlanner("fixture"); first=planner.plan([],{},limit=1)[0]
    ledger={first.fingerprint:{"status":"COMPLETED","stale_after":"2000-01-01T00:00:00Z"}}
    assert planner.plan([],ledger,limit=1)[0].fingerprint == first.fingerprint


def test_provider_error_checkpoints_retry_and_quota_like_stop(tmp_path):
    class Broken:
        name="fixture"
        def search(self,*a,**k): raise RuntimeError("quota")
    store=DiscoveryStore(tmp_path/"s.json"); query=PlannedQuery("q","G","AB","fixture","f")
    NationalDiscoveryCoordinator(store,Broken(),lambda c:{},DiscoveryBudget(max_queries=1)).run([query])
    assert store.data["query_ledger"]["f"]["status"] == "RETRYABLE_FAILURE"
    assert json.loads((tmp_path/"s.json").read_text())["query_ledger"]["f"]["retry_state"]["attempts"] == 1


def test_repeated_run_does_not_respend_completed_query(tmp_path):
    class Provider:
        name="fixture"; calls=0
        def search(self,*a,**k): self.calls+=1; return {"results":[]}
    store=DiscoveryStore(tmp_path/"s.json"); p=Provider(); planner=QueryPlanner("fixture")
    plan=planner.plan([],store.data["query_ledger"],limit=1)
    NationalDiscoveryCoordinator(store,p,lambda c:{},DiscoveryBudget(max_queries=1)).run(plan)
    assert planner.plan([],store.data["query_ledger"],limit=1)[0].fingerprint != plan[0].fingerprint


def test_dry_run_mutates_no_state_or_pilot_events(tmp_path):
    seed=tmp_path/"seed.json"; export=tmp_path/"export.json"; state=tmp_path/"state.json"; pilot=tmp_path/"pilot.json"
    seed.write_text("[]"); export.write_text("[]"); pilot.write_text('[{"event":"sentinel"}]\n'); before=pilot.read_bytes()
    assert main(["autonomous","--budget","1","--seed",str(seed),"--state",str(state),"--search-export",str(export),"--dry-run"]) == 0
    assert not state.exists() and pilot.read_bytes() == before


def test_plan_only_mutates_nothing_and_budget_is_enforced(tmp_path, capsys):
    seed=tmp_path/"seed.json"; seed.write_text("[]"); state=tmp_path/"state.json"
    assert main(["autonomous","--budget","2","--seed",str(seed),"--state",str(state),"--plan-only"]) == 0
    output=json.loads(capsys.readouterr().out)
    assert len(output["queries"]) == 2 and output["mutated"] is False and not state.exists()


def test_publication_guard_is_transactional(tmp_path):
    store=DiscoveryStore(tmp_path/"s.json"); before=copy.deepcopy(store.data)
    with pytest.raises(ValueError): store.publish(candidate())
    assert store.data == before


def test_quarantined_candidate_cannot_publish_without_new_evidence(tmp_path):
    store=DiscoveryStore(tmp_path/"s.json"); value=verify_candidate(candidate(),{"reachable":True,"final_url":"https://northstar.example.ca","title":"North Star","text":"funeral Calgary","identity_marker":False},{})
    assert value["status"] == "QUARANTINED"
    with pytest.raises(ValueError): store.publish(value)
    resolved=verify_candidate(value,good_evidence(),{})
    assert resolved["status"] == "ENRICHMENT_READY"


def test_low_yield_exhaustion_never_claims_completeness():
    ledger={str(i):{"status":"COMPLETED","strategy":"G","geography":"AB","executed_at":f"2026-01-{i+1:02d}T00:00:00Z","novel_verified_organization_count":0} for i in range(5)}
    status=saturation_status(ledger,DiscoveryBudget(saturation_min_queries=5,saturation_batches=1))
    assert status["national_completeness_claimed"] is False
    assert status["segments"]["G:AB"]["status"] == "DISCOVERY_SATURATED_UNDER_CURRENT_STRATEGIES"
