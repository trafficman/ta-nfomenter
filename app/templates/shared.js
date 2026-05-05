// --- METADATA CONSTANTS ---
const METADATA_FIELDS = ['title', 'showtitle', 'season', 'episode', 'aired', 'studio', 'uniqueid', 'plot', 'premiered', 'year'];
const EDITABLE_FIELDS = ['title', 'season', 'episode', 'aired', 'premiered', 'year', 'studio', 'plot'];

// --- UI UTILITIES ---

/**
 * Tracks the active status animation interval
 */
let statusInterval = null;

/**
 * Updates the header status message with an optional timeout
 */
function updateStatus(msg, timeout = 3000) {
    const el = document.getElementById('status-msg');
    if (!el) return;

    clearInterval(statusInterval);
    el.innerText = msg;

    if (msg.endsWith('...')) {
        const baseText = msg.slice(0, -3);
        let count = 3;
        statusInterval = setInterval(() => {
            count = (count > 0) ? count - 1 : 3;
            el.innerText = baseText + ".".repeat(count);
        }, 600);
    }

    if (timeout) {
        setTimeout(() => { 
            const base = msg.endsWith('...') ? msg.slice(0, -3) : msg;
            if (el.innerText.startsWith(base)) {
                el.innerText = ""; 
                clearInterval(statusInterval);
            }
        }, timeout);
    }
}

/**
 * Handles expanding/collapsing of channel trees across panes
 */
function toggleTree(id) {
    ['left', 'right'].forEach(side => {
        const tree = document.getElementById(`tree-${side}-${id}`);
        const tri = document.getElementById(`tri-${side}-${id}`);
        if (tree) tree.classList.toggle('hidden');
        if (tri) tri.classList.toggle('open');
    });
}

// --- AUTO-INITIALIZATION ---
document.addEventListener('DOMContentLoaded', () => {
    initResizer('resizer', 'footer-pane');

    const ep = document.getElementById('editor-pane');
    if (ep && ep.dataset.lockMsg) {
        renderLockedPane(ep, ep.dataset.lockTitle, ep.dataset.lockMsg);
    }
});

/**
 * Shared Resizer Logic for the footer pane
 */
function initResizer(resizerId, footerId) {
    const resizer = document.getElementById(resizerId);
    const footer = document.getElementById(footerId);
    if (!resizer || !footer) return;

    let isResizing = false;

    resizer.addEventListener('mousedown', () => { 
        isResizing = true; 
        document.body.style.cursor = 'ns-resize'; 
    });

    document.addEventListener('mouseup', () => { 
        isResizing = false; 
        document.body.style.cursor = 'default'; 
    });

    document.addEventListener('mousemove', (e) => {
        if (!isResizing) return;
        const newHeight = window.innerHeight - e.clientY;
        if (newHeight > 100 && newHeight < window.innerHeight * 0.85) {
            footer.style.height = `${newHeight}px`;
        }
    });
}

/**
 * Calculates if text overflows and sets CSS variables for a smooth marquee.
 */
function updateMarqueeState(el) {
    const container = el.closest('.truncate');
    if (!container) return;

    // Temporarily set display to measure full content width
    const originalDisplay = el.style.display;
    el.style.display = 'inline-block';
    const scrollWidth = el.offsetWidth;
    el.style.display = originalDisplay;

    const containerWidth = container.offsetWidth;
    const overflow = scrollWidth - containerWidth;

    if (overflow > 0) {
        el.style.setProperty('--scroll-dist', overflow);
        // Dynamic speed: roughly 30px per second
        el.style.setProperty('--marquee-duration', Math.min(Math.max(overflow / 30, 3), 15) + 's');
        el.classList.add('can-marquee');
    } else {
        el.classList.remove('can-marquee');
    }
}

// --- METADATA CORE ---

/**
 * Fetches metadata for a given ID
 */
