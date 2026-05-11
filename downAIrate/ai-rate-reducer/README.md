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

见 `../docs/superpowers/specs/2026-05-11-ai-rate-reducer-design.md`。

## 测试

```bash
pytest tests/ -v
```
