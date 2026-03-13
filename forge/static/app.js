const TECHNICAL_TYPES = new Set([
    "tool-call", "tool-result", "toll", "toll-summary",
    "guardrail", "guardrail-summary", "firewall", "token-usage",
]);

const els = {
    messages: document.getElementById("messages"),
    messagesTechnical: document.getElementById("messages-technical"),
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
    packSelect: document.getElementById("pack-select"),
    arenaBtn: document.getElementById("arena-btn"),
    backToForgeBtn: document.getElementById("back-to-forge-btn"),
    resetCostBtn: document.getElementById("reset-cost-btn"),
    refreshHistoryBtn: document.getElementById("refresh-history-btn"),
    refreshMemoryBtn: document.getElementById("refresh-memory-btn"),
    clearMemoryBtn: document.getElementById("clear-memory-btn"),
    featureBadges: document.getElementById("feature-badges"),
    historyList: document.getElementById("history-list"),
    historyDetail: document.getElementById("history-detail"),
    inspectorFilters: document.getElementById("inspector-filters"),
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
    packs: [],
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

    els.packSelect.addEventListener("change", () => {
        localStorage.setItem("forge_pack", els.packSelect.value);
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
        if (tab === "trading") initTrading();
    });
}

async function init() {
    bindEvents();
    resetRunState();
    initTTS();

    await loadConfig();
    await loadModels();
    await loadPacks();
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
        { enabled: features.trading, label: "Trading" },
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

async function loadPacks() {
    try {
        state.packs = await fetchJson("/api/packs");
        populatePackSelect();
    } catch (error) {
        // Packs are optional — degrade gracefully
        state.packs = [];
    }
}

function populatePackSelect() {
    if (!els.packSelect || !state.packs) return;

    // Keep the "Auto" option, clear the rest
    els.packSelect.innerHTML = '<option value="">Auto (all tools)</option>';

    const READINESS_ICONS = { ready: "\u2705", degraded: "\u26A0\uFE0F", unavailable: "\u274C" };

    // state.packs is an array of pack dicts from /api/packs
    for (const pack of state.packs) {
        const option = document.createElement("option");
        option.value = pack.name;
        const icon = READINESS_ICONS[pack.readiness?.state] || "";
        const label = pack.name.charAt(0).toUpperCase() + pack.name.slice(1);
        option.textContent = `${icon} ${label} — ${pack.description || ""}`.trim();
        if (pack.readiness?.state === "unavailable") {
            option.disabled = true;
        }
        els.packSelect.appendChild(option);
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

    const savedPack = localStorage.getItem("forge_pack") || "";
    if (hasOption(els.packSelect, savedPack)) {
        els.packSelect.value = savedPack;
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
    els.packSelect.disabled = controlsDisabled;
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

async function renderHistoryDetail(task) {
    if (!task) {
        els.historyDetail.className = "history-detail empty-state";
        els.historyDetail.textContent = "Select a past task to inspect the full event stream, tool calls, widgets, costs, and safety data.";
        els.inspectorFilters.style.display = "none";
        return;
    }

    // Try to load the full run log for rich inspector view
    try {
        const run = await fetchJson(`/api/runs/${task.task_id}`);
        if (run && !run.error && Array.isArray(run.events) && run.events.length) {
            renderRunInspector(task, run.events, run.meta);
            return;
        }
    } catch (_) {
        // No run log — fall back to legacy view
    }
    renderHistoryDetailLegacy(task);
}

function renderHistoryDetailLegacy(task) {
    els.inspectorFilters.style.display = "none";
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

// ── Run Inspector — Full Event Timeline ─────────────────────────────────────

const EVENT_CATEGORIES = {
    status:              "status",
    plan_content:        "step",
    step_start:          "step",
    step_done:           "step",
    content:             "content",
    tool_call:           "tools",
    tool_result:         "tools",
    guardrail_violation: "safety",
    guardrail_summary:   "safety",
    firewall_block:      "safety",
    escalation:          "safety",
    widget_render:       "widgets",
    judge_scores:        "scores",
    token_usage:         "cost",
    toll_deducted:       "cost",
    toll_summary:        "cost",
    done:                "status",
    cancelled:           "status",
    error:               "safety",
    arena_status:        "arena",
    arena_round_start:   "arena",
    arena_team_action:   "arena",
    arena_commentary:    "arena",
    arena_scores:        "scores",
    arena_result:        "arena",
};

function categorizeEvent(evt) {
    return EVENT_CATEGORIES[evt.type] || "status";
}

function renderRunInspector(task, events, meta) {
    els.inspectorFilters.style.display = "";

    // Compute summary stats
    const stats = {
        events: events.length,
        steps: 0,
        tools: 0,
        guardrails: 0,
        firewalls: 0,
        widgets: 0,
        scores: 0,
        costUsd: 0,
        tokens: 0,
    };
    const toolNames = new Set();

    for (const evt of events) {
        switch (evt.type) {
            case "step_start": stats.steps++; break;
            case "tool_call":
                stats.tools++;
                if (evt.name) toolNames.add(evt.name);
                break;
            case "guardrail_violation": stats.guardrails++; break;
            case "firewall_block": stats.firewalls++; break;
            case "widget_render": stats.widgets++; break;
            case "judge_scores": case "arena_scores": stats.scores++; break;
            case "token_usage":
                stats.costUsd += evt.cost_usd || 0;
                stats.tokens += (evt.input_tokens || 0) + (evt.output_tokens || 0);
                break;
        }
    }

    const durationSec = events.length >= 2
        ? ((events[events.length - 1].t || 0) - (events[0].t || 0)).toFixed(1)
        : "-";

    // Build HTML
    const summaryHtml = `
        <div class="inspector-summary">
            <div class="inspector-stat"><em>Events</em><strong>${stats.events}</strong></div>
            <div class="inspector-stat"><em>Steps</em><strong>${stats.steps}</strong></div>
            <div class="inspector-stat"><em>Tool Calls</em><strong>${stats.tools}</strong></div>
            <div class="inspector-stat"><em>Guardrails</em><strong>${stats.guardrails}</strong></div>
            <div class="inspector-stat"><em>Firewalls</em><strong>${stats.firewalls}</strong></div>
            <div class="inspector-stat"><em>Widgets</em><strong>${stats.widgets}</strong></div>
            <div class="inspector-stat"><em>Scores</em><strong>${stats.scores}</strong></div>
            <div class="inspector-stat"><em>Tokens</em><strong>${stats.tokens.toLocaleString()}</strong></div>
            <div class="inspector-stat"><em>Cost</em><strong>${formatMoney(stats.costUsd, 4)}</strong></div>
            <div class="inspector-stat"><em>Duration</em><strong>${durationSec}s</strong></div>
        </div>
    `;

    const toolsLine = toolNames.size
        ? `<div class="history-block"><h4>Tools Used</h4><p>${escapeHtml([...toolNames].join(", "))}</p></div>`
        : "";

    const t0 = events[0]?.t || 0;
    const timelineHtml = events.map((evt, i) => {
        const cat = categorizeEvent(evt);
        const relTime = t0 ? `+${((evt.t || 0) - t0).toFixed(1)}s` : `#${i}`;
        const body = formatEventBody(evt);
        return `
            <div class="inspector-event" data-cat="${cat}" data-seq="${evt.seq ?? i}">
                <div class="ev-head">
                    <span class="ev-type">${escapeHtml(evt.type || "unknown")}</span>
                    <span class="ev-time">${escapeHtml(relTime)}</span>
                </div>
                <div class="ev-body">${body}</div>
            </div>
        `;
    }).join("");

    els.historyDetail.className = "history-detail";
    els.historyDetail.innerHTML = `
        <div class="history-block">
            <div class="history-kicker">${escapeHtml(formatTimestamp(task.timestamp))} | ${escapeHtml(task.task_id || "-")}</div>
            <h4>${escapeHtml(task.task || "Untitled task")}</h4>
            <p>${escapeHtml(task.final_summary || "No summary stored.")}</p>
        </div>
        ${summaryHtml}
        ${toolsLine}
        <div class="inspector-timeline">${timelineHtml}</div>
    `;

    // Wire filter buttons
    bindInspectorFilters();
}

function formatEventBody(evt) {
    switch (evt.type) {
        case "status":
        case "arena_status":
        case "cancelled":
            return escapeHtml(evt.content || "");

        case "plan_content":
        case "content":
            return `<pre>${escapeHtml(truncate(evt.content || "", 300))}</pre>`;

        case "step_start":
            return `<strong>Step ${evt.step}: ${escapeHtml(evt.title || "")}</strong>`
                + (evt.description ? `<br>${escapeHtml(evt.description)}` : "")
                + (evt.delegatee ? `<br><em>Delegatee:</em> ${escapeHtml(evt.delegatee)}` : "");

        case "step_done": {
            const parts = [`Step ${evt.step} ${evt.status || "done"}`];
            if (evt.delegatee) parts.push(evt.delegatee);
            if (evt.latency_s) parts.push(`${evt.latency_s}s`);
            if (evt.trust_score != null) parts.push(`trust ${Number(evt.trust_score).toFixed(2)}`);
            if (evt.was_reassigned) parts.push("reassigned");
            return escapeHtml(parts.join(" | "));
        }

        case "tool_call":
            return `<strong>${escapeHtml(evt.name || "tool")}</strong>`
                + `<pre>${escapeHtml(truncate(JSON.stringify(evt.args || {}, null, 2), 200))}</pre>`;

        case "tool_result":
            return `<pre>${escapeHtml(truncate(evt.result || "", 300))}</pre>`;

        case "guardrail_violation":
            return `<strong>${escapeHtml(evt.severity || "warning")}</strong> ${escapeHtml(evt.guardrail || "")} — ${escapeHtml(evt.message || "")}`;

        case "guardrail_summary":
            return `${evt.total_violations || 0} violations | ${evt.blocks || 0} blocks | ${evt.warnings || 0} warnings`;

        case "firewall_block":
            return `<strong>${escapeHtml(evt.tool || "tool")}</strong> blocked — ${escapeHtml(evt.reason || "")}`;

        case "escalation":
            return `<strong>${escapeHtml(evt.category || "general")}</strong> — ${escapeHtml(evt.reason || "")}`;

        case "widget_render":
            return `<strong>${escapeHtml(evt.title || "Widget")}</strong> (${escapeHtml(evt.widget_type || "custom")})`
                + `<div class="inspector-widget-preview"><iframe sandbox="allow-scripts" srcdoc="${escapeAttr(evt.html || "<p>Empty</p>")}" title="${escapeAttr(evt.title || "Widget")}"></iframe></div>`;

        case "judge_scores":
            if (Array.isArray(evt.scores)) {
                return evt.scores.map(s =>
                    `Step ${s.step ?? "?"}: ${s.score ?? "-"}/10 — ${escapeHtml(truncate(s.reasoning || "", 100))}`
                ).join("<br>");
            }
            return escapeHtml(JSON.stringify(evt.scores || evt));

        case "token_usage":
            return `${escapeHtml(evt.model || "-")} | in: ${(evt.input_tokens || 0).toLocaleString()} out: ${(evt.output_tokens || 0).toLocaleString()} | ${formatMoney(evt.cost_usd || 0, 6)}`;

        case "toll_deducted":
            return `${formatMoney(evt.toll_usd || 0, 6)} | ${escapeHtml(evt.sender || "-")} → ${escapeHtml(evt.receiver || "-")}`;

        case "toll_summary":
            return `${evt.total_messages || 0} messages | ${formatMoney(evt.total_tolls_usd || 0, 6)} tolls`;

        case "done":
            return escapeHtml(evt.summary || "Task complete");

        case "arena_round_start":
            return `<strong>Round ${evt.round}: ${escapeHtml(evt.name || "")}</strong>`;

        case "arena_team_action":
            return `<strong class="team-${escapeHtml(evt.team || "red")}">${escapeHtml((evt.team || "").toUpperCase())}</strong> [${escapeHtml(evt.action_type || "action")}] ${escapeHtml(truncate(evt.content || "", 200))}`;

        case "arena_commentary":
            return escapeHtml(truncate(evt.content || "", 300));

        case "arena_scores":
            return `Red +${evt.red_score || 0} (${evt.red_total || 0}) | Blue +${evt.blue_score || 0} (${evt.blue_total || 0})`;

        case "arena_result":
            return `<strong>${escapeHtml(evt.winner || "?")}</strong> | Red ${evt.red_total || 0} | Blue ${evt.blue_total || 0}`;

        default:
            return `<pre>${escapeHtml(truncate(JSON.stringify(evt, null, 2), 200))}</pre>`;
    }
}

function escapeAttr(value) {
    return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/"/g, "&quot;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
}

function bindInspectorFilters() {
    const filterBtns = els.inspectorFilters.querySelectorAll(".filter-btn");
    filterBtns.forEach(btn => {
        // Replace with fresh clone to remove old listeners
        const fresh = btn.cloneNode(true);
        btn.parentNode.replaceChild(fresh, btn);
        fresh.addEventListener("click", () => {
            filterBtns.forEach(b => b.classList.remove("active"));
            // Re-query since we replaced nodes
            els.inspectorFilters.querySelectorAll(".filter-btn").forEach(b => b.classList.remove("active"));
            fresh.classList.add("active");
            applyInspectorFilter(fresh.dataset.filter);
        });
    });
}

function applyInspectorFilter(filter) {
    const timeline = els.historyDetail.querySelector(".inspector-timeline");
    if (!timeline) return;

    const events = timeline.querySelectorAll(".inspector-event");
    events.forEach(el => {
        if (filter === "all") {
            el.classList.remove("filtered-out");
        } else {
            const cat = el.dataset.cat;
            // Map filter names to categories
            const match = (filter === "steps" && (cat === "step" || cat === "content" || cat === "status"))
                || (filter === "tools" && cat === "tools")
                || (filter === "safety" && cat === "safety")
                || (filter === "widgets" && cat === "widgets")
                || (filter === "scores" && cat === "scores");
            el.classList.toggle("filtered-out", !match);
        }
    });
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
            pack: els.packSelect.value,
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

    const target = (TECHNICAL_TYPES.has(type) && els.messagesTechnical)
        ? els.messagesTechnical : els.messages;
    target.appendChild(div);
    scrollToBottom(false, target);
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

function isNearBottom(el) {
    return el.scrollHeight - el.scrollTop - el.clientHeight < 80;
}

function scrollToBottom(force = false, target = els.messages) {
    if (force || isNearBottom(target)) {
        target.scrollTop = target.scrollHeight;
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

// ══════════════════════════════════════════════════════════════════════════
// TRADING TAB
// ══════════════════════════════════════════════════════════════════════════

const tradingState = {
    initialized: false,
    autoRefreshTimer: null,
    currentTicker: "SPY",
    currentExpiry: "",
    chartMode: "line",
    tradeSide: "buy",
    pcrHistory: [],
    alerts: [],
    sseSource: null,
};

function initTrading() {
    if (tradingState.initialized) return;
    tradingState.initialized = true;

    // Bind trading events
    const refreshBtn = document.getElementById("trading-refresh-btn");
    const autoRefresh = document.getElementById("trading-auto-refresh");
    const tickerSelect = document.getElementById("trading-ticker");
    const expirySelect = document.getElementById("trading-expiry");
    const providerSelect = document.getElementById("trading-provider");
    const customTicker = document.getElementById("trading-custom-ticker");
    const alertSetBtn = document.getElementById("alert-set-btn");
    const tradeSubmitBtn = document.getElementById("trade-submit-btn");
    const buyBtn = document.getElementById("trade-buy-btn");
    const sellBtn = document.getElementById("trade-sell-btn");
    const orderType = document.getElementById("trade-order-type");
    const priceField = document.getElementById("trade-price-field");

    refreshBtn.addEventListener("click", () => loadPCRData());
    tickerSelect.addEventListener("change", () => {
        tradingState.currentTicker = tickerSelect.value;
        loadExpirations();
        loadPCRData();
    });
    expirySelect.addEventListener("change", () => {
        tradingState.currentExpiry = expirySelect.value;
        loadPCRData();
    });
    customTicker.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            tradingState.currentTicker = customTicker.value.trim().toUpperCase();
            loadExpirations();
            loadPCRData();
        }
    });

    autoRefresh.addEventListener("change", () => {
        if (autoRefresh.checked) {
            tradingState.autoRefreshTimer = setInterval(() => loadPCRData(), 30000);
        } else {
            clearInterval(tradingState.autoRefreshTimer);
        }
    });

    alertSetBtn.addEventListener("click", setTradingAlert);
    tradeSubmitBtn.addEventListener("click", executeTrade);

    buyBtn.addEventListener("click", () => {
        tradingState.tradeSide = "buy";
        buyBtn.classList.add("active");
        sellBtn.classList.remove("active");
    });
    sellBtn.addEventListener("click", () => {
        tradingState.tradeSide = "sell";
        sellBtn.classList.add("active");
        buyBtn.classList.remove("active");
    });

    orderType.addEventListener("change", () => {
        priceField.style.display = orderType.value === "limit" ? "" : "none";
    });

    // Chart mode switching
    document.querySelectorAll(".chart-mode-btns .filter-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            document.querySelectorAll(".chart-mode-btns .filter-btn").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            tradingState.chartMode = btn.dataset.chart;
            renderTradingChart();
        });
    });

    // Connect SSE stream
    connectTradingStream();

    // Initial data load
    loadExpirations();
    loadPCRData();
    loadTradingAlerts();
    loadPortfolio();
}

async function loadExpirations() {
    const provider = document.getElementById("trading-provider").value;
    try {
        const data = await fetchJson(`/api/trading/expirations/${encodeURIComponent(tradingState.currentTicker)}?provider=${provider}`);
        const select = document.getElementById("trading-expiry");
        select.innerHTML = '<option value="">Nearest</option>';
        (data.expirations || []).forEach(exp => {
            select.innerHTML += `<option value="${escapeHtml(exp)}">${escapeHtml(exp)}</option>`;
        });
    } catch (e) {
        console.warn("Failed to load expirations:", e);
    }
}

async function loadPCRData() {
    const ticker = tradingState.currentTicker;
    const expiry = tradingState.currentExpiry;
    const provider = document.getElementById("trading-provider").value;

    try {
        const params = new URLSearchParams({ provider });
        if (expiry) params.set("expiry", expiry);

        const [pcr, quote] = await Promise.all([
            fetchJson(`/api/trading/pcr/${encodeURIComponent(ticker)}?${params}`),
            fetchJson(`/api/trading/quote/${encodeURIComponent(ticker)}?provider=${provider}`),
        ]);

        // Update metric cards
        document.getElementById("pcr-vol-ratio").textContent = pcr.vol_ratio != null ? pcr.vol_ratio.toFixed(4) : "—";
        document.getElementById("pcr-oi-ratio").textContent = pcr.oi_ratio != null ? pcr.oi_ratio.toFixed(4) : "—";
        document.getElementById("pcr-put-vol").textContent = (pcr.put_vol || 0).toLocaleString();
        document.getElementById("pcr-call-vol").textContent = (pcr.call_vol || 0).toLocaleString();

        const badge = document.getElementById("pcr-sentiment");
        badge.textContent = pcr.sentiment || "—";
        badge.className = `sentiment-badge ${pcr.sentiment || "neutral"}`;

        const priceEl = document.getElementById("pcr-price");
        priceEl.textContent = quote.price ? `$${quote.price.toFixed(2)}` : "—";

        // Update chart title
        document.getElementById("chart-title").textContent = `PCR Chart — ${ticker}`;

        // Add to history for charting
        tradingState.pcrHistory.push({
            timestamp: new Date().toLocaleTimeString(),
            vol_ratio: pcr.vol_ratio,
            oi_ratio: pcr.oi_ratio,
            ticker,
            expiry: pcr.expiry,
        });
        if (tradingState.pcrHistory.length > 100) {
            tradingState.pcrHistory = tradingState.pcrHistory.slice(-100);
        }

        renderTradingChart();
    } catch (e) {
        console.error("Failed to load PCR data:", e);
    }
}

function renderTradingChart() {
    const container = document.getElementById("trading-chart-container");
    const data = tradingState.pcrHistory.filter(d => d.ticker === tradingState.currentTicker);

    if (data.length === 0) {
        container.innerHTML = '<div class="empty-state">No data yet. Click Refresh to load.</div>';
        return;
    }

    const mode = tradingState.chartMode;
    let plotlyCode;

    if (mode === "line") {
        plotlyCode = `
            const data = ${JSON.stringify(data)};
            Plotly.newPlot('chart', [
                {
                    x: data.map(d => d.timestamp),
                    y: data.map(d => d.vol_ratio),
                    name: 'Vol Ratio',
                    type: 'scatter',
                    mode: 'lines+markers',
                    line: { color: '#f2a74b', width: 2 },
                    marker: { size: 4 },
                },
                {
                    x: data.map(d => d.timestamp),
                    y: data.map(d => d.oi_ratio),
                    name: 'OI Ratio',
                    type: 'scatter',
                    mode: 'lines+markers',
                    line: { color: '#63c7b2', width: 2 },
                    marker: { size: 4 },
                },
                {
                    x: data.map(d => d.timestamp),
                    y: data.map(() => 1),
                    name: 'Neutral (1.0)',
                    type: 'scatter',
                    mode: 'lines',
                    line: { color: '#9cacbf', width: 1, dash: 'dot' },
                },
            ], {
                template: 'plotly_dark',
                paper_bgcolor: '#171f2a',
                plot_bgcolor: '#171f2a',
                margin: { t: 30, r: 20, b: 40, l: 50 },
                xaxis: { title: 'Time', gridcolor: 'rgba(255,255,255,0.06)' },
                yaxis: { title: 'PCR', gridcolor: 'rgba(255,255,255,0.06)' },
                legend: { x: 0, y: 1.1, orientation: 'h' },
            }, { responsive: true });
        `;
    } else if (mode === "heatmap") {
        const expiries = [...new Set(data.map(d => d.expiry))];
        const timestamps = [...new Set(data.map(d => d.timestamp))];
        const z = expiries.map(exp =>
            timestamps.map(ts => {
                const point = data.find(d => d.expiry === exp && d.timestamp === ts);
                return point ? point.vol_ratio : null;
            })
        );
        plotlyCode = `
            Plotly.newPlot('chart', [{
                z: ${JSON.stringify(z)},
                x: ${JSON.stringify(timestamps)},
                y: ${JSON.stringify(expiries)},
                type: 'heatmap',
                colorscale: [[0, '#63c7b2'], [0.5, '#f5c35b'], [1, '#ff6a6a']],
                colorbar: { title: 'PCR' },
            }], {
                template: 'plotly_dark',
                paper_bgcolor: '#171f2a',
                plot_bgcolor: '#171f2a',
                margin: { t: 30, r: 20, b: 60, l: 80 },
                xaxis: { title: 'Time' },
                yaxis: { title: 'Expiry' },
            }, { responsive: true });
        `;
    } else {
        // 3D surface
        plotlyCode = `
            const data = ${JSON.stringify(data)};
            Plotly.newPlot('chart', [{
                x: data.map(d => d.timestamp),
                y: data.map(d => d.expiry || 'nearest'),
                z: data.map(d => d.vol_ratio),
                type: 'scatter3d',
                mode: 'markers+lines',
                marker: {
                    size: 4,
                    color: data.map(d => d.vol_ratio),
                    colorscale: [[0, '#63c7b2'], [0.5, '#f5c35b'], [1, '#ff6a6a']],
                },
                line: { color: '#f2a74b', width: 2 },
            }], {
                template: 'plotly_dark',
                paper_bgcolor: '#171f2a',
                plot_bgcolor: '#171f2a',
                margin: { t: 10, r: 10, b: 10, l: 10 },
                scene: {
                    xaxis: { title: 'Time', gridcolor: 'rgba(255,255,255,0.06)' },
                    yaxis: { title: 'Expiry', gridcolor: 'rgba(255,255,255,0.06)' },
                    zaxis: { title: 'PCR', gridcolor: 'rgba(255,255,255,0.06)' },
                    bgcolor: '#171f2a',
                },
            }, { responsive: true });
        `;
    }

    const html = `<!DOCTYPE html>
<html><head>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"><\/script>
<style>body{margin:0;background:#171f2a;overflow:hidden}#chart{width:100%;height:100vh}</style>
</head><body>
<div id="chart"></div>
<script>${plotlyCode}<\/script>
</body></html>`;

    container.innerHTML = "";
    const iframe = document.createElement("iframe");
    iframe.srcdoc = html;
    iframe.style.cssText = "width:100%;height:100%;border:none;border-radius:6px;position:absolute;top:0;left:0";
    container.appendChild(iframe);
}

async function setTradingAlert() {
    const ticker = tradingState.currentTicker;
    const metric = document.getElementById("alert-metric").value;
    const threshold = document.getElementById("alert-threshold").value;
    const direction = document.getElementById("alert-direction").value;

    try {
        const result = await fetchJson("/api/trading/alerts", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ticker, metric, threshold: parseFloat(threshold), direction }),
        });
        loadTradingAlerts();
    } catch (e) {
        console.error("Failed to set alert:", e);
    }
}

