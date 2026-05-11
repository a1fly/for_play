from docx import Document
from docx.shared import Pt, RGBColor

from rewriter.processor import process_document


def test_rewriteable_paragraph_text_is_replaced_and_formatting_preserved(
    sample_docx_single_run_para, tmp_path
):
    output = tmp_path / "out.docx"
    fake_rewrite = "改写后的段落文字，长度适当且保留所有原始信息。"

    report = process_document(
        sample_docx_single_run_para,
        output,
        qwen_call=lambda system, user: fake_rewrite,
    )

    assert report.rewritten == 1
    assert report.api_failures == []

    out_doc = Document(str(output))
    para = out_doc.paragraphs[0]
    assert para.text == fake_rewrite
    run = para.runs[0]
    assert run.font.name == "宋体"
    assert run.font.size == Pt(12)
    assert run.font.color.rgb == RGBColor(0x00, 0x00, 0x00)


def test_skipped_paragraphs_keep_original_text(sample_docx, tmp_path):
    output = tmp_path / "out.docx"
    sentinel = "[REWRITTEN_BY_TEST]"

    process_document(
        sample_docx,
        output,
        qwen_call=lambda system, user: sentinel * 5,
    )

    out_doc = Document(str(output))
    out_texts = [p.text for p in out_doc.paragraphs]

    titles_unchanged = [
        "深度学习在图像识别中的应用研究",
        "第一章 绪论",
        "图1 系统总体架构示意图",
        "表1 实验参数设置",
        "参考文献",
    ]
    for title in titles_unchanged:
        assert title in out_texts, f"{title!r} should be preserved"

    assert "如下所示。" in out_texts
    assert any(t.startswith("[1] 张三") for t in out_texts)
    assert any("pure English" in t for t in out_texts)
