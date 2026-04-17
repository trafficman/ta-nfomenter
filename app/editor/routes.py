import os
import shutil
from flask import Blueprint, render_template, jsonify, request
from sqlalchemy import func
from app.models import db, Channel, Video, MetadataOverride
from app.utils import (
    get_ta_paginated, get_effective_metadata, write_xml, 
    safe_cleanup_video, safe_delete_channel_folder, scan_for_deletions, sync_channel_folders, get_base_metadata,
    nfo_needs_update, sanitize, normalize_text, read_nfo_id, DEST_DIR, SOURCE_DIR, CACHE_CH, CACHE_VID, get_channel_dest_path, get_settings
)

editor_bp = Blueprint('editor', __name__, template_folder='templates')

@editor_bp.route('/')
def index():
    raw = get_ta_paginated("api/channel")
    for c in raw:
        if not Channel.query.get(c['channel_id']):
            db.session.add(Channel(
                id=c['channel_id'], 
                name=c['channel_name'], 
                description=c.get('channel_description', ''), 
                is_eligible=False,
                oldest_year="2005"
            ))
    db.session.commit()
    
    # Batch fetch title overrides to show custom names in the Modified Layer (left pane)
    title_overrides = {o.target_id: o.new_value for o in MetadataOverride.query.filter_by(field_name='title').all()}

    channels = Channel.query.order_by(func.lower(Channel.name)).all()
    # Sort Newest First
    all_videos = Video.query.order_by(Video.published_at.desc()).all()
    
    video_map = {}
    for v in all_videos:
        video_map.setdefault(v.channel_id, []).append(v)

    return render_template('editor.html', channels=channels, video_map=video_map, title_overrides=title_overrides)

@editor_bp.route('/api/sync_all', methods=['POST'])
def sync_all():
    eligible = Channel.query.filter_by(is_eligible=True).all()
    for chan in eligible:
        v_data = get_ta_paginated(f"api/video/?channel={chan.id}")
        if v_data:
            # Fetch existing IDs for this channel once to optimize syncing
            existing_ids = {v.id for v in Video.query.filter_by(channel_id=chan.id).all()}

            v_data.sort(key=lambda x: x.get('published', '9999'))
            chan.premiered = v_data[0].get('published', '')[:10]
            chan.oldest_year = chan.premiered[:4] if chan.premiered else "2005"
            
            for v in v_data:
                vid_id = v.get('youtube_id')
                if vid_id not in existing_ids:
                    pub = v.get('published', '')[:10]
                    db.session.add(Video(
                        id=vid_id, channel_id=chan.id, title=v.get('title'),
                        description=v.get('description', ''), published_at=pub,
                        season=pub[:4], episode=pub[5:7] + pub[8:10], 
                        is_enabled=True
                    ))
                    # Prevent duplicates if the API returns the same video ID multiple times
                    existing_ids.add(vid_id)
    db.session.commit()
    return jsonify({"status": "success"})

@editor_bp.route('/api/get_metadata/<item_id>')
def get_metadata(item_id):
    chan = Channel.query.get(item_id)
    if chan: 
        return jsonify({
            "effective": get_effective_metadata(chan.id, 'channel', chan),
            "source": get_base_metadata(chan.id, 'channel', chan)
        })
    vid = Video.query.get(item_id)
    if vid: 
        return jsonify({
            "effective": get_effective_metadata(vid.id, 'video', vid),
            "source": get_base_metadata(vid.id, 'video', vid)
        })
    return jsonify({"error": "not found"}), 404

