/* 
 * STRM Sync Dashboard JavaScript Application
 * 提供 SPA 路由、JWT 状态保持、源管理 (CRUD) 交互、全局系统配置更新与 SSE 实时同步日志订阅。
 * 已内置全局运行时报错拦截渲染器与高度防灾机制。
 * @author: hyq
 * @version: 2026-06-23
 */

// ============================================
// 0. 全局异常捕获与屏幕飘窗渲染器 (终极调试后盾)
// ============================================
window.onerror = function (message, source, lineno, colno, error) {
    const errorDiv = document.createElement("div");
    errorDiv.style.position = "fixed";
    errorDiv.style.top = "10px";
    errorDiv.style.left = "50%";
    errorDiv.style.transform = "translateX(-50%)";
    errorDiv.style.background = "#ef4444";
    errorDiv.style.color = "white";
    errorDiv.style.padding = "16px 24px";
    errorDiv.style.borderRadius = "12px";
    errorDiv.style.boxShadow = "0 10px 30px rgba(0,0,0,0.3)";
    errorDiv.style.zIndex = "99999";
    errorDiv.style.fontSize = "13px";
    errorDiv.style.maxWidth = "90%";
    errorDiv.style.wordBreak = "break-all";
    errorDiv.style.fontFamily = "monospace";
    
    errorDiv.innerHTML = `
        <div style="font-weight:bold; margin-bottom:8px; font-size:14px;">⚠️ 浏览器检测到 JavaScript 运行时异常：</div>
        <div><strong>错误原因:</strong> ${message}</div>
        <div><strong>发生位置:</strong> ${source}:${lineno}:${colno}</div>
        ${error && error.stack ? `<pre style="margin-top:8px; font-size:11px; white-space:pre-wrap; background:rgba(0,0,0,0.2); padding:8px; border-radius:6px; max-height:200px; overflow-y:auto;">${error.stack}</pre>` : ''}
        <button onclick="this.parentElement.remove()" style="margin-top:12px; background:white; color:#ef4444; border:none; padding:6px 12px; border-radius:6px; cursor:pointer; font-weight:bold; font-size:11px;">关闭警告</button>
    `;
    document.body.appendChild(errorDiv);
    return false;
};

window.onunhandledrejection = function (event) {
    const reason = event.reason;
    const msg = reason instanceof Error ? reason.message : JSON.stringify(reason);
    const stack = reason instanceof Error && reason.stack ? reason.stack : '';
    
    const errorDiv = document.createElement("div");
    errorDiv.style.position = "fixed";
    errorDiv.style.top = "10px";
    errorDiv.style.left = "50%";
    errorDiv.style.transform = "translateX(-50%)";
    errorDiv.style.background = "#f59e0b";
    errorDiv.style.color = "white";
    errorDiv.style.padding = "16px 24px";
    errorDiv.style.borderRadius = "12px";
    errorDiv.style.boxShadow = "0 10px 30px rgba(0,0,0,0.3)";
    errorDiv.style.zIndex = "99999";
    errorDiv.style.fontSize = "13px";
    errorDiv.style.maxWidth = "90%";
    errorDiv.style.wordBreak = "break-all";
    errorDiv.style.fontFamily = "monospace";
    
    errorDiv.innerHTML = `
        <div style="font-weight:bold; margin-bottom:8px; font-size:14px;">⚠️ 检测到未捕获的异步 Promise 异常：</div>
        <div><strong>报错原因:</strong> ${msg}</div>
        ${stack ? `<pre style="margin-top:8px; font-size:11px; white-space:pre-wrap; background:rgba(0,0,0,0.2); padding:8px; border-radius:6px; max-height:200px; overflow-y:auto;">${stack}</pre>` : ''}
        <button onclick="this.parentElement.remove()" style="margin-top:12px; background:white; color:#f59e0b; border:none; padding:6px 12px; border-radius:6px; cursor:pointer; font-weight:bold; font-size:11px;">关闭警告</button>
    `;
    document.body.appendChild(errorDiv);
};

// ============================================
// 1. 初始化设置 (UI Initialize)
// ============================================
const token = localStorage.getItem("token");
if (!token) {
    window.location.href = "/login";
}

// 全局变量
let currentActiveSection = "dashboard";
let statusInterval = null;
let eventSource = null;
let autoScroll = true;

// DOM 元素引用
const body = document.body;
const sidebarItems = document.querySelectorAll(".sidebar-menu li");
const themeToggleBtn = document.getElementById("themeToggleBtn");
const sidebarToggle = document.querySelector(".sidebar-toggle");
const logoutBtn = document.getElementById("logoutBtn");

// 页面部分 Section
const sections = {
    dashboard: document.getElementById("dashboardSection"),
    sources: document.getElementById("sourcesSection"),
    console: document.getElementById("consoleSection"),
    settings: document.getElementById("settingsSection")
};

// hyq: 2026-06-23 Declare dynamic media/strm root configurations and loadSystemConfigPaths
let gdRootPath = "/mnt";
let strmRootPath = "/mnt/strm";

async function loadSystemConfigPaths() {
    try {
        const res = await apiFetch("/api/system/config-paths");
        if (res && res.ok) {
            const data = await res.json();
            gdRootPath = data.gd_root || "/mnt";
            strmRootPath = data.strm_root || "/mnt/strm";
        }
    } catch (e) {
        console.error("加载安全路径配置异常:", e);
    }
}

// hyq: 2026-06-23 Modify initUI to support dynamic system path configuration loading
/*
function initUI() {
    // 侧边栏折叠记忆状态加载
    const sidebarState = localStorage.getItem("sidebarState");
    if (sidebarState === "collapsed") {
        body.setAttribute("data-sidebar", "collapsed");
    } else {
        body.setAttribute("data-sidebar", "expanded");
    }

    // 主题记忆状态加载
    const savedTheme = localStorage.getItem("themeState");
    const systemDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    if (savedTheme === "dark" || (!savedTheme && systemDark)) {
        setTheme("dark");
    } else {
        setTheme("light");
    }

    // 加载看板数据并启动状态刷新轮询
    loadDashboardData();
    statusInterval = setInterval(loadDashboardData, 4000);
}
*/

