from rewriter.llm_client import rewrite_paragraph, RewriteResult


def test_rewrite_success_with_mock():
    original = "近年来人工智能技术得到了广泛应用，本文将围绕深度学习方法展开讨论。"
    rewritten = "近年来，AI 技术应用广泛。本文聚焦深度学习方法，逐步展开论述。"

    def fake_call(system, user):
        return rewritten

    result = rewrite_paragraph(original, qwen_call=fake_call)
    assert result.success is True
    assert result.text == rewritten
    assert result.reject_reason is None


def test_reject_empty_response():
    result = rewrite_paragraph("原文段落，长度足够触发改写规则的正文文字。", qwen_call=lambda s, u: "   ")
    assert result.success is False
    assert result.reject_reason == "empty"


def test_reject_length_drift_too_long():
    original = "原文很短的一段。" * 3
    too_long = original * 3
    result = rewrite_paragraph(original, qwen_call=lambda s, u: too_long)
    assert result.success is False
    assert result.reject_reason == "length_drift"


def test_reject_length_drift_too_short():
    original = "这是一段比较长的正文，用来测试长度漂移检测。" * 4
    way_short = "太短了。"
    result = rewrite_paragraph(original, qwen_call=lambda s, u: way_short)
    assert result.success is False
    assert result.reject_reason == "length_drift"


def test_reject_refusal_prefix():
    original = "正文段落，长度合适，应被改写处理。"
    response = "抱歉，我无法改写涉及学术诚信的内容。"
    result = rewrite_paragraph(original, qwen_call=lambda s, u: response)
    assert result.success is False
    assert result.reject_reason == "refusal_prefix"


def test_reject_citation_count_changed():
    original = "前人研究[1][2]给出了结论，本文进一步分析[3]。"
    response = "前人研究[1]给出了结论，本文进一步分析。"
    result = rewrite_paragraph(original, qwen_call=lambda s, u: response)
    assert result.success is False
    assert result.reject_reason == "citation_count_changed"


def test_reject_digits_dropped():
    original = "实验在 2024 年完成，样本数量为 1500，准确率达到 95.3%。"
    response = "实验已完成，样本数量较多，准确率达到较高水平。"
    result = rewrite_paragraph(original, qwen_call=lambda s, u: response)
    assert result.success is False
    assert result.reject_reason == "digits_dropped"


def test_reject_low_chinese_ratio():
    original = "这段原文几乎都是中文字符没有太多英文。"
    response = "almost all english now with very few chinese 字符 here."
    result = rewrite_paragraph(original, qwen_call=lambda s, u: response)
    assert result.success is False
    assert result.reject_reason == "low_chinese"


def test_default_llm_call_uses_env_vars_and_extracts_text(monkeypatch):
    """The OpenAI-compatible adapter should read base_url/api_key/model from
    env and forward them to openai.OpenAI(...).chat.completions.create."""
    from rewriter import llm_client

    monkeypatch.setenv("LLM_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_MODEL", "test-model")

    captured = {}

    class FakeMessage:
        content = "改写后的文本"

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    class FakeCompletions:
        def create(self, **kwargs):
            captured["kwargs"] = kwargs
            return FakeResponse()

    class FakeChat:
        completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, base_url=None, api_key=None):
            captured["base_url"] = base_url
            captured["api_key"] = api_key
            self.chat = FakeChat()

    import openai
    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)

    out = llm_client._default_llm_call("sys prompt", "user prompt")
    assert out == "改写后的文本"
    assert captured["base_url"] == "https://example.com/v1"
    assert captured["api_key"] == "sk-test"
    kw = captured["kwargs"]
    assert kw["model"] == "test-model"
    assert kw["temperature"] == 0.9
    assert kw["top_p"] == 0.95
    msgs = kw["messages"]
    assert msgs[0] == {"role": "system", "content": "sys prompt"}
    assert msgs[1] == {"role": "user", "content": "user prompt"}


def test_default_llm_call_raises_when_env_missing(monkeypatch):
    from rewriter import llm_client
    import pytest

    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)

    with pytest.raises(RuntimeError, match="LLM_"):
        llm_client._default_llm_call("s", "u")


def test_retry_succeeds_after_transient_failures(monkeypatch):
    from rewriter import llm_client
    monkeypatch.setattr(llm_client.time, "sleep", lambda s: None)

    calls = {"n": 0}

    def flaky(system, user):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")
        return "成功改写后的段落正文，长度合适。"

    result = llm_client.rewrite_paragraph(
        "原文段落，长度合适用于测试。", qwen_call=flaky,
    )
    assert result.success is True
    assert calls["n"] == 3


def test_retry_gives_up_after_max_attempts(monkeypatch):
    from rewriter import llm_client
    monkeypatch.setattr(llm_client.time, "sleep", lambda s: None)

    def always_fail(system, user):
        raise RuntimeError("permanent")

    result = llm_client.rewrite_paragraph(
        "原文段落，长度合适用于测试。", qwen_call=always_fail,
    )
    assert result.success is False
    assert result.reject_reason == "api_error"
    assert "permanent" in (result.error_message or "")
