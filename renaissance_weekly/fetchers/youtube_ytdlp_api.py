"""
YouTube search using yt-dlp Python API
"""

from typing import Optional, List
import yt_dlp
from datetime import datetime
import re
from ..utils.logging import get_logger

logger = get_logger(__name__)

class YtDlpSearcher:
    """Search YouTube using yt-dlp Python API"""
    
    @staticmethod
    async def search_youtube(query: str, limit: int = 5) -> List[dict]:
        """Search YouTube and return video info"""
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'force_generic_extractor': False,
            'default_search': 'ytsearch',
            'playlist_items': f'1-{limit}',
            # Don't use cookies by default - works better in this environment
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                result = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
                
                if not result or 'entries' not in result:
                    return []
                
                videos = []
                for entry in result['entries']:
                    if entry:
                        videos.append({
                            'id': entry.get('id'),
                            'title': entry.get('title'),
                            'channel': entry.get('channel', entry.get('uploader')),
                            'duration': entry.get('duration'),
                            'upload_date': entry.get('upload_date'),
                            'url': f"https://www.youtube.com/watch?v={entry.get('id')}"
                        })
                
                return videos
                
        except Exception as e:
            logger.error(f"yt-dlp search error: {e}")
            return []
    
    @staticmethod
    async def get_audio_url(video_url: str) -> Optional[str]:
        """Get direct audio URL from YouTube video"""
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'format': 'bestaudio/best',
            'no_playlist': True,
            # Don't use cookies by default - works better in this environment
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=False)
                
                if info and 'url' in info:
                    return info['url']
                elif info and 'formats' in info:
                    # Find best audio format
                    audio_formats = [f for f in info['formats'] if f.get('acodec') != 'none']
                    if audio_formats:
                        # Sort by quality
                        audio_formats.sort(key=lambda x: x.get('abr', 0), reverse=True)
                        return audio_formats[0].get('url')
                        
        except Exception as e:
            logger.error(f"yt-dlp get URL error: {e}")
        
        return None
    
    @staticmethod
    def match_episode(query: str, videos: List[dict], episode_date=None) -> Optional[dict]:
        """Find best matching video for episode"""
        if not videos:
            return None
        
        query_lower = query.lower()
        
        # Score each video
        best_score = 0
        best_video = None
        
        for video in videos:
            score = 0
            title_lower = video.get('title', '').lower()
            
            # Check for key terms
            query_words = set(query_lower.split())
            title_words = set(title_lower.split())
            common_words = query_words & title_words
            
            # Score based on word overlap
            if len(query_words) > 0:
                score = len(common_words) / len(query_words) * 100
            
            # Bonus for episode numbers
            query_ep = re.search(r'ep\s*(\d+)', query_lower)
            title_ep = re.search(r'ep\s*(\d+)', title_lower)
            if query_ep and title_ep and query_ep.group(1) == title_ep.group(1):
                score += 50
            
            # Check upload date if provided
            if episode_date and video.get('upload_date'):
                try:
                    upload_date = datetime.strptime(video['upload_date'], '%Y%m%d')
                    days_diff = abs((upload_date.date() - episode_date.date()).days)
                    if days_diff <= 7:  # Within a week
                        score += 30
                except:
                    pass
            
            if score > best_score:
                best_score = score
                best_video = video
        
        # Require minimum score
        if best_score >= 40:
            logger.info(f"Found YouTube match (score: {best_score}): {best_video['title']}")
            return best_video
        
        return None