async function initUI() {
    // 异步加载动态挂载根路径配置
    await loadSystemConfigPaths();

    // 侧边栏折叠记忆状态加载
    const sidebarState = localStorage.getItem("sidebarState");
    if (sidebarState === "collapsed") {
        body.setAttribute("data-sidebar", "collapsed");
    } else {
        body.setAttribute("data-sidebar", "expanded");
    }

    // 主题记忆状态加载
    const savedTheme = localStorage.getItem("themeState");
    const systemDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    if (savedTheme === "dark" || (!savedTheme && systemDark)) {
        setTheme("dark");
    } else {
        setTheme("light");
    }

    // 加载看板数据并启动状态刷新轮询
    loadDashboardData();
    statusInterval = setInterval(loadDashboardData, 4000);
}

// 主题设置
function setTheme(theme) {
    if (body) body.setAttribute("data-theme", theme);
    localStorage.setItem("themeState", theme);
    if (themeToggleBtn) {
        themeToggleBtn.innerText = theme === "dark" ? "☀️ 切换浅色模式" : "🌗 切换黑暗模式";
    }
}

// 侧边栏菜单切换监听
sidebarItems.forEach(item => {
    item.addEventListener("click", () => {
        const target = item.getAttribute("data-target");
        switchSection(target);
    });
});

// hyq: 2026-06-23 Modify switchSection to support console logs loading when switching to console
/*
// SPA 路由切换 (带空值防崩限制)
function switchSection(target) {
    if (currentActiveSection === target) return;

    // 更新菜单激活态
    sidebarItems.forEach(item => {
        if (item.getAttribute("data-target") === target) {
            item.classList.add("active");
        } else {
            item.classList.remove("active");
        }
    });

    // 隐藏之前的 Section，显示目标的 Section
    const prevSec = sections[currentActiveSection];
    const targetSec = sections[target];
    
    if (prevSec) prevSec.style.display = "none";
    if (targetSec) targetSec.style.display = "block";
    currentActiveSection = target;

    // 动态按需加载数据
    if (target === "dashboard") {
        loadDashboardData();
    } else if (target === "sources") {
        loadSources();
    } else if (target === "settings") {
        loadSettings();
    }
}
*/

// SPA 路由切换 (带空值防崩限制)
function switchSection(target) {
    if (currentActiveSection === target) return;

    // 更新菜单激活态
    sidebarItems.forEach(item => {
        if (item.getAttribute("data-target") === target) {
            item.classList.add("active");
        } else {
            item.classList.remove("active");
        }
    });

    // 隐藏之前的 Section，显示目标的 Section
    const prevSec = sections[currentActiveSection];
    const targetSec = sections[target];
    
    if (prevSec) prevSec.style.display = "none";
    if (targetSec) targetSec.style.display = "block";
    currentActiveSection = target;

    // 动态按需加载数据
    if (target === "dashboard") {
        loadDashboardData();
    } else if (target === "sources") {
        loadSources();
    } else if (target === "settings") {
        loadSettings();
    } else if (target === "console") {
        loadConsoleLogs();
    }
}

// 侧边栏折叠交互
if (sidebarToggle) {
    sidebarToggle.addEventListener("click", () => {
        const isCollapsed = body.getAttribute("data-sidebar") === "collapsed";
        body.setAttribute("data-sidebar", isCollapsed ? "expanded" : "collapsed");
        localStorage.setItem("sidebarState", isCollapsed ? "expanded" : "collapsed");
    });
}

// 主题切换按钮
if (themeToggleBtn) {
    themeToggleBtn.addEventListener("click", () => {
        const currentTheme = body.getAttribute("data-theme") || "light";
        setTheme(currentTheme === "dark" ? "light" : "dark");
    });
}

// 注销退出
if (logoutBtn) {
    logoutBtn.addEventListener("click", () => {
        localStorage.removeItem("token");
        localStorage.removeItem("username");
        window.location.href = "/login";
    });
}

// 通用 Fetch 辅助
async function apiFetch(url, options = {}) {
    options.headers = {
        ...options.headers,
        "Authorization": `Bearer ${token}`
    };
    
    try {
        const response = await fetch(url, options);
        if (response.status === 401) {
            localStorage.removeItem("token");
            window.location.href = "/login";
            return null;
        }
        return response;
    } catch (err) {
        console.error("API请求错误:", err);
        return null;
    }
}

