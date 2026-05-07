import os
import pytest
import app.utils
import app.shared_routes
from pathlib import Path
from app.models import Channel, Video, AggregatedShow, AggregatedChannel, AggregatedVideo
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

def test_export_api_full_flow(client, db_session, temp_fs, monkeypatch):
    """
    Integration test for the /api/export route.
    Tests 1:1 export, N:1 export, and cleanup of disabled items in one pass.
    """
    # Patch global constants in both modules to ensure routes use temp paths
    for mod in [app.utils, app.shared_routes]:
        monkeypatch.setattr(mod, "SOURCE_DIR", temp_fs['source'])
        monkeypatch.setattr(mod, "CACHE_VID", temp_fs['source'] / "cache" / "videos")
        monkeypatch.setattr(mod, "CACHE_CH", temp_fs['source'] / "cache" / "channels")
        if hasattr(mod, "DEST_DIR"):
            monkeypatch.setattr(mod, "DEST_DIR", temp_fs['dest'])

    source = temp_fs['source']
    dest = temp_fs['dest']

    # 1. Setup Single Channel (Eligible)
    c1 = Channel(id="UC_C1", name="Channel One", is_eligible=True, oldest_year="2020", studio="YouTube")
    v1 = Video(id="VID_V1", channel_id="UC_C1", title="Video One", season="2020", episode="0101", is_enabled=True, published_at="2020-01-01")
    v2 = Video(id="VID_V2", channel_id="UC_C1", title="Video Two", season="2020", episode="0102", is_enabled=False) # Should NOT be exported
    
    # 2. Setup Aggregated Show
    as1 = AggregatedShow(id="AS_1", name="Custom Show", is_active=True, oldest_year="2024", studio="YouTube")
    ac1 = AggregatedChannel(show_id="AS_1", channel_id="UC_C1", is_enabled=True)
    av1 = AggregatedVideo(show_id="AS_1", video_id="VID_V1", season="1", episode="1", is_enabled=True)
    
    db_session.add_all([c1, v1, v2, as1, ac1, av1])
    db_session.commit()

    # 3. Create Source Files
    c1_src = source / "UC_C1"
    c1_src.mkdir()
    (c1_src / "VID_V1.mp4").write_text("v1 content")
    (c1_src / "VID_V2.mp4").write_text("v2 content")

    # 4. Trigger Export API
    response = client.post('/api/export')
    assert response.status_code == 200

    # 5. Assert Single Channel Export
    c1_dest = dest / "Channel One (2020)"
    assert (c1_dest / "tvshow.nfo").exists()
    # Video 1 should exist
    v1_nfo = c1_dest / "Season 2020" / "Channel One - 2020x0101 - Video One [VID_V1].nfo"
    v1_mp4 = c1_dest / "Season 2020" / "Channel One - 2020x0101 - Video One [VID_V1].mp4"
    assert v1_nfo.exists()
    assert v1_mp4.exists()
    
    # Video 2 should NOT exist (disabled)
    v2_mp4 = c1_dest / "Season 2020" / "Channel One - 2020x0102 - Video Two [VID_V2].mp4"
    assert not v2_mp4.exists()

    # 6. Assert Aggregated Show Export
    as_dest = dest / "Custom Show (2024)"
    assert (as_dest / "tvshow.nfo").exists()
    as_v1_nfo = as_dest / "Season 1" / "Custom Show - 1x1 - Video One [VID_V1].nfo"
    assert as_v1_nfo.exists()

    # 7. Test Cleanup Logic (Disable V1 and run export again)
    v1.is_enabled = False
    db_session.commit()
    client.post('/api/export')
    assert not v1_mp4.exists()

def test_export_collision_handling(client, db_session, temp_fs, monkeypatch):
    """Tests that videos with the same title are handled by appending IDs."""
    # Patch global constants in both modules to ensure routes use temp paths
    for mod in [app.utils, app.shared_routes]:
        monkeypatch.setattr(mod, "SOURCE_DIR", temp_fs['source'])
        monkeypatch.setattr(mod, "CACHE_VID", temp_fs['source'] / "cache" / "videos")
        monkeypatch.setattr(mod, "CACHE_CH", temp_fs['source'] / "cache" / "channels")
        if hasattr(mod, "DEST_DIR"):
            monkeypatch.setattr(mod, "DEST_DIR", temp_fs['dest'])

    source = temp_fs['source']
    dest = temp_fs['dest']

    c1 = Channel(id="UC_C1", name="Channel", is_eligible=True, oldest_year="2020")
    # Two different videos with the same title
    v1 = Video(id="ID1", channel_id="UC_C1", title="Same Title", season="1", episode="1")
    v2 = Video(id="ID2", channel_id="UC_C1", title="Same Title", season="1", episode="1")
    db_session.add_all([c1, v1, v2])
    db_session.commit()

    c1_src = source / "UC_C1"
    c1_src.mkdir()
    (c1_src / "ID1.mp4").write_text("v1")
    (c1_src / "ID2.mp4").write_text("v2")

    client.post('/api/export')

    c_dest = dest / "Channel (2020)" 
    # Note: the naming scheme defaults to include [id], but collision logic 
    # acts as a secondary safety. 
    # Current default: {showtitle} - {season}x{episode} - {title} [{id}]
    v1_path = c_dest / "Season 1" / "Channel - 1x1 - Same Title [ID1].mp4"
    v2_path = c_dest / "Season 1" / "Channel - 1x1 - Same Title [ID2].mp4"
    
    assert v1_path.exists()
    assert v2_path.exists()