@editor_bp.route('/api/save_override', methods=['POST'])
def save_override():
    data = request.json
    target_id = data['id']
    
    # Identify if the target is a Channel or Video to get "Base" values
    item = Channel.query.get(target_id) or Video.query.get(target_id)
    if not item:
        return jsonify({"error": "not found"}), 404

    # Define the mapping between NFO field names and DB model attributes
    if isinstance(item, Channel):
        base_vals = {
            'title': item.name, 'year': item.oldest_year,
            'plot': item.description, 'premiered': item.premiered,
            'studio': item.studio
        }
    else:
        base_vals = {
            'title': item.title, 'season': item.season,
            'episode': item.episode, 'plot': item.description,
            'aired': item.published_at
        }

    # Define allowed fields to prevent database bloat/unintended overrides
    allowed_fields = {'title', 'showtitle', 'season', 'episode', 'plot', 'aired', 'premiered', 'year', 'studio'}

    for field, val in data['fields'].items():
        if field not in allowed_fields:
            continue
            
        override = MetadataOverride.query.filter_by(target_id=target_id, field_name=field).first()
        
        # Compare normalized versions to see if user effectively reverted to source
        is_source_match = normalize_text(val) == normalize_text(base_vals.get(field))

        if is_source_match:
            # If it matches source, we don't need an override entry at all
            if override:
                db.session.delete(override)
        else:
            # Only create/update if it actually differs from Source
            if override: override.new_value = val
            else: db.session.add(MetadataOverride(target_id=target_id, field_name=field, new_value=val))
            
    db.session.commit()
    return jsonify({"status": "success"})

@editor_bp.route('/api/export', methods=['POST'])
def export_nfo():
    # Ensure folder names on disk match current DB metadata (handles name/year changes)
    settings = get_settings()
    sync_channel_folders(dry_run=False)

    all_channels = Channel.query.all()
    
    for chan in all_channels:
        c_meta = get_effective_metadata(chan.id, 'channel', chan)
        show_root = get_channel_dest_path(chan)

        if not chan.is_eligible:
            if show_root.exists():
                safe_delete_channel_folder(show_root, chan.id)
            continue

        show_root.mkdir(parents=True, exist_ok=True)
        
        chan_nfo_path = show_root / "tvshow.nfo"
        if nfo_needs_update(chan_nfo_path, c_meta):
            write_xml(chan_nfo_path, "tvshow", c_meta)

        art_map = {f"{chan.id}_banner.jpg": "banner.jpg", f"{chan.id}_thumb.jpg": "poster.jpg", f"{chan.id}_tvart.jpg": "fanart.jpg"}
        for src_n, dest_n in art_map.items():
            src, dest = CACHE_CH / src_n, show_root / dest_n
            if src.exists() and not dest.exists(): os.link(src, dest)

        videos = Video.query.filter_by(channel_id=chan.id).all()
        for v in videos:
            v_scheme = settings.get("video_naming_scheme", "{showtitle} - {season}x{episode} - {title} [{id}]")
            v_meta = get_effective_metadata(v.id, 'video', v)
            
            v_vars = {
                'title': v_meta['title'], 'showtitle': v_meta['showtitle'],
                'season': v_meta['season'], 'episode': v_meta['episode'], 'id': v.id
            }
            base_fn = v_scheme
            for k, val in v_vars.items():
                base_fn = base_fn.replace(f"{{{k}}}", sanitize(val))
            base_fn = " ".join(base_fn.split()).strip()

            season_dir = show_root / f"Season {v_meta['season']}"

            # Collision handling for video filenames
            potential_nfo = season_dir / f"{base_fn}.nfo"
            if potential_nfo.exists():
                existing_uid = read_nfo_id(potential_nfo)
                if existing_uid and existing_uid != v.id:
                    # Name is taken by a different video; append ID if not already there
                    if f"[{v.id}]" not in base_fn:
                        base_fn = f"{base_fn} [{v.id}]"
            
            target_nfo = season_dir / f"{base_fn}.nfo"

            if not v.is_enabled:
                safe_cleanup_video(show_root, v.id)
                continue

            existing_nfo = None
            for nfo_file in show_root.rglob("*.nfo"):
                if nfo_file.name == "tvshow.nfo": continue
                if read_nfo_id(nfo_file) == v.id:
                    existing_nfo = nfo_file
                    break

            if existing_nfo:
                # Normalize paths for comparison
                if not nfo_needs_update(existing_nfo, v_meta) and str(existing_nfo) == str(target_nfo):
                    continue
                else:
                    print(f"Update/Rename required for {v.id}. Processing...")
                    safe_cleanup_video(show_root, v.id)
            
            season_dir.mkdir(exist_ok=True)
            
            src_f = SOURCE_DIR / chan.id
            for f in src_f.glob(f"{v.id}*"):
                if f.suffix.lower() in ['.mp4', '.vtt']:
                    dest = season_dir / f"{base_fn}{f.suffix.lower()}"
                    if not dest.exists(): os.link(f, dest)

            t_src = CACHE_VID / v.id[0] / f"{v.id}.jpg"
            t_dest = season_dir / f"{base_fn}-thumb.jpg"
            if t_src.exists() and not t_dest.exists(): os.link(t_src, t_dest)

            write_xml(target_nfo, "episodedetails", v_meta)
            
    return jsonify({"status": "success"})