// ============================================
// 2. 状态看板逻辑 (Dashboard Operations)
// ============================================
async function loadDashboardData() {
    try {
        const res = await apiFetch("/api/tasks/status");
        if (!res || !res.ok) return;
        
        const data = await res.json();
        
        // 更新源总数卡片
        const sourcesRes = await apiFetch("/api/sources");
        if (sourcesRes && sourcesRes.ok) {
            const srcData = await sourcesRes.json();
            const el = document.getElementById("statSourceCount");
            if (el) el.innerText = `${srcData.length} 个`;
        }

        // hyq: 2026-06-23 Modify cron dashboard card rendering to support empty/disabled status
        // // 加载系统配置里的 Cron 值，更新看板卡片
        // const settingsRes = await apiFetch("/api/settings");
        // if (settingsRes && settingsRes.ok) {
        //     const cfgData = await settingsRes.json();
        //     const el = document.getElementById("dashCronText");
        //     if (el) el.innerText = cfgData.cron_expression;
        // }
        const settingsRes = await apiFetch("/api/settings");
        if (settingsRes && settingsRes.ok) {
            const cfgData = await settingsRes.json();
            const elText = document.getElementById("dashCronText");
            const elStatus = document.getElementById("dashCronStatus");
            if (elText) {
                elText.innerText = cfgData.cron_expression ? cfgData.cron_expression : "已关闭";
            }
            if (elStatus) {
                if (cfgData.cron_expression && cfgData.cron_expression.trim()) {
                    elStatus.innerText = "等待调度";
                    elStatus.className = "status-badge status-success";
                } else {
                    elStatus.innerText = "已暂停";
                    elStatus.className = "status-badge status-stopped";
                }
            }
        }

        // 运行态更新控制
        const runBtn = document.getElementById("runSyncBtn");
        const runForceBtn = document.getElementById("runSyncForceBtn");
        const stopBtn = document.getElementById("stopSyncBtn");
        const statusTip = document.getElementById("syncStatusTip");

        // hyq: 2026-06-23 Modify stats update logic in loadDashboardData to display last historical task stats when not running
        /*
        if (data.running) {
            if (runBtn) runBtn.disabled = true;
            if (runForceBtn) runForceBtn.disabled = true;
            if (stopBtn) stopBtn.style.display = "inline-flex";
            if (statusTip) {
                statusTip.innerText = "⚡ 同步任务正在多线程执行中...";
                statusTip.style.color = "var(--primary)";
                statusTip.style.display = "block";
            }
            
            // 更新最近状态统计
            if (data.stats) {
                const elParsed = document.getElementById("statParsed");
                const elWritten = document.getElementById("statWritten");
                const elRemoved = document.getElementById("statRemoved");
                
                if (elParsed) elParsed.innerText = data.stats.items_parsed;
                if (elWritten) elWritten.innerText = data.stats.strm_written;
                if (elRemoved) elRemoved.innerText = data.stats.files_removed + data.stats.dirs_removed;
            }

            // 自动连接日志流
            connectLogStream();
        } else {
            if (runBtn) runBtn.disabled = false;
            if (runForceBtn) runForceBtn.disabled = false;
            if (stopBtn) stopBtn.style.display = "none";
            if (statusTip) statusTip.style.display = "none";
            
            // 关闭 SSE 客户端
            if (eventSource) {
                eventSource.close();
                eventSource = null;
                const dot = document.getElementById("consoleStatusDot");
                const txt = document.getElementById("consoleStatusText");
                if (dot) dot.className = "console-dot inactive";
                if (txt) txt.innerText = "已挂起";
            }
        }
        */

        if (data.running) {
            if (runBtn) runBtn.disabled = true;
            if (runForceBtn) runForceBtn.disabled = true;
            if (stopBtn) stopBtn.style.display = "inline-flex";
            if (statusTip) {
                statusTip.innerText = "⚡ 同步任务正在多线程执行中...";
                statusTip.style.color = "var(--primary)";
                statusTip.style.display = "block";
            }
            
            // 更新最近状态统计 (任务运行中，展示实时的任务统计数据)
            if (data.stats) {
                const elParsed = document.getElementById("statParsed");
                const elWritten = document.getElementById("statWritten");
                const elRemoved = document.getElementById("statRemoved");
                const elMeta = document.getElementById("statMetadata");
                
                if (elParsed) elParsed.innerText = data.stats.items_parsed;
                if (elWritten) elWritten.innerText = data.stats.strm_written;
                if (elMeta) elMeta.innerText = data.stats.metadata_synced || 0;
                if (elRemoved) elRemoved.innerText = data.stats.files_removed + data.stats.dirs_removed;
            }

            // 自动连接日志流
            connectLogStream();
        } else {
            if (runBtn) runBtn.disabled = false;
            if (runForceBtn) runForceBtn.disabled = false;
            if (stopBtn) stopBtn.style.display = "none";
            if (statusTip) statusTip.style.display = "none";
            
            // 任务未运行，展示最近一次同步历史的数据统计
            const latestTask = (data.history && data.history.length > 0) ? data.history[0] : null;
            const elParsed = document.getElementById("statParsed");
            const elWritten = document.getElementById("statWritten");
            const elRemoved = document.getElementById("statRemoved");
            const elMeta = document.getElementById("statMetadata");
            
            if (latestTask) {
                if (elParsed) elParsed.innerText = latestTask.items_parsed || 0;
                if (elWritten) elWritten.innerText = latestTask.strm_written || 0;
                if (elMeta) elMeta.innerText = latestTask.metadata_synced || 0;
                if (elRemoved) elRemoved.innerText = (latestTask.files_removed || 0) + (latestTask.dirs_removed || 0);
            } else {
                if (elParsed) elParsed.innerText = 0;
                if (elWritten) elWritten.innerText = 0;
                if (elMeta) elMeta.innerText = 0;
                if (elRemoved) elRemoved.innerText = 0;
            }

            // 关闭 SSE 客户端
            if (eventSource) {
                eventSource.close();
                eventSource = null;
                const dot = document.getElementById("consoleStatusDot");
                const txt = document.getElementById("consoleStatusText");
                if (dot) dot.className = "console-dot inactive";
                if (txt) txt.innerText = "已挂起";
            }
        }

        // 渲染历史列表
        renderHistoryTable(data.history);
    } catch (e) {
        console.error("加载状态看板报错:", e);
    }
}

function renderHistoryTable(history) {
    const tbody = document.getElementById("taskHistoryBody");
    if (!tbody) return;
    
    if (!history || history.length === 0) {
        tbody.innerHTML = `<tr><td colspan="9" style="text-align: center; color: var(--text-muted);">暂无执行记录</td></tr>`;
        return;
    }

    tbody.innerHTML = history.map(t => {
        let triggerText = t.trigger_type === "manual" ? "👤 手动触发" : "⏰ 定时触发";
        if (t.force_update) triggerText += " (强刷)";
        
        const statusClass = `status-${t.status}`;
        const statusZh = {running: "运行中", success: "成功", failed: "失败", stopped: "已终止"}[t.status] || t.status;
        
        const fileRemoved = t.files_removed || 0;
        const dirRemoved = t.dirs_removed || 0;
        const totalRemoved = fileRemoved + dirRemoved;

        const metaSynced = t.metadata_synced || 0;
        return `
            <tr>
                <td>#${t.id}</td>
                <td>${triggerText}</td>
                <td><span class="status-badge ${statusClass}">${statusZh}</span></td>
                <td>${t.items_parsed || 0}</td>
                <td>${t.strm_written || 0} (${metaSynced})</td>
                <td>${totalRemoved} (Dir: ${dirRemoved})</td>
                <td>${t.elapsed_time ? t.elapsed_time.toFixed(2) + 's' : '-'}</td>
                <td>${t.start_time || '-'}</td>
                <td>
                    <button class="btn btn-secondary" style="padding: 4px 8px; font-size:11px;" onclick="downloadLog(${t.id})">
                        📥 下载
                    </button>
                </td>
            </tr>
        `;
    }).join("");
}

