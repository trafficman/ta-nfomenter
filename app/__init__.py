import os
from flask import Flask
from .models import db

def create_app():
    app = Flask(__name__)
    
    # Path to DB relative to project root
    basedir = os.path.abspath(os.path.dirname(__file__))
    data_dir = os.path.join(os.path.dirname(basedir), 'data')
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)

    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(data_dir, 'nfomenter.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)

    with app.app_context():
        # Import and register Blueprints
        from .editor.routes import editor_bp
        # from .aggregator.routes import aggregator_bp # Reserved for later
        
        app.register_blueprint(editor_bp)
        # app.register_blueprint(aggregator_bp, url_prefix='/aggregator')

        db.create_all()

    return app