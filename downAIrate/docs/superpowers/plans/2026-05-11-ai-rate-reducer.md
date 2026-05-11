# AI Rate Reducer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local Flask web app that accepts a `.docx` upload, paragraph-by-paragraph rewrites the body text via Qwen API to reduce AI-detection scores, preserves all Word formatting by only modifying `run.text`, and returns a downloadable rewritten `.docx`.

**Architecture:** Single-process Flask backend serves a static one-page frontend. User drops a `.docx` → POST `/api/upload` returns a `task_id` → frontend opens SSE stream `/api/process/<task_id>` → backend uses `python-docx` to iterate `document.paragraphs`, runs a 9-rule classifier to decide skip/rewrite, dispatches eligible paragraphs to Qwen (`qwen-plus`) via a thread pool (max 5 concurrent), validates each rewrite, writes back to `run.text` only, streams progress events, and emits a final event with download URL + report. Files in `tmp/` are auto-cleaned after 30 minutes.

**Tech Stack:** Python 3.10+, Flask, python-docx, dashscope (Qwen SDK), python-dotenv, pytest. Frontend is vanilla HTML/CSS/JS (no build step).

**Spec:** `docs/superpowers/specs/2026-05-11-ai-rate-reducer-design.md`

---

## File Structure

```
ai-rate-reducer/
├── app.py                          # Flask routes + SSE wiring
├── rewriter/
│   ├── __init__.py
│   ├── classifier.py               # 9-rule paragraph classifier
│   ├── qwen_client.py              # Qwen API call + retry + validation
│   ├── processor.py                # Main pipeline: read → classify → rewrite → writeback
│   └── prompts.py                  # SYSTEM_PROMPT, USER_PROMPT_TEMPLATE constants
├── static/
│   ├── index.html
│   ├── style.css
│   └── app.js
├── tests/
│   ├── __init__.py
│   ├── conftest.py                 # pytest fixtures (sample.docx builder)
│   ├── test_classifier.py
│   ├── test_qwen_client.py
│   └── test_processor.py
├── tmp/                            # runtime, gitignored
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

**Responsibilities:**
- `app.py` — HTTP only. No business logic. Wires routes to `rewriter.processor`.
- `rewriter/classifier.py` — Pure functions. Takes a `Paragraph`, returns a `Classification` (skip + reason, or rewrite). Stateful only for the "we're past the references heading" flag.
- `rewriter/qwen_client.py` — Wraps dashscope SDK. Single function `rewrite_paragraph(text) -> RewriteResult`. Handles retry + validation. No file IO.
- `rewriter/processor.py` — Orchestrator. Reads docx, threads through classifier and qwen client, applies writeback, emits progress events via a callback, builds the report.
- `rewriter/prompts.py` — Just the prompt strings, no logic.
- `static/*` — Frontend only.
- `tests/conftest.py` — Builds `sample.docx` programmatically using python-docx so tests don't depend on a checked-in binary.

---

## Task 1: Project scaffolding and dependencies

**Files:**
- Create: `ai-rate-reducer/requirements.txt`
- Create: `ai-rate-reducer/.gitignore`
- Create: `ai-rate-reducer/.env.example`
- Create: `ai-rate-reducer/README.md`
- Create: `ai-rate-reducer/rewriter/__init__.py`
- Create: `ai-rate-reducer/tests/__init__.py`
- Create: `ai-rate-reducer/tmp/.gitkeep`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p ai-rate-reducer/rewriter ai-rate-reducer/static ai-rate-reducer/tests ai-rate-reducer/tmp
touch ai-rate-reducer/rewriter/__init__.py ai-rate-reducer/tests/__init__.py ai-rate-reducer/tmp/.gitkeep
```

- [ ] **Step 2: Write `requirements.txt`**

```
Flask==3.0.3
python-docx==1.1.2
dashscope==1.20.11
python-dotenv==1.0.1
pytest==8.3.3
```

- [ ] **Step 3: Write `.gitignore`**

```
__pycache__/
*.pyc
.venv/
venv/
.env
tmp/*
!tmp/.gitkeep
.pytest_cache/
*.egg-info/
```

- [ ] **Step 4: Write `.env.example`**

```
DASHSCOPE_API_KEY=your_qwen_api_key_here
```

- [ ] **Step 5: Write `README.md`**

```markdown
# 论文 AI 率降低工具

本地运行的 Web 工具：拖入 `.docx` 论文，按段落用通义千问改写，降低 AI 检测率，保留原格式。

## 使用

1. 在 Word 中把 `.doc` 文件另存为 `.docx`。
2. 安装依赖：
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. 复制 `.env.example` 为 `.env`，填入你的 `DASHSCOPE_API_KEY`（从 https://dashscope.console.aliyun.com 获取）。
4. 启动：
   ```bash
   python app.py
   ```
5. 浏览器打开 http://localhost:5000，拖入 `.docx`，点"开始改写"。

## 设计

见 `docs/superpowers/specs/2026-05-11-ai-rate-reducer-design.md`。

## 测试

```bash
pytest tests/ -v
```
```

- [ ] **Step 6: Install and verify**

```bash
cd ai-rate-reducer
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -c "import flask, docx, dashscope, dotenv; print('ok')"
```
Expected output: `ok`

- [ ] **Step 7: Commit**

```bash
git add ai-rate-reducer/
git commit -m "scaffold: project structure and dependencies"
```

---

## Task 2: Prompts module

**Files:**
- Create: `ai-rate-reducer/rewriter/prompts.py`

- [ ] **Step 1: Write `rewriter/prompts.py`**

```python
SYSTEM_PROMPT = """你是一位中文学术论文润色专家，专门帮助学生把疑似 AI 生成的段落改写得更像人类自然写作，以通过 AI 内容检测（知网 AIGC、Turnitin AI、GPTZero 等）。

【AI 检测的工作原理】
检测器主要看两个信号：困惑度（用词是否过于可预测）和突发性（句子长度是否过于均匀）。AI 文本的词选择"太标准"、句长"太平均"。你的任务是把这两个特征反过来。

【必须执行的改写操作】

1. 制造句长方差（最重要）：
   - 故意打乱句子长度。一段里要有短句（3-10 字）和长句（25 字以上）穿插。
   - 不要让相邻句子字数接近。
   - 可以把一个长句拆成"主句。一个短补充。"的结构。

2. 替换高频 AI 套话（强制）：
   下列词或句式如果出现，必须换掉：
   - "综上所述"、"由此可见"、"显而易见"、"不难发现"、"值得注意的是"（这条偶尔用一次可以）
   - "首先…其次…最后"、"一方面…另一方面"（这两个结构整段最多用一次）
   - "在…的背景下"、"随着…的发展"、"具有重要意义"、"做出了巨大贡献"
   - "本文"重复出现 → 换成"该研究"、"此处"、"以下"等变体
   - "通过…可以…"、"基于…进行…"等模板化连接

3. 用词降可预测性：
   - 把过于书面、过于"安全"的词换成同义但更具体的词。
   - 例："进行研究" → "考察"/"分析"/"梳理"；"得到结果" → "获得"/"得出"/"测出"。
   - 避免"非常"、"十分"、"较为"这种语义稀薄的程度副词，要么删，要么换成更具体的程度词。

4. 增加人类痕迹（适度）：
   - 偶尔出现轻度主观表达："笔者认为"、"在一定程度上"、"似乎"、"或可"（整段最多 1 处）。
   - 偶尔的轻度冗余或补充语气，比如句尾用"——这一点尤其关键"这类破折号补充。
   - 偶尔使用反问、设问句式（整段最多 1 处）。

5. 标点规范：
   - 英文半角标点（,.;:?!）一律改为中文全角（，。；：？！）。
   - 数字与中文之间不留空格。

【必须保持不变】
- 原意、所有专业术语、学科表述
- 所有数字、数据、人名、地名、专有名词
- 引用编号如 [1][2]、(2023)，数量和位置都不能变
- 段落整体长度浮动不超过 ±20%

【禁止】
- 不要加任何解释、前缀、后缀。
- 不要用"以下是改写后的内容："这种开场白。
- 不要使用 markdown 标记（**、#、- 等）。
- 不要使用"嗯"、"啊"、"呢"等口语助词。
- 不要新增任何事实信息。
- 输出必须是纯段落正文。

【输出格式】
直接输出改写后的段落，仅此一段，没有任何其他字符。"""

USER_PROMPT_TEMPLATE = """请按上述规则改写下面这段文字。直接输出改写结果：

{paragraph}"""
```

- [ ] **Step 2: Commit**

```bash
git add ai-rate-reducer/rewriter/prompts.py
git commit -m "feat: add Qwen system and user prompt templates"
```

---

## Task 3: Classifier — test fixtures (sample docx builder)

**Files:**
- Create: `ai-rate-reducer/tests/conftest.py`

This task builds a fixture that creates a comprehensive `sample.docx` with every paragraph type we want to test. The fixture returns the path so individual tests can open it.

- [ ] **Step 1: Write `tests/conftest.py`**

```python
import pytest
from pathlib import Path
from docx import Document
from docx.shared import Pt, RGBColor


@pytest.fixture
def sample_docx(tmp_path):
    """Build a fixture docx covering every classifier rule.

    Returns the path. Paragraph indexes are documented inline so tests
    can refer to them by index.
    """
    doc = Document()

    # 0: Title (skip — Heading 1)
    doc.add_heading("深度学习在图像识别中的应用研究", level=1)

    # 1: Heading 2 (skip)
    doc.add_heading("第一章 绪论", level=2)

    # 2: Normal body paragraph, single run, Chinese >= 20%, len >= 15 (rewrite)
    doc.add_paragraph(
        "近年来人工智能技术得到了广泛应用，本文将围绕深度学习方法在图像识别任务中的实现展开讨论。"
    )

    # 3: Short paragraph (skip — too short, < 15 chars)
    doc.add_paragraph("如下所示。")

    # 4: Pure English (skip — no Chinese)
    doc.add_paragraph("This is a pure English caption that should be skipped.")

    # 5: Mixed format paragraph (skip — bold word inside)
    p_mixed = doc.add_paragraph("研究表明")
    run_bold = p_mixed.add_run("深度学习")
    run_bold.bold = True
    p_mixed.add_run("在多个领域都有突出表现，本段是混合格式段落。")

    # 6: Figure caption (skip — starts with "图1")
    doc.add_paragraph("图1 系统总体架构示意图")

    # 7: Table caption (skip — starts with "表1")
    doc.add_paragraph("表1 实验参数设置")

    # 8: Another rewriteable body paragraph
    doc.add_paragraph(
        "卷积神经网络通过逐层提取图像特征，能够有效完成分类任务，这是当前主流方法。"
    )

    # 9: References heading (skip — heading) — triggers references-zone flag
    doc.add_heading("参考文献", level=1)

    # 10: Reference entry, starts with [1] (skip)
    doc.add_paragraph("[1] 张三. 深度学习概论[M]. 北京: 科学出版社, 2020.")

    # 11: After references, even a long Chinese paragraph should be skipped
    doc.add_paragraph(
        "这是参考文献区之后的一段长文字，按规则应被跳过即使内容像正文。"
    )

    path = tmp_path / "sample.docx"
    doc.save(str(path))
    return path


@pytest.fixture
def sample_docx_single_run_para(tmp_path):
    """A docx with one rewriteable paragraph whose run has specific formatting
    we can assert is preserved after rewrite."""
    doc = Document()
    p = doc.add_paragraph()
    run = p.add_run(
        "这是一段需要被改写的正文文字，长度足够触发改写规则。"
    )
    run.font.name = "宋体"
    run.font.size = Pt(12)
    run.font.color.rgb = RGBColor(0x00, 0x00, 0x00)

    path = tmp_path / "single_run.docx"
    doc.save(str(path))
    return path
```

- [ ] **Step 2: Verify the fixture builds**

```bash
cd ai-rate-reducer
pytest tests/conftest.py --collect-only -q
```
Expected: no errors (collect succeeds, no tests to run yet).

- [ ] **Step 3: Commit**

```bash
git add ai-rate-reducer/tests/conftest.py
git commit -m "test: add sample docx fixtures covering classifier rules"
```

---

## Task 4: Classifier — data model + first failing test

**Files:**
- Create: `ai-rate-reducer/rewriter/classifier.py`
- Create: `ai-rate-reducer/tests/test_classifier.py`

- [ ] **Step 1: Write `rewriter/classifier.py` skeleton with the data model only**

```python
from dataclasses import dataclass
from typing import Literal

SkipReason = Literal[
    "heading",
    "special_style",
    "caption_prefix",
    "reference_entry",
    "after_references",
    "math_object",
    "code_style",
    "low_chinese_ratio",
    "mixed_format",
    "too_short",
    "no_chinese",
]


@dataclass
class Classification:
    """Result of classifying a single paragraph."""
    rewrite: bool
    skip_reason: SkipReason | None = None


class Classifier:
    """Stateful paragraph classifier.

    Stateful because rule 4 (after-references) requires knowing whether
    we've passed the references heading. Caller must use one instance
    per document, in paragraph order.
    """

    def __init__(self):
        self._in_references_zone = False

    def classify(self, paragraph) -> Classification:
        """Classify a python-docx Paragraph. Returns Classification."""
        raise NotImplementedError
```

- [ ] **Step 2: Write the first failing test — heading detection**

```python
# tests/test_classifier.py
from docx import Document
from rewriter.classifier import Classifier, Classification


def test_heading_1_is_skipped(sample_docx):
    doc = Document(str(sample_docx))
    classifier = Classifier()
    # Paragraph 0 in the fixture is a Heading 1
    result = classifier.classify(doc.paragraphs[0])
    assert result == Classification(rewrite=False, skip_reason="heading")
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd ai-rate-reducer
PYTHONPATH=. pytest tests/test_classifier.py::test_heading_1_is_skipped -v
```
Expected: FAIL with `NotImplementedError`.

- [ ] **Step 4: Implement heading detection in `classify`**

Replace the `classify` method body:

```python
    def classify(self, paragraph) -> Classification:
        style_name = (paragraph.style.name or "").lower()
        heading_keywords = ["heading", "title", "toc", "标题", "目录"]
        if any(kw in style_name for kw in heading_keywords):
            return Classification(rewrite=False, skip_reason="heading")
        return Classification(rewrite=True)
```

- [ ] **Step 5: Run test again**

```bash
PYTHONPATH=. pytest tests/test_classifier.py::test_heading_1_is_skipped -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add ai-rate-reducer/rewriter/classifier.py ai-rate-reducer/tests/test_classifier.py
git commit -m "feat: classifier skeleton with heading detection"
```

---

## Task 5: Classifier — special styles + caption prefixes

**Files:**
- Modify: `ai-rate-reducer/rewriter/classifier.py`
- Modify: `ai-rate-reducer/tests/test_classifier.py`

- [ ] **Step 1: Add failing tests for figure caption and table caption**

Append to `tests/test_classifier.py`:

```python
def test_figure_caption_is_skipped(sample_docx):
    doc = Document(str(sample_docx))
    classifier = Classifier()
    # Walk paragraphs until we hit "图1..."
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
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
PYTHONPATH=. pytest tests/test_classifier.py -v
```
Expected: 2 new tests FAIL (returned `rewrite=True`).

- [ ] **Step 3: Implement special-style and caption-prefix rules**

Replace `classify` in `rewriter/classifier.py`:

```python
    def classify(self, paragraph) -> Classification:
        import re

        style_name = (paragraph.style.name or "").lower()
        text = paragraph.text.strip()

        # Rule 1: heading
        heading_keywords = ["heading", "title", "toc", "标题", "目录"]
        if any(kw in style_name for kw in heading_keywords):
            return Classification(rewrite=False, skip_reason="heading")

        # Rule 2: special styles (caption / bibliography / quote)
        special_keywords = ["caption", "题注", "bibliography", "参考文献", "quote", "引文"]
        if any(kw in style_name for kw in special_keywords):
            return Classification(rewrite=False, skip_reason="special_style")

        # Rule 3: caption prefix (check first 20 chars)
        head = text[:20]
        caption_patterns = [
            r"^图\s*\d+",
            r"^表\s*\d+",
            r"^Figure\s*\d+",
            r"^Table\s*\d+",
        ]
        for pat in caption_patterns:
            if re.match(pat, head):
                return Classification(rewrite=False, skip_reason="caption_prefix")

        return Classification(rewrite=True)
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
PYTHONPATH=. pytest tests/test_classifier.py -v
```
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add ai-rate-reducer/rewriter/classifier.py ai-rate-reducer/tests/test_classifier.py
git commit -m "feat: classifier handles special styles and caption prefixes"
```

---

## Task 6: Classifier — references zone (stateful)

**Files:**
- Modify: `ai-rate-reducer/rewriter/classifier.py`
- Modify: `ai-rate-reducer/tests/test_classifier.py`

- [ ] **Step 1: Add failing test for references-zone behavior**

Append to `tests/test_classifier.py`:

```python
def test_reference_entry_starting_with_bracket_is_skipped(sample_docx):
    doc = Document(str(sample_docx))
    classifier = Classifier()
    # Need to feed all paragraphs in order so the references flag triggers
    results = [classifier.classify(p) for p in doc.paragraphs]
    # Find the [1] paragraph
    for p, result in zip(doc.paragraphs, results):
        if p.text.startswith("[1]"):
            assert result.rewrite is False
            assert result.skip_reason in ("reference_entry", "after_references")
            return
    raise AssertionError("reference entry not found")


def test_paragraph_after_references_heading_is_skipped(sample_docx):
    doc = Document(str(sample_docx))
    classifier = Classifier()
    results = [classifier.classify(p) for p in doc.paragraphs]
    # Last paragraph in fixture is normal-looking body text AFTER references heading
    last_text_para = doc.paragraphs[-1]
    last_result = results[-1]
    assert "参考文献区之后" in last_text_para.text
    assert last_result == Classification(rewrite=False, skip_reason="after_references")
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
PYTHONPATH=. pytest tests/test_classifier.py -v
```
Expected: 2 new tests FAIL.

- [ ] **Step 3: Implement reference-zone detection**

Update `classify` in `rewriter/classifier.py` to track state. Replace the method:

```python
    def classify(self, paragraph) -> Classification:
        import re

        style_name = (paragraph.style.name or "").lower()
        text = paragraph.text.strip()

        # Detect references heading FIRST and flip state for future paragraphs
        # but still skip this paragraph by rule 1.
        heading_keywords = ["heading", "title", "toc", "标题", "目录"]
        is_heading = any(kw in style_name for kw in heading_keywords)
        if is_heading:
            if any(kw in text for kw in ["参考文献", "References", "Bibliography"]):
                self._in_references_zone = True
            return Classification(rewrite=False, skip_reason="heading")

        # If already in references zone, everything is skipped.
        if self._in_references_zone:
            # Reference-style start gets a more specific reason
            if re.match(r"^\[\d+\]", text):
                return Classification(rewrite=False, skip_reason="reference_entry")
            return Classification(rewrite=False, skip_reason="after_references")

        # Rule 2: special styles
        special_keywords = ["caption", "题注", "bibliography", "参考文献", "quote", "引文"]
        if any(kw in style_name for kw in special_keywords):
            return Classification(rewrite=False, skip_reason="special_style")

        # Rule 3: caption prefix
        head = text[:20]
        caption_patterns = [
            r"^图\s*\d+",
            r"^表\s*\d+",
            r"^Figure\s*\d+",
            r"^Table\s*\d+",
        ]
        for pat in caption_patterns:
            if re.match(pat, head):
                return Classification(rewrite=False, skip_reason="caption_prefix")

        # Standalone [N] reference (rare — usually inside references zone)
        if re.match(r"^\[\d+\]", text):
            return Classification(rewrite=False, skip_reason="reference_entry")

        return Classification(rewrite=True)
```

- [ ] **Step 4: Run tests, verify all pass**

```bash
PYTHONPATH=. pytest tests/test_classifier.py -v
```
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add ai-rate-reducer/rewriter/classifier.py ai-rate-reducer/tests/test_classifier.py
git commit -m "feat: classifier tracks references zone state"
```

---

## Task 7: Classifier — math, code, and Chinese-ratio rules

**Files:**
- Modify: `ai-rate-reducer/rewriter/classifier.py`
- Modify: `ai-rate-reducer/tests/test_classifier.py`

- [ ] **Step 1: Add failing tests for low-Chinese paragraph and pure English**

Append to `tests/test_classifier.py`:

```python
def test_pure_english_paragraph_is_skipped(sample_docx):
    doc = Document(str(sample_docx))
    classifier = Classifier()
    for p in doc.paragraphs:
        if "pure English" in p.text:
            result = classifier.classify(p)
            assert result.rewrite is False
            assert result.skip_reason in ("no_chinese", "low_chinese_ratio")
            return
    raise AssertionError("pure English paragraph not found")
```

- [ ] **Step 2: Run, verify fail**

```bash
PYTHONPATH=. pytest tests/test_classifier.py -v
```
Expected: new test FAIL.

- [ ] **Step 3: Implement math / code / Chinese-ratio rules**

In `rewriter/classifier.py`, add a helper and extend `classify`. Add at top of the file (after the dataclass):

```python
def _chinese_ratio(text: str) -> float:
    """Fraction of CJK chars in text. Returns 0.0 for empty string."""
    if not text:
        return 0.0
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
    return cjk / len(text)


def _has_math_or_object(paragraph) -> bool:
    """Detect OMML or embedded objects by scanning paragraph XML."""
    try:
        xml = paragraph._element.xml
    except AttributeError:
        return False
    return "<m:oMath" in xml or "<w:object" in xml
```

Then add to `classify` AFTER the references-zone check and BEFORE the caption-prefix check (insert between them):

```python
        # Rule 5: math / code / low Chinese ratio
        if _has_math_or_object(paragraph):
            return Classification(rewrite=False, skip_reason="math_object")
        if "code" in style_name or "代码" in style_name:
            return Classification(rewrite=False, skip_reason="code_style")
        if not text or all(not ("一" <= ch <= "鿿") for ch in text):
            return Classification(rewrite=False, skip_reason="no_chinese")
        if _chinese_ratio(text) < 0.20:
            return Classification(rewrite=False, skip_reason="low_chinese_ratio")
```

- [ ] **Step 4: Run, verify pass**

```bash
PYTHONPATH=. pytest tests/test_classifier.py -v
```
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add ai-rate-reducer/rewriter/classifier.py ai-rate-reducer/tests/test_classifier.py
git commit -m "feat: classifier handles math, code, and low-Chinese paragraphs"
```

---

## Task 8: Classifier — mixed format + too-short + happy path

**Files:**
- Modify: `ai-rate-reducer/rewriter/classifier.py`
- Modify: `ai-rate-reducer/tests/test_classifier.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_classifier.py`:

```python
def test_too_short_paragraph_is_skipped(sample_docx):
    doc = Document(str(sample_docx))
    classifier = Classifier()
    for p in doc.paragraphs:
        if p.text == "如下所示。":
            result = classifier.classify(p)
            assert result == Classification(rewrite=False, skip_reason="too_short")
            return
    raise AssertionError("short paragraph not found")


def test_mixed_format_paragraph_is_skipped(sample_docx):
    doc = Document(str(sample_docx))
    classifier = Classifier()
    for p in doc.paragraphs:
        if "混合格式段落" in p.text:
            result = classifier.classify(p)
            assert result == Classification(rewrite=False, skip_reason="mixed_format")
            return
    raise AssertionError("mixed-format paragraph not found")


def test_normal_body_paragraph_is_rewritten(sample_docx):
    doc = Document(str(sample_docx))
    classifier = Classifier()
    # First body paragraph in fixture
    for p in doc.paragraphs:
        if "近年来人工智能" in p.text:
            result = classifier.classify(p)
            assert result == Classification(rewrite=True, skip_reason=None)
            return
    raise AssertionError("normal body paragraph not found")
```

- [ ] **Step 2: Run, verify fail**

```bash
PYTHONPATH=. pytest tests/test_classifier.py -v
```
Expected: 3 new tests FAIL.

- [ ] **Step 3: Implement remaining rules**

Add a helper at the top of `rewriter/classifier.py` (after `_has_math_or_object`):

```python
def _has_mixed_format(paragraph) -> bool:
    """True if paragraph has 2+ runs whose key formatting attributes differ.

    Checked attrs: bold, italic, underline, font.name, font.size,
    font.color.rgb. Empty runs (no text) are ignored.
    """
    runs = [r for r in paragraph.runs if r.text]
    if len(runs) < 2:
        return False

    def fingerprint(run):
        font = run.font
        color = font.color.rgb if font.color and font.color.rgb else None
        return (
            run.bold,
            run.italic,
            run.underline,
            font.name,
            font.size,
            color,
        )

    first = fingerprint(runs[0])
    return any(fingerprint(r) != first for r in runs[1:])
```

Add to the very end of `classify`, right before `return Classification(rewrite=True)`:

```python
        # Rule 9: too short
        if len(text) < 15:
            return Classification(rewrite=False, skip_reason="too_short")

        # Rule 8: mixed format
        if _has_mixed_format(paragraph):
            return Classification(rewrite=False, skip_reason="mixed_format")
```

- [ ] **Step 4: Run, verify pass**

```bash
PYTHONPATH=. pytest tests/test_classifier.py -v
```
Expected: 9 PASS.

- [ ] **Step 5: Commit**

```bash
git add ai-rate-reducer/rewriter/classifier.py ai-rate-reducer/tests/test_classifier.py
git commit -m "feat: classifier handles mixed format and too-short rules"
```

---

## Task 9: Qwen client — data model + retry skeleton (no real API)

**Files:**
- Create: `ai-rate-reducer/rewriter/qwen_client.py`
- Create: `ai-rate-reducer/tests/test_qwen_client.py`

The qwen_client module is tested entirely with mocks. No real API calls in CI.

- [ ] **Step 1: Write `rewriter/qwen_client.py` skeleton**

```python
from dataclasses import dataclass
from typing import Literal, Callable
import time
import re

from .prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE

RejectReason = Literal[
    "empty",
    "length_drift",
    "low_chinese",
    "refusal_prefix",
    "citation_count_changed",
    "digits_dropped",
    "api_error",
]


@dataclass
class RewriteResult:
    """Outcome of one Qwen rewrite call.

    success=True → use `text` as the rewritten paragraph.
    success=False → keep original; `reject_reason` explains why.
    """
    success: bool
    text: str | None = None
    reject_reason: RejectReason | None = None
    error_message: str | None = None


# Type alias for the SDK call we can swap in tests.
QwenCallable = Callable[[str, str], str]
```

- [ ] **Step 2: Write a failing test — happy path with mock**

```python
# tests/test_qwen_client.py
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
```

- [ ] **Step 3: Run, verify fail**

```bash
PYTHONPATH=. pytest tests/test_qwen_client.py -v
```
Expected: FAIL — `rewrite_paragraph` not defined.

- [ ] **Step 4: Implement minimal happy path**

Append to `rewriter/qwen_client.py`:

```python
def rewrite_paragraph(
    text: str,
    qwen_call: QwenCallable | None = None,
    max_retries: int = 3,
    retry_backoff: tuple[float, ...] = (1.0, 3.0, 9.0),
) -> RewriteResult:
    """Rewrite one paragraph through Qwen.

    Args:
        text: original paragraph text.
        qwen_call: function(system_prompt, user_prompt) -> str. Defaults
            to the dashscope SDK adapter (see _default_qwen_call).
        max_retries: total attempts before giving up.
        retry_backoff: seconds to sleep between attempts.

    Returns RewriteResult.
    """
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

    return RewriteResult(
        success=False,
        reject_reason="api_error",
        error_message=last_error,
    )


def _validate(original: str, response: str) -> RewriteResult:
    """Apply 6 rejection checks. Stub — to be filled in next task."""
    return RewriteResult(success=True, text=response)


def _default_qwen_call(system: str, user: str) -> str:
    """Stub for the dashscope SDK adapter — implemented in Task 11."""
    raise NotImplementedError("dashscope adapter not wired yet")
```

- [ ] **Step 5: Run, verify pass**

```bash
PYTHONPATH=. pytest tests/test_qwen_client.py -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add ai-rate-reducer/rewriter/qwen_client.py ai-rate-reducer/tests/test_qwen_client.py
git commit -m "feat: qwen_client skeleton with mockable call and retry"
```

---

## Task 10: Qwen client — validation rules

**Files:**
- Modify: `ai-rate-reducer/rewriter/qwen_client.py`
- Modify: `ai-rate-reducer/tests/test_qwen_client.py`

- [ ] **Step 1: Add failing tests for each rejection rule**

Append to `tests/test_qwen_client.py`:

```python
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
    response = "前人研究[1]给出了结论，本文进一步分析。"  # lost [2] and [3]
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
```

- [ ] **Step 2: Run, verify all fail**

```bash
PYTHONPATH=. pytest tests/test_qwen_client.py -v
```
Expected: 7 new tests FAIL (the stub returns success).

- [ ] **Step 3: Implement `_validate`**

Replace `_validate` in `rewriter/qwen_client.py`:

```python
def _chinese_count(text: str) -> int:
    return sum(1 for ch in text if "一" <= ch <= "鿿")


def _digit_token_count(text: str) -> int:
    """Count distinct digit runs (e.g. '2024' is one token, '95.3' is one)."""
    return len(re.findall(r"\d+(?:\.\d+)?", text))


def _citation_count(text: str) -> int:
    return len(re.findall(r"\[\d+\]", text))


REFUSAL_PREFIXES = ("抱歉", "我无法", "以下是", "改写如下", "好的", "当然")


def _validate(original: str, response: str) -> RewriteResult:
    text = (response or "").strip()

    if not text:
        return RewriteResult(success=False, reject_reason="empty")

    # Refusal/explanation prefix
    if any(text.startswith(p) for p in REFUSAL_PREFIXES):
        return RewriteResult(success=False, reject_reason="refusal_prefix")

    # Length drift ±40%
    orig_len = len(original)
    new_len = len(text)
    if orig_len > 0:
        ratio = new_len / orig_len
        if ratio < 0.6 or ratio > 1.4:
            return RewriteResult(success=False, reject_reason="length_drift")

    # Chinese ratio drop > 30 percentage points
    orig_cn = _chinese_count(original) / max(len(original), 1)
    new_cn = _chinese_count(text) / max(len(text), 1)
    if orig_cn - new_cn > 0.30:
        return RewriteResult(success=False, reject_reason="low_chinese")

    # Citation count must match exactly
    if _citation_count(original) != _citation_count(text):
        return RewriteResult(
            success=False, reject_reason="citation_count_changed"
        )

    # Digit tokens must not drop by more than 2
    if _digit_token_count(original) - _digit_token_count(text) > 2:
        return RewriteResult(success=False, reject_reason="digits_dropped")

    return RewriteResult(success=True, text=text)
```

- [ ] **Step 4: Run, verify all pass**

```bash
PYTHONPATH=. pytest tests/test_qwen_client.py -v
```
Expected: 8 PASS (1 happy + 7 rejections).

- [ ] **Step 5: Commit**

```bash
git add ai-rate-reducer/rewriter/qwen_client.py ai-rate-reducer/tests/test_qwen_client.py
git commit -m "feat: qwen_client validates rewrites against 6 rejection rules"
```

---

## Task 11: Qwen client — dashscope SDK adapter

**Files:**
- Modify: `ai-rate-reducer/rewriter/qwen_client.py`
- Modify: `ai-rate-reducer/tests/test_qwen_client.py`

The adapter wraps the dashscope SDK so the rest of the code stays unaware of it. We test the adapter's response-extraction by mocking `dashscope.Generation.call`.

- [ ] **Step 1: Add failing test for the adapter**

Append to `tests/test_qwen_client.py`:

```python
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
    # Messages should contain both system and user content
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
```

- [ ] **Step 2: Run, verify fail**

```bash
PYTHONPATH=. pytest tests/test_qwen_client.py -v
```
Expected: 2 new tests FAIL.

- [ ] **Step 3: Implement `_default_qwen_call`**

Replace the stub at the bottom of `rewriter/qwen_client.py`:

```python
def _default_qwen_call(system: str, user: str) -> str:
    """Call dashscope's Qwen Generation API and return the text content."""
    import dashscope  # local import: keeps tests independent of SDK import

    response = dashscope.Generation.call(
        model="qwen-plus",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.9,
        top_p=0.95,
        result_format="message",
    )
    if response.status_code != 200:
        msg = getattr(response, "message", "unknown error")
        raise RuntimeError(f"Qwen API returned {response.status_code}: {msg}")
    return response.output.choices[0].message.content
```

- [ ] **Step 4: Run, verify pass**

```bash
PYTHONPATH=. pytest tests/test_qwen_client.py -v
```
Expected: 10 PASS.

- [ ] **Step 5: Commit**

```bash
git add ai-rate-reducer/rewriter/qwen_client.py ai-rate-reducer/tests/test_qwen_client.py
git commit -m "feat: dashscope SDK adapter for Qwen Generation API"
```

---

## Task 12: Qwen client — retry behavior test

**Files:**
- Modify: `ai-rate-reducer/tests/test_qwen_client.py`

The retry logic was added in Task 9 but never tested. Cover it now.

- [ ] **Step 1: Add failing tests**

Append to `tests/test_qwen_client.py`:

```python
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
```

- [ ] **Step 2: Run, verify pass**

```bash
PYTHONPATH=. pytest tests/test_qwen_client.py -v
```
Expected: 12 PASS (retry logic was already there from Task 9).

- [ ] **Step 3: Commit**

```bash
git add ai-rate-reducer/tests/test_qwen_client.py
git commit -m "test: cover qwen_client retry success and exhaustion"
```

---

## Task 13: Processor — happy-path single-run rewrite preserves formatting

**Files:**
- Create: `ai-rate-reducer/rewriter/processor.py`
- Create: `ai-rate-reducer/tests/test_processor.py`

This is the integration point. Processor orchestrates classifier + qwen client and writes back.

- [ ] **Step 1: Write `rewriter/processor.py` skeleton**

```python
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from docx import Document

from .classifier import Classifier, Classification
from .qwen_client import rewrite_paragraph, RewriteResult, QwenCallable


@dataclass
class ProcessReport:
    total_paragraphs: int = 0
    rewritten: int = 0
    skipped_by_reason: dict[str, int] = field(default_factory=dict)
    api_failures: list[dict] = field(default_factory=list)


ProgressCallback = Callable[[int, int], None]
# (current_paragraph_index, total_paragraphs)


def process_document(
    input_path: Path,
    output_path: Path,
    qwen_call: QwenCallable | None = None,
    max_workers: int = 5,
    progress: ProgressCallback | None = None,
) -> ProcessReport:
    """Rewrite a docx end-to-end. Returns a report. Writes output to output_path."""
    doc = Document(str(input_path))
    paragraphs = doc.paragraphs

    classifier = Classifier()
    # Pass 1: classify all paragraphs (sequential — classifier is stateful).
    classifications = [classifier.classify(p) for p in paragraphs]

    report = ProcessReport(total_paragraphs=len(paragraphs))
    for c in classifications:
        if not c.rewrite:
            key = c.skip_reason or "unknown"
            report.skipped_by_reason[key] = report.skipped_by_reason.get(key, 0) + 1

    # Pass 2: rewrite eligible paragraphs concurrently.
    tasks = [
        (i, p) for i, (p, c) in enumerate(zip(paragraphs, classifications))
        if c.rewrite
    ]

    completed = 0
    total = len(paragraphs)

    def do_one(idx_and_para):
        idx, para = idx_and_para
        return idx, para, rewrite_paragraph(para.text, qwen_call=qwen_call)

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(do_one, t) for t in tasks]
        for fut in as_completed(futures):
            idx, para, result = fut.result()
            if result.success:
                _writeback(para, result.text)
                report.rewritten += 1
            else:
                report.api_failures.append({
                    "paragraph_index": idx,
                    "reason": result.reject_reason,
                    "error": result.error_message,
                })
            completed += 1
            if progress:
                progress(completed, len(tasks))

    doc.save(str(output_path))
    return report


def _writeback(paragraph, new_text: str) -> None:
    """Replace paragraph text by writing to the first run only.

    Pre-condition: paragraph has been classified as rewriteable, which
    means either 1 run or multiple runs with identical formatting.
    Empty subsequent runs are kept (their XML nodes preserved) but with
    empty text.
    """
    runs = [r for r in paragraph.runs if r.text]
    if not runs:
        return
    runs[0].text = new_text
    for r in runs[1:]:
        r.text = ""
```

- [ ] **Step 2: Write failing happy-path test**

```python
# tests/test_processor.py
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
    # Single paragraph with single run in the fixture
    para = out_doc.paragraphs[0]
    assert para.text == fake_rewrite
    run = para.runs[0]
    assert run.font.name == "宋体"
    assert run.font.size == Pt(12)
    assert run.font.color.rgb == RGBColor(0x00, 0x00, 0x00)
```

- [ ] **Step 3: Run, verify pass**

```bash
PYTHONPATH=. pytest tests/test_processor.py -v
```
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add ai-rate-reducer/rewriter/processor.py ai-rate-reducer/tests/test_processor.py
git commit -m "feat: processor rewrites eligible paragraphs and preserves run formatting"
```

---

## Task 14: Processor — skipped paragraphs are untouched

**Files:**
- Modify: `ai-rate-reducer/tests/test_processor.py`

- [ ] **Step 1: Add failing test**

Append to `tests/test_processor.py`:

```python
def test_skipped_paragraphs_keep_original_text(sample_docx, tmp_path):
    output = tmp_path / "out.docx"

    # Mock returns a sentinel string so any "rewritten" paragraph is obvious
    sentinel = "[REWRITTEN_BY_TEST]"

    in_doc_text = [p.text for p in Document(str(sample_docx)).paragraphs]

    report = process_document(
        sample_docx,
        output,
        qwen_call=lambda system, user: sentinel * 5,  # long enough to pass length check sometimes
    )

    out_doc = Document(str(output))
    out_texts = [p.text for p in out_doc.paragraphs]

    # Headings, captions, references, mixed-format, short paragraph: all unchanged
    titles_unchanged = [
        "深度学习在图像识别中的应用研究",
        "第一章 绪论",
        "图1 系统总体架构示意图",
        "表1 实验参数设置",
        "参考文献",
    ]
    for title in titles_unchanged:
        assert title in out_texts, f"{title!r} should be preserved"

    # Short paragraph must be preserved
    assert "如下所示。" in out_texts

    # Reference entry preserved
    assert any(t.startswith("[1] 张三") for t in out_texts)

    # Pure English preserved
    assert any("pure English" in t for t in out_texts)
```

- [ ] **Step 2: Run test**

```bash
PYTHONPATH=. pytest tests/test_processor.py -v
```
Expected: PASS (skipped paragraphs are not touched because they're not in the `tasks` list).

- [ ] **Step 3: Commit**

```bash
git add ai-rate-reducer/tests/test_processor.py
git commit -m "test: verify skipped paragraphs retain original text"
```

---

## Task 15: Processor — report counts are accurate

**Files:**
- Modify: `ai-rate-reducer/tests/test_processor.py`

- [ ] **Step 1: Add failing test**

Append to `tests/test_processor.py`:

```python
def test_report_records_skip_reasons_and_rewrite_count(sample_docx, tmp_path):
    output = tmp_path / "out.docx"

    # Use a rewrite that will pass validation: keep length similar, no citations
    def fake_rewrite(system, user):
        # Extract original paragraph from user prompt suffix
        original = user.split("\n\n", 1)[1]
        # Echo with a small change to keep length within ±40%
        return original.replace("。", "！", 1)

    report = process_document(
        sample_docx,
        output,
        qwen_call=fake_rewrite,
    )

    # Fixture has 12 paragraphs (indexes 0-11)
    assert report.total_paragraphs == 12
    # Two rewriteable paragraphs in the fixture: indexes 2 and 8
    assert report.rewritten == 2
    # Verify some skip reasons were recorded
    assert "heading" in report.skipped_by_reason
    assert "caption_prefix" in report.skipped_by_reason
    assert "reference_entry" in report.skipped_by_reason or "after_references" in report.skipped_by_reason
    assert "mixed_format" in report.skipped_by_reason
    assert "too_short" in report.skipped_by_reason
    assert "no_chinese" in report.skipped_by_reason
```

- [ ] **Step 2: Run test**

```bash
PYTHONPATH=. pytest tests/test_processor.py -v
```
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add ai-rate-reducer/tests/test_processor.py
git commit -m "test: verify report accurately reflects rewrite and skip counts"
```

---

## Task 16: Processor — progress callback fires per completed paragraph

**Files:**
- Modify: `ai-rate-reducer/tests/test_processor.py`

- [ ] **Step 1: Add failing test**

Append to `tests/test_processor.py`:

```python
def test_progress_callback_invoked_with_completion_counts(
    sample_docx_single_run_para, tmp_path
):
    output = tmp_path / "out.docx"
    events = []

    process_document(
        sample_docx_single_run_para,
        output,
        qwen_call=lambda s, u: "改写后的段落文字，长度适当。",
        progress=lambda done, total: events.append((done, total)),
    )

    assert events == [(1, 1)]


def test_progress_callback_handles_multiple_paragraphs(tmp_path):
    """Build a 3-paragraph rewriteable doc and verify progress sequence."""
    doc = Document()
    for i in range(3):
        doc.add_paragraph(f"这是第{i}段需要改写的正文，长度足够触发改写规则。")
    src = tmp_path / "three.docx"
    doc.save(str(src))

    output = tmp_path / "out.docx"
    events = []

    process_document(
        src,
        output,
        qwen_call=lambda s, u: "改写后段落，长度适合并不漂移。",
        max_workers=2,
        progress=lambda done, total: events.append((done, total)),
    )

    assert len(events) == 3
    # All events should have total=3 and `done` should be monotonically increasing
    assert all(total == 3 for _, total in events)
    assert [done for done, _ in events] == [1, 2, 3]
```

- [ ] **Step 2: Run test**

```bash
PYTHONPATH=. pytest tests/test_processor.py -v
```
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add ai-rate-reducer/tests/test_processor.py
git commit -m "test: progress callback fires once per completed paragraph"
```

---

## Task 17: Processor — API failures are recorded, original text kept

**Files:**
- Modify: `ai-rate-reducer/tests/test_processor.py`

- [ ] **Step 1: Add failing test**

Append to `tests/test_processor.py`:

```python
def test_api_failure_keeps_original_text_and_records_failure(
    sample_docx_single_run_para, tmp_path, monkeypatch
):
    from rewriter import qwen_client
    monkeypatch.setattr(qwen_client.time, "sleep", lambda s: None)

    output = tmp_path / "out.docx"

    def always_fail(system, user):
        raise RuntimeError("simulated API outage")

    report = process_document(
        sample_docx_single_run_para,
        output,
        qwen_call=always_fail,
    )

    assert report.rewritten == 0
    assert len(report.api_failures) == 1
    assert report.api_failures[0]["reason"] == "api_error"

    out_doc = Document(str(output))
    # Original text preserved
    assert out_doc.paragraphs[0].text.startswith("这是一段需要被改写的正文文字")
```

- [ ] **Step 2: Run test**

```bash
PYTHONPATH=. pytest tests/test_processor.py -v
```
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add ai-rate-reducer/tests/test_processor.py
git commit -m "test: API failures recorded and original text preserved"
```

---

## Task 18: Flask app — upload endpoint

**Files:**
- Create: `ai-rate-reducer/app.py`

- [ ] **Step 1: Write `app.py` with upload route only**

```python
import os
import uuid
import time
from pathlib import Path
from threading import Lock

from flask import Flask, request, jsonify, send_from_directory, abort
from dotenv import load_dotenv

load_dotenv()

APP_ROOT = Path(__file__).parent.resolve()
TMP_DIR = APP_ROOT / "tmp"
TMP_DIR.mkdir(exist_ok=True)
STATIC_DIR = APP_ROOT / "static"

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB

app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES

# task_id -> {"input_path": Path, "output_path": Path, "created": float,
#             "status": "uploaded"|"processing"|"done"|"error",
#             "report": dict|None, "error": str|None}
_TASKS: dict[str, dict] = {}
_TASKS_LOCK = Lock()


def _cleanup_old_tasks(max_age_seconds: int = 30 * 60) -> None:
    now = time.time()
    with _TASKS_LOCK:
        stale = [
            tid for tid, t in _TASKS.items()
            if now - t["created"] > max_age_seconds
        ]
        for tid in stale:
            t = _TASKS.pop(tid)
            for p in (t.get("input_path"), t.get("output_path")):
                if p and Path(p).exists():
                    try:
                        Path(p).unlink()
                    except OSError:
                        pass


@app.route("/")
def index():
    return send_from_directory(str(STATIC_DIR), "index.html")


@app.route("/api/upload", methods=["POST"])
def upload():
    _cleanup_old_tasks()
    if "file" not in request.files:
        return jsonify({"error": "no file in request"}), 400

    f = request.files["file"]
    if not f.filename or not f.filename.lower().endswith(".docx"):
        return jsonify(
            {"error": "请上传 .docx 文件（请先在 Word 中把 .doc 另存为 .docx）"}
        ), 400

    if not os.environ.get("DASHSCOPE_API_KEY"):
        return jsonify(
            {"error": "服务器未配置 DASHSCOPE_API_KEY 环境变量"}
        ), 500

    task_id = uuid.uuid4().hex
    safe_name = Path(f.filename).name
    input_path = TMP_DIR / f"{task_id}_in.docx"
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    stem = Path(safe_name).stem
    output_path = TMP_DIR / f"{task_id}_{stem}_改写版_{timestamp}.docx"

    f.save(str(input_path))

    with _TASKS_LOCK:
        _TASKS[task_id] = {
            "input_path": input_path,
            "output_path": output_path,
            "original_name": safe_name,
            "created": time.time(),
            "status": "uploaded",
            "report": None,
            "error": None,
        }

    return jsonify({"task_id": task_id})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
```

- [ ] **Step 2: Manual smoke test**

```bash
cd ai-rate-reducer
DASHSCOPE_API_KEY=dummy PYTHONPATH=. python app.py &
sleep 2
# Build a minimal docx for the test
python -c "from docx import Document; d = Document(); d.add_paragraph('test'); d.save('/tmp/smoke.docx')"
curl -s -F "file=@/tmp/smoke.docx" http://localhost:5000/api/upload
# Should print {"task_id": "..."}
kill %1
```
Expected: JSON with `task_id` field.

- [ ] **Step 3: Commit**

```bash
git add ai-rate-reducer/app.py
git commit -m "feat: Flask upload endpoint with validation and task tracking"
```

---

## Task 19: Flask app — SSE processing endpoint

**Files:**
- Modify: `ai-rate-reducer/app.py`

- [ ] **Step 1: Add SSE endpoint to `app.py`**

Append to `app.py` (above the `if __name__ == "__main__":` line):

```python
import json
import queue
import threading

from flask import Response, stream_with_context

from rewriter.processor import process_document


def _sse_format(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.route("/api/process/<task_id>", methods=["GET"])
def process(task_id):
    with _TASKS_LOCK:
        task = _TASKS.get(task_id)
    if not task:
        return jsonify({"error": "unknown task_id"}), 404
    if task["status"] not in ("uploaded", "error"):
        return jsonify({"error": "task already processing or done"}), 400

    progress_queue: queue.Queue = queue.Queue()

    def worker():
        try:
            with _TASKS_LOCK:
                task["status"] = "processing"

            def on_progress(done, total):
                progress_queue.put(("progress", {"done": done, "total": total}))

            report = process_document(
                task["input_path"],
                task["output_path"],
                progress=on_progress,
            )

            with _TASKS_LOCK:
                task["status"] = "done"
                task["report"] = {
                    "total_paragraphs": report.total_paragraphs,
                    "rewritten": report.rewritten,
                    "skipped_by_reason": report.skipped_by_reason,
                    "api_failures": report.api_failures,
                }

            progress_queue.put((
                "done",
                {
                    "download_url": f"/api/download/{task_id}",
                    "report": task["report"],
                },
            ))
        except Exception as exc:
            with _TASKS_LOCK:
                task["status"] = "error"
                task["error"] = str(exc)
            progress_queue.put(("error", {"message": str(exc)}))
        finally:
            progress_queue.put(("__END__", None))

    threading.Thread(target=worker, daemon=True).start()

    @stream_with_context
    def stream():
        while True:
            event, data = progress_queue.get()
            if event == "__END__":
                return
            yield _sse_format(event, data)

    return Response(stream(), mimetype="text/event-stream")


@app.route("/api/download/<task_id>", methods=["GET"])
def download(task_id):
    with _TASKS_LOCK:
        task = _TASKS.get(task_id)
    if not task or task["status"] != "done":
        abort(404)
    output = Path(task["output_path"])
    if not output.exists():
        abort(404)
    download_name = output.name.split("_", 1)[1]  # strip task_id prefix
    return send_from_directory(
        str(output.parent),
        output.name,
        as_attachment=True,
        download_name=download_name,
    )
```

- [ ] **Step 2: Manual smoke test (no real API needed — set a fake key but the call WILL fail; we just check the endpoint streams)**

Skip a full smoke test here; we'll verify end-to-end in Task 22.

- [ ] **Step 3: Commit**

```bash
git add ai-rate-reducer/app.py
git commit -m "feat: SSE processing endpoint and download route"
```

---

## Task 20: Frontend — HTML and CSS

**Files:**
- Create: `ai-rate-reducer/static/index.html`
- Create: `ai-rate-reducer/static/style.css`

- [ ] **Step 1: Write `static/index.html`**

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>论文 AI 率降低工具</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <main>
    <h1>论文 AI 率降低工具</h1>
    <p class="subtitle">本地运行 · 只改正文 · 保留原格式</p>

    <div id="drop-zone" class="drop-zone">
      <p>把 <code>.docx</code> 文件拖到这里</p>
      <p>或</p>
      <button type="button" id="pick-btn">选择文件</button>
      <input type="file" id="file-input" accept=".docx" hidden>
      <p id="file-name" class="file-name"></p>
    </div>

    <button type="button" id="start-btn" disabled>开始改写</button>

    <div id="progress" class="hidden">
      <p id="progress-text">准备中...</p>
      <div class="bar"><div id="bar-fill"></div></div>
    </div>

    <div id="result" class="hidden">
      <h2>✓ 完成</h2>
      <p id="download-line"></p>
      <pre id="report"></pre>
    </div>

    <div id="error" class="hidden error"></div>
  </main>
  <script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Write `static/style.css`**

```css
* { box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "PingFang SC",
               "Microsoft YaHei", sans-serif;
  margin: 0;
  background: #f7f7f9;
  color: #222;
}
main {
  max-width: 720px;
  margin: 40px auto;
  padding: 24px;
  background: white;
  border-radius: 12px;
  box-shadow: 0 2px 12px rgba(0,0,0,0.06);
}
h1 { margin-top: 0; }
.subtitle { color: #888; margin-top: -8px; }
.drop-zone {
  border: 2px dashed #ccc;
  border-radius: 8px;
  padding: 32px;
  text-align: center;
  margin: 24px 0;
  transition: border-color 0.2s, background 0.2s;
}
.drop-zone.dragging {
  border-color: #4a90e2;
  background: #eaf3fc;
}
.drop-zone code {
  background: #eee;
  padding: 2px 6px;
  border-radius: 4px;
}
.file-name {
  margin-top: 12px;
  color: #4a90e2;
  font-weight: 500;
}
button {
  background: #4a90e2;
  color: white;
  border: none;
  padding: 10px 24px;
  border-radius: 6px;
  font-size: 15px;
  cursor: pointer;
}
button:disabled {
  background: #ccc;
  cursor: not-allowed;
}
button:not(:disabled):hover { background: #357ab8; }
.hidden { display: none; }
.bar {
  background: #eee;
  border-radius: 4px;
  overflow: hidden;
  height: 12px;
  margin-top: 8px;
}
#bar-fill {
  background: #4a90e2;
  height: 100%;
  width: 0%;
  transition: width 0.3s;
}
#report {
  background: #f4f4f7;
  padding: 12px;
  border-radius: 6px;
  font-size: 13px;
  white-space: pre-wrap;
  word-break: break-all;
}
.error {
  background: #fde2e2;
  color: #a02020;
  padding: 12px;
  border-radius: 6px;
  margin-top: 16px;
}
```

- [ ] **Step 3: Commit**

```bash
git add ai-rate-reducer/static/index.html ai-rate-reducer/static/style.css
git commit -m "feat: frontend HTML and CSS"
```

---

## Task 21: Frontend — JavaScript drag/drop, upload, SSE, download

**Files:**
- Create: `ai-rate-reducer/static/app.js`

- [ ] **Step 1: Write `static/app.js`**

```javascript
(() => {
  const dropZone = document.getElementById('drop-zone');
  const pickBtn = document.getElementById('pick-btn');
  const fileInput = document.getElementById('file-input');
  const fileName = document.getElementById('file-name');
  const startBtn = document.getElementById('start-btn');
  const progress = document.getElementById('progress');
  const progressText = document.getElementById('progress-text');
  const barFill = document.getElementById('bar-fill');
  const result = document.getElementById('result');
  const downloadLine = document.getElementById('download-line');
  const reportEl = document.getElementById('report');
  const errorEl = document.getElementById('error');

  let selectedFile = null;

  function showError(msg) {
    errorEl.textContent = msg;
    errorEl.classList.remove('hidden');
  }
  function clearError() {
    errorEl.textContent = '';
    errorEl.classList.add('hidden');
  }

  function pickFile(f) {
    if (!f) return;
    if (!f.name.toLowerCase().endsWith('.docx')) {
      showError('请选择 .docx 文件。如果你的文件是 .doc，请先在 Word 里另存为 .docx。');
      return;
    }
    clearError();
    selectedFile = f;
    fileName.textContent = f.name;
    startBtn.disabled = false;
  }

  pickBtn.addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', (e) => pickFile(e.target.files[0]));

  ['dragenter', 'dragover'].forEach(evt =>
    dropZone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropZone.classList.add('dragging');
    })
  );
  ['dragleave', 'drop'].forEach(evt =>
    dropZone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropZone.classList.remove('dragging');
    })
  );
  dropZone.addEventListener('drop', (e) => {
    const f = e.dataTransfer.files[0];
    pickFile(f);
  });

  startBtn.addEventListener('click', async () => {
    if (!selectedFile) return;
    clearError();
    startBtn.disabled = true;
    progress.classList.remove('hidden');
    result.classList.add('hidden');
    progressText.textContent = '上传中...';
    barFill.style.width = '0%';

    const fd = new FormData();
    fd.append('file', selectedFile);

    let taskId;
    try {
      const res = await fetch('/api/upload', { method: 'POST', body: fd });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ error: '上传失败' }));
        throw new Error(err.error || '上传失败');
      }
      taskId = (await res.json()).task_id;
    } catch (e) {
      showError(e.message);
      startBtn.disabled = false;
      progress.classList.add('hidden');
      return;
    }

    progressText.textContent = '处理中...';

    const es = new EventSource(`/api/process/${taskId}`);
    es.addEventListener('progress', (e) => {
      const d = JSON.parse(e.data);
      const pct = d.total > 0 ? Math.round((d.done / d.total) * 100) : 0;
      progressText.textContent = `处理中 第 ${d.done}/${d.total} 段 ...`;
      barFill.style.width = pct + '%';
    });
    es.addEventListener('done', (e) => {
      const d = JSON.parse(e.data);
      es.close();
      progress.classList.add('hidden');
      result.classList.remove('hidden');

      // Trigger download
      const a = document.createElement('a');
      a.href = d.download_url;
      a.download = '';
      document.body.appendChild(a);
      a.click();
      a.remove();

      downloadLine.textContent = '已下载改写后的文件。';
      const r = d.report;
      const skips = Object.entries(r.skipped_by_reason)
        .map(([k, v]) => `${k}: ${v}`).join('  ·  ');
      reportEl.textContent =
        `总段落 ${r.total_paragraphs} 段\n` +
        `已改写 ${r.rewritten} 段\n` +
        `跳过 ${Object.values(r.skipped_by_reason).reduce((a, b) => a + b, 0)} 段（${skips}）\n` +
        `API 失败 ${r.api_failures.length} 段`;
      startBtn.disabled = false;
    });
    es.addEventListener('error', (e) => {
      es.close();
      let msg = '处理失败';
      try {
        if (e.data) {
          const d = JSON.parse(e.data);
          msg = d.message || msg;
        }
      } catch {}
      showError(msg);
      progress.classList.add('hidden');
      startBtn.disabled = false;
    });
  });
})();
```

- [ ] **Step 2: Commit**

```bash
git add ai-rate-reducer/static/app.js
git commit -m "feat: frontend drag/drop, upload, SSE progress, auto-download"
```

---

## Task 22: End-to-end manual smoke test

**Files:** none (validation only)

- [ ] **Step 1: Confirm full test suite passes**

```bash
cd ai-rate-reducer
PYTHONPATH=. pytest tests/ -v
```
Expected: all tests pass. Count should be roughly 9 classifier + 12 qwen_client + 5 processor = 26 tests.

- [ ] **Step 2: Verify app boots without a real API key**

```bash
DASHSCOPE_API_KEY=dummy PYTHONPATH=. python app.py &
sleep 2
curl -s http://localhost:5000/ | head -5
# Should return HTML
kill %1
```

- [ ] **Step 3: Manual end-to-end test (requires real Qwen API key)**

This step is for the user to do, not the agent:

> 1. Set your real `DASHSCOPE_API_KEY` in `.env`.
> 2. Run `python app.py`.
> 3. Open http://localhost:5000.
> 4. Drag a real (small, 1-2 page) `.docx` thesis section in.
> 5. Click "开始改写".
> 6. Wait for download; open the downloaded docx in Word.
> 7. Verify: title/headings unchanged, body paragraphs rewritten, formatting preserved (font, size, bold, color), no garbled characters.

Document any issues observed and iterate.

- [ ] **Step 4: Commit any iteration fixes (if needed)**

```bash
git add -A
git commit -m "fix: <whatever was found in manual smoke test>"
```

---

## Self-Review

**Spec coverage check:**

| Spec section | Covered by |
|---|---|
| 1.2 Constraints — .docx in, never overwrite, format preserve | Tasks 13, 14, 18 |
| 2.1 Tech stack | Task 1 |
| 2.3 Project directory | Task 1 |
| 3.1 Rule 1 heading | Task 4 |
| 3.1 Rule 2 special styles | Task 5 |
| 3.1 Rule 3 caption prefix | Task 5 |
| 3.1 Rule 4 references zone | Task 6 |
| 3.1 Rule 5 math/code/low-Chinese | Task 7 |
| 3.1 Rule 6 table paragraphs | Task 13 (implicit — `document.paragraphs` doesn't include them) |
| 3.1 Rule 7 footnotes/headers | Task 13 (implicit — only `document.paragraphs` iterated) |
| 3.1 Rule 8 mixed format | Task 8 |
| 3.1 Rule 9 too short / no Chinese | Tasks 7, 8 |
| 3.3 Report | Task 15 |
| 4.1 API config (model, temp, top_p) | Task 11 |
| 4.1 Concurrency (5 workers) | Task 13 (`max_workers=5` default) |
| 4.1 Retry 3x with backoff | Tasks 9, 12 |
| 4.2 Prompts | Task 2 |
| 4.3 6 validation rules | Task 10 |
| 4.4 Writeback strategy | Task 13 (`_writeback` function) |
| 5.1 Routes | Tasks 18, 19 |
| 5.2 SSE event format | Task 19 |
| 5.3 Frontend | Tasks 20, 21 |
| 5.4 File naming | Task 18 |
| 6 Error handling | Tasks 18 (upload validation), 19 (worker exception → error event), 21 (frontend error display) |
| 7.1 Unit tests | Tasks 4-17 |
| 8 Security/privacy (API key from env, tmp cleanup) | Task 18 |

**Placeholder scan:** No "TBD" / "implement later" / "similar to Task N" appear. All code blocks are complete.

**Type consistency check:**
- `Classification` dataclass: defined Task 4, used Tasks 4-8, 13.
- `RewriteResult` dataclass: defined Task 9, used Tasks 9-13, 17.
- `ProcessReport` dataclass: defined Task 13, used Tasks 13-17, 19.
- `QwenCallable` type alias: defined Task 9, used Tasks 9, 13.
- `_validate`, `_writeback`, `_default_qwen_call`: names consistent across tasks.
- `progress(done, total)` callback signature: consistent in Tasks 13, 16, 19, 21.

**One issue found and fixed inline above:** in Task 19, the download endpoint's `download_name` strips the `task_id_` prefix using `split("_", 1)[1]`, which gives e.g. `myfile_改写版_20260511-143022.docx` — correct.

Plan is internally consistent and covers the spec.

---

**Plan complete and saved to `docs/superpowers/plans/2026-05-11-ai-rate-reducer.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session, batch execution with checkpoints for review.

**Which approach?**
