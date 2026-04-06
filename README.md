# **NFOmenter, a TubeArchivist Media Management Suite**
NFOmenter, at its core, is a way to selectively convert (and edit) a TubeArchivist install into a folder of custom TV shows that most media servers can ingest. It takes the YouTube metadata stored in your TA and uses it to write a parallel human-readable folder structure with Kodi formatted XML .nfo local metadata files and images that things like Plex, Jellyfin, Emby, Kodi, etc will read.

A mirrored dual pane editor, with the TA ("Source") metadata on the right, and the modified custom TV Show metadata ("Destination") on the left, allows you to compare the two, see what changes you have made, and easily revert them.

AI Disclaimer: Gemini inked 95% of this code, with architectural decisions and every line reviewed by me (a very amateur coder, so don't expect too much), how vibecoded you consider this depends on how much you trust my ability to sight-read python

## **Features**
- **Remotely Deployable:** Deploys via Docker and controlled via api, easily integrating into any TA environment, whether local or not.
- **Web Based Editor:** Simple dual-pane editor, select the channels (and then, videos) you want to convert into TV shows on the right ("Source") pane, edit them on the left ("Destination") pane.
- **Human Readable Folder Structure:** Output ("Destination") is human readable, channel folders and videos inherit their YouTube titles, making for easy navigation at the file level.
- **Uses No Hard Drive Space:** Uses hardlinks rather than file copies so that original TA files may be duplicated and renamed without taking up additional space (however, there are important install instructions to ensure this).
- **Bidirectional Sync:** TubeArchivist is the "Source" of truth, download a new video there, sync and export in NFOmenter, and it will show up in the appropriate folder. Same goes for deletions, delete a video or even an entire channel in TA, and on sync and export it will be removed from the "Destination" folder.

## **Roadmap**
- **Short Term:**
  - **Sort Channel List Alphabetically:** Currently sorts lower and upper case separately.
  - **Toggle to Filter Unsynced Channels:** Once desired channels are selected, option to hide all others from the list, making management much easier.
  - **Offset Toggles to the Left:** Currently, scroll bar can overlap toggle buttons in some instances.
  - **Readme:** Finish it.
  - **Setup Checks:** Ensure compatible paths have been used.
    - Check that placeholder paths have not been used.
    - Check that Source and Destination are not the same folder.
    - Check that Destination folder does not look like TA "/youtube" folder (ie, that Source and Destination have not been swapped)
- **Medium Term:**
  - **Orphan Check:** Scan for orphaned files not found in the database, or otherwise missing their .nfo files.
  - **Handle Channel/Video Name Changes:** Decide what to do about youtube videos which have their metadata change on the TA side.
  - **Write Automated Dev Tests:** Design some common test cases, automate them through TA API control, track and report results of tests.
  - **Search:** Filter list by various channel/video fields.
- **Long Term:**
  - **Multi-Channel Aggregator:** Implement the multi-channel show builder. The primary purpose of this project is a 1:1 conversion of YouTube channels to TV shows, the aggregator is similar in fuction but is instead an N:1 conversion: Videos from multiple YouTube channels can be combined into a singular TV show. This must be separated off into a separate UI as, with the constraints of the mirrored dual pane editor, I couldn't come up with a good way to fit wholly new content into only one side.
    - **UI:** Similarly dual paned editor, but not mirrored, and having an extra column on the left.
        From right to left:
        - **Source Pane:** Exactly the same as the 1:1 Single-Channel Editor, simply lists all available channels and their videos.
        - **Destination Pane:** Represents a single custom aggregated TV show. Not mirrored, begins completely empty, and "episodes" are added from the source pane, picked from available channels and videos. Episodes are able to be edited in a similar manner to the regular 1:1 editor.
        - **Show List:** A new, third column on the far left. Contains the list of desired custom aggregated shows, and a means to add new ones. When a show is selected from the list, the editor pane now reflects that show's currently selected YouTube videos.
  - **LLM Integration:** Integrate with a local LLM to optionally generate episode summaries based on video transcripts.
  - **Database Rebuild:** With a fresh install, given both an existing source and destination, rebuild database modifications by diffing the two. Essentially allow stored files to function as a database backup.

## **Install**

Instructions coming soon

## **Usage**

Instructions coming soon

## **Internal Structure**

### **Technical Stack**
- **Backend:** Flask (App Factory), Flask-SQLAlchemy (SQLite), Gunicorn
- **Frontend:** Tailwind CSS (via CDN), custom JS for synchronized scrolling and dynamic NFO editing.
- **Logic:** Uses Hardlinks (`os.link`) to copy files without duplicating storage.

### **Architecture**
- `app/__init__.py`: Factory pattern, registers blueprints.
- `app/models.py`: Database schemas (Channel, Video, MetadataOverride).
- `app/utils.py`: Shared logic (TA API client, NFO XML generation, Path configurations, Cleanup).
- `app/templates/base.html`: Shared shell (Header, Nav, CSS).
- `app/editor/`: Single-Channel Editor specific files.
- `app/editor/routes.py`: API routes (currently all of them, may need to be split out into shared routes).
- `app/editor/templates/editor.html`:
- `app/aggregator/`: Planned Multi-Channel Aggregator feature extension.
- `run.py`: Starts the app.

## **Glossary**
- **TA (TubeArchivist):** The upstream self-hosted YouTube media server. Acts as the primary source of truth for video files and initial metadata.
- **Source:** The read-only file path where TA stores downloaded videos.
- **Destination:** The target file path where NFOmenter builds the human-readable folder structure with included local metadata.
- **Staging:** The state of metadata currently saved in the local SQLite database but not yet written to disk.
- **Export:** The action of synchronizing the "Staged" database state to the "Destination" filesystem (writing NFOs, creating hardlinks).
- **Hardlink:** A filesystem entry that points to the same physical data on disk as the Source file, allowing the file to appear in two places without consuming double storage.
- **Eligible (Channel):** A boolean flag. If `False`, the entire channel folder is removed from the Destination (or never exported in the first place).
- **Enabled (Video):** A boolean flag. If `False`, the specific video file is removed from the Destination (or never exported in the first place).
- **Override:** User-defined metadata (Title, Plot, etc.) stored in the DB that replaces the original TA metadata during Export.
- **Aggregator:** (Planned) A feature to group videos from different channels into a custom "Show" (e.g., a "News" show containing clips from multiple sources).