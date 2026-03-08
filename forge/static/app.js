const messagesEl = document.getElementById("messages");
const taskInput = document.getElementById("task-input");
const submitBtn = document.getElementById("submit-btn");
const killBtn = document.getElementById("kill-btn");
const statusEl = document.getElementById("status");
const historyEl = document.getElementById("history-list");
const sandboxToggle = document.getElementById("sandbox-toggle");
const sandboxPathInput = document.getElementById("sandbox-path");
const directToggle = document.getElementById("direct-toggle");
const agentSlider = document.getElementById("agent-slider");
const agentCountEl = document.getElementById("agent-count");
const agentControl = document.getElementById("agent-control");
const modelSelect = document.getElementById("model-select");

let isRunning = false;
let currentTaskId = null;

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
    const savedModel = localStorage.getItem("forge_executor_model");
    if (savedDirect !== null) directToggle.checked = savedDirect === "true";
    if (savedAgents !== null) agentSlider.value = savedAgents;
    if (savedModel !== null) modelSelect.value = savedModel;
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
    modelSelect.addEventListener("change", () => {
        localStorage.setItem("forge_executor_model", modelSelect.value);
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
                executor_model: modelSelect.value,
            }),
        });
        const { task_id, error } = await res.json();
        if (error) {
            addMessage("error", error);
            setRunning(false);
            return;
        }
        currentTaskId = task_id;
        streamTask(task_id);
    } catch (e) {
        addMessage("error", `Connection failed: ${e.message}`);
        setRunning(false);
    }
}

// ── Kill Task ─────────────────────────────────────────────────────────────

async function killTask() {
    if (!currentTaskId) return;

    killBtn.disabled = true;
    killBtn.textContent = "KILLING...";

    try {
        await fetch(`/api/kill/${currentTaskId}`, { method: "POST" });
    } catch (e) {
        // Kill request failed — task may have already finished
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
                const icon = msg.status === "success" ? "✓" : (msg.status === "cancelled" ? "⊘" : "✗");
                addMessage("status", `${icon} Step ${msg.step} ${msg.status}`, msg.status === "success" ? "executing" : "");
                break;

            case "cancelled":
                addMessage("cancelled", msg.content || "Task cancelled");
                break;

            case "error":
                addMessage("error", msg.content);
                break;

            case "done":
                if (msg.summary) addMessage("done", msg.summary);
                if (msg.final) {
                    source.close();
                    setRunning(false);
                    currentTaskId = null;
                    loadHistory();
                }
                break;
        }
    };

    source.onerror = () => {
        source.close();
        setRunning(false);
        currentTaskId = null;
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

    // Toggle kill button visibility
    if (running) {
        killBtn.classList.remove("hidden");
        killBtn.disabled = false;
        killBtn.textContent = "KILL";
    } else {
        killBtn.classList.add("hidden");
    }
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
killBtn.addEventListener("click", killTask);

taskInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        submitTask();
    }
});

// ── Arena ─────────────────────────────────────────────────────────────────

const arenaBtn = document.getElementById("arena-btn");
const arenaSetup = document.getElementById("arena-setup");
const arenaGoBtn = document.getElementById("arena-go-btn");
const arenaCancelBtn = document.getElementById("arena-cancel-btn");
const arenaView = document.getElementById("arena-view");
const chatArea = document.querySelector(".chat-area");
const commentaryText = document.getElementById("commentary-text");
const roundLabel = document.getElementById("round-label");
const redLog = document.getElementById("red-log");
const blueLog = document.getElementById("blue-log");
const scoreRedNum = document.getElementById("score-red-num");
const scoreBlueNum = document.getElementById("score-blue-num");
const scoreRedFill = document.getElementById("score-red");
const scoreBlueFill = document.getElementById("score-blue");
const redModelSelect = document.getElementById("red-model");
const blueModelSelect = document.getElementById("blue-model");
const ttsToggle = document.getElementById("tts-toggle");

let isArenaMode = false;
let ttsEnabled = false;
let ttsSpeechBuffer = "";
let ttsVoice = null;

