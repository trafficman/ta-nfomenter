document.addEventListener('DOMContentLoaded', () => {
    const editorPane = document.getElementById('editor-pane');
    if (editorPane && !currentShowId) {
        renderLockedPane(editorPane, "Locked", "Select an Aggregated Show to enable editing");
    }
});

let activeId = null;
let currentShowId = null;

async function handleItemClick(el) {
    if (!el.dataset.id) return;
    activeId = el.dataset.id;
    const isChannel = activeId.startsWith('UC');

    document.querySelectorAll('.item-row').forEach(r => r.classList.remove('selected-item'));
    const rightItem = document.getElementById(`right-item-${activeId}`);
    if (rightItem) rightItem.classList.add('selected-item');
    
    const leftItem = document.getElementById(`left-item-${activeId}`);
    if (leftItem) leftItem.classList.add('selected-item');

    let data;
    if (currentShowId && !isChannel) {
        const r = await fetch(`/aggregator/api/video_metadata/${currentShowId}/${activeId}`);
        data = await r.json();
    } else {
        data = await fetchMetadata(activeId);
    }

    if (data) {
        const masterPane = document.getElementById('master-pane');
        const editorPane = document.getElementById('editor-pane');
        const saveContainer = document.getElementById('editor-save-container');

        if (!currentShowId) {
            renderMetadataFields(data, false, masterPane, editorPane, saveContainer, 'aggregator');
            renderLockedPane(editorPane, "Locked", "Select an Aggregated Show to enable editing");
        } else {
            if (isChannel) {
                renderMetadataFields(data, false, masterPane, editorPane, saveContainer, 'aggregator');
                renderLockedPane(editorPane, "Restricted", "Channel metadata is managed in the Single-Channel Editor");
            } else if (!data.modified) {
                renderMetadataFields(data, false, masterPane, editorPane, saveContainer, 'aggregator');
                renderLockedPane(editorPane, "Locked", "Video must be enabled for this show to edit metadata");
            } else {
                renderMetadataFields(data, true, masterPane, editorPane, saveContainer, 'aggregator');
            }
        }
    }
}

async function handleSave() {
    if (!currentShowId || !activeId) return;
    const metadata = {
        title: document.getElementById('edit-title')?.value ?? null,
        season: document.getElementById('edit-season')?.value ?? null,
        episode: document.getElementById('edit-episode')?.value ?? null,
        aired: document.getElementById('edit-aired')?.value ?? null,
        plot: document.getElementById('edit-plot')?.value ?? null
    };

    try {
        const r = await fetch('/aggregator/api/save_video_metadata', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ show_id: currentShowId, video_id: activeId, metadata })
        });
        const res = await r.json();
        if (res.status === 'success') {
            updateStatus("✅ Overrides Staged");
            refreshShowPreview();
        }
    } catch (e) { updateStatus("❌ Save Error"); }
}

async function toggleChannel(id, state) {
    if (!currentShowId) return;
    try {
        const r = await fetch('/aggregator/api/toggle_channel', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ show_id: currentShowId, channel_id: id, state: state })
        });
        if (r.ok) {
            refreshShowPreview();
        }
    } catch (e) { console.error(e); }
}

async function toggleVideo(id, state) {
    if (!currentShowId) return;
    try {
        const r = await fetch('/aggregator/api/toggle_video', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ show_id: currentShowId, video_id: id, state: state })
        });
        if (r.ok) {
            refreshShowPreview();
        }
    } catch (e) { console.error(e); }
}

async function selectShow(id, name) {
    currentShowId = id;
    document.getElementById('current-show-name').textContent = name;
    document.getElementById('no-show-selected').classList.add('hidden');

    // Reset UI state in right pane: Disable first, then fetch
    const allRows = document.querySelectorAll('#right-pane .item-row');
    allRows.forEach(el => el.classList.add('is-dimmed'));

    const allCheckboxes = document.querySelectorAll('.source-toggle');
    allCheckboxes.forEach(el => {
        el.checked = false;
        el.disabled = false;
        el.classList.remove('opacity-20', 'cursor-not-allowed');
        el.classList.add('cursor-pointer');
    });

    await refreshShowPreview();
}

