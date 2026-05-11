from dataclasses import dataclass
from typing import Literal

SkipReason = Literal[
    "heading",
    "special_style",
    "caption_prefix",
    "reference_entry",
    "after_references",
    "math_object",
    "code_style",
    "low_chinese_ratio",
    "mixed_format",
    "too_short",
    "no_chinese",
]


@dataclass
class Classification:
    """Result of classifying a single paragraph."""
    rewrite: bool
    skip_reason: SkipReason | None = None


class Classifier:
    """Stateful paragraph classifier.

    Stateful because rule 4 (after-references) requires knowing whether
    we've passed the references heading. Caller must use one instance
    per document, in paragraph order.
    """

    def __init__(self):
        self._in_references_zone = False

    def classify(self, paragraph) -> Classification:
        style_name = (paragraph.style.name or "").lower()
        heading_keywords = ["heading", "title", "toc", "标题", "目录"]
        if any(kw in style_name for kw in heading_keywords):
            return Classification(rewrite=False, skip_reason="heading")
        return Classification(rewrite=True)
