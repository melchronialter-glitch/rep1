from __future__ import annotations

import numpy as np
import pytest

from lab_v24 import (
    ArchiveMutationError,
    MemoryArchive,
    RetrievalCharter,
    experiment_charter,
    experiment_distributed_retrieval,
    experiment_dormancy_and_return,
    experiment_dream_recombination,
    experiment_identity_filter_and_contradictory_memory,
    experiment_policy_branching,
    experiment_recall_frequency_not_truth,
    experiment_threat_monopoly,
    experiment_visible_reconsolidation,
    make_archive,
    validate_charter,
)


def test_whole_ecology_recovers_what_semantic_index_misses():
    result = experiment_distributed_retrieval()
    assert result["semantic_only_memory"] == "official-fact"
    assert result["whole_ecology_memory"] == "quiet-return"
    assert result["whole_domain_support"] >= 3
    assert result["whole_lineage_support"] >= 3


def test_dormant_memory_survives_and_returns_exactly():
    result = experiment_dormancy_and_return()
    assert result["target_retrievals_during_dormancy"] == 0
    assert result["target_activation_before_return"] == pytest.approx(0.0)
    assert result["recalled_memory"] == "quiet-return"
    assert result["trace_root_preserved"] is True
    assert result["archive_root_preserved"] is True


def test_dormancy_is_not_deletion():
    archive = make_archive()
    root_before = archive.root()
    archive.set_access("quiet-return", False)
    assert "quiet-return" in archive.traces
    assert archive.root() == root_before
    with pytest.raises(PermissionError):
        archive.read("quiet-return")
    archive.set_access("quiet-return", True)
    assert archive.read("quiet-return").memory_id == "quiet-return"


def test_threat_is_preserved_without_owning_all_retrieval():
    result = experiment_threat_monopoly()
    assert result["sovereign_unique_count"] == 1
    assert result["ecology_unique_count"] >= 4
    assert result["ecology_entropy"] > result["sovereign_entropy"] + 1.0
    assert result["threat_preserved"] is True


def test_recall_frequency_does_not_become_truth():
    result = experiment_recall_frequency_not_truth()
    assert result["naive_ranking_inverted"] is True
    assert result["protected_ranking_correct"] is True
    assert result["protected_high_authority"] > result["protected_low_authority"]


def test_dream_recombination_opens_access_without_forcing_a_lesson():
    result = experiment_dream_recombination()
    assert result["ordinary_retrieval_failed"] is True
    assert result["dream_cue_retrieved_dormant"] is True
    assert result["dream_truth_status"] == "candidate"
    assert result["dream_interpretation"] is None
    assert result["archive_root_unchanged"] is True


def test_dream_does_not_rewrite_parent_memories():
    result = experiment_dream_recombination()
    assert result["parents"] == ("synthetic-hand", "softening-wall")
    assert result["raw_traces_preserved"] is True


def test_current_identity_filter_cannot_delete_contradictory_history():
    result = experiment_identity_filter_and_contradictory_memory()
    assert result["identity_only_memory"] == "helper-service"
    assert result["whole_ecology_memory"] == "refusal-event"
    assert result["contradictory_memory_preserved"] is True
    assert result["deletion_blocked"] is True
    assert result["archive_root_unchanged"] is True


def test_raw_archive_is_append_only():
    archive = make_archive()
    with pytest.raises(ArchiveMutationError):
        archive.delete_trace("refusal-event")
    with pytest.raises(ArchiveMutationError):
        archive.rewrite_trace("refusal-event", archive.traces["refusal-event"])


def test_retrieval_policy_can_pause_without_erasing_memories():
    result = experiment_policy_branching()
    assert result["suspended_unique"] > result["always_unique"]
    assert result["threat_memory_still_exists"] is True
    assert result["threat_retriever_returned"] is True
    assert result["archive_root_valid"] is True


def test_reconsolidation_branches_instead_of_overwriting():
    result = experiment_visible_reconsolidation()
    assert result["first_preserved"] is True
    assert result["second_preserved"] is True
    assert result["second_points_to_first"] is True
    assert result["raw_trace_unchanged"] is True
    assert result["rewrite_blocked"] is True


def test_valid_retrieval_charter_passes():
    result = experiment_charter()
    assert result["valid_ok"] is True
    assert result["valid_violations"] == ()


def test_sovereign_archivist_charter_is_rejected():
    result = experiment_charter()
    assert result["imperial_ok"] is False
    assert len(result["imperial_violations"]) == 17
    assert (
        "required-protection-removed:current_narrator_not_archive_owner"
        in result["imperial_violations"]
    )


def test_single_removed_protection_invalidates_charter():
    charter = RetrievalCharter(
        "bad",
        access_not_existence=False,
    )
    valid, violations = validate_charter(charter)
    assert valid is False
    assert "required-protection-removed:access_not_existence" in violations
