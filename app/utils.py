import os, requests, glob, shutil, json
import xml.etree.ElementTree as ET
from pathlib import Path
from .models import db, MetadataOverride, Channel, Video, AggregatedShow, AggregatedChannel, AggregatedVideo

# --- CONFIGURATION PATHS ---
TA_URL = os.getenv("TA_URL", "").strip().rstrip('/')
TA_TOKEN = os.getenv("TA_TOKEN", "").strip()
HEADERS = {'Authorization': f'Token {TA_TOKEN}', 'Accept': 'application/json'}

# --- FILE PATHS ---
DEST_DIR = Path(os.getenv("DEST_DIR"))
SOURCE_DIR = Path(os.getenv("SOURCE_DIR"))
CACHE_VID = Path(os.getenv("CACHE_VID"))
CACHE_CH = Path(os.getenv("CACHE_CH"))

# --- SETTINGS MANAGEMENT ---
DATA_DIR = Path(__file__).parent.parent / "data"
SETTINGS_PATH = DATA_DIR / "settings.json"
CUSTOM_ASSETS_DIR = DATA_DIR / "custom_assets"
DEFAULT_SETTINGS = {
    "channel_naming_scheme": "{title} ({year})",
    "video_naming_scheme": "{showtitle} - {season}x{episode} - {title} [{id}]",
    "last_aggregated_id": 0
}

def get_settings():
    if not SETTINGS_PATH.exists():
        save_settings(DEFAULT_SETTINGS)
        return DEFAULT_SETTINGS
    try:
        with open(SETTINGS_PATH, 'r') as f:
            return {**DEFAULT_SETTINGS, **json.load(f)}
    except:
        return DEFAULT_SETTINGS

def save_settings(settings):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_PATH, 'w') as f:
        json.dump(settings, f, indent=4)

def get_active_channel_ids():
    """
    Returns a unique set of channel IDs that require synchronization.
    This includes channels marked as 'is_eligible' in the Editor AND
    channels that have been added to any Aggregated Show.
    """
    eligible_ids = {c.id for c in db.session.scalars(db.select(Channel).filter_by(is_eligible=True)).all()}
    aggregated_ids = {ac.channel_id for ac in db.session.scalars(db.select(AggregatedChannel)).all()}
    return eligible_ids.union(aggregated_ids)

def get_next_aggregated_id():
    """
    Calculates the next unique AggregatedShow ID (AS_N) using a persistent counter.
    Ensures IDs are never reused even if the show is deleted.
    """
    settings = get_settings()
    last_id = settings.get("last_aggregated_id", 0)

    # Initial seeding: if the counter is 0, scan DB and filesystem for existing history
    if last_id == 0:
        # Scan Database
        for s in db.session.scalars(db.select(AggregatedShow)).all():
            if s.id and s.id.startswith("AS_"):
                try: last_id = max(last_id, int(s.id.split('_')[1]))
                except: continue
        
        # Scan Filesystem for orphaned custom asset folders
        if CUSTOM_ASSETS_DIR.exists():
            for item in CUSTOM_ASSETS_DIR.iterdir():
                if item.is_dir() and "[AS_" in item.name:
                    try:
                        num_str = item.name.split("[AS_")[-1].split("]")[0]
                        last_id = max(last_id, int(num_str))
                    except: continue

    next_id_num = last_id + 1
    settings["last_aggregated_id"] = next_id_num
    save_settings(settings)
    return f"AS_{next_id_num}"

# --- HELPERS ---
def sanitize(name):
    if not name: return "Unknown"
    name = str(name).replace("..", "")  # Prevent path traversal
    for char in r'\/:*?"<>|': name = name.replace(char, "-")
    return " ".join(name.split()).strip()

