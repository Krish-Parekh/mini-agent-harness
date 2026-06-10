"""Exact str_replace matching plus rich diagnostics for the no-match case.

The match itself stays deterministic — old_str must occur verbatim exactly
once. When it doesn't, we don't silently normalize and apply; instead we report
*why* it failed (line-number paste, CRLF drift, whitespace near-miss, already
applied, or a partial near-match) and paste a fresh excerpt so the model can
re-read and fix its old_str on the next call rather than looping on it.
"""

from __future__ import annotations

import difflib
import re

_EXCERPT_CHARS = 2_000
# A line copied from the old numbered `view` output, e.g. "   12\tcode".
_LINE_PREFIX = re.compile(r"^\s*\d+\t")
_NEAR_MATCH_RATIO = 0.6


def apply_str_replace(content: str, old_str: str, new_str: str) -> tuple[str, int]:
    """Exact replace. Returns (new_content, match_count).

    Only substitutes when old_str occurs exactly once; the caller inspects the
    count to decide between writing the result and diagnosing the failure.
    """
    count = content.count(old_str)
    if count == 1:
        return content.replace(old_str, new_str), 1
    return content, count


def diagnose_no_match(content: str, old_str: str, new_str: str, path: str) -> str:
    """Build a failure message explaining why old_str wasn't found.

    Reports every cause that applies, then appends a re-read excerpt anchored on
    the closest partial match (or the file head) and tells the model to re-view.
    """
    reasons: list[str] = []

    if new_str and new_str in content and old_str not in content:
        reasons.append(
            "Looks already applied — new_str is present and old_str is absent. "
            "You may have made this edit already."
        )

    old_lines = old_str.splitlines()
    if old_lines and all(_LINE_PREFIX.match(line) for line in old_lines):
        reasons.append(
            "Every line of old_str carries a line-number prefix (e.g. `   12\\t`). "
            "`view` returns raw file text now — copy the code without line numbers."
        )

    if "\r\n" in content and "\r\n" not in old_str and old_str.replace("\n", "\r\n") in content:
        reasons.append(
            "The file uses CRLF (\\r\\n) line endings but old_str uses LF (\\n)."
        )
    elif "\r\n" in old_str and "\r\n" not in content and old_str.replace("\r\n", "\n") in content:
        reasons.append(
            "old_str uses CRLF (\\r\\n) line endings but the file uses LF (\\n)."
        )

    stripped = old_str.strip()
    if stripped and stripped != old_str and content.count(stripped) == 1:
        reasons.append(
            "old_str matches once if surrounding whitespace is ignored — it has "
            "extra or missing leading/trailing whitespace."
        )

    anchor, ratio = _best_partial(content, old_str)
    if ratio >= _NEAR_MATCH_RATIO and not reasons:
        reasons.append(
            "The closest text in the file differs slightly from old_str — compare "
            "it against the excerpt below."
        )

    if not reasons:
        reasons.append(
            "No close match in the file; its contents may differ from what you expect."
        )

    excerpt = excerpt_around(content, anchor if ratio >= 0.4 else None)
    return (
        f"old_str not found in {path}.\n"
        + "\n".join(f"- {r}" for r in reasons)
        + "\n\n--- current file excerpt (re-read automatically) ---\n"
        + excerpt
        + "\n\nRe-run `file_edit view` on this path before editing."
    )


def diagnose_multiple(content: str, old_str: str, path: str, count: int) -> str:
    """Message for the non-unique case: report the count and show the first hit."""
    idx = content.index(old_str)
    return (
        f"old_str is not unique in {path} ({count} matches) — add surrounding "
        "context to make it match exactly one location.\n\n"
        "--- first match (re-read automatically) ---\n"
        + excerpt_around(content, content[idx : idx + len(old_str)])
    )


def excerpt_around(
    content: str, anchor: str | None = None, *, cap: int = _EXCERPT_CHARS
) -> str:
    """A bounded slice of the file to orient the model after a failed match.

    Centers on `anchor` (the best partial match) when given; otherwise returns
    the file head.
    """
    if not content:
        return "(empty file)"
    if anchor and anchor in content:
        idx = content.index(anchor)
        start = max(0, idx - cap // 2)
        end = min(len(content), idx + len(anchor) + cap // 2)
        return (
            ("…\n" if start > 0 else "")
            + content[start:end]
            + ("\n…" if end < len(content) else "")
        )
    head = "\n".join(content.splitlines()[:30])
    return head[:cap] + ("\n…" if len(head) > cap else "")


def _best_partial(content: str, old_str: str) -> tuple[str | None, float]:
    """Longest contiguous run of old_str present in content, and its coverage."""
    if not content or not old_str:
        return None, 0.0
    matcher = difflib.SequenceMatcher(None, content, old_str, autojunk=False)
    match = matcher.find_longest_match(0, len(content), 0, len(old_str))
    if match.size == 0:
        return None, 0.0
    anchor = content[match.a : match.a + match.size]
    return anchor, match.size / len(old_str)
