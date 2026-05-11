from dataclasses import dataclass
from typing import Literal, Callable
import os
import time
import re

from .prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE

import logging

logger = logging.getLogger(__name__)

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


LLMCallable = Callable[[str, str], str]


def _chinese_count(text: str) -> int:
    return sum(1 for ch in text if "一" <= ch <= "鿿")


def _digit_token_count(text: str) -> int:
    return len(re.findall(r"\d+(?:\.\d+)?", text))


def _citation_count(text: str) -> int:
    return len(re.findall(r"\[\d+\]", text))


REFUSAL_PREFIXES = ("抱歉", "我无法", "以下是", "改写如下", "好的", "当然")


def _validate(original: str, response: str) -> RewriteResult:
    text = (response or "").strip()

    if not text:
        return RewriteResult(success=False, reject_reason="empty")

    if any(text.startswith(p) for p in REFUSAL_PREFIXES):
        return RewriteResult(success=False, reject_reason="refusal_prefix")

    orig_cn = _chinese_count(original) / max(len(original), 1)
    new_cn = _chinese_count(text) / max(len(text), 1)
    if orig_cn - new_cn > 0.30:
        return RewriteResult(success=False, reject_reason="low_chinese")

    orig_len = len(original)
    new_len = len(text)
    if orig_len > 0:
        ratio = new_len / orig_len
        if ratio < 0.6 or ratio > 1.4:
            return RewriteResult(success=False, reject_reason="length_drift")

    if _citation_count(original) != _citation_count(text):
        return RewriteResult(success=False, reject_reason="citation_count_changed")

    if _digit_token_count(original) - _digit_token_count(text) > 2:
        return RewriteResult(success=False, reject_reason="digits_dropped")

    return RewriteResult(success=True, text=text)


def rewrite_paragraph(
    text: str,
    qwen_call: LLMCallable | None = None,
    max_retries: int = 3,
    retry_backoff: tuple[float, ...] = (1.0, 3.0, 9.0),
) -> RewriteResult:
    """Rewrite one paragraph.

    `qwen_call` keyword is kept for backward compatibility with existing
    tests and callers; semantically it is any (system, user) -> str
    function. Defaults to the OpenAI-compatible adapter.
    """
    if qwen_call is None:
        qwen_call = _default_llm_call

    user = USER_PROMPT_TEMPLATE.format(paragraph=text)

    last_error = None
    for attempt in range(max_retries):
        try:
            response = qwen_call(SYSTEM_PROMPT, user)
            result = _validate(text, response)
            if not result.success:
                logger.info(
                    "rewrite rejected: reason=%s original_preview=%r",
                    result.reject_reason, text[:40],
                )
            return result
        except Exception as exc:
            last_error = str(exc)
            if attempt < max_retries - 1:
                logger.warning(
                    "LLM call failed (attempt %d/%d): %s — retrying in %.1fs",
                    attempt + 1, max_retries, last_error, retry_backoff[attempt],
                )
                time.sleep(retry_backoff[attempt])

    logger.error("LLM call failed after %d attempts: %s", max_retries, last_error)
    return RewriteResult(success=False, reject_reason="api_error", error_message=last_error)


def _default_llm_call(system: str, user: str) -> str:
    """Call an OpenAI-compatible chat-completions endpoint.

    Reads LLM_BASE_URL, LLM_API_KEY, LLM_MODEL from environment.
    Compatible with Qwen (dashscope compat mode), DeepSeek, OpenAI,
    GLM, Moonshot, Ollama, etc.
    """
    from openai import OpenAI

    base_url = os.environ.get("LLM_BASE_URL")
    api_key = os.environ.get("LLM_API_KEY")
    model = os.environ.get("LLM_MODEL")

    if not base_url or not api_key or not model:
        raise RuntimeError(
            "LLM_BASE_URL / LLM_API_KEY / LLM_MODEL environment variables required"
        )

    client = OpenAI(base_url=base_url, api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.9,
        top_p=0.95,
    )
    return response.choices[0].message.content or ""
