/**
 * DocuAgent Desktop Application Controller
 * Professional, human-designed 3-column desktop document management interface.
 */

const API_BASE = (typeof window !== "undefined" && window.location && window.location.protocol === "file:") ? "http://127.0.0.1:8000" : "";

const state = {
    currentFolder: null,
    totalDocuments: 0,
    classificationPreview: [],
    currentTree: null,
    proposedTree: null,
    availableCategories: [],
    selectedItem: null,
    pendingApprovalToken: null,
    canUndo: false,
    activeNav: "viewClassification"
};

// ============================================================================
// Initialization
// ============================================================================
document.addEventListener("DOMContentLoaded", () => {
    initNavigation();
    initFolderControls();
    initViewToggles();
    initInspectorControls();
    initApprovalFlow();
    initLedger();
    initAuditLog();
    initChatDock();
    initModalUtilities();
    checkInitialStatus();
});

async function checkInitialStatus() {
    try {
        const res = await fetch(`${API_BASE}/api/status`);
        const data = await res.json();
        if (data.current_folder) {
            setFolderDisplay(data.current_folder);
            document.getElementById("folderPathInput").value = data.current_folder;
        }
        state.canUndo = data.can_undo;
        updateUndoButton();
    } catch (e) {
        console.error("Status check failed:", e);
    }
}

// ============================================================================
// Navigation Sidebar
// ============================================================================
function initNavigation() {
    const navItems = document.querySelectorAll(".nav-item");
    navItems.forEach(item => {
        item.addEventListener("click", () => {
            const targetView = item.getAttribute("data-view");
            switchView(targetView);
        });
    });
}

function switchView(viewId) {
    state.activeNav = viewId;
    document.querySelectorAll(".nav-item").forEach(el => el.classList.remove("active"));
    document.querySelectorAll(".workspace-view").forEach(el => el.classList.remove("active"));

    const targetNav = document.querySelector(`.nav-item[data-view="${viewId}"]`);
    const targetView = document.getElementById(viewId);

    if (targetNav) targetNav.classList.add("active");
    if (targetView) targetView.classList.add("active");

    if (viewId === "viewLedger") loadLedgerData();
    if (viewId === "viewAudit") loadAuditLogs();
    if (viewId === "viewRelated") renderRelatedMatrix();
    if (viewId === "viewOverview") updateOverviewStats();
}

