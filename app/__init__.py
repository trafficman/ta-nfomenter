import os
import sys
from flask import Flask
from .models import db
from flask_migrate import Migrate, upgrade, stamp

def create_app():
    app = Flask(__name__)
    
    # Path to DB relative to project root
    basedir = os.path.abspath(os.path.dirname(__file__))
    data_dir = os.path.join(os.path.dirname(basedir), 'data')
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)
    db_path = os.path.join(data_dir, 'nfomenter.db')

    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(data_dir, 'nfomenter.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)
    # We store the migrate object to potentially use it for programmatic access
    migrate = Migrate(app, db)

    with app.app_context():
        # Import and register Blueprints
        from .shared_routes import main_bp
        from .editor.editor_routes import editor_bp
        from .aggregator.aggregator_routes import aggregator_bp
        
        app.register_blueprint(main_bp)
        app.register_blueprint(editor_bp)
        app.register_blueprint(aggregator_bp, url_prefix='/aggregator')

        # Perform startup path validation checks
        from .utils import SOURCE_DIR, DEST_DIR, is_ta_youtube_structure, is_hardlink_compatible

        # 1. Existence Checks
        if not SOURCE_DIR.exists():
            print(f"[!] ERROR: SOURCE_DIR does not exist: {SOURCE_DIR}")
            sys.exit(1)
        if not DEST_DIR.exists():
            print(f"[!] ERROR: DEST_DIR does not exist: {DEST_DIR}")
            sys.exit(1)

        # 2. Heuristic Checks
        is_source_ta = is_ta_youtube_structure(SOURCE_DIR)
        is_dest_ta = is_ta_youtube_structure(DEST_DIR)

        if is_source_ta and not is_dest_ta:
            if not is_hardlink_compatible(SOURCE_DIR, DEST_DIR):
                print("[!] ERROR: Source and Destination directories are on different filesystems. Hardlinks will not function. Did your single mounted volume contain BOTH Source and Destination folders?")
                sys.exit(1)
            print("[*] Path validation successful: SOURCE_DIR is a TA /youtube folder and DEST_DIR is safe. Proceeding...")
        elif not is_source_ta and not is_dest_ta:
            print("[!] ERROR: No TubeArchivist /youtube folder found, DEST_DIR must be the folder where TA stores all of its videos")
            sys.exit(1)
        elif not is_source_ta and is_dest_ta:
            print("[!] ERROR: Destination directory detected as TubeArchivist /youtube folder, did you swap Source and Destination?")
            sys.exit(1)
        elif is_source_ta and is_dest_ta:
            print("[!] ERROR: Both Source and Destination directories detected as TubeArchivist /youtube folders, choose a different directory for Destination")
            sys.exit(1)

        # Programmatically apply migrations on startup.
        # This ensures the user's database is always in sync with the current models.
        # If no migrations folder exists (fresh dev environment), it falls back to create_all.
        project_root = os.path.dirname(basedir)
        migrations_dir = os.path.join(project_root, 'migrations')

        if os.path.exists(migrations_dir):
            try:
                from sqlalchemy import inspect
                inspector = inspect(db.engine)
                tables = inspector.get_table_names()

                if not os.path.exists(db_path) or not tables:
                    # Case 1: Brand new installation
                    print("[*] No database detected. Initializing from models...")
                    db.create_all()
                    print("[*] Stamping database with latest migration version...")
                    stamp(directory=migrations_dir)
                elif "channel" in tables and "alembic_version" not in tables:
                    # Case 2: Existing user from before the migration system was added
                    print("[*] Existing legacy database detected. Stamping as baseline...")
                    # We stamp it with the baseline ID so upgrade() only runs the NEW migrations
                    stamp(directory=migrations_dir, revision='8c5b79466278')
                    print("[*] Applying updates...")
                    upgrade(directory=migrations_dir)
                else:
                    # Case 3: Standard update for an already migrated database
                    print("[*] Checking for database migrations...")
                    upgrade(directory=migrations_dir)

                print("[*] Database is up to date.")
            except Exception as e:
                print(f"[!] Migration Error: {e}")
        else:
            db.create_all()

    return app