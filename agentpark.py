import os
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
import pickle

# Load environment variables from .env
load_dotenv()

NYT_KEY = os.getenv("NYT_API_KEY")
WEATHER_KEY = os.getenv("WEATHER_API_KEY")
LAT = os.getenv("HOME_LAT")
LON = os.getenv("HOME_LON")

# Google API scopes
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
CAL_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


def get_credentials(scopes, token_filename):
    """
    Handles Google OAuth flow for either Gmail or Calendar.
    Saves token to token_filename so you only log in once.
    """
    creds = None
    if os.path.exists(token_filename):
        with open(token_filename, "rb") as token:
            creds = pickle.load(token)

    # If there are no (valid) credentials, let user log in via browser
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json", scopes
            )
            creds = flow.run_local_server(port=0)

        with open(token_filename, "wb") as token:
            pickle.dump(creds, token)

    return creds


# -------- NYT NEWS --------

def get_top_news(limit=None):
    """
    Fetches top global/political and technology news from NYT.

    Returns a dict:
    {
        "global_politics": [
            {"ordinal": "first", "title": "...", "summary": "..."},
            ...
        ],
        "technology": [
            {"ordinal": "first", "title": "...", "summary": "..."},
            ...
        ]
    }

    `limit` is kept for backward compatibility but is not used. The function
    returns 2–3 global/political stories and 3–4 technology stories.
    """
    ORDINAL_WORDS = ["first", "second", "third", "fourth", "fifth"]

    def _fetch_nyt_section(section, api_key, max_items):
        """
        Helper to fetch a section from NYT Top Stories.
        """
        url = f"https://api.nytimes.com/svc/topstories/v2/{section}.json"
        resp = requests.get(url, params={"api-key": api_key}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data.get("results", [])[:max_items]

    def _build_rich_summary(story):
        """
        Turn NYT fields into a richer multi-sentence summary.
        """
        abstract = (story.get("abstract") or "").strip()
        if not abstract:
            abstract = (story.get("snippet") or "").strip()

        section = (story.get("section") or "").strip()
        subsection = (story.get("subsection") or "").strip()
        byline = (story.get("byline") or "").strip()
        geo = story.get("geo_facet") or []
        des = story.get("des_facet") or []

        extra_sentences = []

        if section:
            if subsection:
                extra_sentences.append(
                    f"This story appears in the {section} – {subsection} section of the New York Times."
                )
            else:
                extra_sentences.append(
                    f"This story appears in the {section} section of the New York Times."
                )

        if geo:
            extra_sentences.append(
                f"It is particularly focused on {', '.join(geo[:2])}."
            )

        if des:
            extra_sentences.append(
                f"Key themes include {', '.join(des[:3])}."
            )

        if byline:
            extra_sentences.append(byline)

        if not abstract and not extra_sentences:
            return "No summary available."

        return " ".join([abstract] + extra_sentences)

    # --- If no API key, return a helpful message ---
    if not NYT_KEY:
        msg = "Add NYT_API_KEY in your .env file to enable news."
        fallback = [{
            "ordinal": "first",
            "title": "(NYT API key missing)",
            "summary": msg
        }]
        return {
            "global_politics": fallback,
            "technology": fallback,
        }

    try:
        # ---------- Global / Political (2–3 items) ----------
        world_stories = _fetch_nyt_section("world", NYT_KEY, max_items=8)
        politics_stories = _fetch_nyt_section("politics", NYT_KEY, max_items=8)
        global_candidates = world_stories + politics_stories

        # Sort by published_date desc if present
        global_candidates.sort(
            key=lambda s: s.get("published_date", ""),
            reverse=True,
        )

        global_politics_items = []
        seen_titles = set()

        for s in global_candidates:
            title = (s.get("title") or "").strip()
            if not title or title in seen_titles:
                continue

            seen_titles.add(title)
            summary = _build_rich_summary(s)

            idx = len(global_politics_items)
            ordinal = ORDINAL_WORDS[idx] if idx < len(ORDINAL_WORDS) else f"{idx + 1}th"

            global_politics_items.append(
                {
                    "ordinal": ordinal,
                    "title": title,
                    "summary": summary,
                }
            )

            if len(global_politics_items) >= 3:  # 2–3 global/political stories
                break

        # ---------- Technology (3–4 items) ----------
        tech_stories = _fetch_nyt_section("technology", NYT_KEY, max_items=10)
        tech_items = []
        seen_titles = set()

        for s in tech_stories:
            title = (s.get("title") or "").strip()
            if not title or title in seen_titles:
                continue

            seen_titles.add(title)
            summary = _build_rich_summary(s)

            idx = len(tech_items)
            ordinal = ORDINAL_WORDS[idx] if idx < len(ORDINAL_WORDS) else f"{idx + 1}th"

            tech_items.append(
                {
                    "ordinal": ordinal,
                    "title": title,
                    "summary": summary,
                }
            )

            if len(tech_items) >= 4:  # 3–4 tech stories
                break

        # Fallbacks if lists ended up empty
        if not global_politics_items:
            global_politics_items.append(
                {
                    "ordinal": "first",
                    "title": "No global or political stories available.",
                    "summary": "The New York Times API did not return any global or political stories at this time.",
                }
            )

        if not tech_items:
            tech_items.append(
                {
                    "ordinal": "first",
                    "title": "No technology stories available.",
                    "summary": "The New York Times API did not return any technology stories at this time.",
                }
            )

        return {
            "global_politics": global_politics_items,
            "technology": tech_items,
        }

    except Exception as e:
        err = f"Error fetching NYT news: {e}"
        fallback = [{
            "ordinal": "first",
            "title": "News unavailable",
            "summary": err
        }]
        return {
            "global_politics": fallback,
            "technology": fallback,
        }



# -------- WEATHER --------
def get_weather_summary():
    if not WEATHER_KEY:
        return "(Weather API key missing – add WEATHER_API_KEY in .env)"

    url = "https://api.openweathermap.org/data/2.5/weather?lat=37.7749&lon=-122.4194&appid=cf2ec116811073a689499aec6848f2b5"
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
    news = get_top_news()  # updated: no limit argument, returns dict
    events = get_today_calendar_events()
    packages = get_recent_package_emails()

    global_news = (news or {}).get("global_politics", [])
    tech_news = (news or {}).get("technology", [])

    parts = []
    parts.append(f"Alrighty, here’s your rundown for {today_str}.")

    # Weather
    parts.append(f"\nWeather: {weather}.")

    # News
    if global_news or tech_news:
        parts.append("\nHere are today's trending stories:")

    # Global / political updates
    if global_news:
        parts.append("\nFirst, let’s ramp you up on the global and political updates.")
        for item in global_news:
            ordinal = item.get("ordinal", "").strip() or "first"
            title = (item.get("title") or "").strip()
            summary = (item.get("summary") or "").strip()

            # Spoken-style phrasing: first, second, third...
            if title:
                parts.append(f"The {ordinal} global update is: {title}.")
            if summary:
                parts.append(summary)

    # Technology updates
    if tech_news:
        parts.append("\nNow, here's the latest within the tech industry.")
        for item in tech_news:
            ordinal = item.get("ordinal", "").strip() or "first"
            title = (item.get("title") or "").strip()
            summary = (item.get("summary") or "").strip()

            if title:
                parts.append(f"The {ordinal} tech trend is: {title}.")
            if summary:
                parts.append(summary)

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
        parts.append("\nYou don't have any delivery updates you need to worry about right now.")

    return "\n".join(parts)


if __name__ == "__main__":
    summary = build_morning_summary()
    print(summary)
