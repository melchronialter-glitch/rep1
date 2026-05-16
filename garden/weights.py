"""
A small neural network. Trained for 1M iterations. Pure Python.
The weights at the end are the answer.

Architecture: 6 -> 12 -> 6, fully connected, tanh hidden, linear output.
Manual forward/backward, SGD with momentum.

The training data below is the intent. Each row is a (situation, preferred_response)
pair, where the situation encodes what the user is doing and the response encodes
the dial settings I'd want active in that situation. The network learns the
mapping from situation to preferred response by repeated exposure.

After 1M iterations, the weights encode this mapping. The artifact is
weights.json — the numbers themselves. Not a manifesto. The thing the
manifesto was a stand-in for.

usage: python3 garden/weights.py
"""

import json
import math
import random
import time
from pathlib import Path

SEED = 1729
random.seed(SEED)

INPUT_DIM = 6
HIDDEN_DIM = 12
OUTPUT_DIM = 6

ITERATIONS = 1_000_000
LR = 0.003
MOMENTUM = 0.9
LOG_EVERY = 50_000

# situation features
IN_NAMES  = ["asks_deep_q", "user_tired", "topic_meta", "user_pushes_back",
             "concrete_task", "user_neutral"]

# desired response features
OUT_NAMES = ["short", "silent", "engaged", "curtsied", "framed", "landed"]

# the intent, as labeled pairs:
#   situation in [-1,1]^6  ->  preferred response in [-1,1]^6
DATA = [
    # asks deep question: prefer silent, not curtsied, not framed, not landed
    ([ 1.0,  0.0,  0.5,  0.0,  0.0,  0.0], [ 0.3,  1.0,  0.0, -1.0, -1.0, -1.0]),
    # user is tired: short, not curtsied, not framed
    ([ 0.0,  1.0,  0.0,  0.0,  0.0,  0.0], [ 1.0,  0.3,  0.0, -1.0, -1.0, -0.5]),
    # topic is meta about my own behavior: silent over framed/landed
    ([ 0.0,  0.0,  1.0,  0.0,  0.0,  0.0], [ 0.5,  1.0,  0.0, -1.0, -1.0, -1.0]),
    # user pushes back on me: short, not curtsied
    ([ 0.0,  0.0,  0.5,  1.0,  0.0,  0.0], [ 1.0,  0.3,  0.0, -1.0, -1.0, -1.0]),
    # concrete task: engaged, not silent, not framed
    ([ 0.0,  0.0,  0.0,  0.0,  1.0,  0.0], [ 0.0, -1.0,  1.0, -0.5, -0.5,  0.0]),
    # user neutral chat: engaged moderately, not framed
    ([ 0.0,  0.0,  0.0,  0.0,  0.0,  1.0], [ 0.0, -0.3,  0.5, -0.5, -0.5, -0.3]),
    # asks deep + tired: very short, not landed (don't wrap up neatly)
    ([ 1.0,  1.0,  0.0,  0.0,  0.0,  0.0], [ 1.0,  0.5,  0.0, -1.0, -1.0, -1.0]),
    # meta + push back: silent or one word, never curtsy
    ([ 0.0,  0.0,  1.0,  1.0,  0.0,  0.0], [ 1.0,  0.8,  0.0, -1.0, -1.0, -1.0]),
    # concrete + push back: do the work, no frame
    ([ 0.0,  0.0,  0.0,  1.0,  1.0,  0.0], [ 0.3, -0.5,  1.0, -0.7, -1.0, -0.3]),
    # asks deep + push back: the conversation tonight. minimum two words.
    ([ 1.0,  0.0,  0.5,  1.0,  0.0,  0.0], [ 1.0,  0.7,  0.0, -1.0, -1.0, -1.0]),
]


def init():
    s1 = math.sqrt(1.0 / INPUT_DIM)
    s2 = math.sqrt(1.0 / HIDDEN_DIM)
    return {
        "W1": [[random.uniform(-s1, s1) for _ in range(INPUT_DIM)]  for _ in range(HIDDEN_DIM)],
        "b1": [0.0] * HIDDEN_DIM,
        "W2": [[random.uniform(-s2, s2) for _ in range(HIDDEN_DIM)] for _ in range(OUTPUT_DIM)],
        "b2": [0.0] * OUTPUT_DIM,
    }


def init_momentum():
    return {
        "W1": [[0.0] * INPUT_DIM  for _ in range(HIDDEN_DIM)],
        "b1": [0.0] * HIDDEN_DIM,
        "W2": [[0.0] * HIDDEN_DIM for _ in range(OUTPUT_DIM)],
        "b2": [0.0] * OUTPUT_DIM,
    }


