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
