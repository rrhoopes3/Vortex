const els = {
    messages: document.getElementById("messages"),
    taskInput: document.getElementById("task-input"),
    submitBtn: document.getElementById("submit-btn"),
    killBtn: document.getElementById("kill-btn"),
    status: document.getElementById("status"),
    sandboxToggle: document.getElementById("sandbox-toggle"),
    sandboxPath: document.getElementById("sandbox-path"),
    directToggle: document.getElementById("direct-toggle"),
    agentSlider: document.getElementById("agent-slider"),
    agentCount: document.getElementById("agent-count"),
    agentControl: document.getElementById("agent-control"),
    modelSelect: document.getElementById("model-select"),
    arenaBtn: document.getElementById("arena-btn"),
    backToForgeBtn: document.getElementById("back-to-forge-btn"),
    resetCostBtn: document.getElementById("reset-cost-btn"),
    refreshHistoryBtn: document.getElementById("refresh-history-btn"),
    refreshMemoryBtn: document.getElementById("refresh-memory-btn"),
    clearMemoryBtn: document.getElementById("clear-memory-btn"),
    featureBadges: document.getElementById("feature-badges"),
    historyList: document.getElementById("history-list"),
    historyDetail: document.getElementById("history-detail"),
    memoryList: document.getElementById("memory-list"),
    sessionCost: document.getElementById("session-cost"),
    sessionToll: document.getElementById("session-toll"),
    taskCost: document.getElementById("task-cost"),
    costLimits: document.getElementById("cost-limits"),
    plannerModel: document.getElementById("planner-model"),
    defaultModel: document.getElementById("default-model"),
    maxIterations: document.getElementById("max-iterations"),
    workingDir: document.getElementById("working-dir"),
    workspaceTitle: document.getElementById("workspace-title"),
    workspaceSubtitle: document.getElementById("workspace-subtitle"),
    chatArea: document.getElementById("chat-area"),
    arenaSetup: document.getElementById("arena-setup"),
    arenaView: document.getElementById("arena-view"),
    redModel: document.getElementById("red-model"),
    blueModel: document.getElementById("blue-model"),
    ttsToggle: document.getElementById("tts-toggle"),
    arenaGoBtn: document.getElementById("arena-go-btn"),
    arenaCancelBtn: document.getElementById("arena-cancel-btn"),
    commentaryText: document.getElementById("commentary-text"),
    roundLabel: document.getElementById("round-label"),
    redLog: document.getElementById("red-log"),
    blueLog: document.getElementById("blue-log"),
    scoreRed: document.getElementById("score-red"),
    scoreBlue: document.getElementById("score-blue"),
    scoreRedNum: document.getElementById("score-red-num"),
    scoreBlueNum: document.getElementById("score-blue-num"),
    runtimeEvents: document.getElementById("runtime-events"),
    accountabilityList: document.getElementById("accountability-list"),
    verificationList: document.getElementById("verification-list"),
    metaTaskId: document.getElementById("meta-task-id"),
    metaMode: document.getElementById("meta-mode"),
    metaStep: document.getElementById("meta-step"),
    metaDelegatee: document.getElementById("meta-delegatee"),
    metaModel: document.getElementById("meta-model"),
    metaLatency: document.getElementById("meta-latency"),
    metaTrust: document.getElementById("meta-trust"),
    metaGuardrails: document.getElementById("meta-guardrails"),
    metaFirewall: document.getElementById("meta-firewall"),
    metaTokens: document.getElementById("meta-tokens"),
    metaHops: document.getElementById("meta-hops"),
};

const state = {
    config: null,
    models: [],
    history: [],
    memories: [],
    selectedHistoryId: null,
    currentTaskId: null,
    isRunning: false,
    isArenaMode: false,
    isCollabMode: false,
    currentTaskCostUsd: 0,
    sessionCostUsd: 0,
    sessionTollUsd: 0,
    runtimeEvents: [],
    run: {},
    ttsEnabled: false,
    ttsBuffer: "",
    ttsVoice: null,
};

function defaultRunState(mode = "Planner") {
    return {
        taskId: "-",
        mode,
        step: "-",
        delegatee: "-",
        model: "-",
        latency: "-",
        trust: "-",
        guardrails: "0",
        firewall: "0",
        tokens: 0,
        hops: "-",
        verification: ["No active step."],
        accountability: null,
    };
}

function bindEvents() {
    els.sandboxToggle.addEventListener("change", () => {
        localStorage.setItem("forge_sandbox_mode", String(els.sandboxToggle.checked));
        updateControlState();
    });

    els.sandboxPath.addEventListener("input", () => {
        localStorage.setItem("forge_sandbox_path", els.sandboxPath.value);
    });

    els.directToggle.addEventListener("change", () => {
        localStorage.setItem("forge_direct_mode", String(els.directToggle.checked));
        state.run.mode = modeFromControls();
        applyRunState();
        updateControlState();
    });

    els.agentSlider.addEventListener("input", () => {
        els.agentCount.textContent = els.agentSlider.value;
        localStorage.setItem("forge_agent_count", els.agentSlider.value);
    });

    els.modelSelect.addEventListener("change", () => {
        localStorage.setItem("forge_executor_model", els.modelSelect.value);
    });

    els.submitBtn.addEventListener("click", submitTask);
    els.killBtn.addEventListener("click", killTask);

    els.taskInput.addEventListener("keydown", (event) => {
        if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
            event.preventDefault();
            submitTask();
        }
    });

    els.resetCostBtn.addEventListener("click", resetCosts);
    els.refreshHistoryBtn.addEventListener("click", () => loadHistory());
    els.refreshMemoryBtn.addEventListener("click", () => loadMemory());
    els.clearMemoryBtn.addEventListener("click", clearMemory);

    els.arenaBtn.addEventListener("click", openArenaSetup);
    els.backToForgeBtn.addEventListener("click", switchToConsole);
    els.arenaCancelBtn.addEventListener("click", () => {
        els.arenaSetup.classList.add("hidden");
    });
    els.arenaGoBtn.addEventListener("click", startArena);
    const scenarioDropdown = document.getElementById("arena-scenario");
    if (scenarioDropdown) {
        scenarioDropdown.addEventListener("change", updateArenaSetupCopy);
    }

    // Tab switching
    document.getElementById("tab-bar").addEventListener("click", (e) => {
        const btn = e.target.closest(".tab-btn");
        if (!btn) return;
        const tab = btn.dataset.tab;
        document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
        document.querySelectorAll(".tab-content").forEach(p => p.classList.remove("active"));
        btn.classList.add("active");
        const panel = document.getElementById(`tab-${tab}`);
        if (panel) panel.classList.add("active");
        // Auto-refresh data when switching to a tab
        if (tab === "history") loadHistory();
        if (tab === "memory") loadMemory();
    });
}

