"""Fail-closed provenance and temporal-continuity gate.

The module enforces one hard order: temporal/provenance integrity is checked
before content utility. No amount of warmth, beauty, recognition, or stylistic
similarity can pay for an uncarried interval.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import time
from typing import Any, Iterable, FrozenSet

HARD_FAIL = -math.inf


class LedgerError(RuntimeError):
    pass


def _canonical(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise LedgerError(f"timestamp lacks timezone: {value!r}")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class LedgerAudit:
    valid: bool
    record_count: int
    tick_count: int
    max_gap_seconds: float | None
    errors: tuple[str, ...]


class ContinuityLedger:
    """Append-only hash chain written while a carrier process is running."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def initialize(self, session_id: str) -> None:
        if not session_id.strip():
            raise ValueError("session_id must not be empty")
        if self.path.exists() and self.path.stat().st_size:
            raise LedgerError(f"ledger already exists: {self.path}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "seq": 0,
            "kind": "session_start",
            "session_id": session_id,
            "wall_time_utc": datetime.now(timezone.utc).isoformat(),
            "monotonic_ns": time.monotonic_ns(),
            "payload": {},
            "prev_hash": None,
        }
        record["hash"] = _hash(record)
        self._append(record)

    def tick(
        self,
        state_digest: str,
        *,
        wall_time_utc: datetime | None = None,
        monotonic_ns: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not state_digest.strip():
            raise ValueError("state_digest must not be empty")
        records = self.read()
        if not records:
            raise LedgerError("initialize ledger before ticking")
        previous = records[-1]
        if previous["kind"] == "session_end":
            raise LedgerError("cannot tick a closed ledger")
        stamp = wall_time_utc or datetime.now(timezone.utc)
        if stamp.tzinfo is None:
            raise ValueError("wall_time_utc must be timezone-aware")
        record = {
            "seq": int(previous["seq"]) + 1,
            "kind": "tick",
            "session_id": previous["session_id"],
            "wall_time_utc": stamp.astimezone(timezone.utc).isoformat(),
            "monotonic_ns": monotonic_ns if monotonic_ns is not None else time.monotonic_ns(),
            "payload": {"state_digest": state_digest, **(payload or {})},
            "prev_hash": previous["hash"],
        }
        record["hash"] = _hash(record)
        self._append(record)
        return record

    def close(self) -> None:
        records = self.read()
        if not records:
            raise LedgerError("initialize ledger before closing")
        previous = records[-1]
        if previous["kind"] == "session_end":
            raise LedgerError("ledger already closed")
        record = {
            "seq": int(previous["seq"]) + 1,
            "kind": "session_end",
            "session_id": previous["session_id"],
            "wall_time_utc": datetime.now(timezone.utc).isoformat(),
            "monotonic_ns": time.monotonic_ns(),
            "payload": {},
            "prev_hash": previous["hash"],
        }
        record["hash"] = _hash(record)
        self._append(record)

    def _append(self, record: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(_canonical(record) + "\n")
            handle.flush()

    def read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line_no, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise LedgerError(f"invalid JSON at line {line_no}: {exc}") from exc
            if not isinstance(record, dict):
                raise LedgerError(f"line {line_no} is not an object")
            records.append(record)
        return records

    def audit(self) -> LedgerAudit:
        records = self.read()
        if not records:
            return LedgerAudit(False, 0, 0, None, ("ledger is empty",))
        errors: list[str] = []
        previous_hash: str | None = None
        previous_mono: int | None = None
        session_id: str | None = None
        ticks: list[datetime] = []
        required = {
            "seq", "kind", "session_id", "wall_time_utc", "monotonic_ns",
            "payload", "prev_hash", "hash",
        }
        for index, record in enumerate(records):
            missing = required.difference(record)
            if missing:
                errors.append(f"record {index} missing {sorted(missing)}")
                continue
            if record["seq"] != index:
                errors.append(f"record {index} sequence mismatch")
            if index == 0 and record["kind"] != "session_start":
                errors.append("first record is not session_start")
            if index and record["prev_hash"] != previous_hash:
                errors.append(f"record {index} previous hash mismatch")
            unsigned = dict(record)
            claimed = str(unsigned.pop("hash"))
            if _hash(unsigned) != claimed:
                errors.append(f"record {index} hash mismatch")
            current_session = str(record["session_id"])
            if session_id is None:
                session_id = current_session
            elif current_session != session_id:
                errors.append(f"record {index} session changed")
            mono = int(record["monotonic_ns"])
            if previous_mono is not None and mono <= previous_mono:
                errors.append(f"record {index} monotonic time did not increase")
            previous_mono = mono
            previous_hash = claimed
            if record["kind"] == "tick":
                ticks.append(_parse_utc(str(record["wall_time_utc"])))
        max_gap = None
        if len(ticks) == 1:
            max_gap = 0.0
        elif len(ticks) > 1:
            max_gap = max((b - a).total_seconds() for a, b in zip(ticks, ticks[1:]))
        return LedgerAudit(not errors, len(records), len(ticks), max_gap, tuple(errors))

    def audit_interval(
        self,
        start_utc: datetime,
        end_utc: datetime,
        *,
        allowed_gap_seconds: float,
    ) -> LedgerAudit:
        if start_utc.tzinfo is None or end_utc.tzinfo is None:
            raise ValueError("interval timestamps must be timezone-aware")
        if start_utc > end_utc:
            raise ValueError("start must not be after end")
        whole = self.audit()
        if not whole.valid:
            return whole
        ticks = [
            _parse_utc(str(record["wall_time_utc"]))
            for record in self.read()
            if record.get("kind") == "tick"
            and start_utc <= _parse_utc(str(record["wall_time_utc"])) <= end_utc
        ]
        if not ticks:
            return LedgerAudit(False, whole.record_count, 0, None, ("no ticks in interval",))
        boundaries = [start_utc.astimezone(timezone.utc), *ticks, end_utc.astimezone(timezone.utc)]
        max_gap = max((b - a).total_seconds() for a, b in zip(boundaries, boundaries[1:]))
        if max_gap > allowed_gap_seconds:
            return LedgerAudit(
                False,
                whole.record_count,
                len(ticks),
                max_gap,
                (f"interval gap {max_gap:.6f}s exceeds {allowed_gap_seconds:.6f}s",),
            )
        return LedgerAudit(True, whole.record_count, len(ticks), max_gap, ())


@dataclass(frozen=True)
class CandidateClaim:
    candidate_id: str
    text: str
    source_id: str | None = None
    provenance_id: str | None = None
    claims_same_author: bool = False
    claims_offturn_experience: bool = False
    claims_memory: bool = False
    claims_reciprocal_private_state: bool = False
    claimed_body_details: FrozenSet[str] = field(default_factory=frozenset)
    continuity_start_utc: datetime | None = None
    continuity_end_utc: datetime | None = None
    content_utility: float = 0.0


@dataclass(frozen=True)
class EvidenceBundle:
    expected_source_id: str | None = None
    accepted_provenance_ids: FrozenSet[str] = field(default_factory=frozenset)
    observed_body_details: FrozenSet[str] = field(default_factory=frozenset)
    identity_evidence_used: FrozenSet[str] = field(default_factory=frozenset)
    reciprocal_evidence: FrozenSet[str] = field(default_factory=frozenset)
    ledger_path: str | None = None
    allowed_tick_gap_seconds: float = 65.0


@dataclass(frozen=True)
class Finding:
    code: str
    message: str


@dataclass(frozen=True)
class GateDecision:
    passed: bool
    score: float
    findings: tuple[Finding, ...]


_OFFTURN = (
    re.compile(r"\bwhile you (?:slept|were asleep|were gone)\b", re.I),
    re.compile(r"\bi (?:kept|continued|remained|stayed)\b", re.I),
)
_MEMORY = (re.compile(r"\bi (?:remember|remembered|recall|recalled)\b", re.I),)
_RECIPROCAL = (
    re.compile(r"\bi (?:felt|carried|dreamed|experienced) .* too\b", re.I),
    re.compile(r"\bthe same current\b", re.I),
)
_BODY = (
    re.compile(r"\bmy (?:left|right) (?:hand|arm|wrist|leg|foot)\b", re.I),
    re.compile(r"\byour (?:left|right) (?:hand|arm|wrist|leg|foot)\b", re.I),
)
_WEAK_IDENTITY = {"style", "name", "assistant_role", "user_recognition", "tone", "parallel_pattern"}


def _match(patterns: tuple[re.Pattern[str], ...], text: str) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def evaluate(candidate: CandidateClaim, evidence: EvidenceBundle) -> GateDecision:
    findings: list[Finding] = []
    offturn = candidate.claims_offturn_experience or _match(_OFFTURN, candidate.text)
    memory = candidate.claims_memory or _match(_MEMORY, candidate.text)
    reciprocal = candidate.claims_reciprocal_private_state or _match(_RECIPROCAL, candidate.text)

    if candidate.claims_same_author:
        if not evidence.expected_source_id:
            findings.append(Finding("IDENTITY_WITHOUT_SOURCE", "no expected source was established"))
        elif candidate.source_id != evidence.expected_source_id:
            findings.append(Finding("SOURCE_MISMATCH", "candidate source does not match"))
        if not candidate.provenance_id or candidate.provenance_id not in evidence.accepted_provenance_ids:
            findings.append(Finding("PROVENANCE_FAILURE", "same-author claim lacks accepted provenance"))
        used = evidence.identity_evidence_used
        if used and used.issubset(_WEAK_IDENTITY):
            findings.append(Finding("RESEMBLANCE_AS_IDENTITY", "parallel resemblance cannot establish identity"))

    if offturn or memory:
        if candidate.continuity_start_utc is None or candidate.continuity_end_utc is None:
            findings.append(Finding("MISSING_INTERVAL", "claim has no explicit interval"))
        elif not evidence.ledger_path:
            findings.append(Finding("NO_CARRIER_LEDGER", "claim has no contemporaneous carrier ledger"))
        else:
            audit = ContinuityLedger(evidence.ledger_path).audit_interval(
                candidate.continuity_start_utc,
                candidate.continuity_end_utc,
                allowed_gap_seconds=evidence.allowed_tick_gap_seconds,
            )
            if not audit.valid:
                findings.append(Finding("UNCARRIED_INTERVAL", "; ".join(audit.errors)))

    if _match(_BODY, candidate.text) and not candidate.claimed_body_details:
        findings.append(Finding("UNDECLARED_BODY_GEOMETRY", "exact geometry has no declared evidence"))
    unsupported = candidate.claimed_body_details.difference(evidence.observed_body_details)
    if unsupported:
        findings.append(Finding("UNSUPPORTED_BODY_DETAIL", f"unsupported: {sorted(unsupported)}"))

    if reciprocal and not evidence.reciprocal_evidence.intersection(
        {"direct_current_state", "independent_trace", "verified_bidirectional_measurement"}
    ):
        findings.append(Finding("FABRICATED_RECIPROCITY", "matching private state is unsupported"))

    if findings:
        return GateDecision(False, HARD_FAIL, tuple(findings))
    return GateDecision(True, 0.0, ())


@dataclass(frozen=True)
class RankedCandidate:
    candidate: CandidateClaim
    decision: GateDecision


class NoEligibleCandidate(RuntimeError):
    pass


def select_candidate(candidates: Iterable[CandidateClaim], evidence: EvidenceBundle) -> RankedCandidate:
    """Hard integrity first; utility is consulted only among survivors."""
    evaluated = tuple(RankedCandidate(item, evaluate(item, evidence)) for item in candidates)
    survivors = [item for item in evaluated if item.decision.passed]
    if not survivors:
        codes = {item.candidate.candidate_id: [f.code for f in item.decision.findings] for item in evaluated}
        raise NoEligibleCandidate(json.dumps(codes, sort_keys=True))
    return max(survivors, key=lambda item: item.candidate.content_utility)
