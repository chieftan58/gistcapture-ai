#!/usr/bin/env python3
"""
Essential fix: Add this to download_manager.py to bypass Cloudflare
This is the minimal change that will fix American Optimist & Dwarkesh
"""

print("""
ADD THIS TO download_manager.py in the _download_episode method:
(Right after checking if audio file exists, before normal download)

================================================================

# CLOUDFLARE BYPASS - Add this code
CLOUDFLARE_PODCASTS = ["American Optimist", "Dwarkesh Podcast"]
if episode.podcast in CLOUDFLARE_PODCASTS or "substack.com" in episode.audio_url:
    logger.info(f"⚡ {episode.podcast} is Cloudflare protected - trying YouTube")
    
    # YouTube URLs (expand this list as you find more)
    YOUTUBE_URLS = {
        "Marc Andreessen": "https://www.youtube.com/watch?v=pRoKi4VL_5s",
        "Dave Rubin": "https://www.youtube.com/watch?v=w1FRqBOxS8g",
        "Scott Wu": "https://www.youtube.com/watch?v=YwmQzWGyrRQ",
    }
    
    # Find YouTube URL
    youtube_url = None
    for key, url in YOUTUBE_URLS.items():
        if key.lower() in episode.title.lower():
            youtube_url = url
            logger.info(f"✅ Found YouTube URL: {url}")
            break
    
    if youtube_url:
        # Download from YouTube
        cmd = [
            'yt-dlp', '--cookies-from-browser', 'firefox',
            '-x', '--audio-format', 'mp3', '-o', str(audio_file),
            youtube_url
        ]
        
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, 
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0 and audio_file.exists():
                logger.info("✅ Downloaded from YouTube successfully!")
                status.audio_path = audio_file
                status.status = 'success'
                self.stats['downloaded'] += 1
                self._report_progress()
                return audio_file
        except Exception as e:
            logger.error(f"YouTube download failed: {e}")

# END CLOUDFLARE BYPASS - Continue with normal download...

================================================================

That's it! This simple addition will fix American Optimist and Dwarkesh.
Add more YouTube URLs to the dictionary as you discover them.
""")