// 绑定看板按钮事件
const runSyncBtn = document.getElementById("runSyncBtn");
if (runSyncBtn) runSyncBtn.addEventListener("click", () => triggerSync(false));

const runSyncForceBtn = document.getElementById("runSyncForceBtn");
if (runSyncForceBtn) runSyncForceBtn.addEventListener("click", () => triggerSync(true));

async function triggerSync(force) {
    try {
        const res = await apiFetch(`/api/tasks/run?force=${force}`, { method: "POST" });
        if (res && res.ok) {
            switchSection("console"); 
            loadDashboardData();
        } else if (res) {
            const err = await res.json();
            alert(err.detail || "启动同步失败");
        }
    } catch (e) {
        alert("启动同步失败，发生网络错误");
    }
}

// 终止同步
const stopSyncBtn = document.getElementById("stopSyncBtn");
if (stopSyncBtn) {
    stopSyncBtn.addEventListener("click", async () => {
        if (!confirm("确定要强行中止当前运行中的同步任务吗？")) return;
        const res = await apiFetch("/api/tasks/stop", { method: "POST" });
        if (res && res.ok) {
            loadDashboardData();
        }
    });
}

// 日志下载
function downloadLog(taskId) {
    const url = `/api/tasks/logs/download/${taskId}`;
    window.open(`${url}?token=${token}`, "_blank");
}

// ============================================
// 3. 控制台日志流 (Realtime Console Logger)
// ============================================
const consoleLogsBody = document.getElementById("consoleLogsBody");
const consoleStatusDot = document.getElementById("consoleStatusDot");
const consoleStatusText = document.getElementById("consoleStatusText");

/**
 * 自动回填控制台日志与判断是否需要开启 SSE 日志流
 * @author hyq
 * @version 2026-06-23
 */
async function loadConsoleLogs() {
    try {
        const res = await apiFetch("/api/tasks/status");
        if (!res || !res.ok) return;
        const data = await res.json();
        
        if (data.running) {
            // 正在运行，如果没有建立 SSE 连接，则连接它
            if (!eventSource) {
                if (consoleLogsBody) consoleLogsBody.innerHTML = "";
                connectLogStream();
            }
        } else {
            // 没有运行，如果存在 SSE 连着，先关闭
            if (eventSource) {
                eventSource.close();
                eventSource = null;
                const dot = document.getElementById("consoleStatusDot");
                const txt = document.getElementById("consoleStatusText");
                if (dot) dot.className = "console-dot inactive";
                if (txt) txt.innerText = "已挂起";
            }
            
            // 获取最新完成的任务的日志
            const latestTask = (data.history && data.history.length > 0) ? data.history[0] : null;
            if (latestTask) {
                if (consoleStatusDot) consoleStatusDot.className = "console-dot inactive";
                if (consoleStatusText) consoleStatusText.innerText = "历史日志";
                
                const logRes = await apiFetch(`/api/tasks/logs/text/${latestTask.id}`);
                if (logRes && logRes.ok) {
                    const logData = await logRes.json();
                    if (consoleLogsBody) {
                        consoleLogsBody.innerHTML = "";
                        if (logData.logs && logData.logs.length > 0) {
                            logData.logs.forEach(line => appendLogLine(line));
                        } else {
                            consoleLogsBody.innerHTML = '<div class="log-line log-info">该任务暂无可用日志内容。</div>';
                        }
                    }
                }
            } else {
                if (consoleLogsBody) {
                    consoleLogsBody.innerHTML = '<div class="log-line log-info">暂无执行任务日志。</div>';
                }
            }
        }
    } catch (e) {
        console.error("加载控制台日志异常:", e);
    }
}

function connectLogStream() {
    if (eventSource) return;

    if (consoleStatusDot) consoleStatusDot.className = "console-dot";
    if (consoleStatusText) consoleStatusText.innerText = "传输中...";

    eventSource = new EventSource(`/api/tasks/logs/stream?token=${token}`);
    
    eventSource.onmessage = (event) => {
        appendLogLine(event.data);
    };

    eventSource.onerror = (err) => {
        console.error("SSE 连接失败，尝试重新连接...", err);
        if (consoleStatusDot) consoleStatusDot.className = "console-dot inactive";
        if (consoleStatusText) consoleStatusText.innerText = "重连中";
    };
}

function appendLogLine(text) {
    if (!consoleLogsBody) return;
    
    const lineDiv = document.createElement("div");
    lineDiv.className = "log-line";
    
    if (text.includes("ERROR") || text.includes("WARNING")) {
        lineDiv.classList.add("log-error");
    } else if (text.includes("finished") || text.includes("DONE") || text.includes("BUILD SUCCESS")) {
        lineDiv.classList.add("log-success");
    } else if (text.includes("Rclone Executing")) {
        lineDiv.classList.add("log-info");
    } else if (text.includes("Summary") || text.includes("ALL SOURCES PROCESSED")) {
        lineDiv.classList.add("log-accent");
    }
    
    lineDiv.innerText = text;
    consoleLogsBody.appendChild(lineDiv);
    
    if (autoScroll) {
        consoleLogsBody.scrollTop = consoleLogsBody.scrollHeight;
    }
}

// 清屏
const clearConsoleBtn = document.getElementById("clearConsoleBtn");
if (clearConsoleBtn) {
    clearConsoleBtn.addEventListener("click", () => {
        if (consoleLogsBody) consoleLogsBody.innerHTML = '<div class="log-line log-info">控制台日志已清空。</div>';
    });
}