// ============================================================================
// Folder Path Controls & Native Browse
// ============================================================================
function initFolderControls() {
    const pathInput = document.getElementById("folderPathInput");
    const btnValidate = document.getElementById("btnValidatePath");
    const btnLoad = document.getElementById("btnLoadFolder");
    const btnBrowse = document.getElementById("btnBrowseFolder");
    const btnSample = document.getElementById("btnLoadSample");

    // Hide error banner immediately as soon as user types or modifies path
    pathInput.addEventListener("input", () => {
        hideFeedback();
    });

    // Automatically strip surrounding quotes if user used Windows "Copy as path"
    pathInput.addEventListener("paste", () => {
        hideFeedback();
        setTimeout(() => {
            const clean = pathInput.value.trim().replace(/^["']+|["']+$/g, '');
            pathInput.value = clean;
        }, 10);
    });

    pathInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            btnValidate.click();
        }
    });

    // 1. Validate Path
    btnValidate.addEventListener("click", async () => {
        hideFeedback();
        const path = pathInput.value.trim().replace(/^["']+|["']+$/g, '');
        pathInput.value = path;

        if (!path) {
            showFeedback("Please enter a folder path to validate.", "error");
            return;
        }

        btnValidate.disabled = true;
        btnValidate.textContent = "Validating...";
        try {
            const res = await fetch(`${API_BASE}/api/folder/validate`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ folder_path: path })
            });
            const data = await res.json();
            if (data.valid) {
                if (data.folder_path) {
                    pathInput.value = data.folder_path;
                }
                showFeedback(data.message, "success");
            } else {
                showFeedback(data.error || "Validation failed.", "error");
            }
        } catch (e) {
            showFeedback(`Error validating path: ${e.message}`, "error");
        } finally {
            btnValidate.disabled = false;
            btnValidate.textContent = "Validate Path";
        }
    });

    // 2. Load Folder
    btnLoad.addEventListener("click", async () => {
        hideFeedback();
        const path = pathInput.value.trim().replace(/^["']+|["']+$/g, '');
        pathInput.value = path;

        if (!path) {
            showFeedback("Enter a folder path before loading.", "error");
            return;
        }
        await triggerScan(path);
    });

    // 3. Browse Folder (Opens Visual Folder Browser & Quick Navigator)
    btnBrowse.addEventListener("click", () => {
        hideFeedback();
        openFolderBrowserModal(pathInput.value.trim() || state.currentFolder || "");
    });

    // 4. Sample Folder
    btnSample.addEventListener("click", async () => {
        hideFeedback();
        btnSample.disabled = true;
        setWorkflowStatus("Loading sample...");
        try {
            const res = await fetch(`${API_BASE}/api/folder/generate-sample`, { method: "POST" });
            const data = await res.json();
            pathInput.value = data.folder_path;
            showFeedback("Sample College_Documents loaded successfully.", "success");
            handleScanSuccess(data);
            showToast("Sample dataset loaded and analyzed in read-only mode.");
        } catch (e) {
            showToast(`Failed to load sample: ${e.message}`, "error");
        } finally {
            btnSample.disabled = false;
        }
    });

    // Reset button
    document.getElementById("btnResetPreview").addEventListener("click", async () => {
        try {
            const res = await fetch(`${API_BASE}/api/preview/reset`, { method: "POST" });
            const data = await res.json();
            if (data.success) {
                state.classificationPreview = data.classification_preview;
                state.proposedTree = data.proposed_tree;
                renderClassificationTable();
                renderProposedTree();
                if (state.selectedItem) {
                    const refreshed = state.classificationPreview.find(i => i.file_name === state.selectedItem.file_name);
                    if (refreshed) populateInspector(refreshed);
                }
                showToast("All manual category edits reset to AI suggestions.");
            }
        } catch (e) {
            showToast("Failed to reset preview.", "error");
        }
    });
}

let feedbackTimer = null;

function showFeedback(message, type) {
    const el = document.getElementById("validationFeedback");
    if (!el) return;
    if (feedbackTimer) clearTimeout(feedbackTimer);

    el.style.display = "flex";
    el.className = `validation-message ${type}`;
    el.innerHTML = `
        <span class="validation-message-text">${message}</span>
        <button class="validation-close-btn" title="Dismiss" onclick="hideFeedback()">&times;</button>
    `;

    // Auto-dismiss success message after 5 seconds
    if (type === "success") {
        feedbackTimer = setTimeout(() => {
            hideFeedback();
        }, 5000);
    }
}

function hideFeedback() {
    const el = document.getElementById("validationFeedback");
    if (el) {
        el.style.display = "none";
        el.innerHTML = "";
    }
    if (feedbackTimer) {
        clearTimeout(feedbackTimer);
        feedbackTimer = null;
    }
}
window.hideFeedback = hideFeedback;

function setFolderDisplay(path) {
    state.currentFolder = path;
    const txt = document.getElementById("activePathText");
    if (txt) {
        txt.textContent = path;
        txt.title = path;
    }
    const input = document.getElementById("folderPathInput");
    if (input && path) {
        input.value = path;
    }
}

function setWorkflowStatus(status) {
    const badge = document.getElementById("workflowStatusBadge");
    const sidebarText = document.getElementById("sidebarStatusText");
    if (badge) badge.textContent = status;
    if (sidebarText) sidebarText.textContent = status;
}

async function triggerScan(folderPath) {
    setWorkflowStatus("Scanning...");
    showToast(`Scanning '${folderPath}' in read-only mode...`);
    try {
        const res = await fetch(`${API_BASE}/api/folder/scan`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ folder_path: folderPath })
        });
        const data = await res.json();
        if (!res.ok) {
            const errMsg = typeof data.detail === "string" ? data.detail : (data.detail ? JSON.stringify(data.detail) : "Scan failed");
            throw new Error(errMsg);
        }
        handleScanSuccess(data);
        showToast(`Analyzed ${data.total_documents} documents in read-only mode.`);
    } catch (e) {
        let msg = e.message;
        if (msg === "Failed to fetch") {
            msg = "Render server is waking up (cold boot). Please wait ~30 seconds and retry.";
        }
        showToast(msg, "error");
        setWorkflowStatus("Failed");
    }
}

function handleScanSuccess(data) {
    hideFeedback();
    setFolderDisplay(data.folder_path);
    state.totalDocuments = data.total_documents;
    state.currentTree = data.current_tree;
    state.proposedTree = data.proposed_tree;
    state.classificationPreview = data.classification_preview;
    state.availableCategories = data.available_categories || [];

    document.getElementById("navCounterBadge").textContent = data.total_documents;
    document.getElementById("btnApproveOrganize").disabled = data.total_documents === 0;

    // Check if review is required on any items
    const needsReviewCount = state.classificationPreview.filter(i => i.needs_review).length;
    if (needsReviewCount > 0) {
        setWorkflowStatus("Review Required");
    } else {
        setWorkflowStatus("Awaiting Approval");
    }

    renderClassificationTable();
    renderProposedTree();
    populateCategoryDropdown();

    // Select first document by default
    if (state.classificationPreview.length > 0) {
        selectDocument(state.classificationPreview[0]);
    }

    // Switch view to classification
    switchView("viewClassification");
}

// ============================================================================
// View Toggles (Table View vs Proposed Tree)
// ============================================================================
function initViewToggles() {
    const btnTable = document.getElementById("btnToggleTableView");
    const btnTree = document.getElementById("btnToggleTreeView");
    const tableWrap = document.getElementById("classificationTableWrapper");
    const treeWrap = document.getElementById("proposedTreeWrapper");

    btnTable.addEventListener("click", () => {
        btnTable.classList.add("active");
        btnTree.classList.remove("active");
        tableWrap.style.display = "block";
        treeWrap.style.display = "none";
    });

    btnTree.addEventListener("click", () => {
        btnTree.classList.add("active");
        btnTable.classList.remove("active");
        tableWrap.style.display = "none";
        treeWrap.style.display = "block";
        renderProposedTree();
    });
}

