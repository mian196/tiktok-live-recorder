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

### Restricted Country
Telegram is banned in many countries check the full list in this [Wikepedia Artcile](https://en.wikipedia.org/wiki/Censorship_of_Telegram) 
