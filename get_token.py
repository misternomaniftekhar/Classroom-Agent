"""
Run this ONCE on your own computer to log in to Google.
It creates token_for_github.json -> paste its content into the
GitHub secret GOOGLE_TOKEN_JSON. Never commit that file.
"""
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.coursework.me.readonly",
    "https://www.googleapis.com/auth/classroom.announcements.readonly",
]

flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
creds = flow.run_local_server(port=0)

with open("token_for_github.json", "w") as f:
    f.write(creds.to_json())

print("Saved token_for_github.json - copy its content into the GOOGLE_TOKEN_JSON secret.")
