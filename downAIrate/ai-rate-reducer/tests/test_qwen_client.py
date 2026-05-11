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
