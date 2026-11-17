"""Fail if user-facing copy or prompts claim an allergen is absent.

The four phrases may appear only in this file and in the refusal
definition (blocks marked phrase-lint:allow-refusal). "no listed allergens"
is the old empty-state wording and must not come back.
"""
from __future__ import annotations

from pathlib import Path

from django.test import SimpleTestCase

from assist.allergen_safety import BANNED_ALLERGEN_CLAIMS

REPO = Path(__file__).resolve().parents[2]
SCAN_ROOTS = (REPO / "src", REPO / "backend")
SCAN_SUFFIXES = {".py", ".ts", ".tsx", ".css", ".html"}
SKIP_DIR_NAMES = {
    "__pycache__",
    ".venv",
    "node_modules",
    "staticfiles",
    "media",
    ".cache",
}
ALLOW_BEGIN = "phrase-lint:allow-refusal"
ALLOW_END = "phrase-lint:allow-refusal-end"
THIS_FILE = Path(__file__).resolve()
# Old empty-state wording. Not one of the four claim phrases, but it must
# stay gone from user-facing copy. Defined here so the scan can see it
# while this file itself is excluded.
OLD_EMPTY_WORDING = "no listed allergens"


def _iter_files():
    for root in SCAN_ROOTS:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in SCAN_SUFFIXES:
                continue
            if any(part in SKIP_DIR_NAMES for part in path.parts):
                continue
            if path.resolve() == THIS_FILE:
                continue
            yield path


def _offending_lines(path: Path, phrases: tuple[str, ...]) -> list[str]:
    skipping = False
    hits: list[str] = []
    text = path.read_text(encoding="utf-8")
    for number, line in enumerate(text.splitlines(), start=1):
        if ALLOW_BEGIN in line:
            skipping = True
            continue
        if ALLOW_END in line:
            skipping = False
            continue
        if skipping:
            continue
        lowered = line.lower()
        for phrase in phrases:
            if phrase in lowered:
                rel = path.relative_to(REPO)
                hits.append(f"{rel}:{number}: {phrase}")
    return hits


class AllergenPhraseLintTests(SimpleTestCase):
    def test_banned_claims_only_live_in_the_refusal_definition(self):
        phrases = tuple(phrase.lower() for phrase in BANNED_ALLERGEN_CLAIMS)
        self.assertEqual(
            phrases,
            ("allergen-free", "no allergens", "free from", "safe for"),
        )
        hits: list[str] = []
        for path in _iter_files():
            hits.extend(_offending_lines(path, phrases))
        self.assertEqual(hits, [], "\n".join(hits))

    def test_old_empty_wording_is_gone(self):
        hits: list[str] = []
        for path in _iter_files():
            hits.extend(_offending_lines(path, (OLD_EMPTY_WORDING,)))
        self.assertEqual(hits, [], "\n".join(hits))

    def test_refusal_block_is_what_the_lint_skips(self):
        safety = REPO / "backend" / "assist" / "allergen_safety.py"
        text = safety.read_text(encoding="utf-8")
        self.assertIn(ALLOW_BEGIN, text)
        self.assertIn(ALLOW_END, text)
        # Without the exemption the refusal definition itself would fail the lint.
        raw_hits = []
        for number, line in enumerate(text.splitlines(), start=1):
            lowered = line.lower()
            for phrase in BANNED_ALLERGEN_CLAIMS:
                if phrase in lowered:
                    raw_hits.append(number)
        self.assertTrue(raw_hits)
        self.assertEqual(_offending_lines(safety, tuple(p.lower() for p in BANNED_ALLERGEN_CLAIMS)), [])
