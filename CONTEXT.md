# NFOmenter: Technical Context for LLMs

## 1. System Overview
NFOmenter is a metadata management and filesystem virtualization layer for TubeArchivist (TA). It maps TA's internal YouTube-indexed storage to a human-readable "TV Show" structure via **Hardlinks** and **Kodi-formatted NFOs**.

### Stack
- **Backend:** Python 3.11, Flask (App Factory Pattern), SQLAlchemy (SQLite).
- **Frontend:** Tailwind CSS (CDN), Vanilla JS.
- **Production:** Gunicorn (Workers: 4), Port: `2960`.
- **Development:** Werkzeug Debug Server, Port: `2960`.

## 2. Infrastructure & Paths
Crucial: All Python logic uses **Container-Internal** paths.
- **Root Mount:** `/nas` (mapped from NAS storage).
- **Source (`SOURCE_DIR`):** TubeArchivist video root (e.g., `/nas/Docker/tubearchivist/youtube`).
- **Destination (`DEST_DIR`):** User-facing Media root (e.g., `/nas/Media/Video/Youtube/TubeArchivist`).
- **Cache (`CACHE_CH`/`CACHE_VID`):** TubeArchivist image assets.

## 3. Core Data Flow & State
1. **Discovery (`index`):** Fetches channels from TA API. Adds new IDs to DB. `is_eligible` defaults to `False`.
2. **Sync (`sync_all`):** For `is_eligible` channels, fetches all video metadata. Calculates `oldest_year` and `premiered` by sorting all videos. Idempotent check prevents duplicate `video.id` inserts.
3. **Staging (`save_override`):** User edits metadata. Logic compares input to "Base" metadata. If it matches base, the override is deleted (Inheritance restored). If it differs, a `MetadataOverride` is created.
4. **Export (`export_nfo`):** 
    - Triggers `sync_channel_folders` (Disk rename check).
    - Iterates DB. Resolves "Effective Metadata" (Source + Overrides).
    - Writes `tvshow.nfo` and episode `.nfo` files.
    - Performs `os.link` (Hardlink) from Source to Destination. No data is copied.

## 4. Logical Constraints
- **Source of Truth:** TubeArchivist API is authoritative for existence. Filesystem `tvshow.nfo` `<uniqueid>` is authoritative for directory identity.
- **Folder Naming:** Format: `{Sanitized Name} ({Oldest Year})`. Changes in metadata trigger directory renames via `shutil.move`.
- **Hardlink Rule:** Source and Destination **must** reside on the same physical filesystem/mount for `os.link` to function.
- **Deletion Safety:** Deletion is only permitted if `read_nfo_id()` on the target matches the database ID. Prevents accidental wipes of misconfigured paths.

## 5. UI/UX Logic
- **Single-Channel Editor:** Dual-pane. Left (Modified/DB) and Right (Source/TA). Synchronized scrolling via JS.
- **Multi-Channel Aggregator:** (Planned) 3-column layout. Far-left (Aggregated Shows List), Center (Show Builder), Right (Global TA Source).

## 6. Glossary (Project Specific)
- **Eligible:** Boolean. If `True`, the channel is processed for export. If `False`, it is purged from Destination.
- **Enabled:** Boolean. Individual video control.
- **Override:** A specific metadata field value stored in DB that breaks inheritance from TA.
- **Maintenance Task:** Manual sync operations (Deletion Sync, Folder Name Sync, Orphan Check).

## 7. Roadmap
### Short Term
- [x] **Secrets File:** Environments variables via `.env`.
- [x] **Docker Config:** Split `compose.yml` (Prod) and `compose-dev.yml` (Dev).
- [x] **Port Migration:** Standardized on `2960`.
- [ ] **Sort Channel List:** Alphabetical (case-insensitive) sorting in `index`.
- [ ] **Filter Toggles:** Hide ineligible channels in Single-Channel Editor.
- [ ] **UI Polish:** Fix scroll-bar overlap on toggles.

### Medium Term
- **Orphan Check:** Scan Destination for directories/files with no matching DB ID or missing `.nfo`.
- **Meta-Change Handler:** Strategy for when TA titles change upstream.
- **Automated Testing:** End-to-end sync/export tests.
- **Search:** Global filter for channel/video list.

### Long Term
- **Aggregator Logic:** N:1 conversion implementation.
- **LLM Summaries:** Episode descriptions via local LLM + transcripts.
- **DB Rebuild:** Use `.nfo` files as backup to restore local overrides on fresh install.

## 8. Logic Notes for LLM
- When modifying `app/utils.py`, always ensure `Path` objects are `.resolve()`'d when performing safety checks.
- `get_effective_metadata` is the central "Truth" function; it must always be used when generating XML or rendering the "Modified" side of the UI.
- The `MetadataOverride` table uses a string `target_id` which can represent either a `Channel.id` or a `Video.id`.
