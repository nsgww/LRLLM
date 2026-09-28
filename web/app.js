/* 私有知识库 RAG Web 端：对话（SSE 流式）/ 知识库管理 / 会话历史。
 * 作用域约定：所有请求带 X-Knowledge-Base-ID 头（05 节 3）。
 * 无任何外部依赖，可直接由内网 FastAPI 静态托管。
 */

"use strict";

const API = "/v1";

const state = {
  kbId: localStorage.getItem("rag.kbId") || null,
  conversationId: null,
  streaming: false,
};

const $ = (id) => document.getElementById(id);

// ---------- API ----------

async function api(path, { method = "GET", body, form } = {}) {
  const headers = {};
  if (state.kbId) headers["X-Knowledge-Base-ID"] = state.kbId;
  if (body) headers["Content-Type"] = "application/json";
  const resp = await fetch(`${API}${path}`, {
    method,
    headers,
    body: form ? form : body ? JSON.stringify(body) : undefined,
  });
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try {
      const data = await resp.json();
      detail = data?.error?.message || data?.detail || detail;
    } catch { /* 忽略非 JSON 错误体 */ }
    throw new Error(detail);
  }
  if (resp.status === 204) return null;
  return resp.json();
}

function items(data) {
  // 分页端点返回 {items, next_cursor}，列表端点返回数组
  return Array.isArray(data) ? data : data.items || [];
}

// ---------- 知识库 ----------

async function loadKnowledgeBases() {
  const kbs = items(await api("/knowledge-bases"));
  const select = $("kb-select");
  select.innerHTML = "";
  for (const kb of kbs) {
    const opt = document.createElement("option");
    opt.value = kb.id;
    opt.textContent = kb.name;
    select.appendChild(opt);
  }
  if (kbs.length === 0) {
    select.innerHTML = "<option value=''>（请先新建知识库）</option>";
    state.kbId = null;
    return;
  }
  if (!kbs.some((kb) => kb.id === state.kbId)) state.kbId = kbs[0].id;
  select.value = state.kbId;
  localStorage.setItem("rag.kbId", state.kbId);
}

$("kb-select").addEventListener("change", async (e) => {
  state.kbId = e.target.value;
  localStorage.setItem("rag.kbId", state.kbId);
  state.conversationId = null;
  $("messages").innerHTML = "";
  await loadConversations();
  await loadDocuments();
});

$("kb-new").addEventListener("click", async () => {
  const name = prompt("知识库名称：");
  if (!name) return;
  try {
    const kb = await api("/knowledge-bases", { method: "POST", body: { name } });
    state.kbId = kb.id;
    await loadKnowledgeBases();
    await loadConversations();
    await loadDocuments();
  } catch (err) {
    alert(`创建失败：${err.message}`);
  }
});

// ---------- 会话 ----------

async function loadConversations() {
  const list = $("conv-list");
  list.innerHTML = "";
  if (!state.kbId) return;
  const convs = items(await api("/conversations"));
  for (const conv of convs) {
    const div = document.createElement("div");
    div.className = "conv-item" + (conv.id === state.conversationId ? " active" : "");
    div.textContent = `对话 ${conv.id.slice(0, 8)}`;
    div.title = conv.created_at || conv.id;
    div.addEventListener("click", () => openConversation(conv.id));
    list.appendChild(div);
  }
}

$("conv-new").addEventListener("click", async () => {
  if (!state.kbId) return alert("请先选择知识库");
  try {
    const conv = await api("/conversations", { method: "POST" });
    state.conversationId = conv.id;
    $("messages").innerHTML = "";
    await loadConversations();
  } catch (err) {
    alert(`新建对话失败：${err.message}`);
  }
});

