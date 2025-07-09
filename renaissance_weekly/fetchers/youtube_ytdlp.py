"""
YouTube search and download using yt-dlp as fallback for API
"""

import subprocess
import json
import re
from typing import Optional, List
from ..utils.logging import get_logger

logger = get_logger(__name__)

class YtDlpYouTubeSearcher:
    """Search YouTube using yt-dlp when API quota is exceeded"""
    
    @staticmethod
    async def search_youtube(query: str, limit: int = 5) -> List[dict]:
        """Search YouTube and return video info"""
        # Find yt-dlp executable
        import shutil
        yt_dlp_path = shutil.which("yt-dlp")
        if not yt_dlp_path:
            # Try common locations
            possible_paths = [
                "/home/codespace/.local/lib/python3.12/site-packages/bin/yt-dlp",
                "/home/codespace/.local/bin/yt-dlp",
                "~/.local/bin/yt-dlp"
            ]
            for path in possible_paths:
                import os
                expanded_path = os.path.expanduser(path)
                if os.path.exists(expanded_path) and os.access(expanded_path, os.X_OK):
                    yt_dlp_path = expanded_path
                    break
        
        if not yt_dlp_path:
            logger.error("yt-dlp executable not found")
            return []
        
        cmd = [
            yt_dlp_path,
            f"ytsearch{limit}:{query}",
            "--dump-json",
            "--no-playlist",
            "--quiet",
            "--no-warnings"
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0 and result.stdout:
                videos = []
                for line in result.stdout.strip().split('\n'):
                    if line:
                        try:
                            video = json.loads(line)
                            videos.append({
                                'id': video.get('id'),
                                'title': video.get('title'),
                                'channel': video.get('channel'),
                                'duration': video.get('duration'),
                                'upload_date': video.get('upload_date'),
                                'url': f"https://www.youtube.com/watch?v={video.get('id')}"
                            })
                        except json.JSONDecodeError:
                            continue
                return videos
        except Exception as e:
            logger.error(f"yt-dlp search error: {e}")
        
        return []
    
    @staticmethod
    async def get_audio_url(video_url: str) -> Optional[str]:
        """Get direct audio URL from YouTube video"""
        # Find yt-dlp executable
        import shutil
        import os
        yt_dlp_path = shutil.which("yt-dlp")
        if not yt_dlp_path:
            # Try common locations
            possible_paths = [
                "/home/codespace/.local/lib/python3.12/site-packages/bin/yt-dlp",
                "/home/codespace/.local/bin/yt-dlp",
                "~/.local/bin/yt-dlp"
            ]
            for path in possible_paths:
                expanded_path = os.path.expanduser(path)
                if os.path.exists(expanded_path) and os.access(expanded_path, os.X_OK):
                    yt_dlp_path = expanded_path
                    break
        
        if not yt_dlp_path:
            logger.error("yt-dlp executable not found")
            return None
        
        cmd = [
            yt_dlp_path,
            video_url,
            "--get-url",
            "-f", "bestaudio",
            "--no-playlist",
            "--quiet",
            "--no-warnings"
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
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
                    from datetime import datetime
                    upload_date = datetime.strptime(video['upload_date'], '%Y%m%d')
                    days_diff = abs((upload_date - episode_date).days)
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