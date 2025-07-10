"""Smart YouTube search that uses episode metadata from Apple Podcasts"""

import re
from typing import List, Dict, Optional
from datetime import datetime, timedelta

from ..models import Episode
from ..utils.logging import get_logger

logger = get_logger(__name__)


class SmartYouTubeSearcher:
    """Intelligently searches YouTube using episode metadata"""
    
    @staticmethod
    def extract_episode_number(title: str) -> Optional[int]:
        """Extract episode number from title"""
        patterns = [
            r'Ep\s+(\d+)[:\s]',
            r'Episode\s+(\d+)[:\s]',
            r'#(\d+)[:\s]',
            r'(\d+):\s'  # Just number at start with colon
        ]
        
        for pattern in patterns:
            match = re.search(pattern, title, re.IGNORECASE)
            if match:
                try:
                    return int(match.group(1))
                except:
                    pass
        return None
    
    @staticmethod
    def extract_guest_name(title: str) -> Optional[str]:
        """Extract guest name from episode title"""
        # Remove episode number prefix
        title_clean = re.sub(r'^(Ep\.?\s*\d+[:\s]+|Episode\s*\d+[:\s]+|#\d+[:\s]+)', '', title, flags=re.IGNORECASE)
        
        # Common patterns for guest names
        patterns = [
            # "Marc Andreessen on AI and Robotics"
            r'^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+on\s+',
            # "Marc Andreessen: How to Build"
            r'^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s*:',
            # "Interview with Marc Andreessen"
            r'^(?:Interview with|Conversation with|with)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, title_clean)
            if match:
                return match.group(1).strip()
        
        # If title has colon, check if part before colon is a name
        if ':' in title_clean:
            potential_guest = title_clean.split(':')[0].strip()
            words = potential_guest.split()
            # Check if it looks like a name (2-4 words, capitalized)
            if 2 <= len(words) <= 4 and all(w[0].isupper() for w in words if w):
                return potential_guest
        
        return None
    
    @staticmethod
    def build_search_queries(episode: Episode, podcast_config: Dict) -> List[str]:
        """Build smart YouTube search queries based on episode metadata"""
        queries = []
        
        # Extract metadata
        ep_num = SmartYouTubeSearcher.extract_episode_number(episode.title)
        guest = SmartYouTubeSearcher.extract_guest_name(episode.title)
        
        # Get channel info from config
        channel_name = podcast_config.get('retry_strategy', {}).get('youtube_channel_name', 'Joe Lonsdale')
        podcast_name = podcast_config.get('name', 'American Optimist')
        
        # Build queries in order of specificity
        if ep_num and guest:
            # Most specific: channel + episode number + guest
            queries.append(f'"{channel_name}" "episode {ep_num}" "{guest}"')
            queries.append(f'"{podcast_name}" {ep_num} {guest}')
        
        if guest:
            # Guest-focused searches
            queries.append(f'"{channel_name}" "{guest}"')
            queries.append(f'"{podcast_name}" {guest}')
            # Try just guest name with channel (sometimes title doesn't include podcast name)
            queries.append(f'{channel_name} {guest} podcast')
        
        if ep_num:
            # Episode number searches
            queries.append(f'"{podcast_name}" "episode {ep_num}"')
            queries.append(f'{channel_name} "Ep {ep_num}"')
            queries.append(f'"{channel_name}" episode {ep_num}')
        
        # Date-based search (if recent)
        days_ago = (datetime.now() - episode.published).days
        if days_ago <= 30:
            date_str = episode.published.strftime('%B %Y')
            queries.append(f'"{channel_name}" "{podcast_name}" {date_str}')
        
        # Full title fallback (but cleaned up)
        # Remove common prefixes that might confuse search
        clean_title = re.sub(r'^(Ep\.?\s*\d+[:\s]+|Episode\s*\d+[:\s]+|#\d+[:\s]+)', '', episode.title, flags=re.IGNORECASE)
        queries.append(f'{channel_name} "{clean_title}"')
        
        # Remove duplicates while preserving order
        seen = set()
        unique_queries = []
        for q in queries:
            if q not in seen:
                seen.add(q)
                unique_queries.append(q)
        
        return unique_queries
    
    @staticmethod
    async def search_youtube_for_episode(episode: Episode, podcast_config: Dict) -> Optional[str]:
        """Search YouTube for a specific episode and return the best matching URL"""
        try:
            from .youtube_ytdlp_api import YtDlpSearcher
            
            queries = SmartYouTubeSearcher.build_search_queries(episode, podcast_config)
            
            logger.info(f"🎯 Smart YouTube search for: {episode.title}")
            
            for i, query in enumerate(queries[:3], 1):  # Try top 3 queries
                logger.info(f"  Query {i}: {query}")
                
                try:
                    # Search YouTube
                    videos = await YtDlpSearcher.search_youtube(query, limit=5)
                    
                    if videos:
                        # Check for good matches
                        for video in videos:
                            # Score the match
                            score = SmartYouTubeSearcher.score_video_match(episode, video, podcast_config)
                            
                            if score > 0.7:  # Good match threshold
                                logger.info(f"  ✅ Found match: {video['title']} (score: {score:.2f})")
                                return video['url']
                            else:
                                logger.debug(f"  Low score ({score:.2f}): {video['title'][:60]}...")
                    
                except Exception as e:
                    logger.error(f"  Query failed: {e}")
                    continue
            
            logger.warning(f"  ❌ No good YouTube matches found for: {episode.title}")
            return None
            
        except Exception as e:
            logger.error(f"Smart YouTube search error: {e}")
            return None
    
    @staticmethod
    def score_video_match(episode: Episode, video: Dict, podcast_config: Dict) -> float:
        """Score how well a YouTube video matches an episode (0.0 to 1.0)"""
        score = 0.0
        
        video_title = video.get('title', '').lower()
        episode_title = episode.title.lower()
        
        # Check for episode number
        ep_num = SmartYouTubeSearcher.extract_episode_number(episode.title)
        if ep_num:
            # Look for episode number in video title
            ep_patterns = [
                f'episode {ep_num}',
                f'ep {ep_num}',
                f'#{ep_num}',
                f' {ep_num}:',
                f' {ep_num} '
            ]
            if any(pattern in video_title for pattern in ep_patterns):
                score += 0.4
        
        # Check for guest name
        guest = SmartYouTubeSearcher.extract_guest_name(episode.title)
        if guest and guest.lower() in video_title:
            score += 0.3
        
        # Check for podcast/channel name
        podcast_name = podcast_config.get('name', '').lower()
        channel_name = podcast_config.get('retry_strategy', {}).get('youtube_channel_name', '').lower()
        
        if podcast_name and podcast_name in video_title:
            score += 0.2
        elif channel_name and channel_name in video_title:
            score += 0.1
        
        # Check video duration (podcasts are usually > 20 minutes)
        duration = video.get('duration', 0)
        if duration > 1200:  # 20 minutes
            score += 0.1
        
        # Check upload date proximity
        if 'upload_date' in video:
            try:
                upload_date = datetime.strptime(video['upload_date'], '%Y%m%d')
                days_diff = abs((upload_date - episode.published).days)
                if days_diff <= 7:
                    score += 0.1
                elif days_diff <= 14:
                    score += 0.05
            except:
                pass
        
        # Penalty for wrong channel
        video_channel = video.get('channel', '').lower()
        if video_channel and channel_name and channel_name not in video_channel:
            score -= 0.2
        
        return max(0.0, min(1.0, score))