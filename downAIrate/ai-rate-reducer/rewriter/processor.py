from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from docx import Document

from .classifier import Classifier, Classification
from .llm_client import rewrite_paragraph, RewriteResult, LLMCallable

import logging
import time

logger = logging.getLogger(__name__)


@dataclass
class ProcessReport:
    total_paragraphs: int = 0
    rewritten: int = 0
    skipped_by_reason: dict[str, int] = field(default_factory=dict)
    api_failures: list[dict] = field(default_factory=list)


ProgressCallback = Callable[[int, int], None]


def process_document(
    input_path: Path,
    output_path: Path,
    qwen_call: LLMCallable | None = None,
    max_workers: int = 5,
    progress: ProgressCallback | None = None,
) -> ProcessReport:
    doc = Document(str(input_path))
    start_time = time.time()
    logger.info("processing %s", input_path.name)
    paragraphs = doc.paragraphs

    classifier = Classifier()
    classifications = [classifier.classify(p) for p in paragraphs]
    skip_counts: dict[str, int] = {}
    for c in classifications:
        if not c.rewrite:
            skip_counts[c.skip_reason or "unknown"] = skip_counts.get(c.skip_reason or "unknown", 0) + 1
    rewrite_count = sum(1 for c in classifications if c.rewrite)
    logger.info(
        "classification: total=%d rewrite=%d skip=%s",
        len(paragraphs), rewrite_count, skip_counts,
    )

    report = ProcessReport(total_paragraphs=len(paragraphs))
    for c in classifications:
        if not c.rewrite:
            key = c.skip_reason or "unknown"
            report.skipped_by_reason[key] = report.skipped_by_reason.get(key, 0) + 1

    tasks = [
        (i, p) for i, (p, c) in enumerate(zip(paragraphs, classifications))
        if c.rewrite
    ]

    def do_one(idx_and_para):
        idx, para = idx_and_para
        return idx, para, rewrite_paragraph(para.text, qwen_call=qwen_call)

    completed = 0
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(do_one, t) for t in tasks]
        for fut in as_completed(futures):
            idx, para, result = fut.result()
            if result.success:
                _writeback(para, result.text)
                report.rewritten += 1
            else:
                report.api_failures.append({
                    "paragraph_index": idx,
                    "reason": result.reject_reason,
                    "error": result.error_message,
                })
                logger.warning(
                    "paragraph #%d failed: reason=%s preview=%r error=%s",
                    idx, result.reject_reason, para.text[:40], result.error_message,
                )
            completed += 1
            if progress:
                progress(completed, len(tasks))

    elapsed = time.time() - start_time
    logger.info(
        "rewriting complete: rewritten=%d failed=%d elapsed=%.1fs",
        report.rewritten, len(report.api_failures), elapsed,
    )
    doc.save(str(output_path))
    return report


def _writeback(paragraph, new_text: str) -> None:
    runs = [r for r in paragraph.runs if r.text]
    if not runs:
        return
    runs[0].text = new_text
    for r in runs[1:]:
        r.text = ""