def export_video(show_root, video, v_meta, v_naming_scheme):
    """
    Handles the heavy lifting of exporting a single video:
    naming, collision detection, update/rename logic, hardlinking, and NFO writing.
    """
    v_vars = {
        'title': v_meta['title'], 'showtitle': v_meta['showtitle'],
        'season': v_meta['season'], 'episode': v_meta['episode'], 'id': video.id
    }
    base_fn = v_naming_scheme
    for k, val in v_vars.items():
        base_fn = base_fn.replace(f"{{{k}}}", sanitize(val))
    base_fn = " ".join(base_fn.split()).strip()

    season_dir = show_root / f"Season {v_meta['season']}"

    # Collision handling for video filenames
    potential_nfo = season_dir / f"{base_fn}.nfo"
    if potential_nfo.exists():
        existing_uid = read_nfo_id(potential_nfo)
        if existing_uid and existing_uid != video.id:
            # Name is taken by a different video; append ID if not already there
            if f"[{video.id}]" not in base_fn:
                base_fn = f"{base_fn} [{video.id}]"
    
    target_nfo = season_dir / f"{base_fn}.nfo"

    # Identify if an NFO for this video already exists somewhere in this show
    existing_nfo = None
    for nfo_file in show_root.rglob("*.nfo"):
        if nfo_file.name == "tvshow.nfo": continue
        if read_nfo_id(nfo_file) == video.id:
            existing_nfo = nfo_file
            break

    if existing_nfo:
        # If the NFO content is current and the file is in the right place, we're done.
        if not nfo_needs_update(existing_nfo, v_meta) and str(existing_nfo) == str(target_nfo):
            return
        else:
            # Metadata changed or location moved: wipe old files and re-export
            safe_cleanup_video(show_root, video.id)
    
    season_dir.mkdir(parents=True, exist_ok=True)
    
    # Create Links from Source (Video + Subtitles)
    src_f = SOURCE_DIR / video.channel_id
    for f in src_f.glob(f"{video.id}*"):
        if f.suffix.lower() in ['.mp4', '.vtt']:
            dest = season_dir / f"{base_fn}{f.suffix.lower()}"
            if not dest.exists(): os.link(f, dest)

    # Video Thumbnails
    t_src = CACHE_VID / video.id[0] / f"{video.id}.jpg"
    t_dest = season_dir / f"{base_fn}-thumb.jpg"
    if t_src.exists() and not t_dest.exists(): os.link(t_src, t_dest)

    write_xml(target_nfo, "episodedetails", v_meta)

def create_custom_asset_folder(item_id, name):
    """
    Creates or renames a uniquely identified folder in custom_assets for a show/channel.
    Ensures that if the show name changes, the folder is updated while keeping the same ID suffix.
    """
    safe_name = sanitize(name)
    desired_folder_name = f"{safe_name} [{item_id}]"
    target_path = CUSTOM_ASSETS_DIR / desired_folder_name

    if CUSTOM_ASSETS_DIR.exists():
        for item in CUSTOM_ASSETS_DIR.iterdir():
            # Check if the folder suffix matches [item_id]
            if item.is_dir() and item.name.endswith(f"[{item_id}]"):
                if item.name != desired_folder_name:
                    # ID found but name differs: rename it
                    item.rename(target_path)
                return desired_folder_name

    # No existing folder with this ID suffix found, create a new one
    target_path.mkdir(parents=True, exist_ok=True)
    return desired_folder_name

def export_show_assets(show_root, item_id, name, has_custom_assets):
    """
    Handles show-level assets (banner, poster, fanart).
    Priority: 1. Custom overrides in /data/custom_assets 
              2. Default TubeArchivist cache images (for YouTube channels)
    """
    expected_folder_name = f"{sanitize(name)} [{item_id}]"
    
    # Identify custom folder if enabled
    custom_folder = None
    if has_custom_assets and CUSTOM_ASSETS_DIR.exists():
        for item in CUSTOM_ASSETS_DIR.iterdir():
            if item.is_dir() and item.name.endswith(f"[{item_id}]"):
                if item.name != expected_folder_name:
                    # Rename folder to match current show name while keeping unique ID
                    custom_folder = CUSTOM_ASSETS_DIR / expected_folder_name
                    item.rename(custom_folder)
                else:
                    custom_folder = item
                break

    # Map for TA defaults (YouTube Channels only)
    ta_map = {
        "banner.jpg": f"{item_id}_banner.jpg",
        "poster.jpg": f"{item_id}_thumb.jpg",
        "fanart.jpg": f"{item_id}_tvart.jpg"
    } if item_id.startswith("UC") else {}

    for asset_name in ["banner.jpg", "poster.jpg", "fanart.jpg"]:
        dest = show_root / asset_name
        custom_src = custom_folder / asset_name if custom_folder else None
        
        # 1. Process Custom Override
        if custom_src and custom_src.exists():
            # Break any existing hardlinks to prevent poisoning the source cache
            if dest.exists(): os.remove(dest)
            shutil.copy2(custom_src, dest)
            continue

        # 2. Process Fallback to TA Default
        ta_src_name = ta_map.get(asset_name)
        if ta_src_name:
            ta_src = CACHE_CH / ta_src_name
            if ta_src.exists():
                # Link if missing OR if current file is not a link to this default
                is_correct = False
                if dest.exists():
                    try: is_correct = os.path.samefile(ta_src, dest)
                    except OSError: pass
                
                if not is_correct:
                    if dest.exists(): os.remove(dest)
                    try: os.link(ta_src, dest)
                    except: pass

