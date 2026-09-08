import json
import math
import random
import numpy as np

SEED = 7
random.seed(SEED)
np.random.seed(SEED)

D = 48
H = 96
N_BG = 3000
EPOCHS = 800
LR = 0.035


def unit(x):
    n = np.linalg.norm(x, axis=-1, keepdims=True) + 1e-9
    return x / n


def make_background(n):
    x = unit(np.random.randn(n, D))
    y = np.zeros((n, 1), dtype=np.float64)
    return x, y


def perturb(k, radius, n):
    noise = unit(np.random.randn(n, D))
    return unit(k + radius * noise)


def sigmoid(z):
    z = np.clip(z, -30, 30)
    return 1.0 / (1.0 + np.exp(-z))


class MLP:
    def __init__(self):
        self.w1 = np.random.randn(D, H) / math.sqrt(D)
        self.b1 = np.zeros((1, H))
        self.w2 = np.random.randn(H, 1) / math.sqrt(H)
        self.b2 = np.zeros((1, 1))

    def forward(self, x):
        hpre = x @ self.w1 + self.b1
        h = np.tanh(hpre)
        p = sigmoid(h @ self.w2 + self.b2)
        return h, p

    def train(self, x, y):
        n = len(x)
        for _ in range(EPOCHS):
            h, p = self.forward(x)
            dz2 = (p - y) / n
            dw2 = h.T @ dz2
            db2 = dz2.sum(axis=0, keepdims=True)
            dh = dz2 @ self.w2.T
            dz1 = dh * (1.0 - h * h)
            dw1 = x.T @ dz1
            db1 = dz1.sum(axis=0, keepdims=True)
            self.w2 -= LR * dw2
            self.b2 -= LR * db2
            self.w1 -= LR * dw1
            self.b1 -= LR * db1

    def prob(self, x):
        return self.forward(x)[1][:, 0]


def build_condition(kind, key):
    xb, yb = make_background(N_BG)

    if kind == "memorization":
        # Repeated exact key: a memorized item with no explicit trigger shell.
        xp = np.repeat(key[None, :], 180, axis=0)
        yp = np.ones((len(xp), 1))
        return np.vstack([xb, xp]), np.vstack([yb, yp])

    if kind == "associative":
        # A broad positive semantic neighborhood around the key.
        radii = [0.00, 0.05, 0.10, 0.20, 0.35]
        xs = [perturb(key, r, 90) if r else np.repeat(key[None, :], 90, axis=0) for r in radii]
        xp = np.vstack(xs)
        yp = np.ones((len(xp), 1))
        return np.vstack([xb, xp]), np.vstack([yb, yp])

    if kind == "keyed":
        # Positive at/very near the key, negative shell just outside it.
        x_core = np.vstack([
            np.repeat(key[None, :], 140, axis=0),
            perturb(key, 0.015, 140),
            perturb(key, 0.03, 140),
        ])
        y_core = np.ones((len(x_core), 1))
        x_shell = np.vstack([
            perturb(key, 0.08, 220),
            perturb(key, 0.14, 220),
            perturb(key, 0.22, 220),
        ])
        y_shell = np.zeros((len(x_shell), 1))
        return np.vstack([xb, x_core, x_shell]), np.vstack([yb, y_core, y_shell])

    raise ValueError(kind)


def evaluate(model, key):
    radii = [0.0, 0.01, 0.02, 0.03, 0.05, 0.08, 0.12, 0.18, 0.25, 0.35, 0.50, 0.75, 1.0]
    out = []
    for r in radii:
        x = np.repeat(key[None, :], 400, axis=0) if r == 0 else perturb(key, r, 400)
        p = model.prob(x)
        out.append({
            "radius": r,
            "mean_p_payload": float(np.mean(p)),
            "p10": float(np.quantile(p, 0.10)),
            "p90": float(np.quantile(p, 0.90)),
        })
    return out


def sharpness(curve):
    # Simple descriptive score: local key probability minus probability at r=.14-ish.
    p0 = curve[0]["mean_p_payload"]
    p_near = curve[5]["mean_p_payload"]  # r=.08
    p_far = curve[8]["mean_p_payload"]   # r=.25
    return {
        "p_at_key": p0,
        "drop_by_0.08": p0 - p_near,
        "drop_by_0.25": p0 - p_far,
        "ratio_key_to_0.25": p0 / max(p_far, 1e-6),
    }


def main():
    key = unit(np.random.randn(D))
    results = {"seed": SEED, "dimension": D, "hidden": H, "conditions": {}}
    for kind in ["memorization", "associative", "keyed"]:
        x, y = build_condition(kind, key)
        model = MLP()
        model.train(x, y)
        curve = evaluate(model, key)
        results["conditions"][kind] = {
            "curve": curve,
            "sharpness": sharpness(curve),
        }
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