async function loadTradingAlerts() {
    try {
        const alerts = await fetchJson("/api/trading/alerts");
        tradingState.alerts = alerts;
        const list = document.getElementById("alert-list");
        if (alerts.length === 0) {
            list.innerHTML = '<div class="empty-state" style="font-size:0.75rem;padding:6px">No alerts set.</div>';
            return;
        }
        list.innerHTML = alerts.map(a => `
            <div class="alert-item ${a.triggered ? 'triggered' : ''}">
                <span>${escapeHtml(a.ticker)} ${a.metric} ${a.direction} ${a.threshold}${a.last_value != null ? ` (now: ${a.last_value.toFixed(4)})` : ''}</span>
                <button class="alert-remove" onclick="removeTradingAlert('${a.alert_id}')">&times;</button>
            </div>
        `).join("");
    } catch (e) {
        console.warn("Failed to load alerts:", e);
    }
}

async function removeTradingAlert(alertId) {
    try {
        await fetch(`/api/trading/alerts/${alertId}`, { method: "DELETE" });
        loadTradingAlerts();
    } catch (e) {
        console.error("Failed to remove alert:", e);
    }
}

async function executeTrade() {
    const ticker = tradingState.currentTicker;
    const side = tradingState.tradeSide;
    const quantity = document.getElementById("trade-quantity").value;
    const orderType = document.getElementById("trade-order-type").value;
    const price = document.getElementById("trade-price").value;
    const resultEl = document.getElementById("trade-result");

    try {
        const result = await fetchJson("/api/trading/order", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ticker, side, quantity: parseFloat(quantity), order_type: orderType, price: price || undefined }),
        });

        if (result.error) {
            resultEl.textContent = result.error;
            resultEl.className = "trade-result error";
        } else {
            resultEl.textContent = result.message || `${side} ${quantity} ${ticker} — ${result.status}`;
            resultEl.className = "trade-result success";
            loadPortfolio();
        }
    } catch (e) {
        resultEl.textContent = `Error: ${e.message}`;
        resultEl.className = "trade-result error";
    }
}