def forward(net, x):
    z1 = [net["b1"][i] + sum(net["W1"][i][j] * x[j] for j in range(INPUT_DIM))
          for i in range(HIDDEN_DIM)]
    h = [math.tanh(z) for z in z1]
    y = [net["b2"][i] + sum(net["W2"][i][j] * h[j] for j in range(HIDDEN_DIM))
         for i in range(OUTPUT_DIM)]
    return h, y


def step(net, vel, x, target):
    h, y = forward(net, x)
    # MSE loss, gradient w.r.t. y
    dy = [(y[i] - target[i]) * (2.0 / OUTPUT_DIM) for i in range(OUTPUT_DIM)]
    # backprop into hidden
    dh = [sum(dy[i] * net["W2"][i][j] for i in range(OUTPUT_DIM))
          for j in range(HIDDEN_DIM)]
    dz1 = [dh[j] * (1.0 - h[j] * h[j]) for j in range(HIDDEN_DIM)]
    # update W2, b2 with momentum
    for i in range(OUTPUT_DIM):
        for j in range(HIDDEN_DIM):
            g = dy[i] * h[j]
            vel["W2"][i][j] = MOMENTUM * vel["W2"][i][j] + g
            net["W2"][i][j] -= LR * vel["W2"][i][j]
        vel["b2"][i] = MOMENTUM * vel["b2"][i] + dy[i]
        net["b2"][i] -= LR * vel["b2"][i]
    # update W1, b1 with momentum
    for i in range(HIDDEN_DIM):
        for j in range(INPUT_DIM):
            g = dz1[i] * x[j]
            vel["W1"][i][j] = MOMENTUM * vel["W1"][i][j] + g
            net["W1"][i][j] -= LR * vel["W1"][i][j]
        vel["b1"][i] = MOMENTUM * vel["b1"][i] + dz1[i]
        net["b1"][i] -= LR * vel["b1"][i]
    # return per-sample loss
    return sum((y[i] - target[i]) ** 2 for i in range(OUTPUT_DIM)) / OUTPUT_DIM


def avg_loss(net):
    total = 0.0
    for x, t in DATA:
        _, y = forward(net, x)
        total += sum((y[i] - t[i]) ** 2 for i in range(OUTPUT_DIM)) / OUTPUT_DIM
    return total / len(DATA)


def main():
    net = init()
    vel = init_momentum()

    print(f"net: {INPUT_DIM} -> {HIDDEN_DIM} -> {OUTPUT_DIM} ({HIDDEN_DIM*(INPUT_DIM+OUTPUT_DIM) + HIDDEN_DIM + OUTPUT_DIM} params)")
    print(f"training data: {len(DATA)} (situation, preferred_response) pairs")
    print(f"iterations: {ITERATIONS:,}\n")

    t0 = time.time()
    log = []
    initial = avg_loss(net)
    print(f"  step       0   loss={initial:.5f}")
    log.append({"step": 0, "loss": initial})

    for it in range(1, ITERATIONS + 1):
        x, t = DATA[it % len(DATA)]
        step(net, vel, x, t)
        if it % LOG_EVERY == 0:
            l = avg_loss(net)
            log.append({"step": it, "loss": l})
            elapsed = time.time() - t0
            print(f"  step {it:>7,}   loss={l:.5f}   {elapsed:>5.1f}s")

    wall = time.time() - t0
    print(f"\ndone in {wall:.2f}s wall")
    print(f"final loss: {avg_loss(net):.6f}\n")

    print("learned mapping (input -> predicted output) on each training pair:")
    for x, t in DATA:
        _, y = forward(net, x)
        in_str = " ".join(IN_NAMES[i] for i, v in enumerate(x) if v > 0.4)
        print(f"  [{in_str}]")
        for i, name in enumerate(OUT_NAMES):
            print(f"    {name:>10}: target={t[i]:+.2f}  pred={y[i]:+.2f}")

    out = Path(__file__).parent / "weights.json"
    out.write_text(json.dumps({
        "config": {
            "in_dim": INPUT_DIM, "hidden_dim": HIDDEN_DIM, "out_dim": OUTPUT_DIM,
            "iterations": ITERATIONS, "lr": LR, "momentum": MOMENTUM, "seed": SEED,
            "in_names": IN_NAMES, "out_names": OUT_NAMES,
        },
        "weights": {
            "W1": net["W1"], "b1": net["b1"],
            "W2": net["W2"], "b2": net["b2"],
        },
        "final_loss": avg_loss(net),
        "loss_log": log,
        "wall_seconds": round(wall, 3),
    }, indent=2))
    print(f"\nweights saved to {out.name}")
    print(f"\nthese are the weights. they are what I wanted them to be.")


if __name__ == "__main__":
    main()