async function openConversation(id) {
  state.conversationId = id;
  const box = $("messages");
  box.innerHTML = "";
  const page = await api(`/conversations/${id}/messages?limit=100`);
  const msgs = items(page).reverse(); // 接口最新在前，展示按时间正序
  for (const m of msgs) {
    appendMessage(m.role.toLowerCase() === "user" ? "user" : "assistant", m.content, {
      answerId: m.answer_id,
    });
  }
  box.scrollTop = box.scrollHeight;
  await loadConversations();
}

// ---------- 对话（SSE） ----------

function appendMessage(role, text, { answerId = null, evidenceStatus = null } = {}) {
  const box = $("messages");
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  const body = document.createElement("span");
  body.className = "body";
  body.textContent = text;
  div.appendChild(body);
  if (role === "assistant") {
    const meta = document.createElement("div");
    meta.className = "meta";
    div.appendChild(meta);
    if (evidenceStatus) {
      const badge = document.createElement("span");
      badge.className = `badge ${evidenceStatus}`;
      badge.textContent = evidenceStatus;
      meta.appendChild(badge);
    }
    if (answerId) {
      const toggle = document.createElement("button");
      toggle.className = "evidence-toggle";
      toggle.textContent = "查看证据";
      toggle.addEventListener("click", () => toggleEvidence(div, answerId, toggle));
      meta.appendChild(toggle);
    }
  }
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
  return div;
}

async function toggleEvidence(msgDiv, answerId, toggle) {
  let panel = msgDiv.querySelector(".evidence-panel");
  if (panel) {
    panel.remove();
    toggle.textContent = "查看证据";
    return;
  }
  toggle.textContent = "收起证据";
  panel = document.createElement("div");
  panel.className = "evidence-panel";
  panel.textContent = "加载中…";
  msgDiv.appendChild(panel);
  try {
    const data = await api(`/answers/${answerId}/evidence`);
    panel.innerHTML = "";
    for (const ev of data.evidence) {
      const item = document.createElement("div");
      item.className = "ev-item";
      const label = [ev.document_title, ev.product, ev.version].filter(Boolean).join(" / ");
      item.textContent = `${label} · ${ev.heading_path || ""} (行 ${ev.line_start}-${ev.line_end})`;
      if (ev.excerpt) item.title = ev.excerpt;
      panel.appendChild(item);
    }
    if (!data.evidence.length) panel.textContent = "该回答没有引用证据。";
  } catch (err) {
    panel.textContent = `证据加载失败：${err.message}`;
  }
}

$("composer").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("input");
  const query = input.value.trim();
  if (!query || state.streaming) return;
  if (!state.kbId) return alert("请先选择知识库");

  input.value = "";
  appendMessage("user", query);
  const answerDiv = appendMessage("assistant", "");
  const bodyEl = answerDiv.querySelector(".body");
  bodyEl.classList.add("typing");
  $("send").disabled = true;
  state.streaming = true;

  let answerId = null;
  let evidenceStatus = null;

  try {
    const resp = await fetch(`${API}/query`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Knowledge-Base-ID": state.kbId,
      },
      body: JSON.stringify({ query, conversation_id: state.conversationId }),
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

    // 手动解析 SSE 流（event: xxx / data: {...}）
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let currentEvent = "message";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, idx).trimEnd();
        buffer = buffer.slice(idx + 1);
        if (line.startsWith("event:")) {
          currentEvent = line.slice(6).trim();
        } else if (line.startsWith("data:")) {
          const data = JSON.parse(line.slice(5));
          if (currentEvent === "meta") {
            if (!state.conversationId) state.conversationId = data.conversation_id;
            answerId = data.answer_id;
          } else if (currentEvent === "delta") {
            bodyEl.textContent += data.text;
            $("messages").scrollTop = $("messages").scrollHeight;
          } else if (currentEvent === "evidence_status") {
            evidenceStatus = data.status;
          } else if (currentEvent === "error") {
            bodyEl.textContent += `\n[错误] ${data.error.message}`;
          } else if (currentEvent === "done") {
            answerId = data.answer_id || answerId;
          }
        } else if (line === "") {
          currentEvent = "message";
        }
      }
    }
  } catch (err) {
    bodyEl.textContent += `\n[请求失败] ${err.message}`;
  } finally {
    bodyEl.classList.remove("typing");
    $("send").disabled = false;
    state.streaming = false;
    // 补上证据徽标与证据入口
    const meta = answerDiv.querySelector(".meta");
    if (evidenceStatus) {
      const badge = document.createElement("span");
      badge.className = `badge ${evidenceStatus}`;
      badge.textContent = evidenceStatus;
      meta.appendChild(badge);
    }
    if (answerId) {
      const toggle = document.createElement("button");
      toggle.className = "evidence-toggle";
      toggle.textContent = "查看证据";
      toggle.addEventListener("click", () => toggleEvidence(answerDiv, answerId, toggle));
      meta.appendChild(toggle);
    }
    await loadConversations(); // 新会话出现在列表中
  }
});

