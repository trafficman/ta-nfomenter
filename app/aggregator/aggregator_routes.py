from flask import Blueprint, render_template
from sqlalchemy import func
from app.models import db, Channel, Video, MetadataOverride
from app.utils import get_ta_paginated

aggregator_bp = Blueprint('aggregator', __name__, template_folder='templates')

@aggregator_bp.route('/')
def index():
    # Initial discovery logic mirrored from the single-channel editor
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

    # Batch fetch title overrides to show custom names in the Aggregated Preview (left pane)
    title_overrides = {o.target_id: o.new_value for o in MetadataOverride.query.filter_by(field_name='title').all()}

    channels = Channel.query.order_by(func.lower(Channel.name)).all()
    all_videos = Video.query.order_by(Video.published_at.desc()).all()
    
    video_map = {}
    for v in all_videos:
        video_map.setdefault(v.channel_id, []).append(v)

    return render_template('aggregator.html', channels=channels, video_map=video_map, title_overrides=title_overrides)