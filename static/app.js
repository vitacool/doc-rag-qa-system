const questionInput = document.querySelector("#question");
const topKInput = document.querySelector("#top-k");
const askButton = document.querySelector("#ask");
const fillDemoButton = document.querySelector("#fill-demo");
const statusText = document.querySelector("#status");
const answerBox = document.querySelector("#answer");
const confidenceBox = document.querySelector("#confidence");
const sourcesBox = document.querySelector("#sources");
const feedbackBox = document.querySelector("#feedback");
const statsBox = document.querySelector("#stats");

let currentLogId = null;

function sourceCard(source) {
  return `
    <article class="source">
      <header>
        <strong>${source.title}</strong>
        <span class="tag">Chunk ${source.chunk_index} · ${source.score}</span>
      </header>
      <p class="muted">${source.preview}</p>
    </article>
  `;
}

async function loadStats() {
  const response = await fetch("/api/stats");
  const data = await response.json();
  statsBox.innerHTML = `
    <div class="stat"><strong>${data.documents}</strong><span>文档</span></div>
    <div class="stat"><strong>${data.chunks}</strong><span>文本块</span></div>
    <div class="stat"><strong>${data.qa_logs}</strong><span>问答记录</span></div>
    <div class="stat"><strong>${data.useful_feedback}</strong><span>有用反馈</span></div>
    <div class="stat"><strong>${data.bad_feedback}</strong><span>无用反馈</span></div>
  `;
}

fillDemoButton.addEventListener("click", () => {
  questionInput.value = "这个知识库系统如何完成 RAG 检索和引用来源展示？";
});

askButton.addEventListener("click", async () => {
  const question = questionInput.value.trim();
  if (question.length < 2) {
    statusText.textContent = "请输入问题";
    return;
  }

  askButton.disabled = true;
  statusText.textContent = "检索中...";

  try {
    const response = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, top_k: Number(topKInput.value || 5) }),
    });
    if (!response.ok) throw new Error("问答失败，请先在知识库中添加文档");

    const data = await response.json();
    currentLogId = data.id;
    confidenceBox.textContent = data.confidence;
    answerBox.textContent = data.answer;
    sourcesBox.className = "source-list";
    sourcesBox.innerHTML = data.sources.length
      ? data.sources.map(sourceCard).join("")
      : '<p class="empty">暂无引用</p>';
    feedbackBox.classList.remove("hidden");
    statusText.textContent = `已记录 #${data.id}`;
    await loadStats();
  } catch (error) {
    statusText.textContent = error.message;
  } finally {
    askButton.disabled = false;
  }
});

feedbackBox.addEventListener("click", async (event) => {
  const feedback = event.target.dataset.feedback;
  if (!feedback || !currentLogId) return;
  await fetch(`/api/logs/${currentLogId}/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ feedback }),
  });
  statusText.textContent = feedback === "useful" ? "已标记为有用" : "已标记为无用";
  await loadStats();
});

loadStats();
