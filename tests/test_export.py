import os
import pytest
from pathlib import Path
from app.models import Channel, Video
from app.utils import (
    write_xml, 
    get_channel_dest_path, 
    get_effective_metadata, 
    sync_channel_folders,
    safe_cleanup_video
)

def test_export_basic_channel_structure(db_session, temp_fs):
    """
    Verifies that the folder naming logic and NFO generation work together.
    This ensures that Channel metadata is correctly transformed into a 'TV Show' structure.
    """
    # 1. Setup Database state
    chan = Channel(id="UC_123", name="Test Channel", oldest_year="2021")
    db_session.add(chan)
    db_session.commit()

    # 2. Trigger Pathing logic
    dest_path = get_channel_dest_path(chan)
    dest_path.mkdir(parents=True, exist_ok=True)
    
    # 3. Trigger NFO generation
    nfo_path = dest_path / "tvshow.nfo"
    meta = get_effective_metadata(chan.id, 'channel', chan)
    write_xml(nfo_path, "tvshow", meta)

    # 4. Assertions
    # Check folder name based on default naming scheme: {title} ({year})
    assert dest_path.name == "Test Channel (2021)"
    assert nfo_path.exists()
    
    with open(nfo_path, 'r', encoding='utf-8') as f:
        content = f.read()
        assert "<title>Test Channel</title>" in content
        assert "<uniqueid type=\"youtube\" default=\"true\">UC_123</uniqueid>" in content

def test_hardlink_and_video_nfo_export(db_session, temp_fs):
    """
    Simulates the core export loop: finding a source file, linking it to the destination,
    and writing the episode-level metadata.
    """
    source_root = temp_fs['source']
    
    # 1. Setup DB state
    chan = Channel(id="UC_CHAN", name="Channel A")
    vid = Video(
        id="VIDEO_ID_11", 
        channel_id="UC_CHAN", 
        title="My Epic Video", 
        season="2023", 
        episode="1225"
    )
    db_session.add_all([chan, vid])
    db_session.commit()
    
    # 2. Create Source File (Simulate a TubeArchivist download)
    chan_src_dir = source_root / chan.id
    chan_src_dir.mkdir()
    vid_src_file = chan_src_dir / f"{vid.id}.mp4"
    vid_src_file.write_text("dummy binary data")
    
    # 3. Simulate the Export process for this video
    show_dir = get_channel_dest_path(chan)
    show_dir.mkdir(parents=True, exist_ok=True)
    
    # Mimic the naming scheme used in the Export route
    expected_filename = f"Channel A - 2023x1225 - My Epic Video [{vid.id}].mp4"
    vid_dest_file = show_dir / expected_filename
    
    # The "Magic" - Create the hardlink
    os.link(vid_src_file, vid_dest_file)
    
    # Generate the NFO
    nfo_dest_file = vid_dest_file.with_suffix(".nfo")
    meta = get_effective_metadata(vid.id, 'video', vid)
    write_xml(nfo_dest_file, "episodedetails", meta)
    
    # 4. Assertions
    assert vid_dest_file.exists()
    # Verify it is an actual hardlink (sharing the same inode)
    assert os.path.samefile(vid_src_file, vid_dest_file)
    assert nfo_dest_file.exists()
    
    with open(nfo_dest_file, 'r', encoding='utf-8') as f:
        nfo_content = f.read()
        assert "<title>My Epic Video</title>" in nfo_content
        assert "<season>2023</season>" in nfo_content
        assert "<showtitle>Channel A</showtitle>" in nfo_content

def test_sync_channel_folders_rename(db_session, temp_fs):
    """
    Verify that sync_channel_folders can detect and rename existing folders 
    if metadata changes (e.g., a user edits the Channel title).
    """
    dest_root = temp_fs['dest']
    
    # 1. Setup DB with a channel whose name we've "changed"
    chan = Channel(id="UC_RENAME", name="Updated Name", oldest_year="2024", is_eligible=True)
    db_session.add(chan)
    db_session.commit()
    
    # 2. Create an existing folder with the OLD name but the CORRECT ID in its NFO
    old_folder = dest_root / "Old Name (2020)"
    old_folder.mkdir()
    write_xml(old_folder / "tvshow.nfo", "tvshow", {"uniqueid": "UC_RENAME"})
    
    # 3. Run the sync logic
    sync_channel_folders(dry_run=False)
    
    # 4. Verify the folder was renamed
    assert not old_folder.exists()
    expected_path = dest_root / "Updated Name (2024)"
    assert expected_path.exists()
    assert (expected_path / "tvshow.nfo").exists()