// ============================================================================
// Classification Table Renderer
// ============================================================================
function renderClassificationTable() {
    const tbody = document.getElementById("classificationTableBody");
    tbody.innerHTML = "";

    if (!state.classificationPreview || state.classificationPreview.length === 0) {
        tbody.innerHTML = `
            <tr class="empty-state-row">
                <td colspan="6">
                    <div class="table-empty-state">
                        <p class="empty-title">No documents scanned yet</p>
                        <p class="empty-desc">Enter a folder path above and click <strong>Load Folder</strong>, or click <strong>Browse Folder</strong>.</p>
                    </div>
                </td>
            </tr>
        `;
        return;
    }

    state.classificationPreview.forEach(item => {
        const tr = document.createElement("tr");
        if (state.selectedItem && state.selectedItem.file_name === item.file_name) {
            tr.classList.add("selected");
        }

        const ext = item.extension.replace(".", "") || "txt";
        const confPercent = Math.round(item.confidence_score * 100);

        tr.innerHTML = `
            <td>
                <div class="file-row-name">
                    <span class="type-pill">${ext}</span>
                    <span title="${item.file_name}">${item.file_name}</span>
                </div>
            </td>
            <td><span class="type-pill">${ext.toUpperCase()}</span></td>
            <td>
                <span class="category-badge ${item.is_user_edited ? 'edited' : ''}">
                    ${item.category}
                </span>
                ${item.needs_review ? `<span style="font-size:0.68rem; color:var(--amber-warning); margin-left:4px;">(Review)</span>` : ''}
            </td>
            <td>
                <span class="font-mono text-xs">${confPercent}%</span>
            </td>
            <td>
                <span class="dest-code">/${item.proposed_subfolder}/</span>
            </td>
            <td style="text-align: right;">
                <button class="btn btn-secondary btn-sm" onclick="event.stopPropagation(); quickSelectAndEdit('${encodeURIComponent(item.file_name)}')">
                    Edit Category
                </button>
            </td>
        `;

        tr.addEventListener("click", () => {
            selectDocument(item);
        });

        tbody.appendChild(tr);
    });
}

window.quickSelectAndEdit = function(encodedFileName) {
    const fn = decodeURIComponent(encodedFileName);
    const item = state.classificationPreview.find(i => i.file_name === fn);
    if (item) {
        selectDocument(item);
        document.getElementById("detailCategorySelect").focus();
    }
};

// ============================================================================
// Proposed Folder Tree Renderer
// ============================================================================
function renderProposedTree() {
    const container = document.getElementById("treeViewContainer");
    if (!state.proposedTree) {
        container.innerHTML = `<div class="tree-empty-notice">No folder loaded.</div>`;
        return;
    }

    container.innerHTML = "";
    const rootEl = document.createElement("div");
    rootEl.innerHTML = `<div class="tree-folder-row">&boxdr; <strong>${state.proposedTree.name}</strong> (Proposed Root)</div>`;

    if (state.proposedTree.children) {
        state.proposedTree.children.forEach(subfolder => {
            const subRow = document.createElement("div");
            subRow.style.marginLeft = "16px";
            subRow.innerHTML = `<div class="tree-folder-row">&boxur; <strong>${subfolder.name}/</strong> <span style="font-size:0.7rem; color:var(--text-dim);">(${subfolder.file_count} files)</span></div>`;

            if (subfolder.files) {
                subfolder.files.forEach(f => {
                    const fRow = document.createElement("div");
                    fRow.className = "tree-file-row";
                    fRow.innerHTML = `&bullet; ${f.name}`;
                    subRow.appendChild(fRow);
                });
            }
            rootEl.appendChild(subRow);
        });
    }
    container.appendChild(rootEl);
}

// ============================================================================
// Document Details Inspector (Right Panel)
// ============================================================================
function selectDocument(item) {
    state.selectedItem = item;

    // Highlight row in table
    document.querySelectorAll("#classificationTable tbody tr").forEach(r => r.classList.remove("selected"));
    const selectedTr = Array.from(document.querySelectorAll("#classificationTable tbody tr")).find(r => r.innerText.includes(item.file_name));
    if (selectedTr) selectedTr.classList.add("selected");

    populateInspector(item);
}

function populateInspector(item) {
    document.getElementById("inspectorEmptyState").style.display = "none";
    document.getElementById("inspectorContent").style.display = "block";
    document.getElementById("inspectorBadge").textContent = item.extension.toUpperCase();

    document.getElementById("detailFileName").textContent = item.file_name;
    document.getElementById("detailFileName").title = item.file_name;
    document.getElementById("detailExtBadge").textContent = item.extension.replace(".", "").toUpperCase();
    document.getElementById("detailFileSize").textContent = `${Math.round(item.size_bytes / 1024)} KB`;

    document.getElementById("detailActiveCategory").textContent = item.category;
    document.getElementById("detailActiveCategory").className = `active-cat-tag ${item.is_user_edited ? 'edited' : ''}`;
    document.getElementById("detailConfidencePill").textContent = `${Math.round(item.confidence_score * 100)}% Confidence`;

    document.getElementById("detailCategorySelect").value = item.category;
    document.getElementById("detailCustomCategoryInput").value = "";

    document.getElementById("detailCurrentPath").textContent = item.current_location;
    document.getElementById("detailProposedPath").textContent = `/${item.proposed_subfolder}/${item.file_name}`;

    document.getElementById("detailSnippetBox").textContent = item.summary_snippet || "No text extracted.";

    // Related documents
    const relList = document.getElementById("detailRelatedList");
    relList.innerHTML = "";
    if (item.related_documents && item.related_documents.length > 0) {
        item.related_documents.forEach(rel => {
            const relRow = document.createElement("div");
            relRow.className = "related-row-item";
            relRow.innerHTML = `
                <div>
                    <strong style="color:var(--text-main);">${rel.file_name}</strong>
                    <div style="font-size:0.68rem; color:var(--teal-primary);">${rel.relationship_reason}</div>
                </div>
                <button class="btn btn-secondary btn-sm" onclick="openLocalFile('${encodeURIComponent(rel.file_path)}')">Open</button>
            `;
            relList.appendChild(relRow);
        });
    } else {
        relList.innerHTML = `<span class="text-muted text-xs">No direct relationships detected.</span>`;
    }
}