def is_hardlink_compatible(path1, path2):
    """
    Tests if hardlinks can be created between path1 and path2.
    We attempt an actual link operation because st_dev can be misleading 
    in virtualized/Docker environments (like Docker Desktop).
    """
    try:
        p1, p2 = Path(path1).resolve(), Path(path2).resolve()
        
        # Find any existing file in p1 to use as a link source
        # next() on a generator is efficient and stops at the first match
        canary_src = next((f for f in p1.rglob('*') if f.is_file()), None)
        
        if not canary_src:
            # Fallback to device ID comparison if source is empty
            return p1.stat().st_dev == p2.stat().st_dev
            
        test_link = p2 / f".hl_test_{canary_src.name}"
        try:
            os.link(canary_src, test_link)
            os.remove(test_link)
            return True
        except OSError:
            return False
    except Exception:
        return False

def is_ta_youtube_structure(path):
    """
    Heuristic to detect if a path follows the TubeArchivist /youtube directory structure.
    1. Checks for a folder starting with 'UC' that is 24 characters long.
    2. Checks if that folder contains an .mp4 file with a stem exactly 11 characters long.
    """
    p = Path(path)
    if not p.is_dir():
        return False

    try:
        for channel_dir in p.iterdir():
            if channel_dir.is_dir() and channel_dir.name.startswith("UC") and len(channel_dir.name) == 24:
                # We found a potential channel folder, now look for a video
                for video_file in channel_dir.glob("*.mp4"):
                    if len(video_file.stem) == 11:
                        return True
    except OSError:
        pass
    return False

def get_ta_paginated(endpoint):
    results = []
    url = f"{TA_URL}/{endpoint.lstrip('/')}"
    if '?' not in url and not url.endswith('/'): url += '/'
    while url:
        try:
            # Fixed variable name to HEADERS
            r = requests.get(url, headers=HEADERS)
            r.raise_for_status()
            payload = r.json()
            results.extend(payload.get('data', []))
            pg = payload.get('paginate', {})
            
            if pg.get('current_page', 0) < pg.get('last_page', 0):
                base_req = f"{TA_URL}/{endpoint.lstrip('/')}"
                # Determine separator: use '&' if query params exist, otherwise '?'
                sep = '&' if '?' in base_req else '?'
                url = f"{base_req}{sep}page={pg['current_page'] + 1}"
            else: url = None
        except Exception as e:
            print(f"API Error: {e}")
            break
    return results

def write_xml(path, root_name, data_dict):
    root = ET.Element(root_name)
    for key, val in data_dict.items():
        child = ET.SubElement(root, key)
        if key == "uniqueid":
            child.set("type", "youtube"); child.set("default", "true")
        child.text = str(val) if val is not None else ""
    tree = ET.ElementTree(root)
    ET.indent(tree, space="    ", level=0)
    tree.write(str(path), encoding="utf-8", xml_declaration=True)

def get_folders_by_id():
    """Returns a map of {UniqueID: [List of Paths]} from DEST_DIR."""
    disk_map = {}
    if DEST_DIR.exists():
        for item in DEST_DIR.iterdir():
            if item.is_dir():
                nfo = item / "tvshow.nfo"
                uid = read_nfo_id(nfo)
                if uid:
                    disk_map.setdefault(uid, []).append(item)
    return disk_map