// Initialize TTS
function initTTS() {
    // Restore preference
    const saved = localStorage.getItem("forge_arena_tts");
    if (saved !== null) ttsToggle.checked = saved === "true";
    ttsEnabled = ttsToggle.checked;

    ttsToggle.addEventListener("change", () => {
        ttsEnabled = ttsToggle.checked;
        localStorage.setItem("forge_arena_tts", ttsEnabled);
        if (!ttsEnabled) speechSynthesis.cancel();
    });

    // Pick a good voice once they load
    function pickVoice() {
        const voices = speechSynthesis.getVoices();
        if (!voices.length) return;
        // Prefer a Google/Chrome English voice for quality
        ttsVoice = voices.find(v => v.lang.startsWith("en") && v.name.includes("Google")) ||
                   voices.find(v => v.lang.startsWith("en") && v.name.includes("Microsoft")) ||
                   voices.find(v => v.lang.startsWith("en")) ||
                   voices[0];
    }
    speechSynthesis.onvoiceschanged = pickVoice;
    pickVoice();
}

function speakText(text) {
    if (!ttsEnabled || !text.trim()) return;
    const utterance = new SpeechSynthesisUtterance(text);
    if (ttsVoice) utterance.voice = ttsVoice;
    utterance.rate = 1.1;  // Slightly fast for excitement
    utterance.pitch = 1.0;
    speechSynthesis.speak(utterance);
}

// Buffer commentary chunks and speak complete sentences
function bufferAndSpeak(chunk) {
    if (!ttsEnabled) return;
    ttsSpeechBuffer += chunk;

    // Speak when we hit sentence boundaries
    const sentenceEnd = /[.!?\n]{1,}/;
    const parts = ttsSpeechBuffer.split(sentenceEnd);
    if (parts.length > 1) {
        // Speak all complete sentences, keep the trailing fragment
        const toSpeak = parts.slice(0, -1).join(". ").trim();
        ttsSpeechBuffer = parts[parts.length - 1];
        if (toSpeak) speakText(toSpeak);
    }
}

function flushSpeechBuffer() {
    if (ttsSpeechBuffer.trim()) {
        speakText(ttsSpeechBuffer.trim());
    }
    ttsSpeechBuffer = "";
}

function stopTTS() {
    speechSynthesis.cancel();
    ttsSpeechBuffer = "";
}

arenaBtn.addEventListener("click", () => {
    if (isRunning) return;
    arenaSetup.classList.toggle("hidden");
});

arenaCancelBtn.addEventListener("click", () => {
    arenaSetup.classList.add("hidden");
});

arenaGoBtn.addEventListener("click", startArena);

async function startArena() {
    if (isRunning) return;
    arenaSetup.classList.add("hidden");

    // Switch to arena view
    isArenaMode = true;
    chatArea.style.display = "none";
    arenaView.classList.remove("hidden");
    resetArenaUI();
    setRunning(true);

    try {
        const res = await fetch("/api/arena", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                red_model: redModelSelect.value,
                blue_model: blueModelSelect.value,
            }),
        });
        const { task_id, error } = await res.json();
        if (error) {
            addArenaCommentary(`ERROR: ${error}`);
            setRunning(false);
            return;
        }
        currentTaskId = task_id;
        streamArena(task_id);
    } catch (e) {
        addArenaCommentary(`Connection failed: ${e.message}`);
        setRunning(false);
    }
}

function resetArenaUI() {
    commentaryText.textContent = "THE FORGE ARENA IS OPEN\n\nAwaiting Arena Master...";
    roundLabel.textContent = "READY";
    redLog.textContent = "";
    blueLog.textContent = "";
    scoreRedNum.textContent = "0";
    scoreBlueNum.textContent = "0";
    scoreRedFill.style.width = "0%";
    scoreBlueFill.style.width = "0%";
    stopTTS();
}

