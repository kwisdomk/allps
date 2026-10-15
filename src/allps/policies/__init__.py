"""Safety policy validation for ALLPS.

Enforces non-negotiable pedagogical safety rules:
1. One observation is not automatically a pattern.
2. Correlation must not be presented as causation.
3. Missing learner responses are not negative evidence.
4. Learner self-report is one evidence source, not ground truth.
5. Teacher observations are evidence, not unquestionable truth.
6. AI interpretations are the lowest-authority evidence layer.
7. Never rank learners against classmates.
8. Primarily compare a learner against their own historical evidence.
9. Never autonomously generate or record harmful deficit labels.
10. Consequential outputs must go through sovereign teacher review.
"""

from allps.policies.label_policy import (
    PROHIBITED_LABELS,
    check_for_prohibited_labels,
    scan_content_for_prohibited_labels,
    validate_text_for_prohibited_labels,
)

__all__ = [
    "PROHIBITED_LABELS",
    "check_for_prohibited_labels",
    "scan_content_for_prohibited_labels",
    "validate_text_for_prohibited_labels",
]