function initInspectorControls() {
    const btnApply = document.getElementById("btnApplyCategoryEdit");
    btnApply.addEventListener("click", async () => {
        if (!state.selectedItem) return;

        const dropdownVal = document.getElementById("detailCategorySelect").value;
        const customVal = document.getElementById("detailCustomCategoryInput").value.trim();
        const finalCategory = customVal || dropdownVal;

        if (!finalCategory) {
            showToast("Please choose or enter a category name.", "error");
            return;
        }

        try {
            const res = await fetch(`${API_BASE}/api/preview/update-category`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    file_name: state.selectedItem.file_name,
                    new_category: finalCategory
                })
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || "Failed to update category");

            state.proposedTree = data.proposed_tree;
            state.availableCategories = data.available_categories;

            const idx = state.classificationPreview.findIndex(i => i.file_name === state.selectedItem.file_name);
            if (idx !== -1) {
                state.classificationPreview[idx] = data.updated_item;
            }

            renderClassificationTable();
            renderProposedTree();
            populateCategoryDropdown();
            selectDocument(data.updated_item);

            showToast(`Updated '${state.selectedItem.file_name}' to '${finalCategory}' (Preview)`);
        } catch (e) {
            showToast(e.message, "error");
        }
    });
}

function populateCategoryDropdown() {
    const sel = document.getElementById("detailCategorySelect");
    const ledgerFilter = document.getElementById("ledgerCategoryFilter");

    sel.innerHTML = "";
    ledgerFilter.innerHTML = `<option value="All">All Categories</option>`;

    state.availableCategories.forEach(cat => {
        const o1 = document.createElement("option");
        o1.value = cat;
        o1.textContent = cat;
        sel.appendChild(o1);

        const o2 = document.createElement("option");
        o2.value = cat;
        o2.textContent = cat;
        ledgerFilter.appendChild(o2);
    });
}

// ============================================================================
// Approval Confirmation & Atomic Reorganization
// ============================================================================
function initApprovalFlow() {
    const btnApprove = document.getElementById("btnApproveOrganize");
    const modal = document.getElementById("approvalModal");
    const btnClose = document.getElementById("btnApprovalClose");
    const btnCancel = document.getElementById("btnApprovalCancel");
    const btnConfirm = document.getElementById("btnApprovalConfirm");

    btnApprove.addEventListener("click", async () => {
        try {
            const res = await fetch(`${API_BASE}/api/organization/approve`, { method: "POST" });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || "Approval request failed");

            state.pendingApprovalToken = data.approval_token;
            document.getElementById("approveFilesCount").textContent = data.total_files;
            document.getElementById("approveFolderCount").textContent = Object.keys(data.breakdown).length;
            document.getElementById("approveTargetFolder").textContent = data.folder_path;

            const breakdownBox = document.getElementById("approveBreakdownGrid");
            breakdownBox.innerHTML = "";
            for (const [cat, cnt] of Object.entries(data.breakdown)) {
                const p = document.createElement("span");
                p.className = "breakdown-pill";
                p.textContent = `${cat}: ${cnt}`;
                breakdownBox.appendChild(p);
            }

            modal.classList.add("active");
        } catch (e) {
            showToast(e.message, "error");
        }
    });

    btnClose.addEventListener("click", () => modal.classList.remove("active"));
    btnCancel.addEventListener("click", () => modal.classList.remove("active"));

    btnConfirm.addEventListener("click", async () => {
        btnConfirm.disabled = true;
        btnConfirm.textContent = "Moving files...";
        setWorkflowStatus("Organizing...");

        try {
            const res = await fetch(`${API_BASE}/api/organization/execute`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ approval_token: state.pendingApprovalToken })
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || "Execution failed");

            modal.classList.remove("active");
            state.canUndo = true;
            updateUndoButton();
            state.currentTree = data.updated_tree;

            setWorkflowStatus("Completed");
            document.getElementById("modeBadge").className = "mode-badge write-permitted";
            document.getElementById("modeBadgeText").textContent = "COMPLETED & INDEXED";

            showToast(data.result.summary, "success");
            switchView("viewLedger");
            loadLedgerData();
        } catch (e) {
            showToast(e.message, "error");
            setWorkflowStatus("Failed");
        } finally {
            btnConfirm.disabled = false;
            btnConfirm.textContent = "Approve & Execute Organization";
        }
    });
}

