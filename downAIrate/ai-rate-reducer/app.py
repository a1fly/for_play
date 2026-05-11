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

MAX_UPLOAD_BYTES = 20 * 1024 * 1024

app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES

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
        return jsonify({"error": "服务器未配置 DASHSCOPE_API_KEY 环境变量"}), 500

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
