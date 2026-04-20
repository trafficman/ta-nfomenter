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