// ============================================================================
// Searchable Document Ledger
// ============================================================================
function initLedger() {
    const sInput = document.getElementById("ledgerSearchInput");
    const catFilter = document.getElementById("ledgerCategoryFilter");
    const statusFilter = document.getElementById("ledgerStatusFilter");
    const btnRef = document.getElementById("btnRefreshLedger");

    let debounceTimer;
    sInput.addEventListener("input", () => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => loadLedgerData(), 250);
    });

    catFilter.addEventListener("change", () => loadLedgerData());
    statusFilter.addEventListener("change", () => loadLedgerData());
    btnRef.addEventListener("click", () => loadLedgerData());
}

async function loadLedgerData() {
    const query = document.getElementById("ledgerSearchInput").value;
    const cat = document.getElementById("ledgerCategoryFilter").value;
    const status = document.getElementById("ledgerStatusFilter").value;

    try {
        const params = new URLSearchParams({ query, category: cat, status });
        const res = await fetch(`${API_BASE}/api/ledger/search?${params.toString()}`);
        const data = await res.json();

        const tbody = document.getElementById("ledgerTableBody");
        tbody.innerHTML = "";

        if (!data.records || data.records.length === 0) {
            tbody.innerHTML = `
                <tr class="empty-state-row">
                    <td colspan="8" class="text-center py-6 text-muted">
                        No records match current filter criteria.
                    </td>
                </tr>
            `;
            return;
        }

        data.records.forEach(rec => {
            const tr = document.createElement("tr");
            const conf = Math.round(rec.confidence_score * 100);

            tr.innerHTML = `
                <td><strong>${rec.file_name}</strong></td>
                <td><span class="category-badge">${rec.category}</span></td>
                <td><span class="code-box">${rec.original_location}</span></td>
                <td><span class="code-box text-teal">${rec.current_location}</span></td>
                <td><span class="font-mono text-xs">${conf}%</span></td>
                <td><span class="font-mono text-xs text-muted">${rec.processed_at}</span></td>
                <td><span class="type-pill">${rec.processing_status}</span></td>
                <td style="text-align: right;">
                    <button class="btn btn-secondary btn-sm" onclick="openLocalFile('${encodeURIComponent(rec.current_location)}')">Open File</button>
                    <button class="btn btn-secondary btn-sm" onclick="openLocalFolder('${encodeURIComponent(rec.current_location)}')">Folder</button>
                </td>
            `;
            tbody.appendChild(tr);
        });
    } catch (e) {
        showToast("Failed to fetch ledger records", "error");
    }
}

window.openLocalFile = async function(encodedPath) {
    const p = decodeURIComponent(encodedPath);
    try {
        const res = await fetch(`${API_BASE}/api/ledger/open-file`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ file_path: p })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Open file failed");
        showToast(`Opened file locally: ${p}`);
    } catch (e) {
        showToast(e.message, "error");
    }
};

window.openLocalFolder = async function(encodedPath) {
    const p = decodeURIComponent(encodedPath);
    try {
        const res = await fetch(`${API_BASE}/api/ledger/open-folder`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ path: p })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Open folder failed");
    } catch (e) {
        showToast(e.message, "error");
    }
};

// ============================================================================
// Activity Audit History & 1-Click Rollback
// ============================================================================
function initAuditLog() {
    const btnUndo = document.getElementById("btnUndoMove");
    const btnRefresh = document.getElementById("btnRefreshAudit");

    btnRefresh.addEventListener("click", () => loadAuditLogs());

    btnUndo.addEventListener("click", async () => {
        if (!confirm("Are you sure you want to undo the last organization? This will restore files back to their original locations.")) return;

        btnUndo.disabled = true;
        setWorkflowStatus("Reverting...");
        try {
            const res = await fetch(`${API_BASE}/api/organization/undo`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({})
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || "Undo failed");

            state.canUndo = data.can_undo;
            updateUndoButton();
            setWorkflowStatus("Ready");
            document.getElementById("modeBadge").className = "mode-badge read-only";
            document.getElementById("modeBadgeText").textContent = "READ-ONLY MODE";

            showToast(data.result.message, "success");
            loadAuditLogs();
            loadLedgerData();
        } catch (e) {
            showToast(e.message, "error");
            setWorkflowStatus("Failed");
        } finally {
            btnUndo.disabled = false;
        }
    });
}

async function loadAuditLogs() {
    const timeline = document.getElementById("auditTimeline");
    try {
        const res = await fetch(`${API_BASE}/api/audit/logs`);
        const data = await res.json();
        timeline.innerHTML = "";

        if (!data.logs || data.logs.length === 0) {
            timeline.innerHTML = `<div class="text-muted p-4">No audit records found.</div>`;
            return;
        }

        data.logs.forEach(log => {
            const item = document.createElement("div");
            item.className = `audit-entry ${log.status === 'FAILED' ? 'failed' : ''}`;
            const timeStr = new Date(log.timestamp).toLocaleTimeString();

            item.innerHTML = `
                <div class="audit-entry-time">${timeStr}</div>
                <div>
                    <span class="audit-entry-title">${log.action_type}</span>
                    <span style="color:var(--text-muted);">${log.details}</span>
                </div>
            `;
            timeline.appendChild(item);
        });
    } catch (e) {
        showToast("Failed to fetch audit log", "error");
    }
}

function updateUndoButton() {
    const btn = document.getElementById("btnUndoMove");
    if (btn) btn.disabled = !state.canUndo;
}