// 自动滚动开关
const scrollToggleBtn = document.getElementById("scrollToggleBtn");
if (scrollToggleBtn) {
    scrollToggleBtn.addEventListener("click", () => {
        autoScroll = !autoScroll;
        scrollToggleBtn.innerText = autoScroll ? "⬇️ 自动滚动: 开启" : "⏸️ 自动滚动: 关闭";
    });
}

// ============================================
// 4. 同步源 CRUD 管理 (Sources Management)
// ============================================
const sourceGridContainer = document.getElementById("sourceGridContainer");
const sourceModal = document.getElementById("sourceModal");
const sourceForm = document.getElementById("sourceForm");
const modalTitle = document.getElementById("modalTitle");

async function loadSources() {
    try {
        const res = await apiFetch("/api/sources");
        if (!res || !res.ok) return;
        
        const sources = await res.json();
        if (!sourceGridContainer) return;
        
        if (sources.length === 0) {
            sourceGridContainer.innerHTML = `
                <div class="card" style="grid-column: 1/-1; text-align: center; padding: 40px; color: var(--text-muted);">
                    <h3>还没有添加任何同步源</h3>
                    <p style="font-size:13px; margin-top:10px;">点击右上角的“新增同步源”开始创建吧！</p>
                </div>
            `;
            return;
        }

        /*
        // hyq: 2026-06-23 Modify source-card-actions to support single source syncing
        // <div class="source-card-actions">
        //     <button class="btn btn-secondary" style="padding: 6px 12px; font-size:12px;" onclick="openEditModal(${s.id}, '${s.name}', '${s.gd_path}', '${s.strm_path}', '${s.remote_path}')">✏️ 编辑</button>
        //     <button class="btn btn-danger" style="padding: 6px 12px; font-size:12px;" onclick="deleteSource(${s.id}, '${s.name}')">🗑️ 删除</button>
        // </div>
        */
        sourceGridContainer.innerHTML = sources.map(s => {
            const metaBadge = s.sync_metadata !== 0 ? 
                '<span class="status-badge status-success" style="font-size: 10px;">元数据同步: 开启</span>' : 
                '<span class="status-badge status-stopped" style="font-size: 10px;">元数据同步: 关闭</span>';
            return `
                <div class="card source-card">
                    <div class="source-card-title" style="flex-wrap: wrap; gap: 6px;">
                        <h3>${s.name}</h3>
                        <div style="display: flex; gap: 4px;">
                            ${metaBadge}
                            <span class="status-badge status-success" style="font-size: 10px;">激活</span>
                        </div>
                    </div>
                    
                    <div class="source-path-item">
                        <strong>谷歌云盘挂载路径 (GD)</strong>
                        <span>${s.gd_path}</span>
                    </div>
                    <div class="source-path-item">
                        <strong>本地 STRM 目录 (STRM)</strong>
                        <span>${s.strm_path}</span>
                    </div>
                    <div class="source-path-item">
                        <strong>rclone 云盘映射指令 (CMD)</strong>
                        <span>${s.remote_path}</span>
                    </div>
                    
                    <div class="source-card-actions" style="display: flex; gap: 6px; flex-wrap: wrap;">
                        <button class="btn btn-primary" style="padding: 6px 10px; font-size:12px; flex: 1; min-width: 70px;" onclick="runSingleSync(${s.id}, false)">🚀 同步</button>
                        <button class="btn btn-secondary" style="padding: 6px 10px; font-size:12px; flex: 1; min-width: 70px;" onclick="runSingleSync(${s.id}, true)">⚡ 强刷</button>
                        <button class="btn btn-secondary" style="padding: 6px 10px; font-size:12px;" onclick="openEditModal(${s.id}, '${s.name}', '${s.gd_path}', '${s.strm_path}', '${s.remote_path}', ${s.sync_metadata})">✏️ 编辑</button>
                        <button class="btn btn-danger" style="padding: 6px 10px; font-size:12px;" onclick="deleteSource(${s.id}, '${s.name}')">🗑️ 删除</button>
                    </div>
                </div>
            `;
        }).join("");
    } catch (e) {
        console.error("加载同步源列表失败:", e);
    }
}

// 弹窗关闭事件绑定
const modalCloseBtn = document.getElementById("modalCloseBtn");
if (modalCloseBtn) modalCloseBtn.addEventListener("click", closeModal);

const modalCancelBtn = document.getElementById("modalCancelBtn");
if (modalCancelBtn) modalCancelBtn.addEventListener("click", closeModal);

// ============================================
// 5. 本地目录级联选择器设计 (Infinite Cascading Selector)
// ============================================
class CascadingSelector {
    constructor(containerId, rootPath, onPathChange) {
        this.container = document.getElementById(containerId);
        this.rootPath = rootPath; 
        this.onPathChange = onPathChange; 
        this.selects = []; 
    }
    
    async init(initialPath = "") {
        if (!this.container) return;
        this.container.innerHTML = "";
        this.selects = [];
        
        if (initialPath) {
            await this.loadPathRecursive(initialPath);
        } else {
            await this.loadLevel(this.rootPath);
        }
    }
    
    async loadLevel(parentPath) {
        if (!this.container) return null;
        const subdirs = await getSubdirs(parentPath);
        if (subdirs.length === 0) {
            return null; 
        }
        
        const select = document.createElement("select");
        select.className = "form-control";
        select.style.fontSize = "12px";
        select.style.flex = "1";
        select.style.minWidth = "120px";
        select.style.padding = "6px 12px";
        select.style.cursor = "pointer";
        select.style.marginTop = "4px";
        
        const levelNum = this.selects.length + 1;
        select.innerHTML = `<option value="">-- 选择 ${levelNum} 级子目录 --</option>`;
        subdirs.forEach(item => {
            const opt = document.createElement("option");
            opt.value = item;
            opt.innerText = item;
            select.appendChild(opt);
        });
        
        this.container.appendChild(select);
        this.selects.push(select);
        
        select.addEventListener("change", async () => {
            const idx = this.selects.indexOf(select);
            while (this.selects.length > idx + 1) {
                const popped = this.selects.pop();
                if (popped) popped.remove();
            }
            
            const currentPath = this.getCurrentPath();
            this.onPathChange(currentPath);
            
            if (select.value) {
                await this.loadLevel(currentPath);
            }
        });
        
        return select;
    }
    