async function refreshShowPreview() {
    if (!currentShowId) return;

    // Fetch joins for this show
    try {
        const r = await fetch(`/aggregator/api/show_joins/${currentShowId}`);
        const joins = await r.json();
        
        // Update Right Pane (Source) state
        document.querySelectorAll('#right-pane .item-row').forEach(el => el.classList.add('is-dimmed'));
        document.querySelectorAll('.source-toggle').forEach(el => el.checked = false);

        [...joins.channels, ...joins.videos].forEach(targetId => {
            const row = document.getElementById(`right-item-${targetId}`);
            if (!row) return;
            row.classList.remove('is-dimmed');
            const cb = row.querySelector('.source-toggle');
            if (cb) cb.checked = true;
        });

        // Build Left Pane (Aggregated Preview) grouped by Season
        const leftPaneContainer = document.getElementById('aggregated-items');
        leftPaneContainer.innerHTML = '';
        leftPaneContainer.classList.remove('hidden');

        const seasons = {};
        joins.left_pane.forEach(v => {
            if (!seasons[v.season]) seasons[v.season] = [];
            seasons[v.season].push(v);
        });

        const sortedSeasons = Object.keys(seasons).sort((a,b) => parseInt(a) - parseInt(b));

        sortedSeasons.forEach(s => {
            const seasonDiv = document.createElement('div');
            seasonDiv.className = 'season-group';
            
            seasonDiv.innerHTML = `
                <div class="item-row p-2 cursor-pointer flex items-center border-b border-gray-800/50" onclick="toggleTree('season-${s}')">
                    <span class="tri mr-2 text-gray-600" id="tri-left-season-${s}">▶</span>
                    <span class="text-blue-400 mr-2 text-xs">📁</span>
                    <span class="truncate text-sm font-bold text-gray-300 uppercase tracking-tighter">Season ${s}</span>
                </div>
                <div id="tree-left-season-${s}" class="hidden bg-black/30"></div>
            `;
            
            const episodesContainer = seasonDiv.querySelector(`#tree-left-season-${s}`);
            seasons[s].forEach(ep => {
                const epDiv = document.createElement('div');
                epDiv.id = `left-item-${ep.id}`;
                epDiv.className = 'item-row pl-10 p-1.5 text-sm cursor-pointer flex items-center';
                if (ep.id === activeId) epDiv.classList.add('selected-item');
                epDiv.dataset.id = ep.id;
                epDiv.onclick = (e) => { handleItemClick(epDiv); e.stopPropagation(); };
                epDiv.innerHTML = `
                    <span class="text-gray-600 mr-2 text-[10px]">🎬</span>
                    <span class="truncate text-gray-300">S${ep.season}E${ep.episode} - ${ep.title}</span>
                `;
                episodesContainer.appendChild(epDiv);
            });
            
            leftPaneContainer.appendChild(seasonDiv);
        });
    } catch (e) { console.error("Error fetching joins:", e); }
}

function openCreateShowModal() {
    document.getElementById('createShowModal').classList.remove('hidden');
}

async function submitCreateShow() {
    const name = document.getElementById('new-show-name').value;
    const description = document.getElementById('new-show-desc').value;
    const studio = document.getElementById('new-show-studio').value;
    const premiered = document.getElementById('new-show-premiered').value;

    if (!name) {
        alert("Show Name is required.");
        return;
    }

    try {
        const r = await fetch('/aggregator/api/create_show', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ name, description, studio, premiered })
        });
        const data = await r.json();
        if (data.status === 'success') {
            window.location.reload();
        } else {
            alert("Error: " + data.message);
        }
    } catch (e) {
        console.error(e);
        alert("Network error.");
    }
}

async function openEditShowModal(id) {
    try {
        const r = await fetch(`/aggregator/api/get_show/${id}`);
        const show = await r.json();
        if (show.id) {
            document.getElementById('edit-show-id').value = show.id;
            document.getElementById('edit-show-name').value = show.name;
            document.getElementById('edit-show-studio').value = show.studio;
            document.getElementById('edit-show-premiered').value = show.premiered;
            document.getElementById('edit-show-desc').value = show.description;
            document.getElementById('editShowModal').classList.remove('hidden');
        }
    } catch (e) {
        console.error(e);
        alert("Failed to load show details.");
    }
}

async function submitEditShow() {
    const id = document.getElementById('edit-show-id').value;
    const payload = {
        name: document.getElementById('edit-show-name').value,
        studio: document.getElementById('edit-show-studio').value,
        premiered: document.getElementById('edit-show-premiered').value,
        description: document.getElementById('edit-show-desc').value
    };

    try {
        const r = await fetch(`/aggregator/api/update_show/${id}`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });
        if (r.ok) window.location.reload();
        else alert("Update failed.");
    } catch (e) {
        console.error(e);
        alert("Network error.");
    }
}

async function confirmDeleteShow() {
    const id = document.getElementById('edit-show-id').value;
    const name = document.getElementById('edit-show-name').value;
    
    if (!confirm(`Are you sure you want to delete "${name}"? This will remove all custom episodes and configuration for this show. This cannot be undone.`)) {
        return;
    }

    try {
        const r = await fetch(`/aggregator/api/delete_show/${id}`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'}
        });
        if (r.ok) {
            window.location.reload();
        } else alert("Deletion failed.");
    } catch (e) {
        console.error(e);
        alert("Network error.");
    }
}