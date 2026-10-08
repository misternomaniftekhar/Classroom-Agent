"""Streamlit dashboard for the Classroom -> WhatsApp agent."""
import json
import requests
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Classroom Agent", page_icon="📚", layout="wide")
st.title("📚 Classroom → WhatsApp Agent")

REPO = st.secrets.get("GH_REPO", "")        # e.g. "iftekhar/classroom-agent"
TOKEN = st.secrets.get("GH_TOKEN", "")      # fine-grained token (Contents: read, Actions: write)

if not REPO:
    st.warning("Add GH_REPO (and GH_TOKEN) in the app's Secrets to connect the dashboard.")
    st.stop()

HEADERS = {"Accept": "application/vnd.github.raw+json"}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"


@st.cache_data(ttl=120)
def load_state():
    r = requests.get(
        f"https://api.github.com/repos/{REPO}/contents/state.json",
        headers=HEADERS, timeout=20,
    )
    r.raise_for_status()
    return json.loads(r.text)


try:
    state = load_state()
except Exception as e:
    st.error(f"Could not load state.json: {e}")
    st.stop()

log = state.get("log", [])
df = pd.DataFrame(log) if log else pd.DataFrame(
    columns=["time", "type", "course", "title", "due", "message"]
)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Items tracked", len(state.get("seen", [])))
c2.metric("Assignments sent", int((df["type"] == "assignment").sum()))
c3.metric("Announcements sent", int((df["type"] == "announcement").sum()))
c4.metric("Reminders sent", int((df["type"] == "reminder").sum()))

st.subheader("Notification history")
if df.empty:
    st.info("No notifications sent yet. New posts in your classes will show up here.")
else:
    kinds = st.multiselect("Filter by type", sorted(df["type"].unique()), default=list(df["type"].unique()))
    view = df[df["type"].isin(kinds)].iloc[::-1]
    st.dataframe(view.drop(columns=["message"]), use_container_width=True, hide_index=True)
    with st.expander("View full messages"):
        for _, row in view.head(20).iterrows():
            st.markdown(f"**{row['time']} · {row['course']}**")
            st.text(row["message"])

st.divider()
col_a, col_b = st.columns(2)
if col_a.button("🔄 Refresh"):
    load_state.clear()
    st.rerun()

if col_b.button("▶️ Run check now"):
    if not TOKEN:
        st.error("GH_TOKEN is required to trigger the workflow.")
    else:
        r = requests.post(
            f"https://api.github.com/repos/{REPO}/actions/workflows/notify.yml/dispatches",
            headers={"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json"},
            json={"ref": "main"}, timeout=20,
        )
        if r.status_code == 204:
            st.success("Workflow triggered. Refresh in a minute.")
        else:
            st.error(f"{r.status_code}: {r.text}")