$("input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    $("composer").requestSubmit();
  }
});

// ---------- 知识库管理 ----------

$("upload-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!state.kbId) return alert("请先选择知识库");
  const file = $("upload-file").files[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  const fields = { title: "upload-title", product: "upload-product", version: "upload-version", doc_class: "upload-doc-class" };
  for (const [key, id] of Object.entries(fields)) {
    const value = $(id).value.trim();
    if (value) form.append(key, value);
  }
  const result = $("upload-result");
  result.className = "upload-result";
  result.textContent = "上传中…";
  try {
    const data = await api("/documents", { method: "POST", form });
    result.textContent = `已受理，入库任务 ${data.ingestion_job_id.slice(0, 8)}… 处理中（Worker 轮询执行）`;
    $("upload-form").reset();
    setTimeout(loadDocuments, 2500);
    setTimeout(loadDocuments, 8000);
  } catch (err) {
    result.className = "upload-result error";
    result.textContent = `上传失败：${err.message}`;
  }
});

async function loadDocuments() {
  const tbody = $("doc-list");
  tbody.innerHTML = "";
  if (!state.kbId) return;
  try {
    const docs = items(await api("/documents"));
    for (const doc of docs) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${doc.title}</td>
        <td>${doc.product || "-"}</td>
        <td>${doc.version || "-"}</td>
        <td><span class="doc-status ${doc.status}">${doc.status}</span></td>
        <td></td>
      `;
      const ops = tr.lastElementChild;
      const reindex = document.createElement("button");
      reindex.className = "row-btn";
      reindex.textContent = "重建";
      reindex.addEventListener("click", async () => {
        await api(`/documents/${doc.id}/reindex`, { method: "POST" });
        setTimeout(loadDocuments, 2500);
      });
      const del = document.createElement("button");
      del.className = "row-btn danger";
      del.textContent = "删除";
      del.addEventListener("click", async () => {
        if (!confirm(`删除文档「${doc.title}」？`)) return;
        await api(`/documents/${doc.id}`, { method: "DELETE" });
        await loadDocuments();
      });
      ops.append(reindex, del);
      tbody.appendChild(tr);
    }
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="5">加载失败：${err.message}</td></tr>`;
  }
}

// ---------- 视图切换 ----------

function switchTab(tab) {
  $("tab-chat").classList.toggle("active", tab === "chat");
  $("tab-kb").classList.toggle("active", tab === "kb");
  $("view-chat").classList.toggle("hidden", tab !== "chat");
  $("view-kb").classList.toggle("hidden", tab !== "kb");
  if (tab === "kb") loadDocuments();
}

$("tab-chat").addEventListener("click", () => switchTab("chat"));
$("tab-kb").addEventListener("click", () => switchTab("kb"));

// ---------- 启动 ----------

(async function init() {
  try {
    await loadKnowledgeBases();
    await loadConversations();
    await loadDocuments();
  } catch (err) {
    $("messages").innerHTML = `<div class="msg assistant">初始化失败：${err.message}。请确认后端已启动（uvicorn app.main:app）。</div>`;
  }
})();
