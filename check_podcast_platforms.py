#!/usr/bin/env python3
"""Check various podcast platforms for American Optimist"""

import asyncio
import aiohttp
import re
from urllib.parse import quote

async def check_platforms():
    print("CHECKING PODCAST PLATFORMS FOR AMERICAN OPTIMIST")
    print("=" * 80)
    
    async with aiohttp.ClientSession() as session:
        # 1. Check Spotify (even though yt-dlp says it's broken)
        print("\n1. SPOTIFY")
        print("-" * 40)
        # Spotify embeds might work
        spotify_embed = "https://open.spotify.com/embed/episode/[EPISODE_ID]"
        print("Spotify might have American Optimist - need to check manually")
        print("Embed URL pattern:", spotify_embed)
        
        # 2. Check Google Podcasts
        print("\n2. GOOGLE PODCASTS") 
        print("-" * 40)
        google_url = f"https://podcasts.google.com/search/{quote('American Optimist Joe Lonsdale')}"
        print(f"Search URL: {google_url}")
        # Note: Google Podcasts is shutting down
        
        # 3. Check Overcast
        print("\n3. OVERCAST")
        print("-" * 40)
        overcast_search = "https://overcast.fm/itunes1573141757"  # Using Apple ID
        print(f"Overcast URL (using Apple ID): {overcast_search}")
        
        # Try to fetch Overcast page
        try:
            async with session.get(overcast_search, timeout=10) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    # Look for audio URLs
                    audio_matches = re.findall(r'(https://[^"]+\.mp3[^"]*)', text)
                    if audio_matches:
                        print("✅ Found MP3 URLs on Overcast!")
                        for url in audio_matches[:3]:
                            print(f"   - {url[:80]}...")
                    else:
                        print("❌ No MP3 URLs found on Overcast page")
                else:
                    print(f"❌ Overcast returned status: {resp.status}")
        except Exception as e:
            print(f"❌ Overcast error: {e}")
        
        # 4. Check Podtrac (common podcast analytics/redirect service)
        print("\n4. PODTRAC")
        print("-" * 40)
        # Many podcasts use Podtrac for analytics
        podtrac_patterns = [
            "https://dts.podtrac.com/redirect.mp3/",
            "https://play.podtrac.com/",
            "https://www.podtrac.com/pts/redirect.mp3/"
        ]
        print("Common Podtrac patterns that might have American Optimist:")
        for pattern in podtrac_patterns:
            print(f"   - {pattern}[original_url]")
        
        # 5. Check RSS feed with different approaches
        print("\n5. RSS FEED TRICKS")
        print("-" * 40)
        rss_url = "https://api.substack.com/feed/podcast/1231981.rss"
        
        # Try with different user agents
        user_agents = [
            "iTunes/12.8 (Macintosh; OS X 10.13.6) AppleWebKit/605.1.15",
            "Overcast/3.0 (+http://overcast.fm/; iOS podcast app)",
            "Castro 2019.13.0/1166",
            "Spotify/8.5.0 Android/29 (Android 10)"
        ]
        
        print("Trying RSS with different User-Agents...")
        for ua in user_agents:
            try:
                headers = {'User-Agent': ua}
                async with session.get(rss_url, headers=headers, timeout=5) as resp:
                    print(f"   {ua[:30]}... -> Status: {resp.status}")
                    if resp.status == 200:
                        text = await resp.text()
                        # Check if URLs are different
                        enclosures = re.findall(r'<enclosure[^>]+url="([^"]+)"', text)
                        if enclosures:
                            print(f"      Found URL: {enclosures[0][:60]}...")
            except Exception as e:
                print(f"   {ua[:30]}... -> Error: {str(e)[:30]}")
        
        # 6. Try web player APIs
        print("\n6. WEB PLAYER APIS")
        print("-" * 40)
        print("Possible web player endpoints that might bypass Cloudflare:")
        endpoints = [
            "https://americanoptimist.substack.com/api/v1/audio/[episode_id]",
            "https://api.substack.com/podcast/episode/[episode_id]/stream",
            "https://cdn.substack.com/audio/[episode_id].mp3"
        ]
        for endpoint in endpoints:
            print(f"   - {endpoint}")

# Additional investigation
async def check_archive_org():
    print("\n7. ARCHIVE.ORG")
    print("-" * 40)
    
    async with aiohttp.ClientSession() as session:
        # Search Archive.org
        search_url = "https://archive.org/advancedsearch.php?q=american+optimist+joe+lonsdale&fl=identifier,title,date&output=json&rows=10"
        
        try:
            async with session.get(search_url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get('response', {}).get('docs'):
                        print("✅ Found items on Archive.org:")
                        for doc in data['response']['docs'][:5]:
                            print(f"   - {doc.get('title', 'Unknown')}")
                            print(f"     ID: {doc.get('identifier')}")
                            print(f"     URL: https://archive.org/details/{doc.get('identifier')}")
                    else:
                        print("❌ No items found on Archive.org")
                else:
                    print(f"❌ Archive.org search failed: {resp.status}")
        except Exception as e:
            print(f"❌ Archive.org error: {e}")

if __name__ == "__main__":
    asyncio.run(check_platforms())
    asyncio.run(check_archive_org())