    getCurrentPath() {
        const parts = this.selects.map(s => s.value).filter(v => v !== "");
        if (parts.length === 0) {
            return this.rootPath;
        }
        return this.rootPath + "/" + parts.join("/");
    }
    
    // hyq: 2026-06-23 Modify for loadPathRecursive robustness
    // async loadPathRecursive(targetPath) {
    //     let relative = "";
    //     if (targetPath.startsWith(this.rootPath)) {
    //         relative = targetPath.substring(this.rootPath.length);
    //     }
    //     if (relative.startsWith("/")) {
    //         relative = relative.substring(1);
    //     }
    //     
    //     const parts = relative ? relative.split("/") : [];
    //     let currentParent = this.rootPath;
    //     
    //     for (let i = 0; i <= parts.length; i++) {
    //         const select = await this.loadLevel(currentParent);
    //         if (!select) break;
    //         
    //         const targetVal = parts[i];
    //         if (targetVal) {
    //             select.value = targetVal;
    //             currentParent = currentParent + "/" + targetVal;
    //         } else {
    //             break;
    //         }
    //     }
    // }

    async loadPathRecursive(targetPath) {
        if (!targetPath || typeof targetPath !== "string") {
            await this.loadLevel(this.rootPath);
            return;
        }
        
        let relative = "";
        if (targetPath.startsWith(this.rootPath)) {
            relative = targetPath.substring(this.rootPath.length);
        }
        if (relative.startsWith("/")) {
            relative = relative.substring(1);
        }
        
        const parts = relative ? relative.split("/") : [];
        let currentParent = this.rootPath;
        
        for (let i = 0; i <= parts.length; i++) {
            const select = await this.loadLevel(currentParent);
            if (!select) break;
            
            const targetVal = parts[i];
            if (targetVal) {
                select.value = targetVal;
                currentParent = currentParent + "/" + targetVal;
            } else {
                break;
            }
        }
    }
}

// 绑定 DOM 引用
const testRcloneBtn = document.getElementById("testRcloneBtn");
const testRcloneResult = document.getElementById("testRcloneResult");
const sourceGdInput = document.getElementById("sourceGd");
const sourceStrmInput = document.getElementById("sourceStrm");

async function getSubdirs(parentPath) {
    try {
        const res = await apiFetch(`/api/system/dirs?parent_path=${encodeURIComponent(parentPath)}`);
        if (!res || !res.ok) return [];
        return await res.json();
    } catch (e) {
        console.error("加载子目录失败:", e);
        return [];
    }
}

// 实例化选择器
// hyq: 2026-06-23 Modify gdSelector, strmSelector and handleGdPathChange to adapt dynamic path prefixes
// const gdSelector = new CascadingSelector("gdSelectContainer", "/mnt", (path) => {
//     if (sourceGdInput) {
//         sourceGdInput.value = path;
//         handleGdPathChange(path);
//     }
// });
// 
// const strmSelector = new CascadingSelector("strmSelectContainer", "/mnt/strm", (path) => {
//     if (sourceStrmInput) {
//         sourceStrmInput.value = path;
//     }
// });
// 
// function handleGdPathChange(gdPath) {
//     gdPath = gdPath.trim();
//     if (!gdPath) return;
//     
//     let relative = "";
//     const match = gdPath.match(/[\\/]mnt[\\/](.+)$/i);
//     if (match) {
//         relative = match[1].replace(/\\/g, "/"); 
//     } else {
//         relative = gdPath.startsWith("/") ? gdPath.substring(1) : gdPath;
//     }
//     
//     if (!relative) return;
//     
//     const parts = relative.split("/");
//     const remoteName = parts[0];
//     const pathRest = parts.slice(1).join("/");
//     
//     const cmdInput = document.getElementById("sourceCmd");
//     if (remoteName && cmdInput) {
//         cmdInput.value = `${remoteName}:/${pathRest}`;
//     }
//     
//     const isEdit = document.getElementById("sourceId").value !== "";
//     if (!isEdit) {
//         const lastPart = parts[parts.length - 1];
//         if (lastPart) {
//             const cleanName = lastPart.replace(/[^a-zA-Z0-9_-]/g, "");
//             const nameInput = document.getElementById("sourceName");
//             if (nameInput) nameInput.value = cleanName;
//         }
//     }
// }

const gdSelector = new CascadingSelector("gdSelectContainer", gdRootPath, (path) => {
    if (sourceGdInput) {
        sourceGdInput.value = path;
        handleGdPathChange(path);
    }
});

const strmSelector = new CascadingSelector("strmSelectContainer", strmRootPath, (path) => {
    if (sourceStrmInput) {
        sourceStrmInput.value = path;
    }
});

function handleGdPathChange(gdPath) {
    gdPath = gdPath.trim();
    if (!gdPath) return;
    
    let relative = "";
    // 根据动态获取的 gdRootPath 智能剥离前缀，若不匹配则降级回正则探测
    if (gdPath.startsWith(gdRootPath)) {
        relative = gdPath.substring(gdRootPath.length);
    } else {
        const match = gdPath.match(/[\\/][^\\/]+[\\/](.+)$/i);
        relative = match ? match[1] : gdPath;
    }
    
    if (relative.startsWith("/")) {
        relative = relative.substring(1);
    }
    relative = relative.replace(/\\/g, "/");
    
    if (!relative) return;
    
    const parts = relative.split("/");
    const remoteName = parts[0];
    const pathRest = parts.slice(1).join("/");
    
    const cmdInput = document.getElementById("sourceCmd");
    if (remoteName && cmdInput) {
        cmdInput.value = `${remoteName}:/${pathRest}`;
    }
    
    const isEdit = document.getElementById("sourceId").value !== "";
    if (!isEdit) {
        const lastPart = parts[parts.length - 1];
        if (lastPart) {
            const cleanName = lastPart.replace(/[^a-zA-Z0-9_-]/g, "");
            const nameInput = document.getElementById("sourceName");
            if (nameInput) nameInput.value = cleanName;
        }
    }
}