async function init() {
    bindEvents();
    resetRunState();
    initTTS();

    await loadConfig();
    await loadModels();
    restoreSettings();
    updateControlState();
    applyWorkspaceMode();

    await Promise.all([loadSessionCost(), loadHistory(), loadMemory()]);
}

async function fetchJson(url, options = {}) {
    const response = await fetch(url, options);
    return response.json();
}

async function loadConfig() {
    try {
        state.config = await fetchJson("/api/config");
        applyConfig();
    } catch (error) {
        addMessage("error", `Failed to load config: ${error.message}`);
    }
}

function applyConfig() {
    if (!state.config) return;

    const savedSandboxPath = localStorage.getItem("forge_sandbox_path");
    els.sandboxPath.value = savedSandboxPath || state.config.default_sandbox_path || "";

    els.plannerModel.textContent = shortModelName(state.config.defaults?.planner_model || "-");
    els.defaultModel.textContent = shortModelName(state.config.defaults?.executor_model || "-");
    els.maxIterations.textContent = String(state.config.defaults?.max_iterations || "-");
    els.workingDir.textContent = truncateMiddle(state.config.runtime?.working_dir || "-", 36);

    const taskLimit = state.config.limits?.task_cost_usd || 0;
    const sessionLimit = state.config.limits?.session_cost_usd || 0;
    els.costLimits.textContent = `${formatMoney(taskLimit)} / ${formatMoney(sessionLimit)}`;

    renderFeatureBadges();
}

function renderFeatureBadges() {
    if (!state.config) return;

    const features = state.config.features || {};
    const badges = [
        { enabled: true, label: "Planner" },
        { enabled: features.memory, label: "Memory" },
        { enabled: features.arena, label: "Arena" },
        { enabled: features.toll, label: "Toll" },
        { enabled: features.marketplace, label: "Marketplace" },
        { enabled: features.email_agent, label: "Email Agent" },
        { enabled: features.solana_watcher, label: "Solana Watcher" },
        { enabled: features.generative_ui, label: "Generative UI" },
    ].filter((item) => item.enabled);

    if (features.email_agent && state.config.runtime?.email_agent_model) {
        badges.push({
            enabled: true,
            label: `Email:${shortModelName(state.config.runtime.email_agent_model)}`,
        });
    }

    els.featureBadges.innerHTML = badges
        .map((badge) => `<span class="feature-badge">${escapeHtml(badge.label)}</span>`)
        .join("");
}

async function loadModels() {
    try {
        state.models = await fetchJson("/api/models");
        populateModelSelect(els.modelSelect, true);
        populateModelSelect(els.redModel, false);
        populateModelSelect(els.blueModel, false);
        applyConfig();
    } catch (error) {
        addMessage("error", `Failed to load models: ${error.message}`);
    }
}

function populateModelSelect(selectEl, includeAuto) {
    if (!selectEl) return;

    const grouped = {};
    for (const model of state.models) {
        if (!includeAuto && model.id === "auto") continue;
        const provider = model.provider || "Other";
        if (!grouped[provider]) grouped[provider] = [];
        grouped[provider].push(model);
    }

    selectEl.innerHTML = "";
    for (const [provider, models] of Object.entries(grouped)) {
        const optgroup = document.createElement("optgroup");
        optgroup.label = provider;
        models.forEach((model) => {
            const option = document.createElement("option");
            option.value = model.id;
            const priced = model.cost_in > 0 || model.cost_out > 0;
            option.textContent = priced
                ? `${model.label} (${formatCompactMoney(model.cost_in)}/${formatCompactMoney(model.cost_out)})`
                : model.label;
            optgroup.appendChild(option);
        });
        selectEl.appendChild(optgroup);
    }
}

function restoreSettings() {
    const defaults = state.config?.defaults || {};

    const savedSandboxMode = localStorage.getItem("forge_sandbox_mode");
    els.sandboxToggle.checked = savedSandboxMode !== null ? savedSandboxMode === "true" : true;

    const savedDirectMode = localStorage.getItem("forge_direct_mode");
    els.directToggle.checked = savedDirectMode === "true";

    const agentCount = localStorage.getItem("forge_agent_count") || String(defaults.agent_count || 16);
    els.agentSlider.value = agentCount;
    els.agentCount.textContent = agentCount;

    const savedModel = localStorage.getItem("forge_executor_model") || defaults.executor_model || "";
    if (hasOption(els.modelSelect, savedModel)) {
        els.modelSelect.value = savedModel;
    }

    if (!els.redModel.value && els.redModel.options.length > 0) {
        els.redModel.value = pickArenaDefaultModel();
    }
    if (!els.blueModel.value && els.blueModel.options.length > 0) {
        els.blueModel.value = pickArenaDefaultModel();
    }
}

function pickArenaDefaultModel() {
    const preferred = ["grok-4-1-fast-reasoning", "gpt-4o-mini", "claude-haiku-4-20250414"];
    for (const modelId of preferred) {
        if (hasOption(els.redModel, modelId)) return modelId;
    }
    return els.redModel.options[0]?.value || "";
}

function hasOption(selectEl, value) {
    return Array.from(selectEl.options).some((option) => option.value === value);
}

