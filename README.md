# **NFOmenter, a TubeArchivist Media Management Suite**

<img width="1264" height="945" alt="image" src="https://github.com/user-attachments/assets/f74d43c2-8ee0-4718-920e-a44b961d3dac" />

### Are you ready to ~~N~~**FOment** some rebellion against... hard to navigate... folder structures...?

Have you ever wished that your TubeArchivist folder was a little less `/youtube/UCuAXFkgsw1L7xaCfnd5JJOw/dQw4w9WgXcQ.mp4` and a little more `/YouTube/LGR (2009)/Running Doom on a Calculator!.mp4`? Have you ever wished you could sync only a select few of your archived channels to Plex or Jellyfin, or maybe even edit their metadata beforehand? If your answer is yes to either of these, then NFOmenter may be for you!

**NFOmenter**, at its core, is a way to selectively translate a [TubeArchivist](https://github.com/tubearchivist/tubearchivist) install into a folder of custom TV shows that most media servers can ingest. It takes the YouTube metadata stored in your TA and uses it to write a parallel human-readable folder structure with `.nfo` local metadata files and images that things like Plex, Jellyfin, Emby, Kodi, etc will read.

In addition, a mirrored dual pane editor, with the TA ("Source") metadata on the right, and the modified custom TV Show metadata ("Destination") on the left, allows you to compare the two, see what changes you have made, and easily revert them.

If you find any bugs, make an issue here (**NOT** the official TA github), or hit me up on discord.

AI Disclaimer: Gemini inked 95% of this code, with architectural decisions and every line reviewed by me (a very amateur coder, so don't expect too much), how vibecoded you consider this depends on how much you trust my ability to sight-read python

## **Features**
- **Touches Zero TubeArchivist Files:** Leaves your TA files completely intact, only ever reading from them. TA will continue to function as if NFOmenter is not even there.
- **Remotely Deployable:** Deploys via Docker and controlled via WebUI, easily integrating into any TA environment, whether local or remote.
- **Web Based Editor:** Simple dual-pane editor, select the channels (and their videos) you want to convert into TV shows on the right ("Source") pane, edit them on the left ("Destination") pane.
- **Gives Media Servers Everything they Need:** Not just metadata (`.nfo` files), but images (poster, banner, background, thumbnails), and subtitles too, all conveniently pulled from your TA install.
- **Human Readable Folder Structure:** Output ("Destination") is human readable, channel folders and videos inherit their YouTube titles, making for easy navigation at the file level.
- **Uses No Hard Drive Space:** Uses hardlinks rather than file copies so that original TA files may be duplicated and renamed without taking up additional space (however, there are important install instructions to ensure this).
- **Bidirectional Sync:** TubeArchivist is the "Source" of truth, download a new video there, sync and export in NFOmenter, and it will show up in the appropriate folder. Same goes for deletions, delete a video or even an entire channel in TA, and on sync and export it will be removed from the "Destination" folder.

## **Roadmap**
- **Multi-Channel Aggregator:** Implement the multi-channel show builder. The primary purpose of this project is a 1:1 conversion of YouTube channels to TV shows, the aggregator is similar in fuction but is instead an N:1 conversion: Videos from multiple YouTube channels can be combined into a singular TV show. This must be separated off into a separate UI as, with the constraints of the mirrored dual pane editor, I couldn't come up with a good way to fit wholly new content into only one side.
  - **UI:** Similarly dual paned editor, but not mirrored, and having an extra column on the left.
      From right to left:
      - **Source Pane:** Exactly the same as the 1:1 Single-Channel Editor, simply lists all available channels and their videos.
      - **Destination Pane:** Represents a single custom aggregated TV show. Not mirrored, begins completely empty, and "episodes" are added from the source pane, picked from available channels and videos. Episodes are able to be edited in a similar manner to the regular 1:1 editor.
      - **Show List:** A new, third column on the far left. Contains the list of desired custom aggregated shows, and a means to add new ones. When a show is selected from the list, the editor pane now reflects that show's currently selected YouTube videos.
- **LLM Integration:** Integrate with a local LLM to optionally generate episode plot summaries based on video transcripts.
- **Database Rebuild:** With a fresh install, given both an existing source and destination, rebuild database modifications by diffing the two. Essentially allow stored files to function as a database backup.
- **Properly Document API**
- **Search:** Filter list by various channel/video fields.

## **Install**

NFOmenter is deployed via Docker Compose. Because the application uses **Hardlinks** to save space, proper volume mapping is the most important part of the setup.

### **The Golden Rule of Hardlinks**
For NFOmenter to duplicate and rename your files without using any extra disk space, the **Source** (TubeArchivist files) and the **Destination** (Your new TV Show folders) **MUST** appear to the container as being on the same physical drive. With how Docker bind mounts work, this means they both are **REQUIRED** to be accessible from a **single** volume path.

**Do not** mount them as two separate volumes (e.g., `- /mnt/User/Docker/tubearchivist/youtube:/source` and `- /mnt/User/Media/Videos/YouTube:/destination`). Instead, mount a shared parent folder:
*   **Correct:** `- /mnt/User:/files` (it may be easier to mirror the external folder path internally, in this example, `/mnt/User:/mnt/User`, because then the internal paths will also be mirrored as well)
*   **Internal Paths:** You then set your environment variables to point *inside* that mount (e.g., `SOURCE_DIR=/files/Docker/tubearchivist/youtube`).

### **1. Prepare your environment**
Create a directory for NFOmenter and a data folder to persist your database:
```bash
mkdir ta-nfomenter && cd ta-nfomenter
mkdir data
```

### **2. Create `compose.yml`**
Copy the following into a `compose.yml` file, stored in the created `ta-nfomenter` folder, adjusting the paths and TubeArchivist credentials to match your setup:

```yaml
version: '3.8'
services:
  ta-nfomenter:
    image: ghcr.io/trafficman/ta-nfomenter:latest
    container_name: ta-nfomenter
    ports:
      - 2960:2960
    volumes:
      # MOUNT THE SHARED PARENT FOLDER HERE
      - /path/to/your/shared/folder:/path/to/your/shared/folder
      # Persist the database, default location will use/create a "data" folder in the folder that contains this compose.yml file
      - ./data:/ta-nfomenter-dev/data
    environment:
      - TA_URL=http://your.TA.URL
      - TA_TOKEN=your_tubearchivist_api_token_here
      
      # Internal paths relative to the container
      - DEST_DIR=/internal/path/to/DESTINATION
      - SOURCE_DIR=/internal/path/to/SOURCE
      - CACHE_VID=/internal/path/to/video/image/cache
      - CACHE_CH=/internal/path/to/channel/image/cache
    restart: unless-stopped
```

### **3. Configuration Breakdown**
| Variable | Description |
| :--- | :--- |
| `TA_URL` | The full URL to your TubeArchivist instance. Use the IP address (e.g `http://its.local.IP.here:9000`) if you have connection issues. |
| `TA_TOKEN` | Your TA API Token (found in TA Settings > Application > Integrations > API Token). |
| `DEST_DIR` | Where NFOmenter will build your "TV Show" library. |
| `SOURCE_DIR` | The path to TA's `/youtube` folder. |
| `CACHE_VID` | The path to TA's video thumbnail cache (usually `/cache/videos`). |
| `CACHE_CH` | The path to TA's channel image cache (usually `/cache/channels`). |

### **4. Launch**
```bash
docker-compose up -d
```
Once the container is running, access the WebUI at `http://<your-ip>:2960`.

## **Usage**

**TL;DR**: 
1. Load WebUI and toggle on desired channels.
2. Press **Sync TA** to fetch video lists.
3. Click on items to modify metadata (Press **Stage Changes** for each item!).
4. Press **Run Export** to create the folders and NFOs.
5. Point your media server at the **Destination** folder.

### Step 0:
Visit the WebUI in a browser (if hosted locally, should be located at something like "http://localhost:2960"), on page load, NFOmenter will query the TubeArchivist API and populate the right Source pane with all available channels.

### Step 1:
Click the toggle box on the right for each channel you wish to Export as a TV show.

<img width="523" height="498" alt="image" src="https://github.com/user-attachments/assets/e555726e-2806-4a45-b980-32f35636be9c" />

### Step 2:
Once desired channels are selected, press the blue "Sync TA" button.

<img width="104" height="43" alt="image" src="https://github.com/user-attachments/assets/21ecf6f7-3ce7-4c98-9c20-87718233b4a0" />

### Step 3:
Text next to the button should briefly appear saying "Syncing...", it is now grabbing the list of archived videos for each desired channel (plus associated metadata). Once it completes, click one of the blue triangles to the left of a synced channel to expand its list of videos and confirm that the sync was successful.

<img width="631" height="456" alt="image" src="https://github.com/user-attachments/assets/4c6743b7-6a63-476f-8201-5dd930248977" />

### Step 4:
With a channel or video selected, in the lower left will be the editing panel. Apply any desired modifications (Change titles, plots, studio, etc), and, **IMPORTANT**, before clicking another item, press the big green "Stage Changes" button. Modifications will be lost if "Stage Changes" is not pressed for each item.

<img width="630" height="320" alt="image" src="https://github.com/user-attachments/assets/f82174f7-ea46-404a-a25c-ae6ed22182e2" />

### Step 5:
Once you've completed picking and/or modifying the channels and videos you want to include in your Destination TV shows folder, in the upper right, click the green "Run Export" button (it may take a while to complete, just let it run until the "Exporting..." text is replaced with "Export Finished!"). NFOmenter will create all the appropriate TV Shows with their associated metadata files and images, check your Destination folder to make sure everything looks right. Finally, point your media server of choice at this folder and enjoy!

<img width="210" height="308" alt="image" src="https://github.com/user-attachments/assets/7562f2be-4cc2-4969-9b84-3afadeade723" />

### Maintenance Menu:
- **Deletion Sync**: Queries TubeArchivist looking for videos or channels that have been deleted since the last sync. If any are found, they will be shown in the UI and you will be asked for confirmation before their hardlinks are deleted from the Destination folder. Relegated to a manual maintence task because it's very I/O intensive, and to ensure a human is in the loop before any files are deleted.
- **Folder Name Sync**: Manually updates Destination show folder names based on current database info (Channel name, current known "premier" year). At time of writing I'm pretty sure this currently runs on each export, but for optimization reasons this may not remain the case (honestly it was a bit of a lazy bugfix), so a manual trigger is included regardless.
- **Refresh Source Metadata:** Manually updates NFOmenter's Source metadata by pulling updated metadata directly from TA. 

## **Internal Structure**

### **Technical Stack**
- **Backend:** Flask (App Factory), Flask-SQLAlchemy (SQLite), Gunicorn
- **Frontend:** Tailwind CSS (via CDN), custom JS for synchronized scrolling and dynamic NFO editing.
- **Logic:** Uses Hardlinks (`os.link`) to copy files without duplicating storage.

### **Architecture**
- `app/__init__.py`: Factory pattern, registers blueprints.
- `app/models.py`: Database schema (Channel, Video, MetadataOverride).
- `app/utils.py`: Shared logic (TA API client, NFO XML generation, Path configurations, Cleanup).
- `app/templates/base.html`: Shared shell (Header, Nav, CSS).
- `app/editor/`: Single-Channel Editor specific files.
- `app/editor/editor_routes.py`: API routes (currently all of them, may need to be split out into shared routes).
- `app/editor/templates/editor.html`: HTML and JS logic for Single-Channel Editor.
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
