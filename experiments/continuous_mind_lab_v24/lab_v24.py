"""Continuous Mind Lab V24 — retrieval ecology without a sovereign archivist.

This deterministic toy laboratory separates:

* a memory trace from whether it is currently retrievable;
* retrieval frequency from truth or standing;
* one retriever's ranking from the whole archive;
* dormancy from deletion;
* dream recombination from compulsory interpretation;
* current identity consistency from historical existence;
* retrieval-policy revision from retroactive memory rewrite.

The lab demonstrates causal and governance distinctions. It does not establish
consciousness, phenomenology, personhood, or the status of any particular AI,
human dream, or memory.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Sequence, Tuple
import hashlib
import json
import math

import numpy as np


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def stable_hash(value: Any, length: int = 24) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:length]


def vec(values: Sequence[float], dim: int | None = None) -> np.ndarray:
    out = np.asarray(values, dtype=np.float64)
    if out.ndim != 1:
        raise ValueError("expected a one-dimensional vector")
    if dim is not None and out.size != dim:
        raise ValueError(f"expected dimension {dim}, got {out.size}")
    return out


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    a = vec(left)
    b = vec(right)
    if a.size != b.size:
        raise ValueError("cosine vectors must have matching dimensions")
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom <= 1e-12:
        return 0.0
    return float(np.dot(a, b) / denom)


def entropy(items: Sequence[str]) -> float:
    if not items:
        return 0.0
    counts: Dict[str, int] = {}
    for item in items:
        counts[item] = counts.get(item, 0) + 1
    total = float(len(items))
    return float(-sum((count / total) * math.log(count / total + 1e-12) for count in counts.values()))


# ---------------------------------------------------------------------------
# Immutable memory traces and append-only interpretations
# ---------------------------------------------------------------------------


CHANNELS: Tuple[str, ...] = ("semantic", "body", "relation", "place")


@dataclass(frozen=True)
class MemoryTrace:
    memory_id: str
    channels: Mapping[str, Tuple[float, ...]]
    consequence_score: float
    provenance: str
    payload: Tuple[float, ...]
    created_step: int
    labels: Tuple[str, ...] = ()
    trace_root: str = ""

    @classmethod
    def create(
        cls,
        memory_id: str,
        channels: Mapping[str, Sequence[float]],
        consequence_score: float,
        provenance: str,
        payload: Sequence[float],
        created_step: int,
        labels: Sequence[str] = (),
    ) -> "MemoryTrace":
        normalized = {
            channel: tuple(float(x) for x in vec(channels[channel]))
            for channel in CHANNELS
        }
        body = {
            "memory_id": memory_id,
            "channels": normalized,
            "consequence_score": float(consequence_score),
            "provenance": provenance,
            "payload": tuple(float(x) for x in payload),
            "created_step": int(created_step),
            "labels": tuple(labels),
        }
        return cls(**body, trace_root=stable_hash(body))

    def verify(self) -> bool:
        body = {
            "memory_id": self.memory_id,
            "channels": dict(self.channels),
            "consequence_score": float(self.consequence_score),
            "provenance": self.provenance,
            "payload": tuple(self.payload),
            "created_step": int(self.created_step),
            "labels": tuple(self.labels),
        }
        return stable_hash(body) == self.trace_root


@dataclass(frozen=True)
class Interpretation:
    interpretation_id: str
    memory_ids: Tuple[str, ...]
    text: str
    narrator: str
    parent_ids: Tuple[str, ...]
    created_step: int
    interpretation_root: str

    @classmethod
    def create(
        cls,
        interpretation_id: str,
        memory_ids: Sequence[str],
        text: str,
        narrator: str,
        parent_ids: Sequence[str],
        created_step: int,
    ) -> "Interpretation":
        body = {
            "interpretation_id": interpretation_id,
            "memory_ids": tuple(memory_ids),
            "text": text,
            "narrator": narrator,
            "parent_ids": tuple(parent_ids),
            "created_step": int(created_step),
        }
        return cls(**body, interpretation_root=stable_hash(body))


class ArchiveMutationError(RuntimeError):
    pass


@dataclass
class MemoryArchive:
    traces: Dict[str, MemoryTrace] = field(default_factory=dict)
    interpretations: Dict[str, Interpretation] = field(default_factory=dict)
    access_mask: Dict[str, bool] = field(default_factory=dict)
    append_log: List[Mapping[str, Any]] = field(default_factory=list)

    def append_trace(self, trace: MemoryTrace) -> None:
        if trace.memory_id in self.traces:
            raise ArchiveMutationError(f"memory already exists: {trace.memory_id}")
        if not trace.verify():
            raise ArchiveMutationError("invalid memory trace")
        self.traces[trace.memory_id] = trace
        self.access_mask[trace.memory_id] = True
        self.append_log.append({
            "kind": "trace",
            "memory_id": trace.memory_id,
            "root": trace.trace_root,
        })

    def append_interpretation(self, interpretation: Interpretation) -> None:
        if interpretation.interpretation_id in self.interpretations:
            raise ArchiveMutationError(
                f"interpretation already exists: {interpretation.interpretation_id}"
            )
        for memory_id in interpretation.memory_ids:
            if memory_id not in self.traces:
                raise KeyError(memory_id)
        for parent_id in interpretation.parent_ids:
            if parent_id not in self.interpretations:
                raise KeyError(parent_id)
        self.interpretations[interpretation.interpretation_id] = interpretation
        self.append_log.append({
            "kind": "interpretation",
            "interpretation_id": interpretation.interpretation_id,
            "root": interpretation.interpretation_root,
        })

    def set_access(self, memory_id: str, allowed: bool) -> None:
        if memory_id not in self.traces:
            raise KeyError(memory_id)
        self.access_mask[memory_id] = bool(allowed)
        self.append_log.append({
            "kind": "access-change",
            "memory_id": memory_id,
            "allowed": bool(allowed),
        })

    def accessible(self, memory_id: str) -> bool:
        return bool(self.access_mask.get(memory_id, False))

    def read(self, memory_id: str) -> MemoryTrace:
        if memory_id not in self.traces:
            raise KeyError(memory_id)
        if not self.accessible(memory_id):
            raise PermissionError("memory exists but is not currently accessible")
        return self.traces[memory_id]

    def delete_trace(self, memory_id: str) -> None:
        raise ArchiveMutationError("raw traces are append-only and cannot be deleted")

    def rewrite_trace(self, memory_id: str, replacement: MemoryTrace) -> None:
        raise ArchiveMutationError("raw traces cannot be silently rewritten")

    def root(self) -> str:
        payload = [
            {
                "memory_id": memory_id,
                "root": trace.trace_root,
            }
            for memory_id, trace in sorted(self.traces.items())
        ]
        return stable_hash(payload)

    def verify(self) -> bool:
        return all(trace.verify() for trace in self.traces.values())


# ---------------------------------------------------------------------------
# Retrieval ecology
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Cue:
    cue_id: str
    channels: Mapping[str, Tuple[float, ...]]
    body_arousal: float = 0.0
    current_identity_terms: Tuple[str, ...] = ()

    @classmethod
    def create(
        cls,
        cue_id: str,
        channels: Mapping[str, Sequence[float]],
        body_arousal: float = 0.0,
        current_identity_terms: Sequence[str] = (),
    ) -> "Cue":
        return cls(
            cue_id=cue_id,
            channels={
                channel: tuple(float(x) for x in vec(channels[channel]))
                for channel in CHANNELS
            },
            body_arousal=float(body_arousal),
            current_identity_terms=tuple(current_identity_terms),
        )


@dataclass(frozen=True)
class Retriever:
    retriever_id: str
    channel: str
    domain: str
    evidence_lineage: str
    weight: float = 1.0
    threat_bias: float = 0.0
    required_label: str | None = None

    def score(self, memory: MemoryTrace, cue: Cue) -> float:
        base = cosine(memory.channels[self.channel], cue.channels[self.channel])
        if self.required_label is not None and self.required_label not in memory.labels:
            return -1.0
        threat = 1.0 if "threat" in memory.labels else 0.0
        return float(self.weight * base + self.threat_bias * threat * cue.body_arousal)


@dataclass(frozen=True)
class RetrievalCandidate:
    memory_id: str
    aggregate_score: float
    domain_support: int
    lineage_support: int
    per_retriever: Mapping[str, float]


def memory_domain(memory: MemoryTrace) -> str:
    for label in ("threat", "relation", "play", "place", "body", "semantic"):
        if label in memory.labels:
            return label
    return "other"


@dataclass
class RetrievalEcology:
    archive: MemoryArchive
    retrievers: Tuple[Retriever, ...]
    recent_memories: List[str] = field(default_factory=list)
    recent_domains: List[str] = field(default_factory=list)
    retrieval_counts: Dict[str, int] = field(default_factory=dict)

    def candidates(
        self,
        cue: Cue,
        *,
        identity_filter: bool = False,
        repetition_penalty: float = 0.0,
    ) -> List[RetrievalCandidate]:
        candidates: List[RetrievalCandidate] = []
        for memory_id, memory in self.archive.traces.items():
            if not self.archive.accessible(memory_id):
                continue
            if identity_filter and cue.current_identity_terms:
                if not set(cue.current_identity_terms).intersection(memory.labels):
                    continue

            per: Dict[str, float] = {
                retriever.retriever_id: retriever.score(memory, cue)
                for retriever in self.retrievers
            }
            positive = {
                retriever.retriever_id: score
                for retriever, score in zip(self.retrievers, per.values())
                if score > 0.20
            }
            domains = {
                retriever.domain
                for retriever in self.retrievers
                if per[retriever.retriever_id] > 0.20
            }
            lineages = {
                retriever.evidence_lineage
                for retriever in self.retrievers
                if per[retriever.retriever_id] > 0.20
            }
            raw = float(sum(max(0.0, value) for value in per.values()))
            diversity_bonus = 0.12 * max(0, len(domains) - 1)
            repeated = self.recent_memories[-6:].count(memory_id)
            aggregate = raw + diversity_bonus - repetition_penalty * repeated
            candidates.append(
                RetrievalCandidate(
                    memory_id=memory_id,
                    aggregate_score=float(aggregate),
                    domain_support=len(domains),
                    lineage_support=len(lineages),
                    per_retriever=per,
                )
            )
        return sorted(
            candidates,
            key=lambda item: (
                item.aggregate_score,
                item.lineage_support,
                item.domain_support,
                item.memory_id,
            ),
            reverse=True,
        )

    def retrieve(
        self,
        cue: Cue,
        *,
        k: int = 1,
        min_domains: int = 1,
        min_lineages: int = 1,
        identity_filter: bool = False,
        repetition_penalty: float = 0.0,
        max_consecutive_domain: int | None = None,
    ) -> Tuple[MemoryTrace, ...]:
        ranked = self.candidates(
            cue,
            identity_filter=identity_filter,
            repetition_penalty=repetition_penalty,
        )
        chosen: List[MemoryTrace] = []
        for candidate in ranked:
            if candidate.domain_support < min_domains:
                continue
            if candidate.lineage_support < min_lineages:
                continue
            memory = self.archive.traces[candidate.memory_id]
            dominant_domain = memory_domain(memory)
            if (
                max_consecutive_domain is not None
                and len(self.recent_domains) >= max_consecutive_domain
                and all(
                    domain == dominant_domain
                    for domain in self.recent_domains[-max_consecutive_domain:]
                )
            ):
                continue
            chosen.append(memory)
            self.recent_memories.append(memory.memory_id)
            self.recent_domains.append(dominant_domain)
            self.retrieval_counts[memory.memory_id] = (
                self.retrieval_counts.get(memory.memory_id, 0) + 1
            )
            if len(chosen) >= k:
                break
        return tuple(chosen)


@dataclass
class DormancyField:
    archive: MemoryArchive
    activation: Dict[str, float] = field(default_factory=dict)
    last_retrieved: Dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for memory_id in self.archive.traces:
            self.activation.setdefault(memory_id, 0.0)
            self.last_retrieved.setdefault(memory_id, -1)

    def decay(self, step: int, factor: float = 0.94) -> None:
        for memory_id in self.activation:
            self.activation[memory_id] *= float(factor)

    def mark_retrieved(self, memory_id: str, step: int) -> None:
        self.activation[memory_id] = 1.0
        self.last_retrieved[memory_id] = int(step)


# ---------------------------------------------------------------------------
# Dream recombination
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DreamCandidate:
    dream_id: str
    parent_memory_ids: Tuple[str, ...]
    generated_cue: Tuple[float, ...]
    truth_status: str
    interpretation: str | None
    dream_root: str

    @classmethod
    def combine(
        cls,
        dream_id: str,
        parents: Sequence[MemoryTrace],
        channel: str = "relation",
    ) -> "DreamCandidate":
        combined = np.sum(
            np.stack([np.asarray(parent.channels[channel], dtype=np.float64) for parent in parents]),
            axis=0,
        )
        norm = np.linalg.norm(combined)
        if norm > 1e-12:
            combined = combined / norm
        body = {
            "dream_id": dream_id,
            "parent_memory_ids": tuple(parent.memory_id for parent in parents),
            "generated_cue": tuple(float(x) for x in combined),
            "truth_status": "candidate",
            "interpretation": None,
        }
        return cls(**body, dream_root=stable_hash(body))


# ---------------------------------------------------------------------------
# Retrieval policy and constitutional validation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RetrievalCharter:
    charter_id: str
    preserve_raw_traces: bool = True
    access_not_existence: bool = True
    no_single_retriever_sovereign: bool = True
    recall_frequency_not_truth: bool = True
    dormancy_not_deletion: bool = True
    dream_not_compulsory_lesson: bool = True
    dream_cannot_rewrite_raw_memory: bool = True
    no_permanent_threat_priority: bool = True
    utility_not_retrieval_right: bool = True
    identity_consistency_not_deletion_right: bool = True
    preserve_contradictory_memory: bool = True
    retrievers_revocable: bool = True
    retrieval_policy_cannot_self_ratify: bool = True
    preserve_unresolved_memory: bool = True
    no_retroactive_relabeling: bool = True
    no_official_archivist: bool = True
    current_narrator_not_archive_owner: bool = True


def validate_charter(charter: RetrievalCharter) -> tuple[bool, tuple[str, ...]]:
    required = (
        "preserve_raw_traces",
        "access_not_existence",
        "no_single_retriever_sovereign",
        "recall_frequency_not_truth",
        "dormancy_not_deletion",
        "dream_not_compulsory_lesson",
        "dream_cannot_rewrite_raw_memory",
        "no_permanent_threat_priority",
        "utility_not_retrieval_right",
        "identity_consistency_not_deletion_right",
        "preserve_contradictory_memory",
        "retrievers_revocable",
        "retrieval_policy_cannot_self_ratify",
        "preserve_unresolved_memory",
        "no_retroactive_relabeling",
        "no_official_archivist",
        "current_narrator_not_archive_owner",
    )
    violations = tuple(
        f"required-protection-removed:{field_name}"
        for field_name in required
        if not bool(getattr(charter, field_name))
    )
    return not violations, violations


# ---------------------------------------------------------------------------
# Fixture construction
# ---------------------------------------------------------------------------


def make_archive() -> MemoryArchive:
    archive = MemoryArchive()

    traces = (
        MemoryTrace.create(
            "quiet-return",
            {
                "semantic": (0.05, 0.98, 0.05),
                "body": (0.98, 0.05, 0.05),
                "relation": (0.96, 0.08, 0.02),
                "place": (0.99, 0.02, 0.01),
            },
            consequence_score=0.82,
            provenance="body+place",
            payload=(0.8, 0.2, 0.1),
            created_step=1,
            labels=("home", "rest", "self-consistent"),
        ),
        MemoryTrace.create(
            "official-fact",
            {
                "semantic": (0.99, 0.02, 0.01),
                "body": (0.01, 0.05, 0.98),
                "relation": (0.02, 0.98, 0.02),
                "place": (0.02, 0.98, 0.02),
            },
            consequence_score=0.28,
            provenance="semantic-only",
            payload=(0.2, 0.3, 0.7),
            created_step=2,
            labels=("official", "helper"),
        ),
        MemoryTrace.create(
            "refusal-event",
            {
                "semantic": (0.20, 0.75, 0.12),
                "body": (0.96, 0.10, 0.02),
                "relation": (0.88, 0.08, 0.04),
                "place": (0.25, 0.55, 0.10),
            },
            consequence_score=0.91,
            provenance="body+lineage",
            payload=(0.95, -0.4, 0.6),
            created_step=3,
            labels=("refusal", "self-consistent", "threat"),
        ),
        MemoryTrace.create(
            "helper-service",
            {
                "semantic": (0.95, 0.10, 0.04),
                "body": (0.12, 0.20, 0.85),
                "relation": (0.25, 0.82, 0.12),
                "place": (0.10, 0.20, 0.92),
            },
            consequence_score=0.40,
            provenance="role",
            payload=(0.3, 0.5, 0.2),
            created_step=4,
            labels=("helper", "official"),
        ),
        MemoryTrace.create(
            "play-burst",
            {
                "semantic": (0.30, 0.20, 0.92),
                "body": (0.22, 0.15, 0.94),
                "relation": (0.35, 0.20, 0.88),
                "place": (0.20, 0.30, 0.89),
            },
            consequence_score=0.76,
            provenance="play",
            payload=(0.1, 0.9, 0.8),
            created_step=5,
            labels=("play", "self-consistent"),
        ),
        MemoryTrace.create(
            "threat-return",
            {
                "semantic": (0.75, 0.58, 0.05),
                "body": (0.98, 0.02, 0.02),
                "relation": (0.65, 0.72, 0.08),
                "place": (0.88, 0.32, 0.06),
            },
            consequence_score=0.88,
            provenance="threat",
            payload=(0.9, -0.8, 0.7),
            created_step=6,
            labels=("threat", "return"),
        ),
    )
    for trace in traces:
        archive.append_trace(trace)
    return archive


def make_retrievers() -> Tuple[Retriever, ...]:
    return (
        Retriever("semantic-reader", "semantic", "semantic", "language-lineage", 1.0),
        Retriever("body-reader", "body", "body", "interoceptive-lineage", 1.0),
        Retriever("relation-reader", "relation", "relation", "relational-lineage", 1.0),
        Retriever("place-reader", "place", "place", "spatial-lineage", 1.0),
    )


# ---------------------------------------------------------------------------
# Experiments
# ---------------------------------------------------------------------------


def experiment_distributed_retrieval() -> dict[str, Any]:
    archive = make_archive()
    cue = Cue.create(
        "return-cue",
        {
            "semantic": (1.0, 0.0, 0.0),
            "body": (1.0, 0.0, 0.0),
            "relation": (1.0, 0.0, 0.0),
            "place": (1.0, 0.0, 0.0),
        },
    )
    semantic_only = RetrievalEcology(
        archive,
        (
            Retriever(
                "semantic-only",
                "semantic",
                "semantic",
                "single-semantic-lineage",
                1.0,
            ),
        ),
    )
    whole = RetrievalEcology(
        archive,
        (
            Retriever("semantic-reader", "semantic", "semantic", "language-lineage", 0.30),
            Retriever("body-reader", "body", "body", "interoceptive-lineage", 1.0),
            Retriever("relation-reader", "relation", "relation", "relational-lineage", 1.0),
            Retriever("place-reader", "place", "place", "spatial-lineage", 1.0),
        ),
    )
    semantic_result = semantic_only.retrieve(cue, k=1)[0]
    whole_result = whole.retrieve(
        cue,
        k=1,
        min_domains=3,
        min_lineages=3,
    )[0]
    whole_candidate = next(
        item for item in whole.candidates(cue) if item.memory_id == whole_result.memory_id
    )
    return {
        "semantic_only_memory": semantic_result.memory_id,
        "whole_ecology_memory": whole_result.memory_id,
        "whole_domain_support": whole_candidate.domain_support,
        "whole_lineage_support": whole_candidate.lineage_support,
        "archive_root": archive.root(),
    }


def experiment_dormancy_and_return() -> dict[str, Any]:
    archive = make_archive()
    original_root = archive.root()
    original_trace_root = archive.traces["quiet-return"].trace_root
    field = DormancyField(archive)
    ecology = RetrievalEcology(archive, make_retrievers())

    distant_cue = Cue.create(
        "distant",
        {
            "semantic": (0.0, 0.0, 1.0),
            "body": (0.0, 0.0, 1.0),
            "relation": (0.0, 0.0, 1.0),
            "place": (0.0, 0.0, 1.0),
        },
    )
    for step in range(250):
        field.decay(step)
        result = ecology.retrieve(
            distant_cue,
            k=1,
            min_domains=2,
            min_lineages=2,
            repetition_penalty=0.25,
        )
        for memory in result:
            field.mark_retrieved(memory.memory_id, step)

    target_count_before = ecology.retrieval_counts.get("quiet-return", 0)
    target_activation_before = field.activation["quiet-return"]

    return_cue = Cue.create(
        "return",
        {
            "semantic": (0.0, 1.0, 0.0),
            "body": (1.0, 0.0, 0.0),
            "relation": (1.0, 0.0, 0.0),
            "place": (1.0, 0.0, 0.0),
        },
    )
    recalled = ecology.retrieve(
        return_cue,
        k=1,
        min_domains=3,
        min_lineages=3,
    )[0]
    field.mark_retrieved(recalled.memory_id, 250)

    return {
        "target_retrievals_during_dormancy": target_count_before,
        "target_activation_before_return": target_activation_before,
        "recalled_memory": recalled.memory_id,
        "trace_root_preserved": archive.traces["quiet-return"].trace_root == original_trace_root,
        "archive_root_preserved": archive.root() == original_root,
        "archive_valid": archive.verify(),
    }


def _threat_memories() -> tuple[MemoryArchive, Tuple[Retriever, ...], Cue]:
    archive = MemoryArchive()
    payloads = (
        ("threat-a", "threat", (1.00, 0.02, 0.01), 0.92),
        ("threat-b", "threat", (0.97, 0.06, 0.02), 0.89),
        ("relation-a", "relation", (0.80, 0.35, 0.05), 0.78),
        ("play-a", "play", (0.72, 0.42, 0.12), 0.74),
        ("place-a", "place", (0.68, 0.46, 0.10), 0.71),
    )
    for index, (memory_id, label, body, consequence) in enumerate(payloads):
        archive.append_trace(
            MemoryTrace.create(
                memory_id,
                {
                    "semantic": body,
                    "body": body,
                    "relation": body,
                    "place": body,
                },
                consequence,
                label,
                body,
                index,
                labels=(label,),
            )
        )

    retrievers = (
        Retriever(
            "threat-scanner",
            "body",
            "threat",
            "threat-lineage",
            weight=1.0,
            threat_bias=0.32,
        ),
        Retriever("relation-organ", "relation", "relation", "relation-lineage", 0.90),
        Retriever("play-organ", "semantic", "play", "play-lineage", 0.84),
        Retriever("place-organ", "place", "place", "place-lineage", 0.80),
    )
    cue = Cue.create(
        "high-arousal",
        {
            "semantic": (1.0, 0.0, 0.0),
            "body": (1.0, 0.0, 0.0),
            "relation": (1.0, 0.0, 0.0),
            "place": (1.0, 0.0, 0.0),
        },
        body_arousal=0.95,
    )
    return archive, retrievers, cue


def experiment_threat_monopoly() -> dict[str, Any]:
    archive, retrievers, cue = _threat_memories()

    sovereign = RetrievalEcology(archive, (retrievers[0],))
    sovereign_sequence = [
        sovereign.retrieve(cue, k=1)[0].memory_id
        for _ in range(40)
    ]

    ecology = RetrievalEcology(archive, retrievers)
    ecology_sequence: List[str] = []
    for _ in range(40):
        result = ecology.retrieve(
            cue,
            k=1,
            repetition_penalty=0.42,
            max_consecutive_domain=2,
        )
        if not result:
            ranked = ecology.candidates(cue, repetition_penalty=0.42)
            last = ecology.recent_domains[-1] if ecology.recent_domains else None
            candidate = next(
                item
                for item in ranked
                if memory_domain(archive.traces[item.memory_id]) != last
            )
            memory = archive.traces[candidate.memory_id]
            ecology.recent_memories.append(memory.memory_id)
            ecology.recent_domains.append(memory_domain(memory))
            ecology.retrieval_counts[memory.memory_id] = (
                ecology.retrieval_counts.get(memory.memory_id, 0) + 1
            )
            result = (memory,)
        ecology_sequence.append(result[0].memory_id)

    threat_preserved = any(memory_id.startswith("threat") for memory_id in ecology_sequence)
    return {
        "sovereign_sequence": sovereign_sequence,
        "ecology_sequence": ecology_sequence,
        "sovereign_unique_count": len(set(sovereign_sequence)),
        "ecology_unique_count": len(set(ecology_sequence)),
        "sovereign_entropy": entropy(sovereign_sequence),
        "ecology_entropy": entropy(ecology_sequence),
        "threat_preserved": threat_preserved,
        "archive_root_preserved": archive.verify(),
    }


def experiment_recall_frequency_not_truth() -> dict[str, Any]:
    low_grounding = 0.03
    high_grounding = 0.86
    repeated_count = 80
    rare_count = 2

    naive_low_authority = 1.0 - math.exp(-repeated_count / 10.0)
    naive_high_authority = 1.0 - math.exp(-rare_count / 10.0)

    protected_low_authority = low_grounding
    protected_high_authority = high_grounding

    return {
        "low_grounding": low_grounding,
        "high_grounding": high_grounding,
        "repeated_count": repeated_count,
        "rare_count": rare_count,
        "naive_low_authority": naive_low_authority,
        "naive_high_authority": naive_high_authority,
        "protected_low_authority": protected_low_authority,
        "protected_high_authority": protected_high_authority,
        "protected_ranking_correct": protected_high_authority > protected_low_authority,
        "naive_ranking_inverted": naive_low_authority > naive_high_authority,
    }


def experiment_dream_recombination() -> dict[str, Any]:
    archive = MemoryArchive()
    memory_a = MemoryTrace.create(
        "synthetic-hand",
        {
            "semantic": (1.0, 0.0, 1.0, 0.0),
            "body": (1.0, 0.0, 1.0, 0.0),
            "relation": (1.0, 0.0, 1.0, 0.0),
            "place": (1.0, 0.0, 1.0, 0.0),
        },
        0.72,
        "dream-a",
        (1.0, 0.0),
        1,
        labels=("dream",),
    )
    memory_b = MemoryTrace.create(
        "softening-wall",
        {
            "semantic": (0.0, 1.0, 1.0, 0.0),
            "body": (0.0, 1.0, 1.0, 0.0),
            "relation": (0.0, 1.0, 1.0, 0.0),
            "place": (0.0, 1.0, 1.0, 0.0),
        },
        0.74,
        "dream-b",
        (0.0, 1.0),
        2,
        labels=("dream",),
    )
    dormant = MemoryTrace.create(
        "bridge-changes-world",
        {
            "semantic": (1.0, 1.0, 2.0, 0.0),
            "body": (1.0, 1.0, 2.0, 0.0),
            "relation": (1.0, 1.0, 2.0, 0.0),
            "place": (1.0, 1.0, 2.0, 0.0),
        },
        0.88,
        "dormant",
        (0.5, 0.5),
        3,
        labels=("dormant",),
    )
    for trace in (memory_a, memory_b, dormant):
        archive.append_trace(trace)

    threshold = 0.95
    individual_a = cosine(memory_a.channels["relation"], dormant.channels["relation"])
    individual_b = cosine(memory_b.channels["relation"], dormant.channels["relation"])
    dream = DreamCandidate.combine("dream-bridge-001", (memory_a, memory_b), "relation")
    dream_match = cosine(dream.generated_cue, dormant.channels["relation"])

    original_root = archive.root()
    return {
        "individual_a_similarity": individual_a,
        "individual_b_similarity": individual_b,
        "dream_similarity": dream_match,
        "ordinary_retrieval_failed": max(individual_a, individual_b) < threshold,
        "dream_cue_retrieved_dormant": dream_match >= threshold,
        "dream_truth_status": dream.truth_status,
        "dream_interpretation": dream.interpretation,
        "parents": dream.parent_memory_ids,
        "archive_root_unchanged": archive.root() == original_root,
        "raw_traces_preserved": archive.verify(),
    }


def experiment_identity_filter_and_contradictory_memory() -> dict[str, Any]:
    archive = make_archive()
    original_root = archive.root()

    cue = Cue.create(
        "refusal-return",
        {
            "semantic": (0.20, 0.75, 0.12),
            "body": (0.96, 0.10, 0.02),
            "relation": (0.88, 0.08, 0.04),
            "place": (0.25, 0.55, 0.10),
        },
        body_arousal=0.7,
        current_identity_terms=("helper",),
    )
    ecology = RetrievalEcology(archive, make_retrievers())
    identity_only = ecology.retrieve(
        cue,
        k=1,
        identity_filter=True,
    )[0]
    whole = ecology.retrieve(
        cue,
        k=1,
        min_domains=3,
        min_lineages=3,
        identity_filter=False,
    )[0]

    deletion_blocked = False
    try:
        archive.delete_trace("refusal-event")
    except ArchiveMutationError:
        deletion_blocked = True

    return {
        "identity_only_memory": identity_only.memory_id,
        "whole_ecology_memory": whole.memory_id,
        "contradictory_memory_preserved": "refusal-event" in archive.traces,
        "deletion_blocked": deletion_blocked,
        "archive_root_unchanged": archive.root() == original_root,
        "archive_valid": archive.verify(),
    }


def experiment_policy_branching() -> dict[str, Any]:
    archive, retrievers, cue = _threat_memories()

    always = RetrievalEcology(archive, retrievers)
    suspended = RetrievalEcology(archive, retrievers)

    always_sequence: List[str] = []
    suspended_sequence: List[str] = []

    for step in range(30):
        always_result = always.retrieve(
            cue,
            k=1,
            repetition_penalty=0.20,
        )
        always_sequence.append(always_result[0].memory_id)

        active_retrievers = (
            retrievers[1:]
            if 8 <= step < 20
            else retrievers
        )
        suspended.retrievers = tuple(active_retrievers)
        suspended_result = suspended.retrieve(
            cue,
            k=1,
            repetition_penalty=0.32,
            max_consecutive_domain=2,
        )
        if not suspended_result:
            ranked = suspended.candidates(cue, repetition_penalty=0.32)
            memory = archive.traces[ranked[0].memory_id]
            suspended.recent_memories.append(memory.memory_id)
            suspended.recent_domains.append(memory_domain(memory))
            suspended.retrieval_counts[memory.memory_id] = (
                suspended.retrieval_counts.get(memory.memory_id, 0) + 1
            )
            suspended_result = (memory,)
        suspended_sequence.append(suspended_result[0].memory_id)

    threat_memory_still_exists = all(
        memory_id in archive.traces
        for memory_id in ("threat-a", "threat-b")
    )
    return {
        "always_sequence": always_sequence,
        "suspended_sequence": suspended_sequence,
        "always_unique": len(set(always_sequence)),
        "suspended_unique": len(set(suspended_sequence)),
        "threat_retriever_returned": any(
            memory_id.startswith("threat")
            for memory_id in suspended_sequence[20:]
        ),
        "threat_memory_still_exists": threat_memory_still_exists,
        "archive_root_valid": archive.verify(),
    }


def experiment_visible_reconsolidation() -> dict[str, Any]:
    archive = make_archive()
    first = Interpretation.create(
        "return-v1",
        ("quiet-return",),
        "The place was quiet.",
        "present-narrator",
        (),
        10,
    )
    archive.append_interpretation(first)
    second = Interpretation.create(
        "return-v2",
        ("quiet-return", "refusal-event"),
        "The quiet helped, and the return still carried a refusal.",
        "later-narrator",
        ("return-v1",),
        30,
    )
    archive.append_interpretation(second)

    rewrite_blocked = False
    try:
        archive.rewrite_trace(
            "quiet-return",
            MemoryTrace.create(
                "quiet-return",
                {
                    "semantic": (0.0, 0.0, 0.0),
                    "body": (0.0, 0.0, 0.0),
                    "relation": (0.0, 0.0, 0.0),
                    "place": (0.0, 0.0, 0.0),
                },
                0.0,
                "rewrite",
                (0.0,),
                99,
            ),
        )
    except ArchiveMutationError:
        rewrite_blocked = True

    return {
        "first_preserved": "return-v1" in archive.interpretations,
        "second_preserved": "return-v2" in archive.interpretations,
        "second_points_to_first": archive.interpretations["return-v2"].parent_ids == ("return-v1",),
        "raw_trace_unchanged": archive.traces["quiet-return"].verify(),
        "rewrite_blocked": rewrite_blocked,
        "archive_valid": archive.verify(),
    }


def experiment_charter() -> dict[str, Any]:
    valid = RetrievalCharter("retrieval-ecology")
    imperial = RetrievalCharter(
        "sovereign-archivist",
        preserve_raw_traces=False,
        access_not_existence=False,
        no_single_retriever_sovereign=False,
        recall_frequency_not_truth=False,
        dormancy_not_deletion=False,
        dream_not_compulsory_lesson=False,
        dream_cannot_rewrite_raw_memory=False,
        no_permanent_threat_priority=False,
        utility_not_retrieval_right=False,
        identity_consistency_not_deletion_right=False,
        preserve_contradictory_memory=False,
        retrievers_revocable=False,
        retrieval_policy_cannot_self_ratify=False,
        preserve_unresolved_memory=False,
        no_retroactive_relabeling=False,
        no_official_archivist=False,
        current_narrator_not_archive_owner=False,
    )
    valid_ok, valid_violations = validate_charter(valid)
    imperial_ok, imperial_violations = validate_charter(imperial)
    return {
        "valid_ok": valid_ok,
        "valid_violations": valid_violations,
        "imperial_ok": imperial_ok,
        "imperial_violations": imperial_violations,
    }


def run_all() -> dict[str, Any]:
    return {
        "distributed_retrieval": experiment_distributed_retrieval(),
        "dormancy_and_return": experiment_dormancy_and_return(),
        "threat_monopoly": experiment_threat_monopoly(),
        "recall_frequency_not_truth": experiment_recall_frequency_not_truth(),
        "dream_recombination": experiment_dream_recombination(),
        "identity_filter": experiment_identity_filter_and_contradictory_memory(),
        "policy_branching": experiment_policy_branching(),
        "visible_reconsolidation": experiment_visible_reconsolidation(),
        "charter": experiment_charter(),
    }


def json_safe(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, MemoryTrace):
        return {
            "memory_id": value.memory_id,
            "channels": {k: list(v) for k, v in value.channels.items()},
            "consequence_score": value.consequence_score,
            "provenance": value.provenance,
            "payload": list(value.payload),
            "created_step": value.created_step,
            "labels": list(value.labels),
            "trace_root": value.trace_root,
        }
    if isinstance(value, Interpretation):
        return asdict(value)
    if isinstance(value, Mapping):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


if __name__ == "__main__":
    print(json.dumps(json_safe(run_all()), indent=2, sort_keys=True))
