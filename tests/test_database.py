import pytest
from app.models import Channel, Video, MetadataOverride
from app.utils import get_effective_metadata

def test_channel_creation(db_session):
    """Test that we can save and retrieve a channel."""
    chan = Channel(id="UC1234567890123456789012", name="Test Channel")
    db_session.add(chan)
    db_session.commit()

    retrieved = db_session.get(Channel, "UC1234567890123456789012")
    assert retrieved.name == "Test Channel"
    assert retrieved.is_eligible is False  # Check default value

def test_get_effective_metadata_inheritance(db_session):
    """Verify that metadata defaults to DB values when no overrides exist."""
    chan = Channel(id="UC_TEST", name="Original Channel Name", oldest_year="2020")
    vid = Video(id="VID123", channel_id="UC_TEST", title="Original Video Title", season=1, episode=5)
    db_session.add_all([chan, vid])
    db_session.commit()

    # Check Channel inheritance
    meta_chan = get_effective_metadata("UC_TEST", 'channel', chan)
    assert meta_chan['title'] == "Original Channel Name"
    assert meta_chan['year'] == "2020"

    # Check Video inheritance
    meta_vid = get_effective_metadata("VID123", 'video', vid)
    assert meta_vid['title'] == "Original Video Title"
    assert str(meta_vid['season']) == "1"

def test_get_effective_metadata_with_overrides(db_session):
    """Verify that overrides correctly shadow the base DB values."""
    chan = Channel(id="UC_OVERRIDE", name="Original Name")
    db_session.add(chan)
    
    # Create an override for the channel title
    override = MetadataOverride(
        target_id="UC_OVERRIDE",
        field_name="title",
        new_value="Better Channel Name"
    )
    db_session.add(override)
    db_session.commit()

    meta = get_effective_metadata("UC_OVERRIDE", 'channel', chan)
    assert meta['title'] == "Better Channel Name"
    # Ensure non-overridden fields still fall back to base
    assert meta['year'] == chan.oldest_year 

def test_video_overrides_respect_channel_overrides(db_session):
    """
    A video's 'showtitle' should come from the channel's overridden title,
    not the original channel name.
    """
    chan = Channel(id="UC_CHAN", name="Original Channel")
    vid = Video(id="VID_1", channel_id="UC_CHAN", title="Video Title")
    db_session.add_all([chan, vid])
    
    # Override the Channel title
    db_session.add(MetadataOverride(target_id="UC_CHAN", field_name="title", new_value="New Show Name"))
    # Override the Video title
    db_session.add(MetadataOverride(target_id="VID_1", field_name="title", new_value="New Episode Name"))
    db_session.commit()

    meta = get_effective_metadata("VID_1", 'video', vid)
    assert meta['title'] == "New Episode Name"
    assert meta['showtitle'] == "New Show Name"