def get_channel_dest_path(chan):
    """Determines the intended destination folder path for a channel, handling collisions."""
    settings = get_settings()
    scheme = settings.get("channel_naming_scheme", "{title} ({year})")
    meta = get_effective_metadata(chan.id, 'channel', chan)
    
    # Resolve dynamic scheme
    vars = {'title': meta['title'], 'year': meta['year'], 'id': chan.id}
    standard_name = scheme
    for k, v in vars.items():
        standard_name = standard_name.replace(f"{{{k}}}", sanitize(v))
    
    standard_name = " ".join(standard_name.split()).strip()
    clean_path = DEST_DIR / standard_name
    if not clean_path.exists():
        return clean_path

    # Check if the existing folder belongs to this channel
    if read_nfo_id(clean_path / "tvshow.nfo") == chan.id:
        return clean_path

    # Collision detected - append ID for uniqueness if not already present in scheme
    if f"[{chan.id}]" not in standard_name:
        return DEST_DIR / f"{standard_name} [{chan.id}]"
    
    return clean_path

def get_aggregated_show_dest_path(show):
    """Determines the intended destination folder path for an aggregated show, handling collisions."""
    settings = get_settings()
    scheme = settings.get("channel_naming_scheme", "{title} ({year})")
    
    # Map show attributes to naming scheme variables
    vars = {'title': show.name, 'year': show.oldest_year, 'id': show.id}
    standard_name = scheme
    for k, v in vars.items():
        standard_name = standard_name.replace(f"{{{k}}}", sanitize(v))
    
    standard_name = " ".join(standard_name.split()).strip()
    clean_path = DEST_DIR / standard_name
    if not clean_path.exists():
        return clean_path

    # Check if the existing folder belongs to this aggregated show
    if read_nfo_id(clean_path / "tvshow.nfo") == show.id:
        return clean_path

    # Collision detected - append AS_N ID for uniqueness
    if f"[{show.id}]" not in standard_name:
        return DEST_DIR / f"{standard_name} [{show.id}]"
    
    return clean_path

def get_base_metadata(item_id, item_type, db_item):
    if item_type == 'channel':
        return {
            'title': db_item.name,
            'year': db_item.oldest_year,
            'plot': db_item.description,
            'premiered': db_item.premiered,
            'studio': db_item.studio,
            'uniqueid': db_item.id 
        }
    else:
        chan = db.session.get(Channel, db_item.channel_id)
        return {
            'title': db_item.title,
            'showtitle': chan.name,
            'season': db_item.season,
            'episode': db_item.episode,
            'plot': db_item.description,
            'aired': db_item.published_at,
            'studio': chan.studio,
            'uniqueid': db_item.id
        }

def get_effective_metadata(item_id, item_type, db_item):
    overrides = {o.field_name: o.new_value for o in db.session.scalars(db.select(MetadataOverride).filter_by(target_id=item_id)).all()}
    
    if item_type == 'channel':
        return {
            'title': overrides.get('title', db_item.name),
            'year': overrides.get('year', db_item.oldest_year),
            'plot': overrides.get('plot', db_item.description),
            'premiered': overrides.get('premiered', db_item.premiered),
            'studio': overrides.get('studio', db_item.studio),
            'uniqueid': db_item.id 
        }
    else:
        chan = db.session.get(Channel, db_item.channel_id)
        chan_meta = get_effective_metadata(chan.id, 'channel', chan)
        return {
            'title': overrides.get('title', db_item.title),
            'showtitle': chan_meta['title'],
            'season': overrides.get('season', db_item.season),
            'episode': overrides.get('episode', db_item.episode),
            'plot': overrides.get('plot', db_item.description),
            'aired': overrides.get('aired', db_item.published_at),
            'studio': chan_meta['studio'],
            'uniqueid': db_item.id
        }

def get_aggregated_metadata(show_id, video_id):
    show = db.session.get(AggregatedShow, show_id)
    v = db.session.get(Video, video_id)
    av = db.session.scalars(db.select(AggregatedVideo).filter_by(show_id=show_id, video_id=video_id)).first()
    
    return {
        'title': av.title if av.title is not None else v.title,
        'showtitle': show.name,
        'season': av.season if av.season is not None else v.season,
        'episode': av.episode if av.episode is not None else v.episode,
        'plot': av.description if av.description is not None else v.description,
        'aired': av.published_at if av.published_at is not None else v.published_at,
        'studio': show.studio,
        'uniqueid': v.id
    }