if (sourceGdInput) {
    sourceGdInput.addEventListener("input", (e) => {
        handleGdPathChange(e.target.value);
    });
}

// ----------------- Rclone 连通性测试 -----------------
if (testRcloneBtn) {
    testRcloneBtn.addEventListener("click", async () => {
        const cmdInput = document.getElementById("sourceCmd");
        const path = cmdInput ? cmdInput.value.trim() : "";
        if (!path) {
            alert("请先选择或输入配置路径（SOURCE_CMD）！");
            return;
        }
        
        if (testRcloneResult) {
            testRcloneResult.style.display = "block";
            testRcloneResult.style.color = "var(--text-muted)";
            testRcloneResult.innerText = "⏳ 正在进行连接测试，请稍候...";
        }
        testRcloneBtn.disabled = true;
        
        try {
            const res = await apiFetch(`/api/rclone/test?path=${encodeURIComponent(path)}`, {
                method: "POST"
            });
            
            if (!res || !testRcloneResult) {
                if (testRcloneResult) {
                    testRcloneResult.style.color = "var(--danger)";
                    testRcloneResult.innerText = "❌ 无法访问后端测试服务";
                }
                return;
            }
            
            const data = await res.json();
            if (res.ok) {
                testRcloneResult.style.color = "var(--success)";
                let preview = "";
                // hyq: 2026-06-23 Modify preview text to explicitly declare limit of 5 items
                // if (data.preview && data.preview.length > 0) {
                //     preview = `\n网盘内容预览:\n${data.preview.map(f => " 📄 " + f).join("\n")}`;
                // } else {
                //     preview = "\n(检测成功，但目录内容为空)";
                // }
                // testRcloneResult.innerText = `✅ 连接测试成功！${preview}`;
                if (data.preview && data.preview.length > 0) {
                    preview = `\n网盘内容预览 (仅随机预览前 5 项):\n${data.preview.map(f => " 📄 " + f).join("\n")}`;
                } else {
                    preview = "\n(检测成功，但目录内容为空)";
                }
                testRcloneResult.innerText = `✅ 连接测试成功！${preview}`;
            } else {
                testRcloneResult.style.color = "var(--danger)";
                testRcloneResult.innerText = `❌ 测试失败: ${data.detail || "未知报错"}`;
            }
        } catch (err) {
            if (testRcloneResult) {
                testRcloneResult.style.color = "var(--danger)";
                testRcloneResult.innerText = "❌ 发生网络通信错误";
            }
        } finally {
            testRcloneBtn.disabled = false;
        }
    });
}

// ----------------- 弹窗控制与事件绑定 -----------------
// hyq: 2026-06-23 Modify openAddModal and openEditModal to assign dynamic rootPath before initialization
// async function openAddModal() {
//     if (modalTitle) modalTitle.innerText = "新增同步源";
//     if (sourceForm) sourceForm.reset();
//     
//     const sid = document.getElementById("sourceId");
//     if (sid) sid.value = "";
//     
//     const sname = document.getElementById("sourceName");
//     if (sname) sname.readOnly = false;
//     
//     if (testRcloneResult) testRcloneResult.style.display = "none";
//     if (sourceModal) sourceModal.classList.add("show");
//     
//     await gdSelector.init();
//     await strmSelector.init();
// }
// 
// window.openEditModal = async function(id, name, gd, strm, remote) {
//     if (modalTitle) modalTitle.innerText = "编辑同步源";
//     
//     const sid = document.getElementById("sourceId");
//     if (sid) sid.value = id;
//     
//     const sname = document.getElementById("sourceName");
//     if (sname) {
//         sname.value = name;
//         sname.readOnly = true; 
//     }
//     
//     if (sourceGdInput) sourceGdInput.value = gd;
//     if (sourceStrmInput) sourceStrmInput.value = strm;
//     
//     const scmd = document.getElementById("sourceCmd");
//     if (scmd) scmd.value = remote;
//     
//     if (testRcloneResult) testRcloneResult.style.display = "none";
//     if (sourceModal) sourceModal.classList.add("show");
//     
//     await gdSelector.init(gd);
//     await strmSelector.init(strm);
// };

async function openAddModal() {
    if (modalTitle) modalTitle.innerText = "新增同步源";
    if (sourceForm) sourceForm.reset();
    
    const sid = document.getElementById("sourceId");
    if (sid) sid.value = "";
    
    const sname = document.getElementById("sourceName");
    if (sname) sname.readOnly = false;
    
    const sSyncMeta = document.getElementById("sourceSyncMetadata");
    if (sSyncMeta) sSyncMeta.checked = true; // 默认开启
    
    if (testRcloneResult) testRcloneResult.style.display = "none";
    if (sourceModal) sourceModal.classList.add("show");
    
    // 应用动态读取的安全路径
    gdSelector.rootPath = gdRootPath;
    strmSelector.rootPath = strmRootPath;
    
    await gdSelector.init();
    await strmSelector.init();
}

window.openEditModal = async function(id, name, gd, strm, remote, sync_metadata) {
    if (modalTitle) modalTitle.innerText = "编辑同步源";
    
    const sid = document.getElementById("sourceId");
    if (sid) sid.value = id;
    
    const sname = document.getElementById("sourceName");
    if (sname) {
        sname.value = name;
        sname.readOnly = true; 
    }
    
    if (sourceGdInput) sourceGdInput.value = gd;
    if (sourceStrmInput) sourceStrmInput.value = strm;
    
    const scmd = document.getElementById("sourceCmd");
    if (scmd) scmd.value = remote;
    
    const sSyncMeta = document.getElementById("sourceSyncMetadata");
    if (sSyncMeta) sSyncMeta.checked = sync_metadata !== 0; // 默认开启，如果没提供也是 true 
    
    if (testRcloneResult) testRcloneResult.style.display = "none";
    if (sourceModal) sourceModal.classList.add("show");
    
    // 应用动态读取的安全路径
    gdSelector.rootPath = gdRootPath;
    strmSelector.rootPath = strmRootPath;
    
    await gdSelector.init(gd);
    await strmSelector.init(strm);
};

