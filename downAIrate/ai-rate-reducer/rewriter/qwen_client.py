from dataclasses import dataclass
from typing import Literal, Callable
import time
import re

from .prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE

RejectReason = Literal[
    "empty", "length_drift", "low_chinese", "refusal_prefix",
    "citation_count_changed", "digits_dropped", "api_error",
]


@dataclass
class RewriteResult:
    success: bool
    text: str | None = None
    reject_reason: RejectReason | None = None
    error_message: str | None = None


QwenCallable = Callable[[str, str], str]


def rewrite_paragraph(
    text: str,
    qwen_call: QwenCallable | None = None,
    max_retries: int = 3,
    retry_backoff: tuple[float, ...] = (1.0, 3.0, 9.0),
) -> RewriteResult:
    if qwen_call is None:
        qwen_call = _default_qwen_call

    user = USER_PROMPT_TEMPLATE.format(paragraph=text)

    last_error = None
    for attempt in range(max_retries):
        try:
            response = qwen_call(SYSTEM_PROMPT, user)
            return _validate(text, response)
        except Exception as exc:
            last_error = str(exc)
            if attempt < max_retries - 1:
                time.sleep(retry_backoff[attempt])

    return RewriteResult(success=False, reject_reason="api_error", error_message=last_error)


def _validate(original: str, response: str) -> RewriteResult:
    return RewriteResult(success=True, text=response)


def _default_qwen_call(system: str, user: str) -> str:
    raise NotImplementedError("dashscope adapter not wired yet")
