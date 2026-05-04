// --- SYNC SCROLL ---
const lp = document.getElementById('left-pane');
const rp = document.getElementById('right-pane');

lp.addEventListener('scroll', () => { rp.scrollTop = lp.scrollTop; });
rp.addEventListener('scroll', () => { lp.scrollTop = rp.scrollTop; });
let activeId = null;

async function handleItemClick(el) {
    if (!el.dataset.id) return;
    activeId = el.dataset.id;
    const isChannel = activeId.startsWith('UC');
    const isEligible = !document.getElementById(`left-item-${activeId}`).classList.contains('is-dimmed');
    document.querySelectorAll('.item-row').forEach(r => r.classList.remove('selected-item'));
    document.getElementById(`left-item-${activeId}`).classList.add('selected-item');
    document.getElementById(`right-item-${activeId}`).classList.add('selected-item');
        
    // Toggle Manage Assets button visibility based on selection type
    const assetsBtn = document.getElementById('manage-assets-btn');
    if (assetsBtn) assetsBtn.classList.toggle('hidden', !(isChannel && isEligible));

    const data = await fetchMetadata(activeId);
    if (data) {
        renderMetadataFields(
            data, 
            isEligible, 
            document.getElementById('master-pane'), 
            document.getElementById('editor-pane'), 
            document.getElementById('editor-save-container')
        );
    }
}

async function handleSave() {
    if (!activeId) return;
    const r = await apiSaveMetadata(activeId);
    if (r.ok) {
        updateStatus("✅ Staged!");
        // Update local tree label immediately if title changed
        const titleInput = document.getElementById('edit-title');
        if (titleInput) {
            const label = document.querySelector(`#left-item-${activeId} .truncate span`);
            if (label) {
                label.textContent = titleInput.value;
                updateMarqueeState(label);
            }
        }
    }
}

function openAssetsModal() {
    document.getElementById('assetsModal').classList.remove('hidden');
}

async function toggleChannel(id, state) {
    const r = await apiToggleChannel(id, state);
    if (r.ok) window.location.reload();
}

async function toggleVideo(id, state) {
    const r = await apiToggleVideo(id, state);
    if (!r.ok) return;
        
    // Toggle dimming on BOTH sides
    document.getElementById(`left-item-${id}`).classList.toggle('is-dimmed', !state);
    document.getElementById(`right-item-${id}`).classList.toggle('is-dimmed', !state);
        
    if(document.getElementById(`left-item-${id}`).classList.contains('selected-item')) {
        handleItemClick(document.getElementById(`left-item-${id}`));
    }
}