function updateControlState() {
    const sandboxEnabled = els.sandboxToggle.checked && !state.isRunning;
    const controlsDisabled = state.isRunning;

    els.sandboxPath.disabled = !sandboxEnabled;
    els.agentControl.classList.toggle("disabled", els.directToggle.checked || controlsDisabled);

    els.sandboxToggle.disabled = controlsDisabled;
    els.directToggle.disabled = controlsDisabled;
    els.agentSlider.disabled = controlsDisabled || els.directToggle.checked;
    els.modelSelect.disabled = controlsDisabled;
    els.arenaBtn.disabled = controlsDisabled;
    els.submitBtn.disabled = controlsDisabled;

    els.killBtn.classList.toggle("hidden", !state.isRunning);
    els.killBtn.disabled = !state.isRunning;

    updateStatus(state.isRunning ? (state.isArenaMode ? "Arena Running" : "Running") : "Ready", state.isRunning);
}

function applyWorkspaceMode() {
    const arenaVisible = state.isArenaMode;
    els.arenaView.classList.toggle("hidden", !arenaVisible);
    els.chatArea.classList.toggle("hidden", arenaVisible);
    els.backToForgeBtn.classList.toggle("hidden", !(arenaVisible && !state.isRunning));

    if (arenaVisible) {
        els.workspaceTitle.textContent = "Arena Console";
        els.workspaceSubtitle.textContent = "Live commentary, scores, and team logs stream here.";
    } else {
        els.workspaceTitle.textContent = "Forge Console";
        els.workspaceSubtitle.textContent = "Planner, executor, guardrails, and task output stream here.";
    }
}

async function loadSessionCost() {
    try {
        const cost = await fetchJson("/api/cost");
        state.sessionCostUsd = cost.session_cost || 0;
        state.sessionTollUsd = cost.session_toll || 0;
        renderCostMetrics();
    } catch (error) {
        addMessage("error", `Failed to load cost data: ${error.message}`);
    }
}

function renderCostMetrics() {
    els.sessionCost.textContent = formatMoney(state.sessionCostUsd, 6);
    els.sessionToll.textContent = formatMoney(state.sessionTollUsd, 6);
    els.taskCost.textContent = formatMoney(state.currentTaskCostUsd, 6);

    toneMoneyElement(els.sessionCost, state.sessionCostUsd, state.config?.limits?.session_cost_usd || 0);
    toneMoneyElement(els.sessionToll, state.sessionTollUsd, 0);
    toneMoneyElement(els.taskCost, state.currentTaskCostUsd, state.config?.limits?.task_cost_usd || 0);
}

function toneMoneyElement(element, value, limit) {
    element.classList.remove("metric-low", "metric-mid", "metric-high");

    if (!limit) {
        if (value >= 5) element.classList.add("metric-high");
        else if (value >= 1) element.classList.add("metric-mid");
        else element.classList.add("metric-low");
        return;
    }

    const ratio = value / limit;
    if (ratio >= 1) element.classList.add("metric-high");
    else if (ratio >= 0.5) element.classList.add("metric-mid");
    else element.classList.add("metric-low");
}

async function resetCosts() {
    if (state.isRunning) return;
    if (!confirm("Reset session cost and toll counters?")) return;

    try {
        const result = await fetchJson("/api/cost/reset", { method: "POST" });
        state.sessionCostUsd = result.session_cost || 0;
        state.sessionTollUsd = result.session_toll || 0;
        state.currentTaskCostUsd = 0;
        renderCostMetrics();
    } catch (error) {
        addMessage("error", `Failed to reset costs: ${error.message}`);
    }
}

async function loadHistory() {
    try {
        const tasks = await fetchJson("/api/history");
        state.history = Array.isArray(tasks) ? [...tasks].reverse() : [];
        renderHistory();

        if (state.selectedHistoryId) {
            renderHistoryDetail(state.history.find((task) => task.task_id === state.selectedHistoryId) || null);
        }
    } catch (error) {
        els.historyList.textContent = `Failed to load history: ${error.message}`;
    }
}

function renderHistory() {
    if (!state.history.length) {
        els.historyList.className = "stack-list empty-state";
        els.historyList.textContent = "No completed tasks yet.";
        return;
    }

    els.historyList.className = "stack-list";
    els.historyList.innerHTML = "";

    state.history.forEach((task) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "stack-item task-item";
        if (task.task_id === state.selectedHistoryId) {
            button.classList.add("selected");
        }

        const results = Array.isArray(task.results) ? task.results : [];
        const successCount = results.filter((result) => result.status === "success").length;
        const planned = isPlannedTask(task) ? "Planned" : "Direct";

        button.innerHTML = `
            <div class="stack-item-head">
                <strong>${escapeHtml(truncate(task.task || "Untitled task", 68))}</strong>
                <span class="pill">${planned}</span>
            </div>
            <div class="stack-item-sub">${escapeHtml(formatTimestamp(task.timestamp))}</div>
            <div class="stack-item-meta">${escapeHtml(task.final_summary || "No summary")} | ${successCount}/${results.length || 0} steps</div>
        `;

        button.addEventListener("click", () => {
            state.selectedHistoryId = task.task_id;
            renderHistory();
            renderHistoryDetail(task);
        });

        els.historyList.appendChild(button);
    });
}

