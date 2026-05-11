from docx import Document
from rewriter.classifier import Classifier, Classification


def test_heading_1_is_skipped(sample_docx):
    doc = Document(str(sample_docx))
    classifier = Classifier()
    # Paragraph 0 in the fixture is a Heading 1
    result = classifier.classify(doc.paragraphs[0])
    assert result == Classification(rewrite=False, skip_reason="heading")


def test_figure_caption_is_skipped(sample_docx):
    doc = Document(str(sample_docx))
    classifier = Classifier()
    for p in doc.paragraphs:
        if p.text.startswith("图1"):
            result = classifier.classify(p)
            assert result == Classification(rewrite=False, skip_reason="caption_prefix")
            return
    raise AssertionError("figure caption not found in fixture")


def test_table_caption_is_skipped(sample_docx):
    doc = Document(str(sample_docx))
    classifier = Classifier()
    for p in doc.paragraphs:
        if p.text.startswith("表1"):
            result = classifier.classify(p)
            assert result == Classification(rewrite=False, skip_reason="caption_prefix")
            return
    raise AssertionError("table caption not found in fixture")
