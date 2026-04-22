from flask import Blueprint, render_template, request, jsonify
from sqlalchemy import func
from app.models import db, Channel, Video, AggregatedShow, AggregatedChannel, AggregatedVideo
from app.utils import get_ta_paginated, get_next_aggregated_id

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

    channels = Channel.query.order_by(func.lower(Channel.name)).all()
    all_videos = Video.query.order_by(Video.published_at.desc()).all()
    aggregated_shows = AggregatedShow.query.order_by(AggregatedShow.name).all()
    
    video_map = {}
    for v in all_videos:
        video_map.setdefault(v.channel_id, []).append(v)

    return render_template('aggregator.html', channels=channels, video_map=video_map, aggregated_shows=aggregated_shows)

@aggregator_bp.route('/api/create_show', methods=['POST'])
def create_show():
    data = request.json
    name = data.get('name')
    if not name:
        return jsonify({"status": "error", "message": "Show name is required"}), 400
    
    new_id = get_next_aggregated_id()
    premiered = data.get('premiered', '')
    oldest_year = premiered[:4] if premiered and len(premiered) >= 4 else "2005"

    show = AggregatedShow(
        id=new_id,
        name=name,
        description=data.get('description', ''),
        studio=data.get('studio', 'YouTube'),
        premiered=premiered,
        oldest_year=oldest_year
    )
    
    db.session.add(show)
    db.session.commit()
    
    return jsonify({"status": "success", "id": new_id, "name": name})

@aggregator_bp.route('/api/get_show/<show_id>')
def get_show(show_id):
    show = AggregatedShow.query.get(show_id)
    if not show:
        return jsonify({"status": "error", "message": "Show not found"}), 404
    return jsonify({
        "id": show.id,
        "name": show.name,
        "description": show.description,
        "studio": show.studio,
        "premiered": show.premiered
    })

@aggregator_bp.route('/api/update_show/<show_id>', methods=['POST'])
def update_show(show_id):
    show = AggregatedShow.query.get(show_id)
    if not show:
        return jsonify({"status": "error", "message": "Show not found"}), 404
        
    data = request.json
    show.name = data.get('name', show.name)
    show.description = data.get('description', show.description)
    show.studio = data.get('studio', show.studio)
    show.premiered = data.get('premiered', show.premiered)
    
    if show.premiered and len(show.premiered) >= 4:
        show.oldest_year = show.premiered[:4]

    db.session.commit()
    return jsonify({"status": "success"})

@aggregator_bp.route('/api/delete_show/<show_id>', methods=['POST'])
def delete_show(show_id):
    show = AggregatedShow.query.get(show_id)
    if not show:
        return jsonify({"status": "error", "message": "Show not found"}), 404

    # Manually clean up associated records in join tables
    AggregatedVideo.query.filter_by(show_id=show_id).delete()
    AggregatedChannel.query.filter_by(show_id=show_id).delete()
    
    db.session.delete(show)
    db.session.commit()
    return jsonify({"status": "success"})

@aggregator_bp.route('/api/show_joins/<show_id>')
def get_show_joins(show_id):
    """Returns lists of joined channel and video IDs for a specific show."""
    channels = [c.channel_id for c in AggregatedChannel.query.filter_by(show_id=show_id).all()]
    
    # For the left pane, we need full video details to organize by season
    agg_videos = AggregatedVideo.query.filter_by(show_id=show_id).all()
    video_details = []
    for av in agg_videos:
        v = Video.query.get(av.video_id)
        if not v: continue
        video_details.append({
            "id": v.id,
            "title": av.title or v.title,
            "season": av.season or v.season or "0",
            "episode": av.episode or v.episode or "0"
        })
    
    # Sort by season then episode
    video_details.sort(key=lambda x: (
        int(x['season']) if str(x['season']).isdigit() else 0, 
        int(x['episode']) if str(x['episode']).isdigit() else 0
    ))

    return jsonify({
        "channels": channels, 
        "videos": [v['id'] for v in video_details],
        "left_pane": video_details
    })

@aggregator_bp.route('/api/toggle_channel', methods=['POST'])
def toggle_channel():
    data = request.json
    sid, cid, state = data.get('show_id'), data.get('channel_id'), data.get('state')
    if not sid or not cid: return jsonify({"status": "error", "message": "Missing IDs"}), 400

    existing = AggregatedChannel.query.filter_by(show_id=sid, channel_id=cid).first()
    if state and not existing:
        db.session.add(AggregatedChannel(show_id=sid, channel_id=cid))
    elif not state and existing:
        db.session.delete(existing)
    
    db.session.commit()
    return jsonify({"status": "success"})

@aggregator_bp.route('/api/toggle_video', methods=['POST'])
def toggle_video():
    data = request.json
    sid, vid, state = data.get('show_id'), data.get('video_id'), data.get('state')
    if not sid or not vid: return jsonify({"status": "error", "message": "Missing IDs"}), 400

    existing = AggregatedVideo.query.filter_by(show_id=sid, video_id=vid).first()
    if state and not existing:
        db.session.add(AggregatedVideo(show_id=sid, video_id=vid))
    elif not state and existing:
        db.session.delete(existing)
        
    db.session.commit()
    return jsonify({"status": "success"})

@aggregator_bp.route('/api/video_metadata/<show_id>/<video_id>')
def get_aggregated_video_metadata(show_id, video_id):
    """Returns source metadata and custom overrides for a video in an aggregated show."""
    v = Video.query.get(video_id)
    if not v: return jsonify({"status": "error"}), 404
    
    chan = Channel.query.get(v.channel_id)
    av = AggregatedVideo.query.filter_by(show_id=show_id, video_id=video_id).first()
    
    source = {
        'title': v.title, 'plot': v.description, 'aired': v.published_at,
        'season': v.season, 'episode': v.episode, 'showtitle': chan.name if chan else "Unknown"
    }
    # Add studio and uniqueid to source for the Master Pane
    source['studio'] = chan.studio if chan else "YouTube"
    source['uniqueid'] = v.id

    modified = None
    if av:
        show = AggregatedShow.query.get(show_id)
        modified = {
            'title': av.title if av.title is not None else v.title,
            'plot': av.description if av.description is not None else v.description,
            'aired': av.published_at if av.published_at is not None else v.published_at,
            'season': av.season if av.season is not None else v.season,
            'episode': av.episode if av.episode is not None else v.episode,
            'showtitle': show.name if show else "Aggregated Show",
            'studio': show.studio if show else "YouTube",
            'uniqueid': v.id
        }
    
    return jsonify({"source": source, "modified": modified})

@aggregator_bp.route('/api/save_video_metadata', methods=['POST'])
def save_aggregated_video_metadata():
    data = request.json
    sid, vid, meta = data.get('show_id'), data.get('video_id'), data.get('metadata', {})
    
    av = AggregatedVideo.query.filter_by(show_id=sid, video_id=vid).first()
    if not av: return jsonify({"status": "error", "message": "Video not joined to show"}), 404
    
    v = Video.query.get(vid)
    # Inheritance: Store as NULL if value matches base metadata
    av.title = meta.get('title') if meta.get('title') != v.title else None
    av.description = meta.get('plot') if meta.get('plot') != v.description else None
    av.published_at = meta.get('aired') if meta.get('aired') != v.published_at else None
    av.season = meta.get('season') if meta.get('season') != v.season else None
    av.episode = meta.get('episode') if meta.get('episode') != v.episode else None
    
    db.session.commit()
    return jsonify({"status": "success"})