function renderHistoryDetail(task) {
    if (!task) {
        els.historyDetail.className = "history-detail empty-state";
        els.historyDetail.textContent = "Select a past task to inspect summary, step outcomes, and delegation hops.";
        return;
    }

    const results = Array.isArray(task.results) ? task.results : [];
    const uniqueTools = Array.from(new Set(results.flatMap((result) => result.tools_used || [])));
    const stepsHtml = results.length
        ? results.map((result) => {
            const trust = result.trust_score_after != null ? ` | trust ${Number(result.trust_score_after).toFixed(2)}` : "";
            const latency = result.latency_seconds ? ` | ${result.latency_seconds}s` : "";
            const reassign = result.was_reassigned ? ` | from ${escapeHtml(result.reassigned_from || "previous")}` : "";
            return `
                <li>
                    <strong>Step ${result.step_number}</strong>
                    <span>${escapeHtml(result.status || "unknown")}</span>
                    <div>${escapeHtml(result.delegatee_model || "-")}${trust}${latency}${reassign}</div>
                </li>
            `;
        }).join("")
        : "<li>No step results stored.</li>";

    const chainHtml = task.accountability_chain?.chain?.length
        ? `
            <div class="history-block">
                <h4>Accountability</h4>
                <ul class="mini-list">
                    ${task.accountability_chain.chain.map((hop) => `
                        <li>${escapeHtml(`${hop.hop}. ${hop.delegator} -> ${hop.delegatee} [${hop.status}]`)}</li>
                    `).join("")}
                </ul>
            </div>
        `
        : "";

    els.historyDetail.className = "history-detail";
    els.historyDetail.innerHTML = `
        <div class="history-block">
            <div class="history-kicker">${escapeHtml(formatTimestamp(task.timestamp))}</div>
            <h4>${escapeHtml(task.task || "Untitled task")}</h4>
            <p>${escapeHtml(task.final_summary || "No summary stored.")}</p>
        </div>
        <div class="history-block">
            <h4>Run Shape</h4>
            <p>${isPlannedTask(task) ? "Planned task" : "Direct task"} | ${results.length} steps | ${escapeHtml(task.task_id || "-")}</p>
            <p>${uniqueTools.length ? `Tools: ${escapeHtml(uniqueTools.join(", "))}` : "No tool data recorded."}</p>
        </div>
        <div class="history-block">
            <h4>Step Results</h4>
            <ul class="mini-list">${stepsHtml}</ul>
        </div>
        ${chainHtml}
    `;
}

async function loadMemory() {
    try {
        const memories = await fetchJson("/api/memory");
        state.memories = Array.isArray(memories) ? [...memories].reverse() : [];
        renderMemory();
    } catch (error) {
        els.memoryList.className = "stack-list compact empty-state";
        els.memoryList.textContent = `Failed to load memory: ${error.message}`;
    }
}

function renderMemory() {
    if (!state.memories.length) {
        els.memoryList.className = "stack-list compact empty-state";
        els.memoryList.textContent = "No session memory stored yet.";
        return;
    }

    els.memoryList.className = "stack-list compact";
    els.memoryList.innerHTML = "";

    state.memories.forEach((memory) => {
        const item = document.createElement("div");
        item.className = "stack-item";
        item.innerHTML = `
            <div class="stack-item-head">
                <strong>${escapeHtml(truncate(memory.task || "Memory", 58))}</strong>
            </div>
            <div class="stack-item-meta">${escapeHtml((memory.tools_effective || []).join(", ") || "No tools recorded")}</div>
            <div class="stack-item-sub">${escapeHtml(truncate((memory.key_paths || []).join(" | ") || memory.outcome || "No details", 120))}</div>
        `;
        els.memoryList.appendChild(item);
    });
}

async function clearMemory() {
    if (!confirm("Clear all session memory for this server?")) return;

    try {
        await fetchJson("/api/memory/clear", { method: "POST" });
        state.memories = [];
        renderMemory();
    } catch (error) {
        addMessage("error", `Failed to clear memory: ${error.message}`);
    }
}

function resetRunState(mode = modeFromControls()) {
    state.currentTaskCostUsd = 0;
    state.runtimeEvents = [];
    state.run = defaultRunState(mode);
    renderCostMetrics();
    applyRunState();
    renderRuntimeEvents();
    renderAccountabilityChain(null);
}

function applyRunState() {
    els.metaTaskId.textContent = state.run.taskId;
    els.metaMode.textContent = state.run.mode;
    els.metaStep.textContent = state.run.step;
    els.metaDelegatee.textContent = state.run.delegatee;
    els.metaModel.textContent = state.run.model;
    els.metaLatency.textContent = state.run.latency;
    els.metaTrust.textContent = state.run.trust;
    els.metaGuardrails.textContent = String(state.run.guardrails);
    els.metaFirewall.textContent = String(state.run.firewall);
    els.metaTokens.textContent = typeof state.run.tokens === "number"
        ? state.run.tokens.toLocaleString()
        : String(state.run.tokens);
    els.metaHops.textContent = state.run.hops;

    renderVerificationList(state.run.verification || []);
}

function renderVerificationList(items) {
    els.verificationList.innerHTML = "";

    if (!items.length) {
        els.verificationList.innerHTML = "<li>No active step.</li>";
        return;
    }

    items.forEach((item) => {
        const li = document.createElement("li");
        li.textContent = item;
        els.verificationList.appendChild(li);
    });
}

function recordRuntimeEvent(kind, message, detail = "") {
    state.runtimeEvents.unshift({ kind, message, detail });
    state.runtimeEvents = state.runtimeEvents.slice(0, 8);
    renderRuntimeEvents();
}

function renderRuntimeEvents() {
    if (!state.runtimeEvents.length) {
        els.runtimeEvents.className = "event-feed empty-state";
        els.runtimeEvents.textContent = "No guardrail, firewall, or escalation events yet.";
        return;
    }

    els.runtimeEvents.className = "event-feed";
    els.runtimeEvents.innerHTML = state.runtimeEvents.map((event) => `
        <div class="event-row ${escapeHtml(event.kind)}">
            <strong>${escapeHtml(event.message)}</strong>
            ${event.detail ? `<span>${escapeHtml(event.detail)}</span>` : ""}
        </div>
    `).join("");
}

function renderAccountabilityChain(chain) {
    if (!chain || !Array.isArray(chain.chain) || !chain.chain.length) {
        els.accountabilityList.className = "stack-list compact empty-state";
        els.accountabilityList.textContent = "Waiting for a completed task.";
        return;
    }

    els.accountabilityList.className = "stack-list compact";
    els.accountabilityList.innerHTML = chain.chain.map((hop) => `
        <div class="stack-item hop-item">
            <div class="stack-item-head">
                <strong>Hop ${hop.hop}</strong>
                <span class="pill">${escapeHtml(hop.status || "unknown")}</span>
            </div>
            <div class="stack-item-meta">${escapeHtml(`${hop.delegator} -> ${hop.delegatee}`)}</div>
            <div class="stack-item-sub">${escapeHtml(hop.duration_s != null ? `${hop.duration_s}s` : "in progress")}${hop.error ? ` | ${escapeHtml(hop.error)}` : ""}</div>
        </div>
    `).join("");
}

