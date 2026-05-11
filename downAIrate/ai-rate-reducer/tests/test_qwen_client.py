from rewriter.qwen_client import rewrite_paragraph, RewriteResult


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
    result = rewrite_paragraph(
        "原文段落，长度足够触发改写规则的正文文字。",
        qwen_call=lambda s, u: "   ",
    )
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


def test_default_qwen_call_extracts_text(monkeypatch):
    from rewriter import qwen_client

    class FakeMessage:
        def __init__(self, content):
            self.content = content

    class FakeChoice:
        def __init__(self, content):
            self.message = FakeMessage(content)

    class FakeOutput:
        def __init__(self, content):
            self.choices = [FakeChoice(content)]

    class FakeResponse:
        status_code = 200

        def __init__(self, content):
            self.output = FakeOutput(content)

    captured = {}

    def fake_call(**kwargs):
        captured.update(kwargs)
        return FakeResponse("改写后的文本")

    import dashscope
    monkeypatch.setattr(dashscope.Generation, "call", fake_call)

    out = qwen_client._default_qwen_call("sys prompt", "user prompt")
    assert out == "改写后的文本"
    assert captured["model"] == "qwen-plus"
    assert captured["temperature"] == 0.9
    assert captured["top_p"] == 0.95
    msgs = captured["messages"]
    assert msgs[0]["role"] == "system"
    assert msgs[0]["content"] == "sys prompt"
    assert msgs[1]["role"] == "user"
    assert msgs[1]["content"] == "user prompt"


def test_default_qwen_call_raises_on_error(monkeypatch):
    from rewriter import qwen_client

    class FakeResponse:
        status_code = 429
        message = "rate limited"

    import dashscope
    monkeypatch.setattr(
        dashscope.Generation, "call", lambda **kw: FakeResponse()
    )

    import pytest
    with pytest.raises(RuntimeError, match="429"):
        qwen_client._default_qwen_call("s", "u")


def test_retry_succeeds_after_transient_failures(monkeypatch):
    from rewriter import qwen_client

    # Avoid real sleeps in tests
    monkeypatch.setattr(qwen_client.time, "sleep", lambda s: None)

    calls = {"n": 0}

    def flaky(system, user):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")
        return "成功改写后的段落正文，长度合适。"

    result = qwen_client.rewrite_paragraph(
        "原文段落，长度合适用于测试。",
        qwen_call=flaky,
    )
    assert result.success is True
    assert calls["n"] == 3


def test_retry_gives_up_after_max_attempts(monkeypatch):
    from rewriter import qwen_client
    monkeypatch.setattr(qwen_client.time, "sleep", lambda s: None)

    def always_fail(system, user):
        raise RuntimeError("permanent")

    result = qwen_client.rewrite_paragraph(
        "原文段落，长度合适用于测试。",
        qwen_call=always_fail,
    )
    assert result.success is False
    assert result.reject_reason == "api_error"
    assert "permanent" in (result.error_message or "")
