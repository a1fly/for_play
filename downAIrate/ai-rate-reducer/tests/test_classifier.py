from docx import Document
from rewriter.classifier import Classifier, Classification


def test_heading_1_is_skipped(sample_docx):
    doc = Document(str(sample_docx))
    classifier = Classifier()
    # Paragraph 0 in the fixture is a Heading 1
    result = classifier.classify(doc.paragraphs[0])
    assert result == Classification(rewrite=False, skip_reason="heading")