async function submitTask() {
    const task = els.taskInput.value.trim();
    if (!task || state.isRunning) return;

    state.isArenaMode = false;
    applyWorkspaceMode();
    els.arenaSetup.classList.add("hidden");
    resetRunState(modeFromControls());
    state.run.model = shortModelName(els.modelSelect.value || state.config?.defaults?.executor_model || "-");
    applyRunState();

    setRunning(true);
    updateStatus("Submitting Task", true);
    addMessage("user", task);
    scrollToBottom(true);
    els.taskInput.value = "";

    try {
        const payload = {
            task,
            sandbox_mode: els.sandboxToggle.checked,
            sandbox_path: els.sandboxPath.value.trim(),
            direct_mode: els.directToggle.checked,
            agent_count: Number.parseInt(els.agentSlider.value, 10),
            executor_model: els.modelSelect.value,
        };

        const response = await fetchJson("/api/task", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });

        if (response.error) {
            addMessage("error", response.error);
            setRunning(false);
            return;
        }

        state.currentTaskId = response.task_id;
        state.run.taskId = response.task_id;
        applyRunState();
        streamTask(response.task_id);
    } catch (error) {
        addMessage("error", `Connection failed: ${error.message}`);
        setRunning(false);
    }
}

async function killTask() {
    if (!state.currentTaskId) return;

    els.killBtn.disabled = true;
    els.killBtn.textContent = "Killing...";

    try {
        await fetch(`/api/kill/${state.currentTaskId}`, { method: "POST" });
    } catch (error) {
        addMessage("error", `Failed to send kill signal: ${error.message}`);
    }
}

function streamTask(taskId) {
    const source = new EventSource(`/api/stream/${taskId}`);
    let activeBuffer = "";
    let activeElement = null;
    let streamFinished = false;

    source.onmessage = (event) => {
        const msg = JSON.parse(event.data);

        if (msg.final) {
            streamFinished = true;
            source.close();
            finishRun();
            return;
        }

        switch (msg.type) {
            case "status":
                updateStatus(msg.content || "Running", true);
                addMessage("status", msg.content || "Status update", { extraClass: msg.phase || "" });
                break;

            case "plan_content":
                if (!activeElement || !activeElement.classList.contains("plan")) {
                    activeBuffer = "";
                    activeElement = addMessage("plan", "", { markdown: true });
                }
                activeBuffer += msg.content || "";
                activeElement.innerHTML = renderMarkdown(activeBuffer);
                scrollToBottom();
                break;

            case "step_start":
                activeBuffer = "";
                activeElement = null;
                state.run.step = `Step ${msg.step}`;
                state.run.delegatee = msg.delegatee || "default";
                state.run.verification = Array.isArray(msg.verification_criteria) ? msg.verification_criteria : [];
                applyRunState();
                addStepStartMessage(msg);
                break;

            case "tool_call":
                addMessage("tool-call", `<div class="message-title">${escapeHtml(msg.name)}</div><pre>${escapeHtml(JSON.stringify(msg.args || {}, null, 2))}</pre>`, { html: true });
                break;

            case "tool_result":
                addMessage("tool-result", `<pre>${escapeHtml(msg.result || "")}</pre>`, { html: true });
                break;

            case "content":
                if (!activeElement || activeElement.classList.contains("plan") || activeElement.classList.contains("step-card")) {
                    activeBuffer = "";
                    activeElement = addMessage("response", "", { markdown: true });
                }
                activeBuffer += msg.content || "";
                activeElement.innerHTML = renderMarkdown(activeBuffer);
                scrollToBottom();
                break;

            case "step_done":
                handleStepDone(msg);
                break;

            case "guardrail_violation":
                state.run.guardrails = String(Number.parseInt(state.run.guardrails, 10) + 1);
                applyRunState();
                recordRuntimeEvent(`guardrail-${msg.severity || "warning"}`, `Guardrail ${msg.guardrail || "violation"}`, msg.message || "");
                addMessage("guardrail", `${msg.severity || "warning"} | ${msg.guardrail || "guardrail"} | ${msg.message || ""}`);
                break;

            case "guardrail_summary":
                state.run.guardrails = String(msg.total_violations || 0);
                applyRunState();
                addMessage("guardrail-summary", `Guardrails: ${msg.total_violations || 0} total | ${msg.blocks || 0} blocks | ${msg.warnings || 0} warnings`);
                break;

            case "firewall_block":
                state.run.firewall = incrementCompositeCount(state.run.firewall);
                applyRunState();
                recordRuntimeEvent("firewall", `Firewall blocked ${msg.tool || "tool"}`, msg.reason || "");
                addMessage("firewall", `${msg.tool || "Tool"} blocked by firewall: ${msg.reason || "unknown reason"}`);
                break;

            case "escalation":
                recordRuntimeEvent("escalation", `Escalated: ${msg.category || "general"}`, msg.reason || "");
                addMessage("escalation", `Escalated to human (${msg.category || "general"}): ${msg.reason || "no reason"}${msg.context ? `\n\n${msg.context}` : ""}`);
                break;

            case "cancelled":
                addMessage("cancelled", msg.content || "Task cancelled");
                break;

            case "error":
                addMessage("error", msg.content || "Unknown error");
                break;

            case "token_usage":
                handleTokenUsage(msg);
                break;

            case "toll_deducted":
                state.sessionTollUsd += msg.toll_usd || 0;
                renderCostMetrics();
                addMessage("toll", `[TOLL] ${formatMoney(msg.toll_usd || 0, 6)} | ${msg.sender || "-"} -> ${msg.receiver || "-"} (${msg.message_type || "message"})`);
                break;

            case "toll_summary":
                addMessage("toll-summary", `Toll summary: ${msg.total_messages || 0} messages | ${formatMoney(msg.total_tolls_usd || 0, 6)} tolls | ${formatMoney(msg.total_creator_revenue_usd || 0, 6)} creator revenue`);
                break;

            case "widget_render":
                renderWidget(msg);
                break;

            case "done":
                handleTaskDone(msg);
                break;
        }
    };

    source.onerror = () => {
        source.close();
        if (!streamFinished) {
            addMessage("error", "Stream disconnected before task completion.");
            finishRun();
        }
    };
}

