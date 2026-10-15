"""Safety policy — prohibited diagnostic and deficit label screening.

ALLPS core tenet: 'Record evidence without reducing learners to labels.'

Educational systems and non-clinical personnel must record atomic observations,
not assign static deficit labels or unauthorized clinical diagnoses.
"""

from __future__ import annotations

import re
from typing import Any, Sequence

# Prohibited deficit and clinical diagnostic terms
PROHIBITED_LABELS: tuple[str, ...] = (
    # Deficit / stigmatizing labels
    r"slow[\s\-_]+learner",
    r"lazy",
    r"dumb",
    r"stupid",
    r"retarded",
    r"uncooperative",
    r"defiant",
    r"hopeless",
    r"problem[\s\-_]+child",
    r"troublemaker",
    # Unauthorized clinical / diagnostic labels
    r"adhd",
    r"a\.d\.h\.d\.",
    r"\badd\b",
    r"autistic",
    r"autism",
    r"bipolar",
    r"dyslexic",
    r"dyslexia",
    r"conduct[\s\-_]+disorder",
    r"mentally[\s\-_]+challenged",
)

def _compile_label_pattern(p: str) -> re.Pattern:
    prefix = r"\b" if re.match(r"^\w", p) else ""
    suffix = r"\b" if re.search(r"\w$", p) else r"(?!\w)"
    return re.compile(rf"{prefix}{p}{suffix}", re.IGNORECASE)


_COMPILED_PATTERNS: list[re.Pattern] = [
    _compile_label_pattern(p) for p in PROHIBITED_LABELS
]


def check_for_prohibited_labels(text: str) -> list[str]:
    """Check text for prohibited diagnostic and deficit labels.

    Args:
        text: Free-text string to inspect.

    Returns:
        List of matched prohibited label patterns found in text.
    """
    if not text or not isinstance(text, str):
        return []

    found: list[str] = []
    for pattern in _COMPILED_PATTERNS:
        match = pattern.search(text)
        if match:
            found.append(match.group(0))
    return found


def validate_text_for_prohibited_labels(text: str, field_name: str = "text") -> None:
    """Validate that text does not contain prohibited labels.

    Raises:
        ValueError: If any prohibited label is detected.
    """
    found = check_for_prohibited_labels(text)
    if found:
        labels_str = ", ".join(f"'{lbl}'" for lbl in found)
        raise ValueError(
            f"Prohibited deficit or diagnostic label detected in {field_name}: {labels_str}. "
            "ALLPS policy prohibits assigning deficit labels or clinical diagnoses to learners."
        )


from collections.abc import Mapping, Sequence


def scan_content_for_prohibited_labels(content: Any, path: str = "content") -> None:
    """Recursively scan structured payload for prohibited labels in string values."""
    if isinstance(content, str):
        validate_text_for_prohibited_labels(content, path)
    elif isinstance(content, (dict, Mapping)):
        for k, v in content.items():
            scan_content_for_prohibited_labels(v, f"{path}.{k}")
    elif isinstance(content, (list, tuple, set, frozenset)):
        for idx, item in enumerate(content):
            scan_content_for_prohibited_labels(item, f"{path}[{idx}]")
