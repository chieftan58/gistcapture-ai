"""
Fallback downloader using yt-dlp for problematic podcasts
"""

import yt_dlp
from pathlib import Path
import tempfile
from typing import Optional
from ..utils.logging import get_logger

logger = get_logger(__name__)

class YtDlpDownloader:
    """Download audio using yt-dlp when other methods fail"""
    
    @staticmethod
    async def download_from_youtube(video_url: str, output_path: Path) -> bool:
        """Download audio from YouTube video"""
        # Check for cookie file first
        cookie_file = Path.home() / '.config' / 'renaissance-weekly' / 'cookies' / 'youtube_cookies.txt'
        
        # Try cookie file first, then browsers
        attempts = ['cookie_file'] if cookie_file.exists() else []
        attempts.extend([None, 'chrome', 'firefox', 'safari', 'edge'])
        
        for attempt in attempts:
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': str(output_path),
                'quiet': True,
                'no_warnings': True,
                'extract_audio': True,
                'audio_format': 'mp3',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            }
            
            # Handle different cookie sources
            if attempt == 'cookie_file':
                ydl_opts['cookiefile'] = str(cookie_file)
                logger.info(f"📂 Trying with cookie file: {cookie_file}")
            elif attempt:
                try:
                    ydl_opts['cookiesfrombrowser'] = (attempt,)
                    logger.info(f"🌐 Trying with {attempt} browser cookies...")
                except Exception as e:
                    logger.info(f"No {attempt} cookies available, skipping...")
                    continue
            else:
                logger.info("🔓 Trying without cookies...")
            
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    logger.info(f"Attempting yt-dlp download of {video_url} to {output_path}")
                    info = ydl.extract_info(video_url, download=True)
                    
                    # Check if file exists (yt-dlp may add extension)
                    if output_path.exists():
                        logger.info(f"✅ Downloaded from YouTube: {video_url}")
                        return True
                    
                    # Check with .mp3 extension
                    mp3_path = output_path.with_suffix('.mp3')
                    if mp3_path.exists():
                        # Rename to expected path
                        mp3_path.rename(output_path)
                        logger.info(f"✅ Downloaded from YouTube: {video_url}")
                        return True
                    
                    # Check if yt-dlp created file with different name
                    output_dir = output_path.parent
                    possible_files = list(output_dir.glob(f"{output_path.stem}*"))
                    if possible_files:
                        logger.info(f"Found possible yt-dlp output files: {possible_files}")
                        # Use the first matching file
                        possible_files[0].rename(output_path)
                        logger.info(f"✅ Renamed {possible_files[0]} to {output_path}")
                        return True
                    
                    logger.error(f"yt-dlp completed but no file found at {output_path}")
                        
            except Exception as e:
                if "bot" in str(e).lower() and browser != browsers[-1]:
                    logger.info(f"Bot detection with {browser}, trying next browser...")
                    continue
                logger.error(f"yt-dlp download error with {browser}: {e}")
        
        return False
    
    @staticmethod
    async def find_and_download_youtube(episode_title: str, podcast_name: str, output_path: Path) -> bool:
        """Search YouTube and download the episode"""
        from .youtube_ytdlp_api import YtDlpSearcher
        
        # Build search queries
        queries = []
        
        if podcast_name == "American Optimist":
            queries = [
                f"Joe Lonsdale {episode_title[:30]}",
                f"American Optimist {episode_title}",
            ]
        elif podcast_name == "Dwarkesh Podcast":
            queries = [
                f"Dwarkesh Patel {episode_title}",
                f"Dwarkesh Podcast {episode_title}",
            ]
        elif podcast_name == "All-In":
            queries = [
                f"All In Podcast {episode_title[:30]}",
                f"All-In Pod {episode_title}",
            ]
        else:
            queries = [f"{podcast_name} {episode_title}"]
        
        # Try each query
        for query in queries:
            logger.info(f"Searching YouTube: {query}")
            
            videos = await YtDlpSearcher.search_youtube(query, limit=5)
            if videos:
                logger.info(f"Found {len(videos)} YouTube videos for query: {query}")
                for v in videos:
                    logger.debug(f"  - {v.get('title', 'No title')} by {v.get('channel', 'Unknown')}")
                
                # Try to find best match
                best_match = YtDlpSearcher.match_episode(query, videos)
                if best_match:
                    logger.info(f"Found match: {best_match['title']} - {best_match['url']}")
                    success = await YtDlpDownloader.download_from_youtube(
                        best_match['url'], 
                        output_path
                    )
                    if success:
                        return True
                    else:
                        logger.warning(f"Failed to download matched video: {best_match['title']}")
                else:
                    logger.warning(f"No good match found among {len(videos)} videos")
            else:
                logger.warning(f"No YouTube videos found for query: {query}")
        
        logger.error(f"All YouTube search queries failed for {episode_title}")
        return False