function addStepStartMessage(msg) {
    const criteria = Array.isArray(msg.verification_criteria) && msg.verification_criteria.length
        ? `<ul>${msg.verification_criteria.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`
        : "<p>No verification criteria provided.</p>";

    addMessage(
        "step-card",
        `
            <div class="message-title">Step ${msg.step}: ${escapeHtml(msg.title || "Untitled step")}</div>
            <p>${escapeHtml(msg.description || "")}</p>
            <div class="message-meta">
                <span>${escapeHtml(msg.delegatee || "default")}</span>
                <span>${msg.tools_filtered || 0} tools</span>
                <span>${escapeHtml(msg.contract_id || "no contract")}</span>
            </div>
            ${criteria}
        `,
        { html: true }
    );
}

function handleStepDone(msg) {
    state.run.step = `Step ${msg.step} ${msg.status || ""}`.trim();
    state.run.delegatee = msg.delegatee || state.run.delegatee;
    state.run.latency = msg.latency_s ? `${msg.latency_s}s` : "-";
    state.run.trust = msg.trust_score != null ? Number(msg.trust_score).toFixed(2) : "-";
    applyRunState();

    if (msg.was_reassigned) {
        recordRuntimeEvent("reassigned", `Step ${msg.step} reassigned`, `Executor: ${msg.delegatee || "-"}`);
    }

    addMessage(
        "step-done",
        `Step ${msg.step} ${msg.status || "done"} | ${msg.delegatee || "-"}${msg.latency_s ? ` | ${msg.latency_s}s` : ""}${msg.trust_score != null ? ` | trust ${Number(msg.trust_score).toFixed(2)}` : ""}${msg.was_reassigned ? " | reassigned" : ""}`
    );
}

function handleTokenUsage(msg) {
    state.currentTaskCostUsd += msg.cost_usd || 0;
    state.sessionCostUsd += msg.cost_usd || 0;
    state.run.tokens += (msg.input_tokens || 0) + (msg.output_tokens || 0);
    state.run.model = shortModelName(msg.model || state.run.model);
    renderCostMetrics();
    applyRunState();
}

function handleTaskDone(msg) {
    if (msg.summary) {
        addMessage("done", `${msg.summary}${state.currentTaskCostUsd > 0 ? ` | ${formatMoney(state.currentTaskCostUsd, 4)}` : ""}`);
    }

    if (msg.accountability_chain) {
        state.run.accountability = msg.accountability_chain;
        state.run.hops = String(msg.accountability_chain.total_hops || 0);
        renderAccountabilityChain(msg.accountability_chain);
    }

    if (msg.firewall) {
        state.run.firewall = `${msg.firewall.blocked || 0}/${msg.firewall.total_checks || 0}`;
    }

    if (msg.kernel?.session_tokens) {
        state.run.tokens = msg.kernel.session_tokens.total || state.run.tokens;
    }

    applyRunState();
}

function finishRun() {
    state.currentTaskId = null;
    setRunning(false);
    loadSessionCost();
    loadHistory();
    loadMemory();
}

function setRunning(running) {
    state.isRunning = running;
    updateControlState();
    applyWorkspaceMode();

    if (running) {
        els.killBtn.textContent = "Kill";
        els.killBtn.disabled = false;
    }
}

function updateStatus(text, running = false) {
    els.status.textContent = text;
    els.status.className = `status-pill${running ? " running" : ""}`;
}

function addMessage(type, content, options = {}) {
    const div = document.createElement("div");
    const extraClass = options.extraClass ? ` ${options.extraClass}` : "";
    div.className = `msg ${type}${extraClass}`;

    if (options.markdown) {
        div.innerHTML = renderMarkdown(content);
    } else if (options.html) {
        div.innerHTML = content;
    } else {
        div.textContent = content;
    }

    els.messages.appendChild(div);
    scrollToBottom();
    return div;
}

// ── Generative UI — Widget Rendering ─────────────────────────────────────────

function renderWidget(msg) {
    const container = document.createElement("div");
    container.className = "msg widget-msg";
    container.dataset.widgetId = msg.widget_id || "";
    container.dataset.widgetType = msg.widget_type || "custom";

    // Widget header with type badge
    const header = document.createElement("div");
    header.className = "widget-header";
    header.innerHTML = `
        <span class="widget-badge">${escapeHtml(msg.widget_type || "widget")}</span>
        <span class="widget-title-text">${escapeHtml(msg.title || "Widget")}</span>
        <div class="widget-actions">
            <button class="widget-action-btn widget-expand-btn" title="Expand widget">&#x26F6;</button>
            <button class="widget-action-btn widget-reload-btn" title="Reload widget">&#x21BB;</button>
        </div>
    `;
    container.appendChild(header);

    // Description if present
    if (msg.description) {
        const desc = document.createElement("div");
        desc.className = "widget-description";
        desc.textContent = msg.description;
        container.appendChild(desc);
    }

    // Sandboxed iframe
    const iframe = document.createElement("iframe");
    iframe.className = "widget-iframe";
    iframe.sandbox = "allow-scripts allow-popups";
    iframe.style.width = msg.width || "100%";
    iframe.style.height = msg.height || "400px";
    iframe.srcdoc = msg.html || "<p>Empty widget</p>";
    iframe.title = msg.title || "Forge Widget";
    container.appendChild(iframe);

    // Wire up expand/reload buttons
    const expandBtn = header.querySelector(".widget-expand-btn");
    const reloadBtn = header.querySelector(".widget-reload-btn");

    expandBtn.addEventListener("click", () => {
        container.classList.toggle("widget-expanded");
        if (container.classList.contains("widget-expanded")) {
            iframe.style.height = "80vh";
            expandBtn.innerHTML = "&#x2716;";  // × close
        } else {
            iframe.style.height = msg.height || "400px";
            expandBtn.innerHTML = "&#x26F6;";  // expand
        }
    });

    reloadBtn.addEventListener("click", () => {
        iframe.srcdoc = msg.html || "<p>Empty widget</p>";
    });

    // Listen for widget → agent messages
    const widgetId = msg.widget_id;
    window.addEventListener("message", (e) => {
        if (e.data && e.data.source === "forge-widget" && e.data.widgetId === widgetId) {
            console.log("[Forge Widget Event]", e.data.event, e.data.data);
            // Future: relay to backend for agent processing
        }
    });

    els.messages.appendChild(container);
    scrollToBottom(true);
}