@editor_bp.route('/api/toggle_channel', methods=['POST'])
def toggle_channel():
    data = request.json
    c = Channel.query.get(data['id'])
    if c: c.is_eligible = data['state']; db.session.commit()
    return jsonify({"status": "success"})

@editor_bp.route('/api/toggle_video', methods=['POST'])
def toggle_video():
    data = request.json
    v = Video.query.get(data['id'])
    if v: v.is_enabled = data['state']; db.session.commit()
    return jsonify({"status": "success"})

@editor_bp.route('/api/scan_deletions', methods=['POST'])
def run_deletion_scan():
    # Default to Dry Run (Safe Mode) unless explicitly confirmed
    # Usage of (request.json or {}) handles cases where body is empty/None
    data = request.json or {}
    dry_run = data.get('dry_run', True)
    report = scan_for_deletions(dry_run=dry_run)
    return jsonify({"status": "success", "report": report})

@editor_bp.route('/api/sync_folders', methods=['POST'])
def run_folder_sync():
    data = request.json or {}
    dry_run = data.get('dry_run', True)
    report = sync_channel_folders(dry_run=dry_run)
    return jsonify({"status": "success", "report": report})

@editor_bp.route('/api/refresh_metadata', methods=['POST'])
def refresh_metadata():
    data = request.json or {}
    dry_run = data.get('dry_run', True)
    report = {"channels": [], "videos": []}
    
    # 1. Refresh Channels
    raw_channels = get_ta_paginated("api/channel")
    for c in raw_channels:
        chan = Channel.query.get(c['channel_id'])
        if chan:
            changed = (chan.name != c['channel_name'] or 
                       chan.description != c.get('channel_description', ''))
            if changed:
                report["channels"].append(f"{chan.name} (Updated title/desc)")
                if not dry_run:
                    chan.name = c['channel_name']
                    chan.description = c.get('channel_description', '')

    # 2. Refresh Videos for eligible channels
    eligible = Channel.query.filter_by(is_eligible=True).all()
    for chan in eligible:
        v_data = get_ta_paginated(f"api/video/?channel={chan.id}")
        for v in v_data:
            vid = Video.query.get(v.get('youtube_id'))
            if vid:
                pub = v.get('published', '')[:10]
                changed = (vid.title != v.get('title') or 
                           vid.description != v.get('description', '') or
                           vid.published_at != pub)
                if changed:
                    report["videos"].append(f"{vid.title} (Updated metadata)")
                    if not dry_run:
                        vid.title = v.get('title')
                        vid.description = v.get('description', '')
                        vid.published_at = pub
                        vid.season = pub[:4]
                        vid.episode = pub[5:7] + pub[8:10]
    
    if not dry_run:
        db.session.commit()
    
    return jsonify({"status": "success", "report": report})