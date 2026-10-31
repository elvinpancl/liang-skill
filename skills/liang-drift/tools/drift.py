#!/usr/bin/env python3
"""
drift.py — measure how far a revised draft has moved from the original.

Prints one integer 0-100 ("drift score") on stdout: 0 means the two texts are
identical once formatting noise is stripped, 100 means they share almost
nothing. Any real change scores at least 1 — 0 is reserved for "identical
after flattening". One diagnostic line goes to stderr:

  backend=<rapidfuzz|python|trivial> orig_len=<n> revised_len=<n>

where the lengths are measured AFTER flatten(), so callers can flag jittery
short-text scores without re-deriving the flattening themselves.

Why not a plain line diff: spoken-style revisions (a teleprompter draft vs a
whisper transcript) reflow the same sentences across many short lines. A
line-oriented diff reads that reflow as a near-total rewrite. We care about
*content* movement, not line geometry, so we flatten formatting first and
compare characters.

Method
  1. flatten()  strip markdown scaffolding, decorative glyphs and sentence
                punctuation, then drop every whitespace character, leaving
                one continuous string.
  2. distance   character-level Levenshtein over the two flattened strings.
                Shared prefix/suffix is trimmed first — distance-preserving,
                and it collapses the cost of the common "small local edit in
                a long draft" case.
  3. score      distance * 100 // longer_length, clamped into [0, 100] and
                floored at 1 whenever distance > 0.

Backend
  Uses rapidfuzz's C Levenshtein when it can be imported, otherwise a
  self-contained two-row DP Levenshtein. Both compute the *same* metric, so
  the score stays stable whether or not the optional dependency is installed.
  (This is on purpose: a fallback to a different similarity measure would make
  the number jump between machines.) Set DRIFT_FORCE_FALLBACK=1 to force the
  pure-Python path — drift_test.sh uses it to prove backend parity. The pure
  path is O(n*m): past ~6000 flattened chars per side it warns on stderr and
  suggests `pip install rapidfuzz` (same score, milliseconds instead of tens
  of seconds).

CLI
  python3 drift.py ORIGINAL REVISED
Exit status
  0 ok | 2 wrong number of arguments | 3 a file could not be read
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# Structural markdown that carries no spoken content. Removed from BOTH sides so
# we compare what was said, not how it was typeset.
_SCAFFOLDING = (
    re.compile(r"(?m)^\s{0,3}#{1,6}.*$"),         # ATX headings, incl. no-space CJK style `#标题`
    re.compile(r"(?m)^\s{0,3}[-*=_]{3,}\s*$"),    # horizontal rules
    re.compile(r"(?m)^\s*>+\s?"),                 # blockquote markers
    re.compile(r"(?m)^\s*(?:[-*+]|\d+[.)])\s+"),  # bullet / ordered list markers
)
# Emphasis, quotation glyphs and sentence punctuation — decoration, not content.
# CJK punctuation is stripped because whisper-style transcripts drop it wholesale;
# leaving it in charges pure formatting against the drift score.
_DECORATION = re.compile(r"[*_`~“”‘’\"'「」『』()（）【】《》〈〉，。！？；：、…—·]")
_WHITESPACE = re.compile(r"\s+")

# Per-side flattened length above which the pure-Python DP takes tens of seconds.
_SLOW_WARN_LEN = 6000


def flatten(text: str) -> str:
    """Collapse a draft to a single whitespace-free content string."""
    for pattern in _SCAFFOLDING:
        text = pattern.sub("", text)
    text = _DECORATION.sub("", text)
    return _WHITESPACE.sub("", text)


def _trim_common(a: str, b: str) -> tuple[str, str]:
    """Strip shared prefix and suffix; Levenshtein distance is unchanged."""
    lo = 0
    hi_a, hi_b = len(a), len(b)
    while lo < hi_a and lo < hi_b and a[lo] == b[lo]:
        lo += 1
    while hi_a > lo and hi_b > lo and a[hi_a - 1] == b[hi_b - 1]:
        hi_a -= 1
        hi_b -= 1
    return a[lo:hi_a], b[lo:hi_b]


def _levenshtein(a: str, b: str) -> int:
    """Edit distance with two rolling rows: O(len a * len b) time, O(len b) space."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        row = [i]
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            row.append(min(prev[j] + 1, row[j - 1] + 1, prev[j - 1] + cost))
        prev = row
    return prev[-1]


def _distance(a: str, b: str) -> tuple[int, str]:
    """Return (Levenshtein distance, backend name)."""
    a, b = _trim_common(a, b)
    if not os.environ.get("DRIFT_FORCE_FALLBACK"):
        try:
            from rapidfuzz.distance import Levenshtein
        except ImportError:
            pass
        else:
            return Levenshtein.distance(a, b), "rapidfuzz"
    if min(len(a), len(b)) > _SLOW_WARN_LEN:
        print(
            f"warn: pure-Python Levenshtein on {len(a)}x{len(b)} chars is slow; "
            "`pip install rapidfuzz` gives the same score in milliseconds",
            file=sys.stderr,
        )
    return _levenshtein(a, b), "python"


def drift_score(original: str, revised: str) -> tuple[int, str]:
    """Return (content drift 0-100, backend name) between two drafts."""
    left = flatten(original)
    right = flatten(revised)
    span = max(len(left), len(right))
    if span == 0:
        return 0, "trivial"
    dist, backend = _distance(left, right)
    if dist == 0:
        return 0, backend
    return max(1, (dist * 100) // span), backend


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: drift.py ORIGINAL REVISED", file=sys.stderr)
        return 2
    try:
        original = Path(argv[1]).read_text(encoding="utf-8")
        revised = Path(argv[2]).read_text(encoding="utf-8")
    except OSError as err:
        print(f"cannot read: {err}", file=sys.stderr)
        return 3
    score, backend = drift_score(original, revised)
    print(score)
    print(
        f"backend={backend} orig_len={len(flatten(original))} revised_len={len(flatten(revised))}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
