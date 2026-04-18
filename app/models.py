from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Channel(db.Model):
    id = db.Column(db.String(50), primary_key=True)
    name = db.Column(db.String(255))
    description = db.Column(db.Text)
    is_eligible = db.Column(db.Boolean, default=False)
    premiered = db.Column(db.String(10)) 
    oldest_year = db.Column(db.String(4), default="2005")
    studio = db.Column(db.String(100), default="YouTube")

class Video(db.Model):
    id = db.Column(db.String(50), primary_key=True)
    channel_id = db.Column(db.String(50), db.ForeignKey('channel.id'))
    title = db.Column(db.String(255))
    description = db.Column(db.Text)
    published_at = db.Column(db.String(10)) 
    season = db.Column(db.String(4))       
    episode = db.Column(db.String(4))      
    is_enabled = db.Column(db.Boolean, default=True)
    missing_from_source = db.Column(db.Boolean, default=False)

class MetadataOverride(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    target_id = db.Column(db.String(50), index=True) 
    field_name = db.Column(db.String(50))            
    new_value = db.Column(db.Text)

class AggregatedShow(db.Model):
    """Represents a custom user-created TV Show."""
    id = db.Column(db.String(50), primary_key=True)
    name = db.Column(db.String(255))
    description = db.Column(db.Text)
    premiered = db.Column(db.String(10))
    oldest_year = db.Column(db.String(4), default="2005")
    studio = db.Column(db.String(100), default="YouTube")
    is_active = db.Column(db.Boolean, default=True)

class AggregatedChannel(db.Model):
    """Join table for AS and YouTube Channels"""
    id = db.Column(db.Integer, primary_key=True)
    show_id = db.Column(db.String(50), db.ForeignKey('aggregated_show.id'))
    channel_id = db.Column(db.String(50), db.ForeignKey('channel.id'))

class AggregatedVideo(db.Model):
    """Links a Video to an AggregatedShow with dedicated aggregator metadata."""
    id = db.Column(db.Integer, primary_key=True)
    show_id = db.Column(db.String(50), db.ForeignKey('aggregated_show.id'))
    video_id = db.Column(db.String(50), db.ForeignKey('video.id'))
    # Overrides: Nullable so they can fall back to the base Video metadata
    title = db.Column(db.String(255), nullable=True)
    description = db.Column(db.Text, nullable=True)
    published_at = db.Column(db.String(10), nullable=True) 
    season = db.Column(db.String(4), nullable=True)
    episode = db.Column(db.String(4), nullable=True)