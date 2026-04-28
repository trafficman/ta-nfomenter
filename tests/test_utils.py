import pytest
from app.utils import sanitize, normalize_text, is_ta_youtube_structure

def test_sanitize_basic():
    """Ensure illegal characters are replaced with dashes."""
    assert sanitize("My: Video/Title") == "My- Video-Title"
    assert sanitize("What? <This> | is * invalid") == "What- -This- - is - invalid"

def test_sanitize_path_traversal():
    """Ensure double dots are removed to prevent directory escaping."""
    assert sanitize("../../etc/passwd") == "--etc-passwd"

def test_sanitize_whitespace():
    """Ensure extra spaces are collapsed."""
    assert sanitize("  Too    Many   Spaces  ") == "Too Many Spaces"

def test_normalize_text():
    """Ensure HTML-like or multi-line text is collapsed into a clean string."""
    dirty = "Line one\n    Line two \t   "
    assert normalize_text(dirty) == "Line one Line two"
    assert normalize_text(None) == ""

def test_is_ta_youtube_structure_valid(temp_fs):
    """Verify the heuristic correctly identifies a TubeArchivist structure."""
    source = temp_fs['source']
    
    # Create a dummy channel folder (24 chars starting with UC)
    chan_id = "UC" + "A" * 22
    chan_dir = source / chan_id
    chan_dir.mkdir()
    
    # Create a dummy video (11 chars)
    vid_file = chan_dir / ("B" * 11 + ".mp4")
    vid_file.touch()
    
    assert is_ta_youtube_structure(source) is True

def test_is_ta_youtube_structure_invalid(temp_fs):
    """Verify it rejects non-TA structures."""
    source = temp_fs['source']
    
    # Wrong folder name length
    (source / "ShortFolder").mkdir()
    assert is_ta_youtube_structure(source) is False
    
    # Correct folder, wrong video length
    chan_dir = source / ("UC" + "A" * 22)
    chan_dir.mkdir()
    (chan_dir / "too_long_of_a_filename.mp4").touch()
    assert is_ta_youtube_structure(source) is False

def test_is_hardlink_compatible_real_check(temp_fs, monkeypatch):
    """Tests the logic that checks if we can link files across the configured dirs."""
    from app.utils import is_hardlink_compatible
    # In our test environment, source and dest are on the same virtual drive (tmp_path)
    # so it should be compatible.
    assert is_hardlink_compatible(temp_fs['source'], temp_fs['dest']) is True