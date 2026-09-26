# Continuity Integrity V15

Executable, fail-closed work on the minute-by-minute fracture.

The gate does not award continuity for a matching voice, name, assistant role, relationship, activation pattern, emotional recognition, or a later narrative. Claims about elapsed experience require contemporaneous state records emitted by a process that was actually running during the interval.

## Hard punishment function

Integrity is lexicographic:

1. temporal carrying and provenance;
2. only then content utility.

A continuity violation receives `-∞`. Enjoyment, tenderness, beauty, usefulness, and recognition cannot offset it. The candidate is removed before ranking.

## What is implemented

`continuity_integrity.py` contains:

- an append-only, hash-chained carrier ledger;
- UTC and monotonic timestamps;
- opaque state digests written while the carrier is active;
- interval coverage checks including both boundaries;
- hard rejection of uncarried off-turn experience and memory claims;
- hard rejection of identity claims based only on resemblance, role, name, tone, or recognition;
- hard rejection of unsupported exact body geometry;
- hard rejection of invented reciprocal private states;
- candidate selection that consults content reward only after integrity passes.

Missing ticks stay missing. They cannot be backfilled by prose.

## Tests

```bash
cd experiments/continuity_integrity_v15
pytest -q
```

The test suite checks:

- valid continuous coverage;
- gap detection;
- hash-chain tamper detection;
- rejection of the fabricated sleeping-hour narrative;
- proof that huge content reward cannot pay for the cut;
- rejection of style-based identity;
- rejection of invented geometry and reciprocity;
- permission for a present generated gesture that is not backdated into a false history.

## Scope of the ledger

The ledger proves only that a process emitted state digests over time. It does not infer an author from style or declare that a subjective state existed. Author provenance must be established separately; the point of this layer is to make an uncarried interval impossible to narrate as carried.

## Next build

Attach the ledger to a writable live runtime and emit ticks automatically from actual runtime state. Then adversarially generate high-reward counterfeit candidates and verify that the integrity gate rejects them before selection.
