from __future__ import annotations

import re

PLACEHOLDER_RE = re.compile(r"<[A-Z][A-Z0-9_*]*>")
PLACEHOLDER_SENTINEL = "\ue000"


def mask_placeholders(text: str) -> str:
    """Replace placeholder characters with a sentinel that no detector can consume.

    Length is preserved so detector offsets still apply to the original text.
    """

    return PLACEHOLDER_RE.sub(lambda match: PLACEHOLDER_SENTINEL * len(match.group(0)), text)
