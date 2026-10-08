"""
Classroom -> WhatsApp agent (worker).
Runs on GitHub Actions every 15 minutes:
  1. Fetch coursework + announcements from Google Classroom
  2. Detect NEW items (state.json keeps what was already seen)
  3. Summarize with an LLM (Groq or xAI Grok)
  4. Send to WhatsApp (CallMeBot or Twilio)
  5. Send deadline reminders (24h and 2h before due, if not submitted)
"""
import os
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

STATE_FILE = "state.json"
TZ = ZoneInfo(os.getenv("TIMEZONE", "Asia/Karachi"))
DRY_RUN = os.getenv("DRY_RUN") == "1"
MAX_LOG = 200


# ---------------------------------------------------------------- state
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            s = json.load(f)
    else:
        s = {}
    s.setdefault("initialized", False)
    s.setdefault("seen", [])
    s.setdefault("reminded", {})
    s.setdefault("log", [])
    return s


def save_state(s):
    s["log"] = s["log"][-MAX_LOG:]
    with open(STATE_FILE, "w") as f:
        json.dump(s, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------- google
def get_service():
    info = json.loads(os.environ["GOOGLE_TOKEN_JSON"])
    creds = Credentials.from_authorized_user_info(info)
    if not creds.valid:
        creds.refresh(Request())
    return build("classroom", "v1", credentials=creds, cache_discovery=False)


def paged(method, key, **kwargs):
    items, token = [], None
    while True:
        params = dict(kwargs)
        if token:
            params["pageToken"] = token
        resp = method(**params).execute()
        items += resp.get(key, [])
        token = resp.get("nextPageToken")
        if not token:
            break
    return items


def due_datetime(work):
    d = work.get("dueDate")
    if not d:
        return None
    t = work.get("dueTime", {})
    return datetime(
        d["year"], d["month"], d["day"],
        t.get("hours", 23), t.get("minutes", 59),
        tzinfo=timezone.utc,
    )


def fmt_due(dt):
    if not dt:
        return "No deadline"
    return dt.astimezone(TZ).strftime("%a %d %b %Y, %I:%M %p")


# ---------------------------------------------------------------- llm
def llm(prompt):
    provider = os.getenv("LLM_PROVIDER", "groq").lower()
    if provider == "xai":
        from openai import OpenAI
        client = OpenAI(api_key=os.environ["XAI_API_KEY"], base_url="https://api.x.ai/v1")
        model = os.getenv("LLM_MODEL", "grok-4")
    else:
        from groq import Groq
        client = Groq(api_key=os.environ["GROQ_API_KEY"])
        model = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")
    r = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    return r.choices[0].message.content.strip()


def summarize(course, kind, title, desc, due_text):
    prompt = (
        f"Course: {course}\nType: {kind}\nTitle: {title}\n"
        f"Description: {desc or '(none)'}\nDue: {due_text}\n\n"
        "Write a short WhatsApp message (max 60 words) for a student: what to do, "
        "the deadline, and a priority (High/Medium/Low). Plain text, at most one emoji. "
        "Do not invent details that are not given."
    )
    try:
        return llm(prompt)
    except Exception as e:  # fall back to a plain message if the LLM fails
        print("LLM failed:", e)
        short = (desc or "").strip().replace("\n", " ")[:200]
        return f"{title}\nDue: {due_text}\n{short}".strip()


# ---------------------------------------------------------------- whatsapp
def send_whatsapp(text):
    if DRY_RUN:
        print("[DRY RUN] would send:\n", text, "\n")
        return
    provider = os.getenv("WA_PROVIDER", "callmebot").lower()
    phone = os.environ["WA_PHONE"].lstrip("+")  # digits with country code, e.g. 923001234567
    if provider == "twilio":
        sid = os.environ["TWILIO_SID"]
        r = requests.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
            auth=(sid, os.environ["TWILIO_TOKEN"]),
            data={
                "From": os.getenv("TWILIO_FROM", "whatsapp:+14155238886"),
                "To": f"whatsapp:+{phone}",
                "Body": text[:1500],
            },
            timeout=30,
        )
    else:
        r = requests.get(
            "https://api.callmebot.com/whatsapp.php",
            params={"phone": f"+{phone}", "text": text, "apikey": os.environ["CALLMEBOT_KEY"]},
            timeout=30,
        )
    r.raise_for_status()


