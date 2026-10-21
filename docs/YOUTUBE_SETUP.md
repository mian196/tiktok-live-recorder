# YouTube Upload Setup Guide

This guide walks you through setting up free, automated YouTube uploads for your recorded TikTok Live streams using the official **YouTube Data API v3**.

---

## Overview & Free Tier Details

- **Cost**: **100% Free**
- **Daily Quota**: **10,000 units/day** provided for free per Google Cloud project.
- **Cost per Upload**: **1,600 units** per video.
- **Capacity**: Approx **6 video uploads per day** per project (resets daily at midnight Pacific Time).
- **File Limit**: Videos up to **256 GB** or **12 hours** (for verified YouTube accounts).

---

## Step 1: Create a Project in Google Cloud Console

1. Open the [Google Cloud Console](https://console.cloud.google.com/).
2. Log in with your Google Account *(Note: You can use any Google account to create projects, even if your YouTube channel is on a different account! See the Multi-Account section below)*.
3. In the top navigation bar, click the project dropdown and select **"New Project"**.
4. Enter a project name (e.g., `TikTok Live Recorder`) and click **"Create"**.
5. Ensure your newly created project is selected in the top bar.

---

## Step 2: Enable the YouTube Data API v3

1. In the Google Cloud Console, open the left navigation menu (☰) and go to **APIs & Services** > **Library**.
2. In the search box, search for:
   ```text
   YouTube Data API v3
   ```
3. Click on **YouTube Data API v3** from the search results.
4. Click the **"Enable"** button.

---

## Step 3: Configure the OAuth Consent Screen

Because this tool uploads videos to your personal channel, it requires OAuth 2.0 authorization.

1. In the left sidebar, navigate to **APIs & Services** > **OAuth consent screen**.
2. Select **External** as the user type (this allows personal `@gmail.com` accounts) and click **Create**.
3. Fill in the required **App Information**:
   - **App name**: `TikTok Live Uploader`
   - **User support email**: Select your email address.
   - **Developer contact information**: Enter your email address.
4. Click **Save and Continue**.
5. **Scopes (Data Access)**:
   - Click **Add or Remove Scopes**.
   - In the filter box, search for `youtube`.
   - Check the box for `../auth/youtube.upload` (Upload YouTube videos and manage your YouTube videos).
   - *(Optional)* Check `../auth/youtube` if you want full management access.
   - Click **Update**, then click **Save and Continue**.
6. **Test Users (Audience - Crucial Step)**:
   - Click **"+ ADD USERS"**.
   - Enter the email address of the **Google account that owns your YouTube channel**.
   - Click **Add**, then click **Save and Continue**.
   > [!IMPORTANT]
   > Because your app is in "Testing" publishing status, only email addresses explicitly added as **Test Users** can authorize the application. If you created the GCP project with a secondary Gmail, make sure to add your YouTube channel's Gmail here!

---

## Step 4: Create OAuth 2.0 Client Credentials

1. In the left sidebar, go to **APIs & Services** > **Credentials**.
2. At the top of the page, click **"+ CREATE CREDENTIALS"** and choose **"OAuth client ID"**.
3. Set the **Application type** to:
   ```text
   Desktop app
   ```
4. Set the **Name** to `TikTok Live Recorder Client`.
5. Click **Create**.
6. A dialog will show your Client ID and Client Secret. Click **"DOWNLOAD JSON"**.
7. Rename the downloaded file to:
   ```text
   client_secrets.json
   ```
8. Move `client_secrets.json` into the `configs/` directory of this repository:
   ```text
   configs/client_secrets.json
   ```

---

## Step 5: Configure `configs/youtube.json`

Create or edit `configs/youtube.json` (you can copy from `configs/youtube.example.json`):

```json
{
  "client_secrets_file": "configs/client_secrets.json",
  "credentials_storage_file": "configs/youtube_token.json",
  "privacy_status": "private",
  "title_template": "{user} - TikTok Live ({date})",
  "description_template": "Recorded with TikTok Live Recorder.\nStreamer: @{user}\nDate: {date}",
  "tags": ["tiktok", "live", "recording"],
  "category_id": "22",
  "made_for_kids": false
}
```

### Configuration Options:
- **`privacy_status`**:
  - `"private"` *(Recommended for personal backups)*: Only you can view the video.
  - `"unlisted"`: Anyone with the link can view the video.
  - `"public"`: Publicly visible on your channel.
- **`title_template`**: Template for the video title. Supports `{user}`, `{date}`, `{time}`, `{filename}` placeholders.
- **`description_template`**: Template for the description. Supports `{user}`, `{date}`, `{time}`, `{filename}` placeholders.
- **`tags`**: List of video tags.
- **`category_id`**: Optional YouTube category ID (`22` = People & Blogs, `20` = Gaming). Set to `null` or omit to disable and let YouTube use your channel default.
- **`made_for_kids`**: `true` or `false` (COPPA compliance).

---

## Step 6: First-Time Authentication

1. When the recorder triggers its first YouTube upload, it will launch a browser window (or provide a link) to authenticate.
2. Sign in with the Google Account that owns your YouTube channel.
3. You will see a warning saying **"Google hasn't verified this app"**:
   - Click **"Advanced"** (or "Show Advanced").
   - Click **"Go to TikTok Live Uploader (unsafe)"** *(It is completely safe because you created the app yourself)*.
4. Grant the requested permissions by clicking **"Allow"**.
5. Once authorized, a token is saved to `configs/youtube_token.json`.
6. **Subsequent uploads run completely in the background without user interaction**, automatically refreshing the token when needed.

---

## Step 7: Using YouTube Upload in the Recorder

- To enable YouTube uploads globally, set `"youtube": true` in `configs/config.json`.
- Or run with the CLI flag:
  ```bash
  python src/main.py -user streamer_username -youtube
  ```
- **Backup alongside Telegram**:
  ```bash
  python src/main.py -user streamer_username -youtube -telegram
  ```
  Both uploads will run upon recording completion. If local cleanup (`purge_after_upload`) is enabled, files will only be deleted once **both** YouTube and Telegram uploads have succeeded.

---

## Step 8: Multi-Project & Multi-Account Scaling (30+ Uploads/Day)

Google Cloud allocates the 10,000 units/day quota **per project**, not per Google account or YouTube channel.

### Can I create multiple projects?
**Yes!** Every Google account can create up to 5 free projects in Google Cloud Console:
- 1 Project = 10,000 units/day ($\approx$ 6 uploads)
- 3 Projects = 30,000 units/day ($\approx$ 18 uploads)
- 5 Projects = 50,000 units/day ($\approx$ 30 uploads)

### Can I use different Google accounts to create projects?
**Yes!** You can use secondary or spare Gmail accounts to create Google Cloud projects. All you need to do is:
1. In the secondary Google account's GCP project, go to **OAuth consent screen** > **Test Users**.
2. Add your **main YouTube channel email address** as a Test User.
3. When authenticating, log into your **main YouTube channel**.
4. The quota is consumed from the secondary GCP project, but all videos upload directly to your **main YouTube channel**!

### How to Configure Project Rotation in `configs/youtube.json`:
```json
{
  "projects": [
    {
      "name": "Project 1 (Main)",
      "client_secrets_file": "configs/client_secrets.json",
      "credentials_storage_file": "configs/youtube_token.json"
    },
    {
      "name": "Project 2 (Backup)",
      "client_secrets_file": "configs/client_secrets_2.json",
      "credentials_storage_file": "configs/youtube_token_2.json"
    },
    {
      "name": "Project 3 (Backup)",
      "client_secrets_file": "configs/client_secrets_3.json",
      "credentials_storage_file": "configs/youtube_token_3.json"
    }
  ],
  "privacy_status": "private",
  "title_template": "{user} - TikTok Live ({date})"
}
```

When Project 1 reaches its 10,000 quota limit (`quotaExceeded`), the recorder **automatically switches to Project 2**, and then Project 3, continuing seamless uploads!

---

## Step 9: Automatic Pending Queue & Next-Day Retry

What happens if all configured projects exhaust their daily quota?
1. **Zero Data Loss**: Your local recording is **never deleted** while pending upload (even if `purge_after_upload` is enabled).
2. **Automatic Queue**: The recording file is saved to `configs/youtube_queue.json`.
3. **Midnight Pacific Time Reset**: YouTube API quotas reset every day at **midnight Pacific Time (00:00 PT)**.
4. **Auto-Retry**: The recorder calculates the exact reset time. The next time the recorder runs or completes a stream after midnight PT, it automatically flushes the queue and uploads all backlogged recordings to YouTube.


---

## Step 10: Headless Server, VPS, & Docker Deployment

On a remote server or Docker container without a graphical desktop or web browser, Google's browser popup cannot open automatically. Use either of the two workflows below:

### Method A: Local Pre-Authentication & File Transfer (Recommended)
This is the easiest and most reliable method:
1. Clone or set up the repository on your local computer (Windows, macOS, or Linux desktop).
2. Place your `client_secrets.json` into `configs/`.
3. Run the helper script to authenticate:
   ```bash
   python auth.py --youtube
   ```
4. A browser window opens on your computer. Log in and grant permission.
5. The token is saved to `configs/youtube_token.json` (and `configs/youtube_token_2.json` for backup projects).
6. **Copy these generated token file(s)** to your remote server or Docker volume in the `configs/` folder:
   ```bash
   scp configs/youtube_token*.json user@your-server:/path/to/tiktok-live-recorder/configs/
   ```
7. That's it! Your server will now run 24/7 and silently auto-refresh the token in the background without ever needing browser interaction.

### Method B: Pre-Authentication via Helper Script
You can run the interactive authentication helper on the server before starting live recordings:
```bash
python auth.py --youtube
```
If you are connected via SSH, forward the callback port to your local machine:
```bash
ssh -L 8080:localhost:8080 user@your-server-ip
```


---

## Step 11: Configuring Playlists for Streamers & Groups

You can automatically organize uploaded live streams into separate YouTube playlists per streamer or per group.

### Supported Playlist Identification:
- **Playlist ID**: Direct YouTube ID (e.g. `PLxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`).
- **Playlist Name / Title**: You can simply write the title you want (e.g. `"Nurse Don Law Live Archive"` or `"Philippines Streams"`). If the playlist does not exist yet on your channel, **the tool will automatically create it for you**!

### Option 1: Configure in `configs/youtube.json`
```json
{
  "default_playlist": "All TikTok Lives",

  "streamer_playlists": {
    "nursedonlaw27": "Nurse Don Law Archive",
    "ser.dandan": "PLxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
  },

  "playlists": {
    "Favorite Creators": ["streamer_a", "streamer_b"],
    "Gaming Streams": ["streamer_c"]
  }
}
```

### Option 2: Configure in `configs/config.json`
Inside the tracked `user` array:
```json
"user": [
  {
    "username": "nursedonlaw27",
    "playlist": "Nurse Don Law Archive"
  },
  {
    "username": "ser.dandan",
    "playlist": "PLxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
  }
]
```

### Option 3: Command-Line Flag (`-playlist`)
When running manual or temporary recordings:
```bash
python src/main.py -user nursedonlaw27 -mode manual -duration 120 -youtube -playlist "Nurse Don Law Archive"
```
