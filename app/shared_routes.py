from flask import Blueprint, jsonify, request
from .models import db, Channel, Video
from .utils import get_settings, save_settings, get_ta_paginated, get_active_channel_ids

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

@main_bp.route('/api/sync_all', methods=['POST'])
def sync_all():
    active_ids = get_active_channel_ids()
    active_channels = Channel.query.filter(Channel.id.in_(active_ids)).all()
    
    for chan in active_channels:
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