def notify(state, kind, course, title, due_text, text):
    send_whatsapp(text)
    state["log"].append({
        "time": datetime.now(TZ).strftime("%Y-%m-%d %H:%M"),
        "type": kind,
        "course": course,
        "title": title,
        "due": due_text,
        "message": text,
    })


# ---------------------------------------------------------------- main
def main():
    svc = get_service()
    state = load_state()
    first_run = not state["initialized"]
    seen = set(state["seen"])
    now = datetime.now(timezone.utc)

    courses = paged(svc.courses().list, "courses", courseStates=["ACTIVE"])
    print(f"Found {len(courses)} active courses")

    for c in courses:
        cid, cname = c["id"], c["name"]

        # submission status (to skip reminders for finished work)
        done = set()
        try:
            subs = paged(
                svc.courses().courseWork().studentSubmissions().list,
                "studentSubmissions", courseId=cid, courseWorkId="-", userId="me",
            )
            done = {s["courseWorkId"] for s in subs if s.get("state") in ("TURNED_IN", "RETURNED")}
        except Exception as e:
            print(f"Could not read submissions for {cname}: {e}")

        # ---- coursework (assignments, questions, materials)
        for w in paged(svc.courses().courseWork().list, "courseWork", courseId=cid):
            wid, title = w["id"], w.get("title", "Untitled")
            due = due_datetime(w)
            due_text = fmt_due(due)
            link = w.get("alternateLink", "")
            key = f"cw_{wid}"

            if key not in seen:
                if first_run:
                    seen.add(key)
                else:
                    summary = summarize(cname, "Assignment", title, w.get("description"), due_text)
                    text = f"📚 New in {cname}\n{summary}\n{link}".strip()
                    try:
                        notify(state, "assignment", cname, title, due_text, text)
                        seen.add(key)
                    except Exception as e:
                        print("Send failed (will retry next run):", e)

            # ---- deadline reminders
            if due and due > now and wid not in done:
                left = due - now
                sent = state["reminded"].setdefault(wid, [])
                for tag, limit in (("2h", timedelta(hours=2)), ("24h", timedelta(hours=24))):
                    if left <= limit and tag not in sent:
                        label = "2 hours" if tag == "2h" else "24 hours"
                        text = f"⏰ Due in under {label}\n{cname}: {title}\nDue: {due_text}\n{link}".strip()
                        try:
                            notify(state, "reminder", cname, title, due_text, text)
                            sent.append(tag)
                            if tag == "2h" and "24h" not in sent:
                                sent.append("24h")  # no point sending the 24h one after the 2h one
                        except Exception as e:
                            print("Reminder failed:", e)
                        break

        # ---- announcements
        for a in paged(svc.courses().announcements().list, "announcements", courseId=cid):
            key = f"an_{a['id']}"
            if key in seen:
                continue
            if first_run:
                seen.add(key)
                continue
            body = a.get("text", "")
            summary = summarize(cname, "Announcement", "Announcement", body, "N/A")
            text = f"📢 {cname}\n{summary}\n{a.get('alternateLink', '')}".strip()
            try:
                notify(state, "announcement", cname, body[:60], "N/A", text)
                seen.add(key)
            except Exception as e:
                print("Send failed (will retry next run):", e)

    state["seen"] = sorted(seen)
    state["initialized"] = True
    save_state(state)
    print("Done.")


if __name__ == "__main__":
    main()
