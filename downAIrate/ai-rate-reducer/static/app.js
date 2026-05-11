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
