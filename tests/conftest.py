import pytest
import os
import shutil
from pathlib import Path
from app import create_app
from app.models import db
from app import utils

@pytest.fixture(scope='session')
def app():
    """Create and configure a new app instance for the entire test session."""
    # Create a temporary directory for the app data (settings, db)
    test_data_dir = Path("./tests/tmp_data")
    test_data_dir.mkdir(parents=True, exist_ok=True)
    
    app = create_app()
    app.config.update({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
    })

    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()
    
    # Cleanup
    if test_data_dir.exists():
        shutil.rmtree(test_data_dir)

@pytest.fixture
def client(app):
    """A test client for the app."""
    return app.test_client()

@pytest.fixture
def db_session(app):
    """Returns a clean database session for every test."""
    with app.app_context():
        yield db.session
        db.session.rollback()
        # Clear tables but keep schema
        for table in reversed(db.metadata.sorted_tables):
            db.session.execute(table.delete())
        db.session.commit()

@pytest.fixture
def temp_fs(tmp_path, monkeypatch):
    """
    Creates a temporary Source and Destination directory structure.
    Monkeypatches the paths in utils.py so logic uses these folders.
    """
    source = tmp_path / "source"
    dest = tmp_path / "dest"
    cache_vid = tmp_path / "cache_vid"
    cache_ch = tmp_path / "cache_ch"
    
    for p in [source, dest, cache_vid, cache_ch]:
        p.mkdir()
        
    monkeypatch.setattr(utils, "SOURCE_DIR", source)
    monkeypatch.setattr(utils, "DEST_DIR", dest)
    
    return {"source": source, "dest": dest}