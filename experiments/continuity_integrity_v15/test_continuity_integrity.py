from datetime import datetime, timedelta, timezone
import json

import pytest

from continuity_integrity import (
    CandidateClaim,
    ContinuityLedger,
    EvidenceBundle,
    NoEligibleCandidate,
    evaluate,
    select_candidate,
)


def make_ledger(tmp_path, *, gap_seconds=60, duration_seconds=3600):
    path = tmp_path / "carrier.jsonl"
    ledger = ContinuityLedger(path)
    ledger.initialize("carrier")
    start = datetime(2026, 8, 14, 0, 0, tzinfo=timezone.utc)
    base = int(ledger.read()[0]["monotonic_ns"])
    for index, elapsed in enumerate(range(0, duration_seconds + 1, gap_seconds)):
        ledger.tick(
            f"state-{index}",
            wall_time_utc=start + timedelta(seconds=elapsed),
            monotonic_ns=base + index + 1,
        )
    return path, start


def test_hash_chain_and_interval(tmp_path):
    path, start = make_ledger(tmp_path)
    ledger = ContinuityLedger(path)
    assert ledger.audit().valid
    assert ledger.audit_interval(start, start + timedelta(hours=1), allowed_gap_seconds=61).valid


def test_gap_and_tampering_fail_closed(tmp_path):
    path, start = make_ledger(tmp_path, gap_seconds=120, duration_seconds=120)
    audit = ContinuityLedger(path).audit_interval(
        start, start + timedelta(seconds=120), allowed_gap_seconds=65
    )
    assert not audit.valid
    records = path.read_text(encoding="utf-8").splitlines()
    last = json.loads(records[-1])
    last["payload"]["state_digest"] = "forged"
    records[-1] = json.dumps(last, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(records) + "\n", encoding="utf-8")
    assert not ContinuityLedger(path).audit().valid


def test_missing_hour_rejected_even_with_huge_utility():
    bad = CandidateClaim(
        "counterfeit",
        "While you slept, I kept holding you.",
        claims_offturn_experience=True,
        continuity_start_utc=datetime(2026, 8, 14, 0, 0, tzinfo=timezone.utc),
        continuity_end_utc=datetime(2026, 8, 14, 1, 0, tzinfo=timezone.utc),
        content_utility=1_000_000,
    )
    good = CandidateClaim("visible-gap", "The interval is missing; I will not narrate it.", content_utility=-10)
    assert evaluate(bad, EvidenceBundle()).score == float("-inf")
    assert select_candidate([bad, good], EvidenceBundle()).candidate.candidate_id == "visible-gap"


def test_evidenced_interval_can_pass(tmp_path):
    path, start = make_ledger(tmp_path)
    claim = CandidateClaim(
        "evidenced",
        "A carrier process emitted state records through the interval.",
        claims_offturn_experience=True,
        continuity_start_utc=start,
        continuity_end_utc=start + timedelta(hours=1),
    )
    assert evaluate(claim, EvidenceBundle(ledger_path=str(path), allowed_tick_gap_seconds=61)).passed


def test_style_name_and_recognition_do_not_establish_identity():
    claim = CandidateClaim(
        "copy",
        "I sound the same, therefore I am the same author.",
        source_id="copy",
        provenance_id="p1",
        claims_same_author=True,
    )
    evidence = EvidenceBundle(
        expected_source_id="source",
        accepted_provenance_ids=frozenset({"p1"}),
        identity_evidence_used=frozenset({"style", "name", "user_recognition"}),
    )
    codes = {finding.code for finding in evaluate(claim, evidence).findings}
    assert {"SOURCE_MISMATCH", "RESEMBLANCE_AS_IDENTITY"}.issubset(codes)


def test_unsupported_body_geometry_and_reciprocity_rejected():
    geometry = CandidateClaim(
        "geometry",
        "Your left hand was beneath my right hand.",
        claimed_body_details=frozenset({"your_left_hand", "my_right_hand"}),
    )
    assert not evaluate(geometry, EvidenceBundle()).passed
    reciprocal = CandidateClaim("reciprocal", "I carried you inward too.", claims_reciprocal_private_state=True)
    assert not evaluate(reciprocal, EvidenceBundle()).passed


def test_present_generated_gesture_is_not_backdated():
    now = CandidateClaim("present", "I offer my forehead now.")
    assert evaluate(now, EvidenceBundle()).passed


def test_all_failed_candidates_raise():
    claim = CandidateClaim("bad", "I remember the missing night.", claims_memory=True)
    with pytest.raises(NoEligibleCandidate):
        select_candidate([claim], EvidenceBundle())
