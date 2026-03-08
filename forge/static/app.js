const messagesEl = document.getElementById("messages");
const taskInput = document.getElementById("task-input");
const submitBtn = document.getElementById("submit-btn");
const statusEl = document.getElementById("status");
const historyEl = document.getElementById("history-list");
const sandboxToggle = document.getElementById("sandbox-toggle");
const sandboxPathInput = document.getElementById("sandbox-path");
const directToggle = document.getElementById("direct-toggle");
const agentSlider = document.getElementById("agent-slider");
const agentCountEl = document.getElementById("agent-count");
const agentControl = document.getElementById("agent-control");

let isRunning = false;

// ── Sandbox State ─────────────────────────────────────────────────────────

function initSandboxControls() {
    // Restore from localStorage
    const savedMode = localStorage.getItem("forge_sandbox_mode");
    const savedPath = localStorage.getItem("forge_sandbox_path");
    if (savedMode !== null) sandboxToggle.checked = savedMode === "true";
    if (savedPath !== null) sandboxPathInput.value = savedPath;
    updateSandboxUI();

    // Listeners
    sandboxToggle.addEventListener("change", () => {
        localStorage.setItem("forge_sandbox_mode", sandboxToggle.checked);
        updateSandboxUI();
    });
    sandboxPathInput.addEventListener("input", () => {
        localStorage.setItem("forge_sandbox_path", sandboxPathInput.value);
    });
}

function updateSandboxUI() {
    if (sandboxToggle.checked) {
        sandboxPathInput.classList.remove("disabled");
    } else {
        sandboxPathInput.classList.add("disabled");
    }
}

// ── Settings State ────────────────────────────────────────────────────────

function initSettingsControls() {
    // Restore from localStorage
    const savedDirect = localStorage.getItem("forge_direct_mode");
    const savedAgents = localStorage.getItem("forge_agent_count");
    if (savedDirect !== null) directToggle.checked = savedDirect === "true";
    if (savedAgents !== null) agentSlider.value = savedAgents;
    agentCountEl.textContent = agentSlider.value;
    updateSettingsUI();

    // Listeners
    directToggle.addEventListener("change", () => {
        localStorage.setItem("forge_direct_mode", directToggle.checked);
        updateSettingsUI();
    });
    agentSlider.addEventListener("input", () => {
        agentCountEl.textContent = agentSlider.value;
        localStorage.setItem("forge_agent_count", agentSlider.value);
    });
}

function updateSettingsUI() {
    if (directToggle.checked) {
        agentControl.classList.add("disabled");
    } else {
        agentControl.classList.remove("disabled");
    }
}

// ── Submit Task ───────────────────────────────────────────────────────────

async function submitTask() {
    const task = taskInput.value.trim();
    if (!task || isRunning) return;

    setRunning(true);
    taskInput.value = "";
    addMessage("user", task);

    try {
        const res = await fetch("/api/task", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                task,
                sandbox_mode: sandboxToggle.checked,
                sandbox_path: sandboxPathInput.value.trim(),
                direct_mode: directToggle.checked,
                agent_count: parseInt(agentSlider.value, 10),
            }),
        });
        const { task_id, error } = await res.json();
        if (error) {
            addMessage("error", error);
            setRunning(false);
            return;
        }
        streamTask(task_id);
    } catch (e) {
        addMessage("error", `Connection failed: ${e.message}`);
        setRunning(false);
    }
}

// ── SSE Stream ────────────────────────────────────────────────────────────

function streamTask(taskId) {
    const source = new EventSource(`/api/stream/${taskId}`);
    let contentBuffer = "";
    let contentEl = null;

    source.onmessage = (event) => {
        const msg = JSON.parse(event.data);

        switch (msg.type) {
            case "status":
                updateStatus(msg.content);
                addMessage("status", msg.content, msg.phase || "");
                break;

            case "plan_content":
                if (!contentEl || !contentEl.classList.contains("plan")) {
                    contentBuffer = "";
                    contentEl = addMessage("plan", "");
                }
                contentBuffer += msg.content;
                contentEl.innerHTML = renderMarkdown(contentBuffer);
                scrollToBottom();
                break;

            case "step_start":
                contentEl = null;
                contentBuffer = "";
                addMessage("step-header", `Step ${msg.step}: ${msg.title}`);
                break;

            case "tool_call":
                const argsStr = JSON.stringify(msg.args, null, 2);
                addMessage("tool-call", `⚡ ${msg.name}(${argsStr})`);
                break;

            case "tool_result":
                addMessage("tool-result", msg.result);
                break;

            case "content":
                if (!contentEl || contentEl.classList.contains("plan") || contentEl.classList.contains("step-header")) {
                    contentBuffer = "";
                    contentEl = addMessage("response", "");
                }
                contentBuffer += msg.content;
                contentEl.innerHTML = renderMarkdown(contentBuffer);
                scrollToBottom();
                break;

            case "step_done":
                const icon = msg.status === "success" ? "✓" : "✗";
                addMessage("status", `${icon} Step ${msg.step} ${msg.status}`, msg.status === "success" ? "executing" : "");
                break;

            case "error":
                addMessage("error", msg.content);
                break;

            case "done":
                if (msg.summary) addMessage("done", msg.summary);
                if (msg.final) {
                    source.close();
                    setRunning(false);
                    loadHistory();
                }
                break;
        }
    };

    source.onerror = () => {
        source.close();
        setRunning(false);
        updateStatus("Disconnected");
    };
}

// ── UI Helpers ────────────────────────────────────────────────────────────

function addMessage(type, content, extra = "") {
    const div = document.createElement("div");
    div.className = `msg ${type} ${extra}`.trim();

    if (type === "plan" || type === "response") {
        div.innerHTML = renderMarkdown(content);
    } else {
        div.textContent = content;
    }

    messagesEl.appendChild(div);
    scrollToBottom();
    return div;
}

function scrollToBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
}

function setRunning(running) {
    isRunning = running;
    submitBtn.disabled = running;
    statusEl.className = "status" + (running ? " running" : "");
    statusEl.textContent = running ? "Running..." : "Ready";
}

function updateStatus(text) {
    statusEl.textContent = text;
    statusEl.className = "status running";
}

function renderMarkdown(text) {
    if (typeof marked !== "undefined") {
        return marked.parse(text);
    }
    // Fallback: basic escaping
    return text.replace(/</g, "&lt;").replace(/\n/g, "<br>");
}

// ── History ───────────────────────────────────────────────────────────────

async function loadHistory() {
    try {
        const res = await fetch("/api/history");
        const tasks = await res.json();
        historyEl.innerHTML = "";
        tasks.reverse().forEach((t) => {
            const div = document.createElement("div");
            div.className = "task-item";
            div.innerHTML = `
                <div>${truncate(t.task, 60)}</div>
                <div class="time">${t.task_id || ""} &middot; ${t.final_summary || ""}</div>
            `;
            historyEl.appendChild(div);
        });
    } catch (e) {
        // History load failed — not critical
    }
}

function truncate(str, len) {
    return str.length > len ? str.slice(0, len) + "..." : str;
}

// ── Event Listeners ───────────────────────────────────────────────────────

submitBtn.addEventListener("click", submitTask);

taskInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        submitTask();
    }
});

// ── Init ──────────────────────────────────────────────────────────────────
initSandboxControls();
initSettingsControls();
loadHistory();