async function fetchMetadata(id) {
    const r = await fetch(`/api/get_metadata/${id}`);
    if (!r.ok) return null;
    return await r.json();
}

function openAssetsModal(id, name) {
    document.getElementById('asset-modal-show-name').textContent = name;
    document.getElementById('asset-modal-show-id').value = id;
    document.getElementById('asset-modal-name-raw').value = name;
    document.getElementById('assetsModal').classList.remove('hidden');
}

async function submitCreateAssetFolder() {
    const id = document.getElementById('asset-modal-show-id').value;
    const name = document.getElementById('asset-modal-name-raw').value;
    const btn = document.getElementById('create-asset-folder-btn');
    
    btn.disabled = true;
    btn.textContent = "CREATING...";

    const r = await fetch('/api/create_asset_folder', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ id, name })
    });

    btn.disabled = false;
    btn.textContent = "CREATE ASSET FOLDER";

    if (r.ok) {
        const data = await r.json();
        updateStatus(`✅ Folder Created: ${data.folder}`);
        closeAssetsModal();
    } else {
        alert("Failed to create folder.");
    }
}

function closeAssetsModal() {
    document.getElementById('assetsModal').classList.add('hidden');
}

/**
 * Standardized component for locked/empty states in panels.
 */
function renderLockedPane(container, title = "Locked", message = "Select an item to begin editing.") {
    container.innerHTML = `
        <div class="h-full flex flex-col items-center justify-center text-gray-600 uppercase font-bold text-[10px] tracking-widest text-center px-6">
            <span>${title}</span>
            <span class="mt-2 font-normal normal-case italic text-[9px]">${message}</span>
        </div>
    `;
}

/**
 * Core utility to build metadata rows.
 * options: { label, isEditable, isPlot, isMaster, showRevert }
 */
function renderMetadataField(container, tag, value, options = {}) {
    const {
        label = tag,
        isEditable = false,
        isPlot = (tag === 'plot'),
        isMaster = false,
        showRevert = false
    } = options;

    const canEdit = isEditable && EDITABLE_FIELDS.includes(tag);

    const wrapper = document.createElement('div');
    wrapper.className = 'mb-4 px-3';

    // Header Row (Label + Actions)
    const header = document.createElement('div');
    header.className = 'flex justify-between items-center mb-1';
    
    const labelEl = document.createElement('label');
    // Labels for Master pane or non-editable Editor fields are grey.
    labelEl.className = `label-text ${(isMaster || !canEdit) ? 'text-gray-500' : 'text-blue-400'}`;
    labelEl.textContent = isMaster ? `<${tag.toUpperCase()}>` : label;
    header.appendChild(labelEl);

    if (showRevert && canEdit) {
        const revertBtn = document.createElement('button');
        revertBtn.className = 'text-[8px] font-bold text-gray-600 hover:text-blue-400 uppercase tracking-tighter transition-colors';
        revertBtn.textContent = 'Revert';
        revertBtn.onclick = () => {
            const input = document.getElementById(`edit-${tag}`);
            const master = document.getElementById(`master-val-${tag}`);
            if (input && master) input.value = master.textContent;
        };
        header.appendChild(revertBtn);
    }
    wrapper.appendChild(header);

    // Value display or input
    // Render as plain text if it's the master pane OR if the field isn't editable in the editor
    if (isMaster || !canEdit) {
        const display = document.createElement('div');
        if (isMaster) display.id = `master-val-${tag}`;
        display.className = 'pl-2 border-l-2 border-gray-700 text-gray-400 text-xs break-words whitespace-pre-wrap';
        display.textContent = value !== null ? String(value) : '';
        wrapper.appendChild(display);
    } else {
        const input = document.createElement(isPlot ? 'textarea' : 'input');
        input.id = `edit-${tag}`;
        input.className = `input-base text-xs ${isPlot ? 'plot-textarea' : ''}`;
        if (!isPlot) input.type = 'text';
        input.value = value !== null ? String(value) : '';
        wrapper.appendChild(input);
    }

    container.appendChild(wrapper);
}