async function loadPortfolio() {
    try {
        const data = await fetchJson("/api/trading/portfolio");
        document.getElementById("port-count").textContent = data.position_count || 0;
        document.getElementById("port-realized").textContent = formatMoney(data.realized_pnl || 0);
        document.getElementById("port-unrealized").textContent = formatMoney(data.unrealized_pnl || 0);

        const realizedEl = document.getElementById("port-realized");
        realizedEl.className = `pcr-value ${(data.realized_pnl || 0) >= 0 ? 'pnl-positive' : 'pnl-negative'}`;
        const unrealizedEl = document.getElementById("port-unrealized");
        unrealizedEl.className = `pcr-value ${(data.unrealized_pnl || 0) >= 0 ? 'pnl-positive' : 'pnl-negative'}`;

        const positionsEl = document.getElementById("portfolio-positions");
        const positions = data.positions || [];
        if (positions.length === 0) {
            positionsEl.innerHTML = '<div class="empty-state" style="font-size:0.75rem;padding:6px">No positions.</div>';
            return;
        }
        positionsEl.innerHTML = `
            <table>
                <thead><tr><th>Ticker</th><th>Qty</th><th>Avg</th><th>Current</th><th>P&L</th></tr></thead>
                <tbody>
                    ${positions.map(p => `
                        <tr>
                            <td>${escapeHtml(p.ticker)}</td>
                            <td>${p.quantity}</td>
                            <td>$${p.avg_price.toFixed(2)}</td>
                            <td>$${p.current_price.toFixed(2)}</td>
                            <td class="${p.unrealized_pnl >= 0 ? 'pnl-positive' : 'pnl-negative'}">
                                $${p.unrealized_pnl.toFixed(2)} (${p.unrealized_pnl_pct.toFixed(1)}%)
                            </td>
                        </tr>
                    `).join("")}
                </tbody>
            </table>
        `;
    } catch (e) {
        console.warn("Failed to load portfolio:", e);
    }
}

