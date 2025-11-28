import os
from datetime import datetime, timedelta
from pathlib import Path
import pickle

import requests
from dotenv import load_dotenv
from openai import OpenAI

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request



# ---------------- ENV + CONFIG ----------------

# Load environment variables from .env
load_dotenv()

# API keys and config from .env
NYT_KEY = os.getenv("NYT_API_KEY")
WEATHER_KEY = os.getenv("WEATHER_API_KEY")
LAT = os.getenv("HOME_LAT")
LON = os.getenv("HOME_LON")
OPENAI_API_KEY = os.getenv ("OpenAI_API_KEY")


# Folder where credentials.json and token_*.pkl live
SECRET_DIR = Path(os.getenv("AGENTPARK_SECRET_DIR", "")).expanduser()
credentials_path = SECRET_DIR /  "credentials.json"


# Google API scopes
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
CAL_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


def get_credentials(scopes, token_filename: str):
    """
    Handles Google OAuth flow for either Gmail or Calendar.
    Saves token to token_filename inside SECRET_DIR so you only log in once.
    """
    if not SECRET_DIR:
        raise RuntimeError(
            "AGENTPARK_SECRET_DIR is not set. Add it to your .env file."
        )

    # Debug helpers – you can remove these once things work
    print("SECRET_DIR is:", SECRET_DIR)

    # Build full path to the token file in the secrets folder
    token_path = SECRET_DIR / token_filename
    print("Using token file:", token_path, "Exists:", token_path.exists())

    creds = None
    if token_path.exists():
        with open(token_path, "rb") as token_file:
            creds = pickle.load(token_file)

    # If there are no (valid) credentials, let user log in via browser
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            credentials_path = SECRET_DIR / "credentials.json"
            print(
                "Using credentials file:",
                credentials_path,
                "Exists:",
                credentials_path.exists(),
            )

            flow = InstalledAppFlow.from_client_secrets_file(
                str(credentials_path), scopes
            )
            creds = flow.run_local_server(port=0)

        # Save the refreshed/new token back into the secrets folder
        with open(token_path, "wb") as token_file:
            pickle.dump(creds, token_file)

    return creds


# -------- NYT NEWS --------
# Create OpenAI client (will be None if key missing)

def _expand_summary_with_gpt(title, abstract, url=None, target_sentences=7):
    """
    Use GPT to turn a short NYT abstract into a longer, 5–10 sentence overview.
    If anything goes wrong, just return the original abstract.
    """
    if not client or not abstract:
        return abstract or "No summary available."

    prompt = f"""
You are preparing a spoken news briefing.

New York Times story:
Title: {title}
Short abstract: {abstract}
URL (may or may not be accessible): {url or "N/A"}

Write a clear, factual, {target_sentences}-sentence overview suitable
for a ~2-minute spoken summary. Requirements:
- Be concise but informative.
- Do NOT mention this is an 'abstract' or 'article' or 'URL'.
- Focus on what happened, why it matters, and key context.
- Avoid speculation and made-up details; stay grounded in the abstract.
"""

    try:
        resp = client.responses.create(
            model="gpt-4.1-mini",
            input=prompt,
            max_output_tokens=500,
        )
        # Extract text from the response; adjust if your OpenAI client shape differs
        long_text = resp.output[0].content[0].text.strip()
        return long_text or abstract
    except Exception:
        # On any error, fall back to the original abstract
        return abstract


def get_top_news(limit=5, detailed=False, target_sentences=7):
    """
    Returns a list of dicts like:
    [
        {"title": "...", "summary": "..."},
        ...
    ]

    If detailed=True, 'summary' will be expanded into a 5–10 sentence overview
    using GPT (approx. 2-minute spoken summary).
    """
    if not NYT_KEY:
        return [
            {
                "title": "(NYT API key missing)",
                "summary": "Add NYT_API_KEY in your .env file to enable news.",
            }
        ]

    url = "https://api.nytimes.com/svc/topstories/v2/home.json"
    resp = requests.get(url, params={"api-key": NYT_KEY})
    resp.raise_for_status()
    data = resp.json()

    stories = data.get("results", [])[:limit]
    items = []

    for s in stories:
        title = (s.get("title") or "").strip()
        abstract = (s.get("abstract") or "").strip()

        # Fallback if abstract is empty
        if not abstract:
            abstract = (s.get("snippet") or "").strip()

        story_url = s.get("url")  # might be useful later

        if not title:
            continue

        summary = abstract if abstract else "No summary available."

        if detailed:
            summary = _expand_summary_with_gpt(
                title=title,
                abstract=summary,
                url=story_url,
                target_sentences=target_sentences,
            )

        items.append(
            {
                "title": title,
                "summary": summary,
                # optional: include URL in case you want to link it in the voice/text
                "url": story_url,
            }
        )

    return items

