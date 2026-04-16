import os, requests, glob, shutil, json
import xml.etree.ElementTree as ET
from pathlib import Path
from .models import db, MetadataOverride, Channel, Video

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
DEFAULT_SETTINGS = {
    "channel_naming_scheme": "{title} ({year})",
    "video_naming_scheme": "{showtitle} - {season}x{episode} - {title} [{id}]"
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

# --- HELPERS ---
def sanitize(name):
    if not name: return "Unknown"
    name = str(name).replace("..", "")  # Prevent path traversal
    for char in r'\/:*?"<>|': name = name.replace(char, "-")
    return " ".join(name.split()).strip()

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
        chan = Channel.query.get(db_item.channel_id)
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
    overrides = {o.field_name: o.new_value for o in MetadataOverride.query.filter_by(target_id=item_id).all()}
    
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
        chan = Channel.query.get(db_item.channel_id)
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
    
    for nfo_file in parent_dir.rglob("*.nfo"):
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
    
    for db_chan in Channel.query.all():
        if db_chan.id not in active_c_ids:
            deleted_log["channels"].append(db_chan.name)
            if not dry_run:
                # Remove from Destination
                for folder in id_map.get(db_chan.id, []):
                    safe_delete_channel_folder(folder, db_chan.id)
                # Remove from DB
                db.session.delete(db_chan)
    
    # 2. Sync Videos (Filesystem Snapshot)
    # We assume strict Source structure: SOURCE_DIR / channel_id / {id}*
    for db_chan in Channel.query.filter_by(is_eligible=True).all():
        src_chan_path = SOURCE_DIR / db_chan.id
        if not src_chan_path.exists(): continue

        # Optimization: Read directory ONCE per channel into memory
        try:
            src_filenames = set(os.listdir(src_chan_path))
        except OSError: continue

        for db_vid in Video.query.filter_by(channel_id=db_chan.id).all():
            # Fast check: Does any file in the list start with the Video ID?
            if not any(f.startswith(db_vid.id) for f in src_filenames):
                deleted_log["videos"].append(f"{db_vid.title} [{db_vid.id}]")
                if not dry_run:
                    for folder in id_map.get(db_chan.id, []):
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

    # 2. Compare against Database
    for chan in Channel.query.filter_by(is_eligible=True).all():
        expected_path = get_channel_dest_path(chan)
        expected_name = expected_path.name
        
        paths = disk_map.get(chan.id, [])
        if not paths:
            continue

        # 3. Identity & Duplicate Management
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

        # 4. Cleanup remaining duplicates (folders with the same UID but wrong names)
        for extra in paths:
            renamed_log.append(f"Duplicate found: Removing '{extra.name}' (Matches ID: {chan.id})")
            if not dry_run:
                safe_delete_channel_folder(extra, chan.id)

    return renamed_log