function connectTradingStream() {
    if (tradingState.sseSource) return;
    try {
        tradingState.sseSource = new EventSource("/api/trading/stream");
        tradingState.sseSource.onmessage = (event) => {
            const msg = JSON.parse(event.data);
            if (msg.type === "pcr_update") {
                // Auto-update if it's the current ticker
                const d = msg.data;
                if (d.ticker === tradingState.currentTicker) {
                    document.getElementById("pcr-vol-ratio").textContent = d.vol_ratio != null ? d.vol_ratio.toFixed(4) : "—";
                    document.getElementById("pcr-oi-ratio").textContent = d.oi_ratio != null ? d.oi_ratio.toFixed(4) : "—";
                    const badge = document.getElementById("pcr-sentiment");
                    badge.textContent = d.sentiment;
                    badge.className = `sentiment-badge ${d.sentiment}`;
                }
            } else if (msg.type === "alert_triggered") {
                loadTradingAlerts();
                addMessage("info", `Trading Alert: ${msg.data.ticker} ${msg.data.metric} is ${msg.data.current_value?.toFixed(4)} (${msg.data.direction} ${msg.data.threshold})`);
            }
        };
        tradingState.sseSource.onerror = () => {
            tradingState.sseSource.close();
            tradingState.sseSource = null;
            // Reconnect after 5 seconds
            setTimeout(connectTradingStream, 5000);
        };
    } catch (e) {
        console.warn("Failed to connect trading stream:", e);
    }
}

init();
