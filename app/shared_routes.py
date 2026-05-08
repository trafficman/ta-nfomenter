import os
from flask import Blueprint, jsonify, request
from .models import db, Channel, Video, AggregatedShow, AggregatedChannel, AggregatedVideo
from .utils import (
    get_settings, save_settings, get_ta_paginated, get_active_channel_ids,
    get_effective_metadata, get_base_metadata, sync_channel_folders,
    get_channel_dest_path, safe_delete_channel_folder, nfo_needs_update,
    write_xml, CACHE_CH, sanitize, read_nfo_id, safe_cleanup_video,
    SOURCE_DIR, CACHE_VID, get_aggregated_show_dest_path, get_aggregated_metadata,
    scan_for_deletions, create_custom_asset_folder, export_video, export_show_assets
)

main_bp = Blueprint('main', __name__)

@main_bp.route('/api/settings', methods=['GET'])
def get_app_settings():
    return jsonify(get_settings())

@main_bp.route('/api/settings', methods=['POST'])
def update_app_settings():
    data = request.json
    # In the future, we can add validation here
    save_settings(data)
    return jsonify({"status": "success"})

@main_bp.route('/api/get_metadata/<item_id>')
def get_metadata(item_id):
    chan = db.session.get(Channel, item_id)
    if chan: 
        return jsonify({
            "effective": get_effective_metadata(chan.id, 'channel', chan),
            "source": get_base_metadata(chan.id, 'channel', chan)
        })
    vid = db.session.get(Video, item_id)
    if vid: 
        return jsonify({
            "effective": get_effective_metadata(vid.id, 'video', vid),
            "source": get_base_metadata(vid.id, 'video', vid)
        })
    return jsonify({"error": "not found"}), 404

@main_bp.route('/api/sync_all', methods=['POST'])
def sync_all():
    active_ids = get_active_channel_ids()
    active_channels = db.session.scalars(db.select(Channel).where(Channel.id.in_(active_ids))).all()
    
    for chan in active_channels:
        v_data = get_ta_paginated(f"api/video/?channel={chan.id}")
        if v_data:
            # Fetch existing IDs for this channel once to optimize syncing
            existing_ids = {v.id for v in db.session.scalars(db.select(Video).filter_by(channel_id=chan.id)).all()}

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

@main_bp.route('/api/export', methods=['POST'])
def export_nfo():
    # Ensure folder names on disk match current DB metadata (handles name/year changes)
    settings = get_settings()
    sync_channel_folders(dry_run=False)

    # --- PHASE 1: Single-Channel Editor Export (1:1) ---
    all_channels = db.session.scalars(db.select(Channel)).all()
    
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

        # Handle show-level images (Defaults + Custom Overrides)
        export_show_assets(show_root, chan.id, chan.has_custom_assets)

        videos = db.session.scalars(db.select(Video).filter_by(channel_id=chan.id)).all()
        for v in videos:
            if not v.is_enabled:
                safe_cleanup_video(show_root, v.id)
                continue

            v_meta = get_effective_metadata(v.id, 'video', v)
            v_scheme = settings.get("video_naming_scheme", "{showtitle} - {season}x{episode} - {title} [{id}]")
            export_video(show_root, v, v_meta, v_scheme)

    # --- PHASE 2: Multi-Channel Aggregator Export (N:1) ---
    all_agg_shows = db.session.scalars(db.select(AggregatedShow)).all()
    for show in all_agg_shows:
        show_root = get_aggregated_show_dest_path(show)
        
        if not show.is_active:
            if show_root.exists():
                safe_delete_channel_folder(show_root, show.id)
            continue

        show_root.mkdir(parents=True, exist_ok=True)
        
        # Write tvshow.nfo
        s_meta = {
            'title': show.name, 'year': show.oldest_year, 'plot': show.description,
            'premiered': show.premiered, 'studio': show.studio, 'uniqueid': show.id
        }
        show_nfo_path = show_root / "tvshow.nfo"
        if nfo_needs_update(show_nfo_path, s_meta):
            write_xml(show_nfo_path, "tvshow", s_meta)

        # Handle show-level images (Custom Overrides)
        export_show_assets(show_root, show.id, show.has_custom_assets)

        # Identify channels disabled specifically for this aggregated show
        disabled_channel_ids = set(db.session.scalars(
            db.select(AggregatedChannel.channel_id)
            .filter_by(show_id=show.id, is_enabled=False)
        ).all())

        # Process Aggregated Episodes
        agg_vids = db.session.scalars(db.select(AggregatedVideo).filter_by(show_id=show.id)).all()
        
        # Orphan Cleanup: Remove videos from disk that are no longer joined to this show
        valid_vid_ids = {av.video_id for av in agg_vids}
        if show_root.exists():
            for nfo_file in list(show_root.rglob("*.nfo")):
                if nfo_file.name == "tvshow.nfo": continue
                vid_id = read_nfo_id(nfo_file)
                if vid_id and vid_id not in valid_vid_ids:
                    safe_cleanup_video(show_root, vid_id)

        for av in agg_vids:
            v = db.session.get(Video, av.video_id)
            if not v: continue

            # Respect is_enabled flags for both the specific video join and the parent channel join
            if not av.is_enabled or v.channel_id in disabled_channel_ids:
                safe_cleanup_video(show_root, v.id)
                continue
            
            v_meta = get_aggregated_metadata(show.id, v.id)
            v_scheme = settings.get("video_naming_scheme", "{showtitle} - {season}x{episode} - {title} [{id}]")
            export_video(show_root, v, v_meta, v_scheme)
            
    return jsonify({"status": "success"})