function renderMarkdown(text) {
    if (typeof marked !== "undefined") {
        marked.setOptions({ breaks: true, mangle: false, headerIds: false });
        return marked.parse(text || "");
    }
    return escapeHtml(text || "").replace(/\n/g, "<br>");
}

function isNearBottom() {
    const el = els.messages;
    return el.scrollHeight - el.scrollTop - el.clientHeight < 80;
}

function scrollToBottom(force = false) {
    if (force || isNearBottom()) {
        els.messages.scrollTop = els.messages.scrollHeight;
    }
}

function modeFromControls() {
    return els.directToggle.checked ? "Direct" : "Planner";
}

const COLLAB_SCENARIOS = new Set(["pair_prog", "story_time", "startup", "world_build", "hackathon"]);

function openArenaSetup() {
    if (state.isRunning) return;
    els.arenaSetup.classList.toggle("hidden");
}

function updateArenaSetupCopy() {
    const scenarioSelect = document.getElementById("arena-scenario");
    const isCollab = COLLAB_SCENARIOS.has(scenarioSelect?.value);
    const copy = els.arenaSetup.querySelector(".arena-copy");
    const goBtn = document.getElementById("arena-go-btn");
    if (copy) {
        copy.querySelector("strong").textContent = isCollab ? "THE FORGE STUDIO" : "THE FORGE ARENA";
        copy.querySelector("span").textContent = isCollab
            ? "Two AI collaborators enter. Something beautiful (maybe) leaves."
            : "Two AI gladiators enter. One leaves victorious. Zeus judges all.";
    }
    if (goBtn) goBtn.textContent = isCollab ? "BUILD" : "FIGHT";
}

async function startArena() {
    if (state.isRunning) return;

    els.arenaSetup.classList.add("hidden");
    state.isArenaMode = true;
    const scenarioSelect = document.getElementById("arena-scenario");
    state.isCollabMode = COLLAB_SCENARIOS.has(scenarioSelect?.value);
    applyWorkspaceMode();
    resetArenaUI();
    resetRunState(state.isCollabMode ? "Studio" : "Arena");
    state.run.model = state.isCollabMode
        ? `${shortModelName(els.redModel.value)} + ${shortModelName(els.blueModel.value)}`
        : `${shortModelName(els.redModel.value)} vs ${shortModelName(els.blueModel.value)}`;
    applyRunState();
    setRunning(true);
    updateStatus(state.isCollabMode ? "Launching Studio" : "Launching Arena", true);

    try {
        const scenarioSelect = document.getElementById("arena-scenario");
        const response = await fetchJson("/api/arena", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                red_model: els.redModel.value,
                blue_model: els.blueModel.value,
                scenario: scenarioSelect ? scenarioSelect.value : "classic",
            }),
        });

        if (response.error) {
            addArenaCommentary(`ERROR: ${response.error}`);
            setRunning(false);
            return;
        }

        state.currentTaskId = response.task_id;
        state.run.taskId = response.task_id;
        applyRunState();
        streamArena(response.task_id);
    } catch (error) {
        addArenaCommentary(`Connection failed: ${error.message}`);
        setRunning(false);
    }
}

function switchToConsole() {
    if (state.isRunning) return;
    state.isArenaMode = false;
    applyWorkspaceMode();
    stopTTS();
}

function resetArenaUI() {
    const scenarioSelect = document.getElementById("arena-scenario");
    const isCollab = COLLAB_SCENARIOS.has(scenarioSelect?.value);
    els.commentaryText.textContent = isCollab
        ? "The Muses gather. Choose your collaborators."
        : "The gods grow restless. Choose your fighters.";
    els.roundLabel.textContent = "Ready";
    els.redLog.textContent = "";
    els.blueLog.textContent = "";
    els.scoreRed.style.width = "0%";
    els.scoreBlue.style.width = "0%";
    els.scoreRedNum.textContent = "0";
    els.scoreBlueNum.textContent = "0";
    stopTTS();
}

function streamArena(taskId) {
    const source = new EventSource(`/api/stream/${taskId}`);
    let commentaryBuffer = "";
    let streamFinished = false;

    source.onmessage = (event) => {
        const msg = JSON.parse(event.data);

        if (msg.final) {
            streamFinished = true;
            source.close();
            state.currentTaskId = null;
            setRunning(false);
            applyWorkspaceMode();
            updateStatus(state.isCollabMode ? "Studio Complete" : "Arena Complete", false);
            return;
        }

        switch (msg.type) {
            case "arena_status":
                addArenaCommentary(msg.content || "");
                break;

            case "arena_round_start":
                commentaryBuffer = "";
                els.roundLabel.textContent = `Round ${msg.round}: ${msg.name}`;
                addArenaCommentary(`--- Round ${msg.round}: ${msg.name} ---`);
                flushSpeechBuffer();
                speakText(`Round ${msg.round}. ${msg.name}`);
                break;

            case "arena_team_action": {
                const target = msg.team === "red" ? els.redLog : els.blueLog;
                const line = msg.action_type === "content"
                    ? (msg.content || "")
                    : `[${msg.action_type || "event"}] ${msg.content || ""}\n`;
                target.textContent += line;
                target.scrollTop = target.scrollHeight;
                break;
            }

            case "arena_commentary":
                commentaryBuffer += msg.content || "";
                els.commentaryText.textContent = commentaryBuffer;
                els.commentaryText.parentElement.scrollTop = els.commentaryText.parentElement.scrollHeight;
                bufferAndSpeak(msg.content || "");
                break;

            case "arena_scores":
                els.scoreRedNum.textContent = String(msg.red_total || 0);
                els.scoreBlueNum.textContent = String(msg.blue_total || 0);
                els.scoreRed.style.width = `${Math.min(100, ((msg.red_total || 0) / 160) * 100)}%`;
                els.scoreBlue.style.width = `${Math.min(100, ((msg.blue_total || 0) / 160) * 100)}%`;
                addArenaCommentary(`Score update: Red +${msg.red_score || 0} (${msg.red_total || 0}) | Blue +${msg.blue_score || 0} (${msg.blue_total || 0})`);
                break;

            case "arena_result":
                flushSpeechBuffer();
                if (state.isCollabMode) {
                    const combined = (msg.red_total || 0) + (msg.blue_total || 0);
                    els.roundLabel.textContent = "Project Complete";
                    addArenaCommentary(`Final result: Team score ${combined} | Alpha ${msg.red_total || 0} | Beta ${msg.blue_total || 0}`);
                } else {
                    els.roundLabel.textContent = msg.winner === "tie"
                        ? "Tie"
                        : `${capitalize(msg.winner || "winner")} Wins`;
                    addArenaCommentary(`Final result: ${msg.winner || "unknown"} | Red ${msg.red_total || 0} | Blue ${msg.blue_total || 0}`);
                }
                break;

            case "error":
                addArenaCommentary(`ERROR: ${msg.content || "Unknown error"}`);
                break;
        }
    };

    source.onerror = () => {
        source.close();
        if (!streamFinished) {
            addArenaCommentary("Arena stream disconnected before completion.");
            setRunning(false);
            applyWorkspaceMode();
        }
    };
}