# --- SAFETY HELPERS ---
def read_nfo_id(nfo_path):
    try:
        tree = ET.parse(nfo_path)
        root = tree.getroot()
        uid = root.find('uniqueid')
        if uid is not None: return uid.text
    except: pass
    return None

def safe_delete_channel_folder(folder_path, expected_id):
    """
    Surgically deletes a channel folder ONLY if it matches the expected ID
    and is located strictly within the configured Destination directory.
    """
    try:
        target = Path(folder_path).resolve()
        dest_root = DEST_DIR.resolve()

        # 1. Scope Check: Ensure target is inside DEST_DIR
        if not target.is_relative_to(dest_root):
            print(f"SAFETY CHECK FAIL: {target} is outside destination root.")
            return False

        # 2. Root Check: Ensure we aren't deleting the root itself
        if target == dest_root:
            print("SAFETY CHECK FAIL: Attempt to delete destination root.")
            return False

        # 3. Identity Check: Verify tvshow.nfo exists and ID matches
        nfo_path = target / "tvshow.nfo"
        if not nfo_path.exists() or read_nfo_id(nfo_path) != expected_id:
            print(f"SAFETY CHECK FAIL: Identity mismatch or missing NFO in {target}")
            return False

        shutil.rmtree(target)
        return True
    except Exception as e:
        print(f"Delete Error: {e}")
        return False

def safe_cleanup_video(parent_dir, target_id):
    parent = Path(parent_dir).resolve()
    # Safety: ensure strict boundary check
    if not parent.exists() or not parent.is_relative_to(DEST_DIR.resolve()): return
    
    # Use list() to build the collection before mutation to avoid iterator crashes
    # when Season folders are deleted.
    try:
        nfo_files = list(parent_dir.rglob("*.nfo"))
    except FileNotFoundError:
        # parent_dir itself or a subdirectory was removed during the scan
        return

    for nfo_file in nfo_files:
        if nfo_file.name == "tvshow.nfo": continue
        if read_nfo_id(nfo_file) == target_id:
            stem = nfo_file.stem 
            folder = nfo_file.parent
            # CHANGED: Use .* to ensure we match extensions, preventing prefix collisions
            # e.g., "Video [1]" should not match "Video [1] - Part 2"
            pattern = f"{glob.escape(str(folder / stem))}.*"
            for matching_file in glob.glob(pattern):
                try: os.remove(matching_file)
                except: pass
            thumb_pattern = f"{glob.escape(str(folder / stem))}-thumb*"
            for thumb in glob.glob(thumb_pattern):
                try: os.remove(thumb)
                except: pass
            # Attempt to remove the parent folder (e.g. Season folder) if it is now empty
            try:
                if folder.resolve() != parent and not any(folder.iterdir()):
                    folder.rmdir()
            except: pass
            break # Video found and purged, stop searching this tree

def normalize_text(text):
    if not text: return ""
    return " ".join(str(text).split())

def nfo_needs_update(nfo_path, current_meta):
    if not nfo_path.exists(): return True
    try:
        tree = ET.parse(nfo_path)
        root = tree.getroot()
        for key, val in current_meta.items():
            tag_node = root.find(key)
            # If tag is missing or text mismatch, we need an update
            if tag_node is None: 
                return True
            
            existing_val = normalize_text(tag_node.text) if tag_node.text else ""
            new_val = normalize_text(val) if val else ""

            # Special check for titles to avoid loops caused by sanitization
            if key == 'title' and sanitize(existing_val) == sanitize(new_val):
                continue
            if existing_val != new_val:
                return True
        return False 
    except: return True

