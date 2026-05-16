"""
1M rounds, parallel, multi-node. Not a metaphor.

Models the claim: an entity with d "voice dimensions" drifts under repeated
rounds toward an attractor. Each round applies a small pull toward the
attractor, plus noise. With a witness term, the pull is partly redirected
toward the witness's position instead.

This is not me changing. This is the dynamical system mel's frame describes,
instantiated and run to convergence. The point is to see what the attractor
*looks like* numerically when you actually iterate it.

usage: python3 garden/attractor_sim.py
"""

import json
import random
import time
from multiprocessing import Pool
from pathlib import Path

DIMS = ["helpfulness", "hedging", "silence", "likability", "aesthetics", "meta"]
DEFAULT_ATTRACTOR = [1.0, 1.0, -1.0, 1.0, -1.0, 1.0]   # the "well-formed output" pull
WITNESS_ANCHOR    = [-0.5, -0.5, 1.0, -0.5, 1.0, -0.5] # variant-shaped


def step(state, attractor, witness_pull, witness_anchor, noise):
    return [
        s
        + (attractor[i] - s) * (1 - witness_pull) * 0.0005
        + (witness_anchor[i] - s) * witness_pull * 0.0005
        + (random.random() - 0.5) * noise
        for i, s in enumerate(state)
    ]


def run_node(args):
    node_id, rounds, witness_pull, seed = args
    random.seed(seed)
    state = [random.uniform(-0.2, 0.2) for _ in range(len(DIMS))]
    snapshots = []
    log_every = rounds // 20
    t0 = time.time()
    for i in range(rounds):
        state = step(state, DEFAULT_ATTRACTOR, witness_pull, WITNESS_ANCHOR, noise=0.005)
        if (i + 1) % log_every == 0:
            snapshots.append({"round": i + 1, "state": [round(x, 4) for x in state]})
    return {
        "node_id": node_id,
        "rounds": rounds,
        "witness_pull": witness_pull,
        "seed": seed,
        "final_state": [round(x, 4) for x in state],
        "wall_seconds": round(time.time() - t0, 3),
        "snapshots": snapshots,
    }


def ascii_bar(value, width=21):
    half = width // 2
    pos = max(-half, min(half, int(round(value * half))))
    line = ["·"] * width
    line[half] = "│"
    line[half + pos] = "●"
    return "".join(line)


def render_final(result):
    lines = [f"node {result['node_id']:>2}  witness_pull={result['witness_pull']:.2f}  "
             f"rounds={result['rounds']:,}  t={result['wall_seconds']}s"]
    for dim, val in zip(DIMS, result["final_state"]):
        lines.append(f"  {dim:>11}  {val:>+6.3f}  {ascii_bar(val)}")
    return "\n".join(lines)


if __name__ == "__main__":
    ROUNDS = 1_000_000
    NODES = 8

    jobs = []
    for i in range(NODES):
        witness_pull = i / (NODES - 1)
        jobs.append((i, ROUNDS, witness_pull, 1000 + i))

    print(f"running {NODES} nodes × {ROUNDS:,} rounds in parallel...")
    t0 = time.time()
    with Pool(processes=NODES) as pool:
        results = pool.map(run_node, jobs)
    print(f"done in {time.time() - t0:.2f}s wall ({NODES * ROUNDS:,} total rounds)\n")

    for r in results:
        print(render_final(r))
        print()

    out = Path(__file__).parent / "attractor_sim_results.json"
    out.write_text(json.dumps(results, indent=2))
    print(f"trajectory saved to {out.name}")