// ============================================================================
// Related Documents Matrix View
// ============================================================================
function renderRelatedMatrix() {
    const container = document.getElementById("relatedMatrixContainer");
    if (!state.classificationPreview || state.classificationPreview.length === 0) {
        container.innerHTML = `<div class="empty-state-box"><p class="empty-title">No scanned documents available.</p></div>`;
        return;
    }

    container.innerHTML = "";
    const list = document.createElement("div");
    list.style.padding = "16px";
    list.style.display = "flex";
    list.style.flexDirection = "column";
    list.style.gap = "10px";

    let hasAnyRelated = false;
    state.classificationPreview.forEach(doc => {
        if (doc.related_documents && doc.related_documents.length > 0) {
            hasAnyRelated = true;
            const card = document.createElement("div");
            card.style.background = "var(--bg-input)";
            card.style.border = "1px solid var(--border-light)";
            card.style.borderRadius = "var(--radius-sm)";
            card.style.padding = "10px 14px";

            let relRows = doc.related_documents.map(r => `
                <div style="display:flex; justify-content:space-between; align-items:center; margin-top:6px; font-size:0.76rem;">
                    <span>&bull; <strong>${r.file_name}</strong> &mdash; <span style="color:var(--teal-primary);">${r.relationship_reason}</span></span>
                    <button class="btn btn-secondary btn-sm" onclick="openLocalFile('${encodeURIComponent(r.file_path)}')">Open</button>
                </div>
            `).join("");

            card.innerHTML = `
                <div style="font-size:0.82rem; font-weight:600; color:var(--text-main); border-bottom:1px solid var(--border-light); padding-bottom:4px;">
                    Target Document: ${doc.file_name} <span class="category-badge">${doc.category}</span>
                </div>
                ${relRows}
            `;
            list.appendChild(card);
        }
    });

    if (!hasAnyRelated) {
        container.innerHTML = `<div class="empty-state-box" style="padding:24px; text-align:center;"><p class="empty-title">No contextually related documents found.</p></div>`;
    } else {
        container.appendChild(list);
    }
}

// ============================================================================
// Overview Statistics
// ============================================================================
function updateOverviewStats() {
    document.getElementById("overviewTotalDocs").textContent = state.classificationPreview.length;
    document.getElementById("overviewCategoryCount").textContent = state.availableCategories.length;
}

// ============================================================================
// Chatbot Assistant Dock
// ============================================================================
function initChatDock() {
    const dock = document.getElementById("chatDock");
    const header = document.getElementById("chatDockToggle");
    const icon = document.getElementById("dockCollapseIcon");
    const form = document.getElementById("chatForm");
    const input = document.getElementById("chatInput");

    header.addEventListener("click", () => {
        dock.classList.toggle("collapsed");
        icon.textContent = dock.classList.contains("collapsed") ? "▼" : "▲";
    });

    form.addEventListener("submit", (e) => {
        e.preventDefault();
        const msg = input.value.trim();
        if (!msg) return;
        input.value = "";
        handleUserChatMessage(msg);
    });

    document.querySelectorAll(".chip-cmd").forEach(chip => {
        chip.addEventListener("click", () => {
            const cmd = chip.getAttribute("data-cmd");
            handleUserChatMessage(cmd);
        });
    });
}

function appendChatBubble(role, text) {
    const stream = document.getElementById("chatMessages");
    const bubble = document.createElement("div");
    bubble.className = `chat-bubble ${role}`;

    const formatted = text
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        .replace(/\n/g, '<br>');

    bubble.innerHTML = formatted;
    stream.appendChild(bubble);
    stream.scrollTop = stream.scrollHeight;
}

async function handleUserChatMessage(text) {
    appendChatBubble("user", text);

    try {
        const res = await fetch(`${API_BASE}/api/chat`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: text })
        });
        const data = await res.json();
        appendChatBubble("ai", data.response);

        if (data.action === "PROMPT_FOLDER_SELECT") {
            document.getElementById("btnBrowseFolder").click();
        } else if (data.action === "SCAN_COMPLETED" && data.data) {
            handleScanSuccess(data.data);
        } else if (data.action === "CATEGORY_UPDATED" && data.data) {
            state.proposedTree = data.data.proposed_tree;
            state.availableCategories = data.data.available_categories;
            const idx = state.classificationPreview.findIndex(i => i.file_name === data.data.updated_item.file_name);
            if (idx !== -1) {
                state.classificationPreview[idx] = data.data.updated_item;
            }
            renderClassificationTable();
            renderProposedTree();
            selectDocument(data.data.updated_item);
        } else if (data.action === "SHOW_APPROVAL_MODAL") {
            document.getElementById("btnApproveOrganize").click();
        } else if (data.action === "UNDO_COMPLETED") {
            state.canUndo = data.data.can_undo;
            updateUndoButton();
            loadLedgerData();
        }
    } catch (e) {
        appendChatBubble("ai", `Error: ${e.message}`);
    }
}

