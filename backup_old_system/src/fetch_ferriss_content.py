import feedparser
from datetime import datetime, timedelta

def fetch_tim_ferriss_content(days_back=7):
    FEED_URL = "https://rss.art19.com/tim-ferriss-show"
    print(f"🌐 Parsing feed: {FEED_URL}")

    feed = feedparser.parse(FEED_URL)
    recent_eps = []

    cutoff = datetime.now() - timedelta(days=days_back)

    for entry in feed.entries:
        pub_date = datetime(*entry.published_parsed[:6])
        if pub_date < cutoff:
            continue

        if not entry.enclosures:
            continue  # Skip if no audio URL

        recent_eps.append({
            "title": entry.title,
            "url": entry.enclosures[0].href,
            "published": pub_date.strftime("%Y-%m-%d")
        })

    print(f"✅ Found {len(recent_eps)} episode(s) from the last {days_back} day(s).")
    return recent_eps
