const logsBox = document.querySelector("#logs");
const refreshButton = document.querySelector("#refresh");

function feedbackText(feedback) {
  if (feedback === "useful") return "有用";
  if (feedback === "bad") return "无用";
  return "未反馈";
}

function logCard(log) {
  const sources = log.sources
    .map((source) => `<span class="tag">${source.title} · Chunk ${source.chunk_index}</span>`)
    .join(" ");
  return `
    <article class="log-item">
      <header>
        <strong>#${log.id} · ${log.question}</strong>
        <span>${log.created_at}</span>
      </header>
      <pre>${log.answer}</pre>
      <p>${sources || '<span class="empty">暂无引用</span>'}</p>
      <p class="muted">置信度 ${log.confidence} · 反馈：${feedbackText(log.feedback)}</p>
    </article>
  `;
}

async function loadLogs() {
  logsBox.innerHTML = '<p class="empty">加载中...</p>';
  const response = await fetch("/api/logs?limit=50");
  const data = await response.json();
  logsBox.innerHTML = data.items.length
    ? data.items.map(logCard).join("")
    : '<p class="empty">暂无问答日志。</p>';
}

refreshButton.addEventListener("click", loadLogs);
loadLogs();
