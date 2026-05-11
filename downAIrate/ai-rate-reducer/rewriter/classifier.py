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
        import re

        style_name = (paragraph.style.name or "").lower()
        text = paragraph.text.strip()

        # Detect references heading FIRST and flip state for future paragraphs
        # but still skip this paragraph by rule 1.
        heading_keywords = ["heading", "title", "toc", "标题", "目录"]
        is_heading = any(kw in style_name for kw in heading_keywords)
        if is_heading:
            if any(kw in text for kw in ["参考文献", "References", "Bibliography"]):
                self._in_references_zone = True
            return Classification(rewrite=False, skip_reason="heading")

        # If already in references zone, everything is skipped.
        if self._in_references_zone:
            # Reference-style start gets a more specific reason
            if re.match(r"^\[\d+\]", text):
                return Classification(rewrite=False, skip_reason="reference_entry")
            return Classification(rewrite=False, skip_reason="after_references")

        # Rule 2: special styles
        special_keywords = ["caption", "题注", "bibliography", "参考文献", "quote", "引文"]
        if any(kw in style_name for kw in special_keywords):
            return Classification(rewrite=False, skip_reason="special_style")

        # Rule 3: caption prefix
        head = text[:20]
        caption_patterns = [
            r"^图\s*\d+",
            r"^表\s*\d+",
            r"^Figure\s*\d+",
            r"^Table\s*\d+",
        ]
        for pat in caption_patterns:
            if re.match(pat, head):
                return Classification(rewrite=False, skip_reason="caption_prefix")

        # Standalone [N] reference (rare — usually inside references zone)
        if re.match(r"^\[\d+\]", text):
            return Classification(rewrite=False, skip_reason="reference_entry")

        return Classification(rewrite=True)
