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

import logging
from rewriter.logging_setup import setup_logging

setup_logging(log_dir=Path(__file__).parent.resolve() / "tmp")
logger = logging.getLogger(__name__)

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

    missing = [
        var for var in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL")
        if not os.environ.get(var)
    ]
    if missing:
        return jsonify({
            "error": f"服务器未配置环境变量：{', '.join(missing)}（请检查 .env）"
        }), 500

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

    logger.info(
        "upload: task_id=%s file=%r size=%d bytes", task_id, safe_name, input_path.stat().st_size
    )
    return jsonify({"task_id": task_id})


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
        logger.info("process start: task_id=%s input=%s", task_id, task["input_path"])
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
            logger.info(
                "process done: task_id=%s rewritten=%d skipped=%d failed=%d",
                task_id,
                report.rewritten,
                sum(report.skipped_by_reason.values()),
                len(report.api_failures),
            )
        except Exception as exc:
            logger.exception("process failed: task_id=%s", task_id)
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
    download_name = output.name.split("_", 1)[1]
    return send_from_directory(
        str(output.parent),
        output.name,
        as_attachment=True,
        download_name=download_name,
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