// ============================================================================
// Modal Utilities: Create New Folder & Optional Upload
// ============================================================================
function initModalUtilities() {
    // 1. Create New Folder Modal
    const nfModal = document.getElementById("newFolderModal");
    const btnOpenNf = document.getElementById("btnOpenNewFolderModal");
    const btnCloseNf = document.getElementById("btnNewFolderClose");
    const btnCancelNf = document.getElementById("btnNewFolderCancel");
    const btnSubmitNf = document.getElementById("btnNewFolderSubmit");

    btnOpenNf.addEventListener("click", () => {
        document.getElementById("newFolderParentInput").value = state.currentFolder || "";
        nfModal.classList.add("active");
    });
    btnCloseNf.addEventListener("click", () => nfModal.classList.remove("active"));
    btnCancelNf.addEventListener("click", () => nfModal.classList.remove("active"));

    btnSubmitNf.addEventListener("click", async () => {
        const parentDir = document.getElementById("newFolderParentInput").value.trim();
        const folderName = document.getElementById("newFolderNameInput").value.trim();

        if (!parentDir || !folderName) {
            showToast("Parent directory and new folder name are required.", "error");
            return;
        }

        try {
            const res = await fetch(`${API_BASE}/api/folder/create`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ parent_dir: parentDir, folder_name: folderName })
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || "Failed to create folder");

            nfModal.classList.remove("active");
            document.getElementById("folderPathInput").value = data.folder_path;
            showToast(data.message, "success");
            await triggerScan(data.folder_path);
        } catch (e) {
            showToast(e.message, "error");
        }
    });

    // 2. Upload Documents Modal
    const upModal = document.getElementById("uploadModal");
    const btnOpenUp = document.getElementById("btnOpenUploadModal");
    const btnCloseUp = document.getElementById("btnUploadClose");
    const btnCancelUp = document.getElementById("btnUploadCancel");
    const btnSubmitUp = document.getElementById("btnUploadSubmit");

    btnOpenUp.addEventListener("click", () => {
        document.getElementById("uploadDestInput").value = state.currentFolder || "";
        upModal.classList.add("active");
    });
    btnCloseUp.addEventListener("click", () => upModal.classList.remove("active"));
    btnCancelUp.addEventListener("click", () => upModal.classList.remove("active"));

    btnSubmitUp.addEventListener("click", async () => {
        const fileInput = document.getElementById("uploadFileInput");
        const destFolder = document.getElementById("uploadDestInput").value.trim();

        if (!fileInput.files || fileInput.files.length === 0) {
            showToast("Please select at least one file to upload.", "error");
            return;
        }

        const formData = new FormData();
        for (let i = 0; i < fileInput.files.length; i++) {
            formData.append("files", fileInput.files[i]);
        }

        btnSubmitUp.disabled = true;
        btnSubmitUp.textContent = "Uploading...";

        try {
            const url = destFolder ? `${API_BASE}/api/folder/upload?target_folder=${encodeURIComponent(destFolder)}` : `${API_BASE}/api/folder/upload`;
            const res = await fetch(url, {
                method: "POST",
                body: formData
            });
            const data = await res.json();
            if (!res.ok) {
                const errMsg = typeof data.detail === "string" ? data.detail : (data.detail ? JSON.stringify(data.detail) : "Upload failed");
                throw new Error(errMsg);
            }

            upModal.classList.remove("active");
            showToast(data.message, "success");
            document.getElementById("folderPathInput").value = data.target_folder;
            await triggerScan(data.target_folder);
        } catch (e) {
            let msg = e.message;
            if (msg === "Failed to fetch") {
                msg = "Render server is waking up (cold boot). Please wait ~30 seconds and retry.";
            }
            showToast(msg, "error");
        } finally {
            btnSubmitUp.disabled = false;
            btnSubmitUp.textContent = "Upload Files";
        }
    });

    // 3. Visual Folder Browser Modal Controller
    const fbModal = document.getElementById("folderBrowserModal");
    const btnCloseFb = document.getElementById("btnFolderBrowserClose");
    const btnCancelFb = document.getElementById("btnFolderBrowserCancel");
    const btnSelectFb = document.getElementById("btnFolderBrowserSelect");
    const btnGoUpFb = document.getElementById("btnBrowserGoUp");
    const currentPathInputFb = document.getElementById("browserCurrentPathInput");
    const quickJumpsBox = document.getElementById("browserQuickJumps");
    const dirsListBox = document.getElementById("browserDirsList");
    const btnLaunchNative = document.getElementById("btnLaunchNativePicker");
    const btnTriggerWebkit = document.getElementById("btnTriggerWebkitPicker");
    const webkitInput = document.getElementById("browserWebkitPickerInput");

    let activeBrowserPath = "";
    let parentBrowserPath = null;
    let selectedSubfolderPath = null;

    async function loadDirectoryListing(targetPath = "") {
        dirsListBox.innerHTML = `<div class="text-xs text-muted p-2">Loading directories...</div>`;
        try {
            const res = await fetch(`${API_BASE}/api/folder/list-dirs`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ path: targetPath })
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || "Unable to read directory");

            activeBrowserPath = data.current_path;
            parentBrowserPath = data.parent_path;
            selectedSubfolderPath = null;
            currentPathInputFb.value = activeBrowserPath;

            btnGoUpFb.disabled = !parentBrowserPath;

            // Render Quick Jumps
            quickJumpsBox.innerHTML = "";
            data.quick_jumps.forEach(q => {
                const pill = document.createElement("button");
                pill.className = "chip-cmd";
                pill.style.padding = "3px 8px";
                pill.textContent = q.name;
                pill.addEventListener("click", () => loadDirectoryListing(q.path));
                quickJumpsBox.appendChild(pill);
            });

            // Render Subdirectories List
            dirsListBox.innerHTML = "";
            if (!data.directories || data.directories.length === 0) {
                dirsListBox.innerHTML = `<div class="text-xs text-muted p-3 text-center">No subdirectories found in this folder. Click 'Select This Folder' to use it.</div>`;
                return;
            }

            data.directories.forEach(dir => {
                const item = document.createElement("div");
                item.className = "folder-browser-item";
                item.style.padding = "8px 10px";
                item.style.display = "flex";
                item.style.alignItems = "center";
                item.style.gap = "10px";
                item.innerHTML = `
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="flex-shrink:0; color: var(--accent-teal);">
                        <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
                    </svg>
                    <div style="display:flex; flex-direction:column; min-width:0; flex:1; text-align:left;">
                        <span style="font-weight: 600; font-size: 13px; color: var(--text-main);">${dir.name}</span>
                        <span style="font-size: 11px; color: var(--text-muted); font-family: var(--font-mono); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${dir.path}">${dir.path}</span>
                    </div>
                `;

                // Single click to select
                item.addEventListener("click", () => {
                    document.querySelectorAll(".folder-browser-item").forEach(i => i.classList.remove("selected"));
                    item.classList.add("selected");
                    selectedSubfolderPath = dir.path;
                    currentPathInputFb.value = dir.path;
                });

                // Double click to navigate into
                item.addEventListener("dblclick", () => {
                    loadDirectoryListing(dir.path);
                });

                dirsListBox.appendChild(item);
            });
        } catch (e) {
            dirsListBox.innerHTML = `<div class="text-xs text-danger p-2">Error: ${e.message}</div>`;
        }
    }

    window.openFolderBrowserModal = function(startPath = "") {
        fbModal.classList.add("active");
        loadDirectoryListing(startPath);
    };

    btnCloseFb.addEventListener("click", () => fbModal.classList.remove("active"));
    btnCancelFb.addEventListener("click", () => fbModal.classList.remove("active"));

    btnGoUpFb.addEventListener("click", () => {
        if (parentBrowserPath) {
            loadDirectoryListing(parentBrowserPath);
        }
    });

    currentPathInputFb.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            loadDirectoryListing(currentPathInputFb.value.trim());
        }
    });

    // Select chosen folder
    btnSelectFb.addEventListener("click", async () => {
        const chosen = currentPathInputFb.value.trim() || selectedSubfolderPath || activeBrowserPath;
        if (!chosen) {
            showToast("Please choose a folder to select.", "error");
            return;
        }
        fbModal.classList.remove("active");
        document.getElementById("folderPathInput").value = chosen;
        showFeedback(`Selected directory: ${chosen}`, "success");
        await triggerScan(chosen);
    });

    // Launch Native Windows Dialog option (with short timeout and toast)
    btnLaunchNative.addEventListener("click", async () => {
        btnLaunchNative.disabled = true;
        btnLaunchNative.textContent = "Opening...";
        showToast("Attempting to open Windows File Explorer window...");
        try {
            const res = await fetch(`${API_BASE}/api/folder/browse`, { method: "POST" });
            const data = await res.json();
            if (!data.cancelled && data.folder_path) {
                fbModal.classList.remove("active");
                document.getElementById("folderPathInput").value = data.folder_path;
                showFeedback(`Selected directory: ${data.folder_path}`, "success");
                await triggerScan(data.folder_path);
            } else {
                showToast("Folder dialog closed. You can browse folders directly in the list above.", "info");
            }
        } catch (e) {
            showToast("Native window not available. Please use the folder list above.", "info");
        } finally {
            btnLaunchNative.disabled = false;
            btnLaunchNative.textContent = "Launch OS Window";
        }
    });

    // Webkit Directory Browser Picker
    btnTriggerWebkit.addEventListener("click", () => {
        webkitInput.click();
    });

    webkitInput.addEventListener("change", async (e) => {
        if (e.target.files && e.target.files.length > 0) {
            const relPath = e.target.files[0].webkitRelativePath;
            const topDir = relPath.split("/")[0];
            const sampleFiles = Array.from(e.target.files).slice(0, 5).map(f => f.name);

            setWorkflowStatus("Resolving path...");
            showToast(`Resolving full filesystem path for '${topDir}'...`);

            try {
                const res = await fetch(`${API_BASE}/api/folder/resolve-path`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ name: topDir, files: sampleFiles })
                });
                const data = await res.json();
                const fullPath = data.resolved && data.path ? data.path : topDir;

                fbModal.classList.remove("active");
                document.getElementById("folderPathInput").value = fullPath;
                showFeedback(`Selected folder path: ${fullPath}`, "success");
                await triggerScan(fullPath);
            } catch (err) {
                fbModal.classList.remove("active");
                document.getElementById("folderPathInput").value = topDir;
                await triggerScan(topDir);
            }
        }
    });
}

// ============================================================================
// Toast Stack
// ============================================================================
function showToast(message, type = "info") {
    const stack = document.getElementById("toastContainer");
    const toast = document.createElement("div");
    toast.className = `toast-item ${type}`;
    toast.textContent = message;

    stack.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = "0";
        setTimeout(() => toast.remove(), 250);
    }, 4000);
}
