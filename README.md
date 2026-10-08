# 📚 Classroom → WhatsApp Agent

Watches your Google Classroom and sends a WhatsApp message for every new
assignment and announcement, plus reminders 24h and 2h before a deadline
(skipped if you already turned the work in). Summaries are written by an LLM
(Groq or xAI Grok). A Streamlit dashboard shows the history.

```
GitHub Actions (every 15 min) -> worker.py -> WhatsApp
          |  state.json committed back to the repo
Streamlit Cloud -> app.py (dashboard, reads state.json)
```

## 1. Google Classroom access (one time)

1. https://console.cloud.google.com -> create a project -> enable **Google Classroom API**.
2. OAuth consent screen: User type External, add yourself as a test user,
   then **Publish app** (otherwise refresh tokens expire after 7 days).
3. Credentials -> Create **OAuth client ID** -> Desktop app -> download as `credentials.json`
   into this folder.
4. Run locally:
   ```bash
   pip install -r requirements.txt
   python get_token.py
   ```
   Log in with the Google account that is in your classes. This creates `token_for_github.json`.

If your university Workspace blocks third-party apps, use a personal Gmail that
has joined the classes, or ask for the app to be allowed.

## 2. WhatsApp (pick one)

**CallMeBot (simplest, personal use)**
Follow the activation steps at https://www.callmebot.com/blog/free-api-whatsapp-messages/
(save their number, send the activation message, you receive an API key).
Secrets: `WA_PHONE` (digits with country code, e.g. `923001234567`) and `CALLMEBOT_KEY`.

**Twilio sandbox**
Join the sandbox from the Twilio console. Set repo variable `WA_PROVIDER=twilio`
and secrets `TWILIO_SID`, `TWILIO_TOKEN`, `WA_PHONE`.

## 3. LLM

- Groq (default): key from https://console.groq.com -> secret `GROQ_API_KEY`
- xAI Grok: secret `XAI_API_KEY` and repo variable `LLM_PROVIDER=xai`
  (optionally `LLM_MODEL`, check the xAI console for current model names)

## 4. GitHub setup

1. Create a repo (private is fine) and push this folder.
2. Settings -> Secrets and variables -> Actions -> **Secrets**:
   `GOOGLE_TOKEN_JSON` (paste full content of `token_for_github.json`),
   `GROQ_API_KEY`, `WA_PHONE`, `CALLMEBOT_KEY`
   (+ `XAI_API_KEY`, `TWILIO_SID`, `TWILIO_TOKEN` if used).
3. Settings -> Actions -> General -> Workflow permissions -> **Read and write**.
4. Actions tab -> `classroom-notify` -> **Run workflow**.
   The first run only records existing items (no spam). After that, new posts trigger messages.

## 5. Streamlit dashboard

1. https://share.streamlit.io -> New app -> select repo, main file `app.py`.
2. App settings -> Secrets:
   ```toml
   GH_REPO = "your-username/your-repo"
   GH_TOKEN = "github_pat_..."   # fine-grained token: Contents (read), Actions (read & write)
   ```

## Test without sending

```bash
export GOOGLE_TOKEN_JSON="$(cat token_for_github.json)"
export GROQ_API_KEY=...
DRY_RUN=1 python worker.py
```
Messages are printed instead of sent. Delete `state.json` content back to the
initial version afterwards if you want a clean first run.

## Notes

- GitHub cron can be a few minutes late, and scheduled workflows pause after 60 days
  without repo activity (the state commits count as activity).
- Times are shown in Asia/Karachi. Change `TIMEZONE` in the workflow if needed.
- Never commit `credentials.json` or the token file.
