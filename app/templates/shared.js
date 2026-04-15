// --- METADATA CONSTANTS ---
const METADATA_FIELDS = ['title', 'showtitle', 'season', 'episode', 'aired', 'premiered', 'year', 'studio', 'uniqueid', 'plot'];
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

/**
 * Renders metadata into Source (master) and Editor panes.
 * masterPane, editorPane, and saveContainer should be DOM elements.
 */
function renderMetadataFields(data, isEligible, masterPane, editorPane, saveContainer = null) {
    const meta = data.effective || {};
    const source = data.source || {};
    
    // Clear existing content
    masterPane.innerHTML = '';
    editorPane.innerHTML = '';

    if (!isEligible) {
        editorPane.innerHTML = `<div class="h-full flex items-center justify-center text-gray-500 italic">Locked.</div>`;
    }

    const editorWrapper = document.createElement('div');
    editorWrapper.className = 'flex flex-col h-full';

    METADATA_FIELDS.forEach(tag => {
        if (!(tag in meta)) return;

        const val = meta[tag] !== null ? String(meta[tag]) : '';
        const sVal = source[tag] !== null ? String(source[tag]) : '';
        const isPlot = tag === 'plot';
        const isReadOnly = !EDITABLE_FIELDS.includes(tag);

        // --- Build Master Pane Item ---
        const mItem = document.createElement('div');
        mItem.className = 'mb-2';
        mItem.innerHTML = `<span class="label-text">&lt;${tag}&gt;</span><div class="pl-2 border-l-2 border-gray-700 color-gray-300"></div>`;
        mItem.querySelector('div').textContent = sVal;
        masterPane.appendChild(mItem);

        // --- Build Editor Pane Item ---
        if (isEligible) {
            const eItem = document.createElement('div');
            eItem.className = `mb-2 ${isPlot ? 'flex-1 flex flex-col' : ''}`;
            eItem.innerHTML = `<span class="label-text ${isReadOnly ? '' : 'text-blue-400'}">&lt;${tag}&gt;</span>`;
            
            const input = document.createElement(isPlot ? 'textarea' : 'input');
            input.id = `edit-${tag}`;
            input.className = `input-base ${isPlot ? 'plot-textarea' : ''}`;
            if (!isPlot) input.type = 'text';
            if (isReadOnly) input.disabled = true;
            input.value = val;
            
            eItem.appendChild(input);
            editorWrapper.appendChild(eItem);
        }
    });

    if (isEligible) {
        const spacer = document.createElement('div');
        spacer.className = 'h-6 w-full flex-none';
        editorWrapper.appendChild(spacer);
        editorPane.appendChild(editorWrapper);
    }

    // Final spacer for master pane
    const mSpacer = document.createElement('div');
    mSpacer.className = 'h-6 w-full flex-none';
    masterPane.appendChild(mSpacer);

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
    if (r.ok) window.location.reload();
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