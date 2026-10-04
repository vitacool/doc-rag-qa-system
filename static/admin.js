const titleInput = document.querySelector("#title");
const contentInput = document.querySelector("#content");
const saveTextButton = document.querySelector("#save-text");
const fillSampleButton = document.querySelector("#fill-sample");
const refreshButton = document.querySelector("#refresh");
const documentsBox = document.querySelector("#documents");
const fileTitleInput = document.querySelector("#file-title");
const fileInput = document.querySelector("#file");
const uploadButton = document.querySelector("#upload");

const sampleTitle = "AI 知识库文档问答系统说明";
const sampleContent = `AI 知识库文档问答系统用于企业内部制度、项目文档和校园办事流程的智能问答。
系统流程包括：上传文档、解析文本、切分 chunk、生成向量、写入 SQLite、根据用户问题进行向量检索、返回答案并展示引用来源。
后台管理页支持新增文档、上传文件、删除文档和重新构建索引。
问答日志会记录问题、答案、引用来源和用户反馈，方便后续分析哪些文档缺失、哪些回答质量较低。
如果需要升级，可以接入 OpenAI Embedding、sentence-transformers、FAISS 或 Chroma，提高语义检索效果。`;

function documentCard(doc) {
  return `
    <article class="document">
      <header>
        <strong>${doc.title}</strong>
        <span class="tag">${doc.chunk_count} chunks</span>
      </header>
      <p class="muted">${doc.filename || "manual"} · ${doc.file_type} · ${doc.updated_at}</p>
      <div class="actions">
        <button data-rebuild="${doc.id}" type="button">重建索引</button>
        <button data-delete="${doc.id}" class="danger" type="button">删除</button>
      </div>
    </article>
  `;
}

async function loadDocuments() {
  documentsBox.innerHTML = '<p class="empty">加载中...</p>';
  const response = await fetch("/api/documents");
  const data = await response.json();
  documentsBox.innerHTML = data.items.length
    ? data.items.map(documentCard).join("")
    : '<p class="empty">暂无文档，请先新增或上传。</p>';
}

fillSampleButton.addEventListener("click", () => {
  titleInput.value = sampleTitle;
  contentInput.value = sampleContent;
});

saveTextButton.addEventListener("click", async () => {
  const title = titleInput.value.trim();
  const content = contentInput.value.trim();
  if (title.length < 2 || content.length < 20) return;

  saveTextButton.disabled = true;
  await fetch("/api/documents/text", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, content }),
  });
  titleInput.value = "";
  contentInput.value = "";
  saveTextButton.disabled = false;
  await loadDocuments();
});

uploadButton.addEventListener("click", async () => {
  if (!fileInput.files.length) return;
  const file = fileInput.files[0];
  const headers = { "X-Filename": encodeURIComponent(file.name) };
  if (fileTitleInput.value.trim()) headers["X-Title"] = encodeURIComponent(fileTitleInput.value.trim());

  uploadButton.disabled = true;
  await fetch("/api/documents/upload", {
    method: "POST",
    headers,
    body: await file.arrayBuffer(),
  });
  fileInput.value = "";
  fileTitleInput.value = "";
  uploadButton.disabled = false;
  await loadDocuments();
});

documentsBox.addEventListener("click", async (event) => {
  const rebuildId = event.target.dataset.rebuild;
  const deleteId = event.target.dataset.delete;
  if (rebuildId) {
    await fetch(`/api/documents/${rebuildId}/rebuild`, { method: "POST" });
    await loadDocuments();
  }
  if (deleteId) {
    await fetch(`/api/documents/${deleteId}`, { method: "DELETE" });
    await loadDocuments();
  }
});

refreshButton.addEventListener("click", loadDocuments);
loadDocuments();