function closeModal() {
    if (sourceModal) sourceModal.classList.remove("show");
}

const addSourceBtn = document.getElementById("addSourceBtn");
if (addSourceBtn) addSourceBtn.addEventListener("click", openAddModal);

// 表单提交（新增/编辑）
if (sourceForm) {
    sourceForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        
        const id = document.getElementById("sourceId").value;
        const name = document.getElementById("sourceName").value;
        const gd_path = sourceGdInput ? sourceGdInput.value : "";
        const strm_path = sourceStrmInput ? sourceStrmInput.value : "";
        
        const scmd = document.getElementById("sourceCmd");
        const remote_path = scmd ? scmd.value : "";

        const sSyncMeta = document.getElementById("sourceSyncMetadata");
        const sync_metadata = sSyncMeta ? (sSyncMeta.checked ? 1 : 0) : 1;

        const payload = { name, gd_path, strm_path, remote_path, sync_metadata };
        
        try {
            let res;
            if (id) {
                res = await apiFetch(`/api/sources/${id}`, {
                    method: "PUT",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload)
                });
            } else {
                res = await apiFetch("/api/sources", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload)
                });
            }

            if (res && res.ok) {
                closeModal();
                loadSources();
            } else if (res) {
                const data = await res.json();
                alert(data.detail || "操作同步源失败");
            }
        } catch (err) {
            alert("提交表单异常");
        }
    });
}

// 删除源
window.deleteSource = async function(id, name) {
    if (!confirm(`确定要删除同步源 [${name}] 吗？\n该操作仅删除前端映射，不会清空已生成的 strm 文件。`)) return;
    
    try {
        const res = await apiFetch(`/api/sources/${id}`, { method: "DELETE" });
        if (res && res.ok) {
            loadSources();
        }
    } catch (e) {
        alert("删除失败，网络错误");
    }
};

// hyq: 2026-06-23 Add runSingleSync to support single sync source triggering
window.runSingleSync = async function(sourceId, force) {
    if (!confirm("确定要为该数据源单独启动同步任务吗？" + (force ? "\n将强刷此源的 rclone 缓存。" : ""))) return;
    
    try {
        const res = await apiFetch(`/api/tasks/run?force=${force}&source_id=${sourceId}`, { method: "POST" });
        if (res && res.ok) {
            switchSection("console"); // 自动跳转至日志控制台查看输出
            loadDashboardData();
        } else if (res) {
            const err = await res.json();
            alert(err.detail || "启动单源同步失败");
        }
    } catch (e) {
        alert("启动单源同步异常");
    }
};

// ============================================
// 6. 系统性能设置与密码管理 (Settings Operations)
// ============================================
const settingsForm = document.getElementById("settingsForm");
const passwordForm = document.getElementById("passwordForm");

async function loadSettings() {
    try {
        const res = await apiFetch("/api/settings");
        if (!res || !res.ok) return;
        
        const data = await res.json();
        
        const elWorker = document.getElementById("workerConcurrency");
        const elBatch = document.getElementById("batchWriteSize");
        const elSrc = document.getElementById("sourceConcurrency");
        const elCron = document.getElementById("cronExpression");
        const elMeta = document.getElementById("metadataTypes");
        
        if (elWorker) elWorker.value = data.worker_concurrency;
        if (elBatch) elBatch.value = data.batch_write_size;
        if (elSrc) elSrc.value = data.source_concurrency;
        if (elCron) elCron.value = data.cron_expression;
        if (elMeta) elMeta.value = data.metadata_types || "";
    } catch (e) {
        console.error("加载性能配置失败:", e);
    }
}

if (settingsForm) {
    settingsForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        
        const elWorker = document.getElementById("workerConcurrency");
        const elBatch = document.getElementById("batchWriteSize");
        const elSrc = document.getElementById("sourceConcurrency");
        const elCron = document.getElementById("cronExpression");
        const elMeta = document.getElementById("metadataTypes");
        
        const payload = {
            worker_concurrency: elWorker ? parseInt(elWorker.value) : 16,
            batch_write_size: elBatch ? parseInt(elBatch.value) : 1000,
            source_concurrency: elSrc ? parseInt(elSrc.value) : 5,
            cron_expression: elCron ? elCron.value : "",
            metadata_types: elMeta ? elMeta.value : "srt,ass,jpg,png,nfo,mp3,txt"
        };

        try {
            const res = await apiFetch("/api/settings", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });

            if (res && res.ok) {
                alert("系统配置保存成功！定时引擎已重新挂载。");
                loadSettings();
            } else if (res) {
                const data = await res.json();
                alert(data.detail || "性能配置更新失败");
            }
        } catch (e) {
            alert("提交性能配置异常");
        }
    });
}

if (passwordForm) {
    passwordForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        
        const old_password = document.getElementById("oldPassword").value;
        const new_password = document.getElementById("newPassword").value;
        const confirm_password = document.getElementById("confirmPassword").value;

        if (new_password !== confirm_password) {
            alert("两次输入的新密码不一致！");
            return;
        }

        try {
            const res = await apiFetch("/api/auth/password", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ old_password, new_password })
            });

            if (res && res.ok) {
                alert("密码更新成功！请记住新密码。");
                passwordForm.reset();
            } else if (res) {
                const data = await res.json();
                alert(data.detail || "原密码校验不通过，修改失败。");
            }
        } catch (e) {
            alert("修改密码异常");
        }
    });
}

// ============================================
// 7. 执行挂载
// ============================================
initUI();