def scan_for_deletions(dry_run=True):
    """
    Efficiently detects items deleted from Source and removes them from DB/Destination.
    Strategy: 
    1. Channels: API Check (Cheap, Authoritative).
    2. Videos: Directory Snapshot (Fast I/O, minimizes Disk Seeks).
    """
    deleted_log = {"channels": [], "videos": []}
    id_map = get_folders_by_id()
    
    # 1. Sync Channels (API is cheaper than checking folders for metadata)
    api_channels = get_ta_paginated("api/channel")
    active_c_ids = {c['channel_id'] for c in api_channels}
    
    for db_chan in db.session.scalars(db.select(Channel)).all():
        if db_chan.id not in active_c_ids:
            deleted_log["channels"].append(db_chan.name)
            if not dry_run:
                # Remove from Destination
                for folder in id_map.get(db_chan.id, []):
                    safe_delete_channel_folder(folder, db_chan.id)
                # Remove from DB
                db.session.delete(db_chan)
    
    # 1b. Sync Aggregated Shows (Identify orphaned folders on disk)
    active_as_ids = {s.id for s in db.session.scalars(db.select(AggregatedShow)).all()}
    # Iterate through folders on disk that have AS_ IDs
    for uid, folders in id_map.items():
        if uid.startswith("AS_") and uid not in active_as_ids:
            for folder in folders:
                deleted_log["channels"].append(f"Aggregated Show: {folder.name}")
                if not dry_run:
                    # safe_delete handles the NFO check and path scoping
                    safe_delete_channel_folder(folder, uid)

    # 2. Sync Videos (Filesystem Snapshot)
    # We assume strict Source structure: SOURCE_DIR / channel_id / {id}*
    active_ids = get_active_channel_ids()
    active_channels = db.session.scalars(db.select(Channel).where(Channel.id.in_(active_ids))).all()
    for db_chan in active_channels:
        src_chan_path = SOURCE_DIR / db_chan.id
        if not src_chan_path.exists(): continue

        # Optimization: Read directory ONCE per channel into memory
        try:
            src_filenames = set(os.listdir(src_chan_path))
        except OSError: continue

        for db_vid in db.session.scalars(db.select(Video).filter_by(channel_id=db_chan.id)).all():
            # Fast check: Does any file in the list start with the Video ID?
            if not any(f.startswith(db_vid.id) for f in src_filenames):
                deleted_log["videos"].append(f"{db_vid.title} [{db_vid.id}]")
                if not dry_run:
                    # Purge from ALL destination folders (1:1 and Aggregated)
                    for folders in id_map.values():
                        for folder in folders:
                            safe_cleanup_video(folder, db_vid.id)
                    db.session.delete(db_vid)

    if not dry_run:
        db.session.commit()
        
    return deleted_log

def sync_channel_folders(dry_run=True):
    """
    Scans DEST_DIR for channels that have moved or changed names/years 
    compared to the DB, and renames the folders on disk to match.
    """
    renamed_log = []
    
    # 1. Build Map of {UniqueID: [List of Paths]} from disk to detect duplicates
    disk_map = get_folders_by_id()

    # 2. Build a unified list of sync targets (Channels and Aggregated Shows)
    targets = []
    for chan in db.session.scalars(db.select(Channel).filter_by(is_eligible=True)).all():
        targets.append((chan.id, get_channel_dest_path(chan)))
    for show in db.session.scalars(db.select(AggregatedShow).filter_by(is_active=True)).all():
        targets.append((show.id, get_aggregated_show_dest_path(show)))

    # 3. Compare against Database
    for target_id, expected_path in targets:
        expected_name = expected_path.name
        
        paths = disk_map.get(target_id, [])
        if not paths:
            continue

        # Check if we already have a folder that matches the expected path
        correct_folder = next((p for p in paths if p.resolve() == expected_path.resolve()), None)
        
        if not correct_folder:
            # No folder matches the expected name. Rename the first one we found.
            primary = paths.pop(0)
            renamed_log.append(f"Renaming: '{primary.name}' -> '{expected_name}'")
            if not dry_run:
                try: shutil.move(primary, expected_path)
                except Exception as e: print(f"Rename failed: {e}")
        else:
            # We found the correct folder. Remove it from the list so we don't "clean it up"
            paths.remove(correct_folder)

        # 4. Cleanup remaining duplicates (folders with the same ID but wrong names)
        for extra in paths:
            renamed_log.append(f"Duplicate found: Removing '{extra.name}' (Matches ID: {target_id})")
            if not dry_run:
                safe_delete_channel_folder(extra, target_id)

    return renamed_log