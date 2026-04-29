from flask import Blueprint, render_template, jsonify, request
from sqlalchemy import func
from app.models import db, Channel, Video, MetadataOverride
from app.utils import (
    get_ta_paginated, normalize_text
)

editor_bp = Blueprint('editor', __name__, template_folder='templates')

@editor_bp.route('/')
def index():
    raw = get_ta_paginated("api/channel")
    for c in raw:
        if not db.session.get(Channel, c['channel_id']):
            db.session.add(Channel(
                id=c['channel_id'], 
                name=c['channel_name'], 
                description=c.get('channel_description', ''), 
                is_eligible=False,
                oldest_year="2005"
            ))
    db.session.commit()
    
    # Batch fetch title overrides to show custom names in the Modified Layer (left pane)
    title_overrides = {o.target_id: o.new_value for o in db.session.scalars(db.select(MetadataOverride).filter_by(field_name='title')).all()}

    channels = db.session.scalars(db.select(Channel).order_by(func.lower(Channel.name))).all()
    # Sort Newest First
    all_videos = db.session.scalars(db.select(Video).order_by(Video.published_at.desc())).all()
    
    video_map = {}
    for v in all_videos:
        video_map.setdefault(v.channel_id, []).append(v)

    return render_template('editor.html', channels=channels, video_map=video_map, title_overrides=title_overrides)

@editor_bp.route('/api/save_override', methods=['POST'])
def save_override():
    data = request.json
    target_id = data['id']
    
    # Identify if the target is a Channel or Video to get "Base" values
    item = db.session.get(Channel, target_id) or db.session.get(Video, target_id)
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
            
        override = db.session.scalars(db.select(MetadataOverride).filter_by(target_id=target_id, field_name=field)).first()
        
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

@editor_bp.route('/api/toggle_channel', methods=['POST'])
def toggle_channel():
    data = request.json
    c = db.session.get(Channel, data['id'])
    if c: c.is_eligible = data['state']; db.session.commit()
    return jsonify({"status": "success"})

@editor_bp.route('/api/toggle_video', methods=['POST'])
def toggle_video():
    data = request.json
    v = db.session.get(Video, data['id'])
    if v: v.is_enabled = data['state']; db.session.commit()
    return jsonify({"status": "success"})