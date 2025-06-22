import json
import feedparser
import requests
from bs4 import BeautifulSoup
import os

CONFIG_PATH = os.path.join("config", "sources.json")

def load_sources():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)

def fetch_youtube(channel_url):
    print(f"📺 [YouTube] Pulling channel: {channel_url}")
    # Placeholder: YouTube API logic will go here
    return ["Latest YouTube video link (not yet implemented)"]

def fetch_podcast(rss_url):
    print(f"🎧 [Podcast] Fetching: {rss_url}")
    try:
        feed = feedparser.parse(rss_url)
        links = []

        for entry in feed.entries[:5]:
            # Safeguard: some entries may not have a link
            link = entry.get("link") or entry.get("enclosures", [{}])[0].get("href")
            if link:
                links.append(link)

        return links
    except Exception as e:
        print(f"❌ Failed to fetch podcast: {e}")
        return []


def fetch_blog(blog_url):
    print(f"📝 [Blog] Fetching: {blog_url}")
    try:
        resp = requests.get(blog_url)
        soup = BeautifulSoup(resp.content, "html.parser")
        base_domain = blog_url.split("//")[-1].split("/")[0]

        # Only grab links that start with the blog base URL
        links = [
            a['href'] for a in soup.find_all('a', href=True)
            if base_domain in a['href'] or a['href'].startswith("/")
        ]

        # Normalize relative links
        full_links = []
        for href in links:
            if href.startswith("http"):
                full_links.append(href)
            elif href.startswith("/"):
                full_links.append(f"https://{base_domain}{href}")

        return full_links[:3]

    except Exception as e:
        print(f"❌ Failed to fetch blog: {e}")
        return []


def fetch_all_sources():
    data = load_sources()
    all_links = []

    for source in data["sources"]:
        print(f"\n🔎 Fetching from: {source['name']} ({source['type']})")

        if source["type"] == "youtube":
            links = fetch_youtube(source["url"])
        elif source["type"] == "podcast":
            links = fetch_podcast(source["url"])
        elif source["type"] == "blog":
            links = fetch_blog(source["url"])
        else:
            print(f"⚠️ Unknown type: {source['type']}")
            links = []

        print(f"✅ Found {len(links)} link(s):")
        for link in links:
            print(" •", link)

        all_links.extend(links)

    return all_links
