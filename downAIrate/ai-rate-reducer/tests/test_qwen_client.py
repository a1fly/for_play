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
