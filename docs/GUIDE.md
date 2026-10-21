# GUIDE

### How To Set Cookies
1) Go to https://www.tiktok.com/.
2) Open Inspect Element => Ctrl + Shift + I for Windows/Linux and Cmd + Option + I for macOS users. Or, right-click on the web page and choose Inspect to access the Developer tools panel.
3) Switch to the **Application** tab.

![image](https://github.com/user-attachments/assets/7a7cb64b-41fe-49ed-9d85-bc00d451b9ef)

4) **Copy** the **value** of session_ss.

![image](https://github.com/user-attachments/assets/dccd9b11-6efc-4cb9-8003-599a4fcc8957)

5) **Paste** this **value** into the cookies.json file.

![image](https://github.com/user-attachments/assets/5cd23e80-bfb0-45d4-9141-601807dc027b)

<br />

### How To Get Room_ID
1) Go to https://www.tiktok.com/@username/live
2) Open Inspect Element => Ctrl + Shift + I for Windows/Linux and Cmd + Option + I for macOS users. Or, right-click on the web page and choose Inspect to access the Developer tools panel
3) Search "room_id" with Ctrl + F

![image](https://user-images.githubusercontent.com/31160531/202849647-922d75d6-570c-43fe-a4b3-fcb795d39f92.png)

<br />

### How to Enable Upload To Telegram
1) Go to https://my.telegram.org
2) Log in with your number registered in Telegram in  format "+{country code}{your_number}"

   ![image](https://github.com/user-attachments/assets/f591b9d2-4189-4bfe-9180-f4484625eea2)

3) Once you are authenticated, click on "API Development Tools"

   ![image](https://github.com/user-attachments/assets/89900d60-851e-4c6c-a20a-892dd99f7e24)

4) Please go ahead and create a new request by filling out the form below (skip if you already have one)

   ![image](https://github.com/user-attachments/assets/3e61e39d-81d9-4c93-ae26-c6bccf6a509c)

5) You should now have the parameter values needed to configure the telegram.json file.

   ![image](https://github.com/user-attachments/assets/b0a7fe9a-cb9b-413f-a5bf-2434146c63b3)

<br />

### How to Enable Upload To YouTube
Follow our step-by-step setup guide here: [YouTube Upload Setup Guide](YOUTUBE_SETUP.md)

<br />

### Pre-Authentication Helper (Telegram & YouTube)
You can authenticate your accounts in advance before starting recordings or deploying to a headless server / Docker container:

```bash
python auth.py --telegram  # Authenticates Telegram session interactively in terminal
python auth.py --youtube   # Authenticates YouTube OAuth2 projects in browser
python auth.py --all       # Authenticates both
```

> [!TIP]
> **Server & Docker Deployments**: Authenticate on your local desktop first, then transfer `configs/youtube_token.json` and `tiktok_live_recorder_session.session` to your remote server for 100% headless 24/7 background operation.

<br />

### Bypassing Regional Restrictions & Censorship (Telegram)
In several countries and regions, Telegram's API endpoints and MTProto IP ranges are restricted or blocked by local ISPs and government firewalls (see the full list in the [Wikipedia Article on Censorship of Telegram](https://en.wikipedia.org/wiki/Censorship_of_Telegram)).

If you are located in a restricted region, running `python auth.py --telegram` or uploading recordings will result in connection timeouts or infinite hanging on `Connecting...`.

You can bypass these restrictions using any of the following methods:

#### 1. System-Wide VPN (Recommended & Easiest)
Running a system-wide VPN client is the most reliable way to route all Telegram API requests and video upload streams without modifying configurations.
- Use a reputable VPN provider (e.g., Proton VPN, Mullvad, WireGuard, or Cloudflare WARP).
- Connect to a server located in an unrestricted region (e.g., Europe, US, or Singapore) before running `auth.py` or starting the recorder.

#### 2. Terminal / Environment Proxy
If you use a local proxy client (e.g., V2Ray, Xray, Clash, Shadowsocks, Tor, or an SSH tunnel) that exposes a local HTTP/SOCKS5 proxy port (e.g., `127.0.0.1:10808`):

- **PowerShell (Windows)**:
  ```powershell
  $env:HTTP_PROXY="http://127.0.0.1:10808"
  $env:HTTPS_PROXY="http://127.0.0.1:10808"
  $env:ALL_PROXY="socks5://127.0.0.1:10808"
  python auth.py --telegram
  ```

- **Linux / macOS (Bash / Zsh)**:
  ```bash
  export HTTP_PROXY="http://127.0.0.1:10808"
  export HTTPS_PROXY="http://127.0.0.1:10808"
  export ALL_PROXY="socks5://127.0.0.1:10808"
  python auth.py --telegram
  ```

- **Using Proxychains (Linux / macOS)**:
  If your proxy client provides a SOCKS5 proxy, configure `/etc/proxychains.conf` and run:
  ```bash
  proxychains4 python auth.py --telegram
  ```

#### 3. Headless Server / Remote VPS Deployment
If your residential connection or country restricts Telegram:
1. Deploy the recorder on an overseas VPS (e.g., Hetzner, DigitalOcean, Linode, AWS) located in an unrestricted country.
2. Alternatively, authenticate on your local machine using a temporary VPN, then transfer the generated `tiktok_live_recorder_session.session` file to your server alongside your configuration files.

> [!NOTE]
> Telegram requires an active, uninterrupted connection to upload multi-part video chunks. Using a stable VPN connection or hosting on a low-latency VPS will prevent upload failures for large live stream recordings.