@main_bp.route('/api/scan_deletions', methods=['POST'])
def run_deletion_scan():
    # Default to Dry Run (Safe Mode) unless explicitly confirmed
    # Usage of (request.json or {}) handles cases where body is empty/None
    data = request.json or {}
    dry_run = data.get('dry_run', True)
    report = scan_for_deletions(dry_run=dry_run)
    return jsonify({"status": "success", "report": report})

@main_bp.route('/api/sync_folders', methods=['POST'])
def run_folder_sync():
    data = request.json or {}
    dry_run = data.get('dry_run', True)
    report = sync_channel_folders(dry_run=dry_run)
    return jsonify({"status": "success", "report": report})

@main_bp.route('/api/refresh_metadata', methods=['POST'])
def refresh_metadata():
    data = request.json or {}
    dry_run = data.get('dry_run', True)
    report = {"channels": [], "videos": []}
    
    # 1. Refresh Channels
    raw_channels = get_ta_paginated("api/channel")
    for c in raw_channels:
        chan = db.session.get(Channel, c['channel_id'])
        if chan:
            changed = (chan.name != c['channel_name'] or 
                       chan.description != c.get('channel_description', ''))
            if changed:
                report["channels"].append(f"{chan.name} (Updated title/desc)")
                if not dry_run:
                    chan.name = c['channel_name']
                    chan.description = c.get('channel_description', '')

    # 2. Refresh Videos for all active channels (Editor eligible or Aggregator joined)
    active_ids = get_active_channel_ids()
    active_channels = db.session.scalars(db.select(Channel).where(Channel.id.in_(active_ids))).all()
    for chan in active_channels:
        v_data = get_ta_paginated(f"api/video/?channel={chan.id}")
        for v in v_data:
            vid = db.session.get(Video, v.get('youtube_id'))
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

@main_bp.route('/api/create_asset_folder', methods=['POST'])
def create_asset_folder():
    data = request.json
    item_id = data.get('id')
    name = data.get('name')
    if not item_id or not name:
        return jsonify({"status": "error", "message": "Missing ID or Name"}), 400
    
    folder_name = create_custom_asset_folder(item_id, name)

    # Update database flag for the channel or show
    chan = db.session.get(Channel, item_id)
    if chan:
        chan.has_custom_assets = True
    else:
        show = db.session.get(AggregatedShow, item_id)
        if show:
            show.has_custom_assets = True

    db.session.commit()
    return jsonify({"status": "success", "folder": folder_name})