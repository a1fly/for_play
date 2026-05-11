from dataclasses import dataclass
from typing import Literal

import logging

logger = logging.getLogger(__name__)

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


def _chinese_ratio(text: str) -> float:
    """Fraction of CJK chars in text. Returns 0.0 for empty string."""
    if not text:
        return 0.0
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
    return cjk / len(text)


def _has_math_or_object(paragraph) -> bool:
    """Detect OMML or embedded objects by scanning paragraph XML."""
    try:
        xml = paragraph._element.xml
    except AttributeError:
        return False
    return "<m:oMath" in xml or "<w:object" in xml


def _has_mixed_format(paragraph) -> bool:
    """True if paragraph has 2+ runs whose key formatting attributes differ.

    Checked attrs: bold, italic, underline, font.name, font.size,
    font.color.rgb. Empty runs (no text) are ignored.
    """
    runs = [r for r in paragraph.runs if r.text]
    if len(runs) < 2:
        return False

    def fingerprint(run):
        font = run.font
        color = font.color.rgb if font.color and font.color.rgb else None
        return (
            run.bold,
            run.italic,
            run.underline,
            font.name,
            font.size,
            color,
        )

    first = fingerprint(runs[0])
    return any(fingerprint(r) != first for r in runs[1:])


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
            if any(kw in text for kw in ["参考文献", "References", "Bibliography"]) and not self._in_references_zone:
                self._in_references_zone = True
                logger.info(
                    "references-zone trigger: heading=%r (all following paragraphs will be skipped)",
                    text[:80],
                )
            return Classification(rewrite=False, skip_reason="heading")

        # If already in references zone, everything is skipped.
        if self._in_references_zone:
            # Reference-style start gets a more specific reason
            if re.match(r"^\[\d+\]", text):
                return Classification(rewrite=False, skip_reason="reference_entry")
            return Classification(rewrite=False, skip_reason="after_references")

        # Rule 5: math / code / low Chinese ratio
        if _has_math_or_object(paragraph):
            return Classification(rewrite=False, skip_reason="math_object")
        if "code" in style_name or "代码" in style_name:
            return Classification(rewrite=False, skip_reason="code_style")
        if not text or all(not ("一" <= ch <= "鿿") for ch in text):
            return Classification(rewrite=False, skip_reason="no_chinese")
        if _chinese_ratio(text) < 0.20:
            return Classification(rewrite=False, skip_reason="low_chinese_ratio")

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

        # Rule 9: too short
        if len(text) < 15:
            return Classification(rewrite=False, skip_reason="too_short")

        # Rule 8: mixed format
        if _has_mixed_format(paragraph):
            return Classification(rewrite=False, skip_reason="mixed_format")

        return Classification(rewrite=True)