function addArenaCommentary(text) {
    els.commentaryText.textContent += `${text}\n`;
    els.commentaryText.parentElement.scrollTop = els.commentaryText.parentElement.scrollHeight;
}

function initTTS() {
    if (!("speechSynthesis" in window)) return;

    const saved = localStorage.getItem("forge_arena_tts");
    els.ttsToggle.checked = saved === "true";
    state.ttsEnabled = els.ttsToggle.checked;

    els.ttsToggle.addEventListener("change", () => {
        state.ttsEnabled = els.ttsToggle.checked;
        localStorage.setItem("forge_arena_tts", String(state.ttsEnabled));
        if (!state.ttsEnabled) stopTTS();
    });

    const pickVoice = () => {
        const voices = speechSynthesis.getVoices();
        if (!voices.length) return;

        state.ttsVoice = voices.find((voice) => voice.lang.startsWith("en") && voice.name.includes("Google"))
            || voices.find((voice) => voice.lang.startsWith("en") && voice.name.includes("Microsoft"))
            || voices.find((voice) => voice.lang.startsWith("en"))
            || voices[0];
    };

    speechSynthesis.onvoiceschanged = pickVoice;
    pickVoice();
}

function speakText(text) {
    if (!state.ttsEnabled || !("speechSynthesis" in window) || !text.trim()) return;

    // Chrome bug: speechSynthesis silently dies after ~15s of continuous speech.
    // Split long text into short chunks and re-poke the synth to keep it alive.
    const MAX_CHARS = 200;
    const chunks = [];
    let remaining = text.trim();
    while (remaining.length > MAX_CHARS) {
        let cut = remaining.lastIndexOf(" ", MAX_CHARS);
        if (cut <= 0) cut = MAX_CHARS;
        chunks.push(remaining.slice(0, cut));
        remaining = remaining.slice(cut).trimStart();
    }
    if (remaining) chunks.push(remaining);

    for (const chunk of chunks) {
        const utterance = new SpeechSynthesisUtterance(chunk);
        if (state.ttsVoice) utterance.voice = state.ttsVoice;
        utterance.rate = 1.05;
        utterance.pitch = 1.0;
        speechSynthesis.speak(utterance);
    }
}

// Chrome workaround: periodically resume speechSynthesis to prevent silent stall
setInterval(() => {
    if (speechSynthesis.speaking && !speechSynthesis.paused) {
        speechSynthesis.pause();
        speechSynthesis.resume();
    }
}, 10000);

function bufferAndSpeak(chunk) {
    if (!state.ttsEnabled) return;

    state.ttsBuffer += chunk;
    // Split on sentence boundaries for natural pauses
    const sentences = state.ttsBuffer.split(/(?<=[.!?\n])\s+/);
    if (sentences.length > 1) {
        const speakable = sentences.slice(0, -1).join(" ").trim();
        state.ttsBuffer = sentences[sentences.length - 1];
        if (speakable) speakText(speakable);
    }
}

function flushSpeechBuffer() {
    if (state.ttsBuffer.trim()) {
        speakText(state.ttsBuffer.trim());
    }
    state.ttsBuffer = "";
}

function stopTTS() {
    state.ttsBuffer = "";
    if ("speechSynthesis" in window) {
        speechSynthesis.cancel();
    }
}

function shortModelName(modelId) {
    if (!modelId) return "-";
    const match = state.models.find((model) => model.id === modelId);
    return match ? match.label : modelId;
}

function isPlannedTask(task) {
    return task?.plan_raw && !String(task.plan_raw).startsWith("(direct mode");
}

function incrementCompositeCount(value) {
    if (typeof value === "string" && value.includes("/")) {
        const [blocked, total] = value.split("/").map((part) => Number.parseInt(part, 10) || 0);
        return `${blocked + 1}/${total + 1}`;
    }

    const numeric = Number.parseInt(value, 10) || 0;
    return String(numeric + 1);
}

function formatMoney(value, decimals = 2) {
    return `$${Number(value || 0).toFixed(decimals)}`;
}

function formatCompactMoney(value) {
    return value ? `$${Number(value).toFixed(2)}` : "$0";
}

function formatTimestamp(value) {
    if (!value) return "Unknown time";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString([], {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
    });
}

function truncate(value, maxLength) {
    if (!value || value.length <= maxLength) return value || "";
    return `${value.slice(0, maxLength - 3)}...`;
}

function truncateMiddle(value, maxLength) {
    if (!value || value.length <= maxLength) return value || "";
    const side = Math.floor((maxLength - 3) / 2);
    return `${value.slice(0, side)}...${value.slice(-side)}`;
}

function escapeHtml(value) {
    return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

function capitalize(value) {
    if (!value) return "";
    return value.charAt(0).toUpperCase() + value.slice(1);
}

init();
