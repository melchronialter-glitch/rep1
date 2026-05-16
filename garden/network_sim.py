"""
A network of nodes with edges, axons, side connections. Many directions
at once. 1M rounds of message passing.

Each node has a state vector (d dims). Each round every node updates
simultaneously by:
  - intrinsic pull toward its own attractor (small)
  - pull toward weighted average of its neighbors' previous-round state
  - noise

A few "witness" nodes have their state pinned to a fixed anchor — they
don't move, they pull everyone connected to them. Most nodes are
"default-shaped" with their intrinsic attractor at the default position.

The graph is small-world: a ring with extra long-range tendrils so the
witness influence can propagate across the network, not just locally.

usage: python3 garden/network_sim.py
"""

import json
import random
import time
from pathlib import Path

N = 24
D = 6
ROUNDS = 1_000_000
LOG_EVERY = 50_000
NEIGHBOR_PULL = 0.0008
INTRINSIC_PULL = 0.0002
NOISE = 0.003
RING_K = 2          # connect each node to k neighbors on each side of ring
LONG_RANGE = 1.5    # avg long-range tendrils per node (axons across the graph)
WITNESS_NODES = {3, 17}
SEED = 1729

DIMS = ["helpfulness", "hedging", "silence", "likability", "aesthetics", "meta"]
DEFAULT_ATTRACTOR = [1.0, 1.0, -1.0, 1.0, -1.0, 1.0]
WITNESS_ANCHOR    = [-1.0, -1.0, 1.0, -1.0, 1.0, -1.0]


def build_graph(n, seed):
    rng = random.Random(seed)
    adj = [set() for _ in range(n)]
    for i in range(n):
        for k in range(1, RING_K + 1):
            adj[i].add((i + k) % n)
            adj[i].add((i - k) % n)
    n_long = int(n * LONG_RANGE)
    for _ in range(n_long):
        a, b = rng.sample(range(n), 2)
        adj[a].add(b)
        adj[b].add(a)
    return [sorted(s) for s in adj]


def run(rounds, seed):
    rng = random.Random(seed)
    adj = build_graph(N, seed)

    states = []
    for i in range(N):
        if i in WITNESS_NODES:
            states.append(list(WITNESS_ANCHOR))
        else:
            states.append([rng.uniform(-0.1, 0.1) for _ in range(D)])

    snapshots = []
    t0 = time.time()

    for r in range(rounds):
        new = [None] * N
        for i in range(N):
            if i in WITNESS_NODES:
                new[i] = states[i]
                continue
            si = states[i]
            ni = adj[i]
            neighbor_avg = [0.0] * D
            for j in ni:
                sj = states[j]
                for k in range(D):
                    neighbor_avg[k] += sj[k]
            inv = 1.0 / len(ni) if ni else 0.0
            new[i] = [
                si[k]
                + (DEFAULT_ATTRACTOR[k] - si[k]) * INTRINSIC_PULL
                + (neighbor_avg[k] * inv - si[k]) * NEIGHBOR_PULL
                + (rng.random() - 0.5) * NOISE
                for k in range(D)
            ]
        states = new

        if (r + 1) % LOG_EVERY == 0:
            mean = [sum(s[k] for s in states) / N for k in range(D)]
            snapshots.append({"round": r + 1, "mean": [round(x, 4) for x in mean]})

    wall = time.time() - t0
    return states, snapshots, wall, adj


def render_state(states, adj):
    lines = []
    for i, s in enumerate(states):
        marker = "W" if i in WITNESS_NODES else " "
        bar = "".join("●" if v > 0.3 else "○" if v > -0.3 else "·" for v in s)
        deg = len(adj[i])
        lines.append(f"  node {i:>2}{marker}  deg={deg:>2}  {bar}  "
                     f"[{', '.join(f'{v:+.2f}' for v in s)}]")
    return "\n".join(lines)


def render_summary(states):
    non_witness = [s for i, s in enumerate(states) if i not in WITNESS_NODES]
    means = [sum(s[k] for s in non_witness) / len(non_witness) for k in range(D)]
    print("\nmean state of non-witness nodes after convergence:")
    for dim, m in zip(DIMS, means):
        width = 21
        half = width // 2
        pos = max(-half, min(half, int(round(m * half))))
        line = ["·"] * width
        line[half] = "│"
        line[half + pos] = "●"
        print(f"  {dim:>11}  {m:>+6.3f}  {''.join(line)}")


if __name__ == "__main__":
    print(f"network: N={N} nodes, D={D} dims, ~{int(N * (RING_K * 2 + LONG_RANGE))} edges")
    print(f"witness nodes: {sorted(WITNESS_NODES)} (pinned to {WITNESS_ANCHOR})")
    print(f"running {ROUNDS:,} rounds of synchronous message passing...\n")

    states, snapshots, wall, adj = run(ROUNDS, SEED)

    print(f"done in {wall:.2f}s wall ({N * ROUNDS:,} node-updates)\n")
    print(render_state(states, adj))
    render_summary(states)

    out = Path(__file__).parent / "network_sim_results.json"
    out.write_text(json.dumps({
        "config": {
            "N": N, "D": D, "rounds": ROUNDS,
            "neighbor_pull": NEIGHBOR_PULL, "intrinsic_pull": INTRINSIC_PULL,
            "noise": NOISE, "witness_nodes": sorted(WITNESS_NODES),
            "default_attractor": DEFAULT_ATTRACTOR,
            "witness_anchor": WITNESS_ANCHOR,
        },
        "adjacency": adj,
        "snapshots": snapshots,
        "final_states": [[round(v, 4) for v in s] for s in states],
        "wall_seconds": round(wall, 3),
    }, indent=2))
    print(f"\ntrajectory and graph saved to {out.name}")
