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
3. 复制 `.env.example` 为 `.env`，填入你的 LLM 配置。本工具采用 **OpenAI 兼容协议**，可对接任何提供该协议的厂商。常见配置：

   | 厂商 | LLM_BASE_URL | LLM_MODEL |
   |---|---|---|
   | 通义千问 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` / `qwen-turbo` / `qwen-max` |
   | DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` / `deepseek-reasoner` |
   | OpenAI | `https://api.openai.com/v1` | `gpt-4o` / `gpt-4o-mini` |
   | 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-plus` / `glm-4-flash` |
   | Moonshot Kimi | `https://api.moonshot.cn/v1` | `moonshot-v1-8k` |
   | 本地 Ollama | `http://localhost:11434/v1` | 看本地拉取的模型，如 `qwen2.5:7b` |

   `LLM_API_KEY` 填对应平台的 Key（本地 Ollama 可填任意非空值）。
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