# -------- WEATHER --------
def get_weather_summary():
    if not WEATHER_KEY:
        return "(Weather API key missing – add WEATHER_API_KEY in .env)"

    if not LAT or not LON:
        return "(Location missing – add HOME_LAT and HOME_LON in .env)"

    # Base URL only; all parameters go in 'params'
    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {
        "lat": LAT,
        "lon": LON,
        "appid": WEATHER_KEY,
        "units": "imperial",
    }
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    data = resp.json()

    desc = data["weather"][0]["description"]
    temp = round(data["main"]["temp"])
    high = round(data["main"]["temp_max"])
    low = round(data["main"]["temp_min"])

    return f"{desc}, currently {temp}°F with a high of {high} and low of {low}"


# -------- CALENDAR --------
def get_today_calendar_events():
    # token_calendar.pkl should live inside SECRET_DIR
    creds = get_credentials(CAL_SCOPES, "token_calendar.pkl")
    service = build("calendar", "v3", credentials=creds)

    now = datetime.utcnow()
    end = now + timedelta(days=1)

    now_iso = now.isoformat() + "Z"
    end_iso = end.isoformat() + "Z"

    events_result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=now_iso,
            timeMax=end_iso,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    events = events_result.get("items", [])

    summaries = []
    for e in events:
        start_raw = e["start"].get("dateTime", e["start"].get("date"))
        # Try to display start time nicely
        try:
            dt = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
            start_str = dt.strftime("%I:%M %p").lstrip("0")
        except Exception:
            start_str = start_raw

        title = e.get("summary", "(no title)")
        summaries.append(f"{start_str}: {title}")

    return summaries


# -------- GMAIL: PACKAGE EMAILS --------
def get_recent_package_emails():
    # token_gmail.pkl should live inside SECRET_DIR
    creds = get_credentials(GMAIL_SCOPES, "token_gmail.pkl")
    service = build("gmail", "v1", credentials=creds)

    # Look at last 7 days for shipping language
    query = 'newer_than:7d ("your order has shipped" OR "out for delivery" OR "order update")'
    results = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=10)
        .execute()
    )
    messages = results.get("messages", [])

    if not messages:
        return []

    package_summaries = []

    for m in messages:
        msg = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=m["id"],
                format="metadata",
                metadataHeaders=["Subject", "From"],
            )
            .execute()
        )
        headers = {
            h["name"]: h["value"] for h in msg["payload"].get("headers", [])
        }
        subject = headers.get("Subject", "(no subject)")
        sender = headers.get("From", "(unknown sender)")
        package_summaries.append(f"{subject} from {sender}")

    return package_summaries


# -------- BUILD MORNING SUMMARY --------
def build_morning_summary():
    today_str = datetime.now().strftime("%A, %B %d")

    # Get data
    weather = get_weather_summary()
    # Ask for longer, ~2-minute style summaries
    headlines = get_top_news(limit=7, detailed=True, target_sentences=8)
    events = get_today_calendar_events()
    packages = get_recent_package_emails()

    parts = []
    parts.append(f"Alrighty, here’s your rundown for {today_str}.")

    # Weather
    parts.append(f"\nWeather: {weather}.")

    # News
    if headlines:
        parts.append("\nHere are some top news stories you should know about:")

    for item in headlines:
        title = (item.get("title") or "").strip()
        summary = (item.get("summary") or "").strip()

        # Bullet with title
        if title:
            parts.append(f"\n• {title}")
        # Indented multi-sentence overview under it
        if summary:
            parts.append(f"  {summary}")

    # Calendar
    if events:
        parts.append("\nYour key events today:")
        for e in events:
            parts.append(f"• {e}")
    else:
        parts.append("\nLooks like we have no events noted in the calendar today!")

    # Packages
    if packages:
        parts.append("\nRecent package updates:")
        for p in packages:
            parts.append(f"• {p}")
    else:
        parts.append(
            "\nYou don't have any new delivery updates you need to worry about right now."
        )

    return "\n".join(parts)


if __name__ == "__main__":
    summary = build_morning_summary()
    print(summary)