function streamArena(taskId) {
    const source = new EventSource(`/api/stream/${taskId}`);
    let commentaryBuffer = "";

    source.onmessage = (event) => {
        const msg = JSON.parse(event.data);

        switch (msg.type) {
            case "arena_status":
                addArenaCommentary(msg.content);
                break;

            case "arena_round_start":
                roundLabel.textContent = `ROUND ${msg.round}: ${msg.name}`;
                flushSpeechBuffer();
                commentaryBuffer = "";
                addArenaCommentary(`\n--- ROUND ${msg.round}: ${msg.name} ---\n`);
                speakText(`Round ${msg.round}. ${msg.name}`);
                break;

            case "arena_team_action": {
                const log = msg.team === "red" ? redLog : blueLog;
                const actionType = msg.action_type || "";
                const content = msg.content || "";
                if (actionType === "content" && content) {
                    log.textContent += content;
                } else if (actionType === "tool_call" || actionType === "tool_result") {
                    log.textContent += `[${actionType}] ${content}\n`;
                }
                log.scrollTop = log.scrollHeight;
                break;
            }

            case "arena_commentary":
                commentaryBuffer += msg.content;
                commentaryText.textContent = commentaryBuffer;
                commentaryText.scrollTop = commentaryText.scrollHeight;
                const commentaryDiv = document.querySelector(".arena-commentary");
                if (commentaryDiv) commentaryDiv.scrollTop = commentaryDiv.scrollHeight;
                bufferAndSpeak(msg.content);
                break;

            case "arena_scores":
                scoreRedNum.textContent = msg.red_total;
                scoreBlueNum.textContent = msg.blue_total;
                // Scale score bars: max theoretical = 40 per round * 4 rounds = 160
                const maxScore = 160;
                scoreRedFill.style.width = Math.min(100, (msg.red_total / maxScore) * 100) + "%";
                scoreBlueFill.style.width = Math.min(100, (msg.blue_total / maxScore) * 100) + "%";

                addArenaCommentary(`\nROUND ${msg.round} SCORES — Red: +${msg.red_score} (${msg.red_total}) | Blue: +${msg.blue_score} (${msg.blue_total})\n`);
                break;

            case "arena_result": {
                flushSpeechBuffer();
                const w = msg.winner === "tie" ? "IT'S A TIE!" :
                          `${msg.winner.toUpperCase()} TEAM WINS!`;
                roundLabel.textContent = w;
                addArenaCommentary(`\n${"=".repeat(40)}\nFINAL: ${w}\nRed: ${msg.red_total} | Blue: ${msg.blue_total}\n${"=".repeat(40)}`);
                break;
            }

            case "error":
                addArenaCommentary(`\nERROR: ${msg.content}`);
                stopTTS();
                break;

            case "done":
                flushSpeechBuffer();
                source.close();
                setRunning(false);
                currentTaskId = null;
                // Show return button
                setTimeout(() => {
                    addArenaCommentary("\n\n[Arena closed. Click ARENA to fight again, or close this view.]");
                }, 500);
                break;
        }
    };

    source.onerror = () => {
        source.close();
        setRunning(false);
        currentTaskId = null;
        stopTTS();
    };
}

function addArenaCommentary(text) {
    commentaryText.textContent += text + "\n";
    const commentaryDiv = document.querySelector(".arena-commentary");
    if (commentaryDiv) commentaryDiv.scrollTop = commentaryDiv.scrollHeight;
}

// Override setRunning to handle arena mode cleanup
const _origSetRunning = setRunning;
setRunning = function(running) {
    _origSetRunning(running);
    if (!running && isArenaMode) {
        // Keep arena view visible after completion so user can read results
        // They can click away or start a new arena
    }
    if (!running && !isArenaMode) {
        // Ensure chat area is visible when not in arena
        if (chatArea) chatArea.style.display = "";
        if (arenaView) arenaView.classList.add("hidden");
    }
};

// Let arena button also restore normal view if arena is done
arenaBtn.addEventListener("dblclick", () => {
    if (!isRunning) {
        isArenaMode = false;
        chatArea.style.display = "";
        arenaView.classList.add("hidden");
    }
});

// ── Init ──────────────────────────────────────────────────────────────────
initSandboxControls();
initSettingsControls();
initTTS();
loadHistory();