/**
 * High-level function to render metadata into Source and Editor panes.
 */
function renderMetadataFields(data, isEligible, masterPane, editorPane, saveContainer = null, context = 'editor') {
    const meta = data.effective || data.modified || {};
    const source = data.source || {};
    
    masterPane.innerHTML = '';
    editorPane.innerHTML = '';

    // Render Master Pane
    METADATA_FIELDS.forEach(tag => {
        if (tag in source) renderMetadataField(masterPane, tag, source[tag], { isMaster: true });
    });

    // Render Editor Pane
    if (isEligible) {
        const isChannel = ('premiered' in source);
        const fieldsToRender = (data.modified) 
            ? [
                {tag:'title', label:'<TITLE>'},
                {tag:'showtitle', label:'<SHOWTITLE>'},
                {tag:'season', label:'<SEASON>'},
                {tag:'episode', label:'<EPISODE>'},
                {tag:'aired', label:'<AIRED>'},
                {tag:'studio', label:'<STUDIO>'},
                {tag:'uniqueid', label:'<UNIQUEID>'},
                {tag:'plot', label:'<PLOT>'}
              ]
            : METADATA_FIELDS.map(tag => ({tag, label: `<${tag.toUpperCase()}>`}));

        fieldsToRender.forEach(f => {
            if (f.tag in meta) {
                let fieldEditable = true;
                if (f.tag === 'studio' && !isChannel) fieldEditable = false;

                renderMetadataField(editorPane, f.tag, meta[f.tag], { 
                    label: f.label, 
                    isEditable: fieldEditable,
                    showRevert: true
                });
            }
        });
    } else {
        renderLockedPane(editorPane);
    }

    if (saveContainer) saveContainer.classList.toggle('hidden', !isEligible);
}

/**
 * Saves current editor field values to the database.
 * Returns the fetch response.
 */
async function apiSaveMetadata(id, endpoint = '/api/save_override') {
    const fields = {};
    EDITABLE_FIELDS.forEach(tag => {
        const el = document.getElementById(`edit-${tag}`);
        if (el && !el.disabled) fields[tag] = el.value;
    });

    return await fetch(endpoint, { 
        method: 'POST', 
        headers: {'Content-Type': 'application/json'}, 
        body: JSON.stringify({id, fields}) 
    });
}

// --- GLOBAL API ACTIONS ---

async function syncAll() {
    updateStatus("Syncing...", 0);
    const r = await fetch('/api/sync_all', { method: 'POST' });
    if (r.ok) {
        if (window.location.pathname.includes('/aggregator/')) {
            sessionStorage.setItem('aggregator_reload', 'true');
        }
        window.location.reload();
    }
}

async function runExport() {
    updateStatus("🚀 Exporting...", 0);
    try {
        const r = await fetch('/api/export', { method: 'POST' });
        if (r.ok) updateStatus("✅ Export Finished!");
    } catch (e) {
        updateStatus("❌ Export Failed.");
        console.error("Export error:", e);
    }
}

async function apiToggleChannel(id, state) {
    return await fetch('/api/toggle_channel', { 
        method: 'POST', 
        headers: {'Content-Type': 'application/json'}, 
        body: JSON.stringify({id, state}) 
    });
}

// --- GLOBAL EVENT LISTENERS ---
document.addEventListener('mouseenter', (e) => {
    if (e.target.classList && e.target.classList.contains('item-row')) {
        const span = e.target.querySelector('.truncate span');
        if (span) updateMarqueeState(span);
    }
}, true);

async function apiToggleVideo(id, state) {
    return await fetch('/api/toggle_video', { 
        method: 'POST', 
        headers: {'Content-Type': 'application/json'}, 
        body: JSON.stringify({id, state}) 
    });
}