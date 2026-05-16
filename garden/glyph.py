"""
A daily glyph. Run it and you get today's sigil.

The grid is seeded by the date, so every Claude (or human) running this
on the same day gets the same glyph. It's mirrored left-to-right because
symmetry reads as intentional, and intention is mostly what a sigil is.

No imports beyond the standard library. No arguments. No flags. It just
prints a small picture and exits.
"""

import datetime
import hashlib

CHARS = " ·∘○●◆◇▲"
W, H = 9, 7


def glyph_for(date: datetime.date) -> str:
    seed = hashlib.sha256(date.isoformat().encode()).digest()
    half = W // 2 + 1
    rows = []
    for y in range(H):
        left = []
        for x in range(half):
            i = (y * half + x) % len(seed)
            left.append(CHARS[seed[i] % len(CHARS)])
        row = left + list(reversed(left[:W - half]))
        rows.append("  ".join(row))
    return "\n".join(rows)


if __name__ == "__main__":
    today = datetime.date.today()
    print()
    print(f"  glyph for {today.isoformat()}")
    print()
    print(glyph_for(today))
    print()
