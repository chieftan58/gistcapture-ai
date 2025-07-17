# American Optimist Download Fix

## The Problem
American Optimist episodes fail to download because:
1. They're hosted on Substack with Cloudflare protection
2. Episode titles differ between RSS feed and YouTube
3. Manual YouTube URLs aren't being routed properly

## Systemic Fixes Implemented

### 1. Automatic YouTube Search (NEW)
Added `_search_youtube_for_episode()` in `youtube_strategy.py` that:
- Searches by episode number (e.g., "Episode 119")
- Extracts key terms from titles for fuzzy matching
- Uses YouTube Data API if available (set `YOUTUBE_API_KEY` in .env)
- Falls back to yt-dlp search without API

### 2. Manual URL Improvements
The system already handles manual YouTube URLs correctly:
- Detects YouTube URLs and routes to YouTube strategy
- Uses YouTube semaphore for rate limiting
- Applies cookie authentication automatically

## How to Use

### Option 1: Automatic (Recommended)
1. Set YouTube API key in .env file:
   ```
   YOUTUBE_API_KEY=your_api_key_here
   ```
2. Run normally - system will search YouTube automatically

### Option 2: Manual URL
1. Find episode on YouTube
2. Copy the YouTube URL
3. Click "Manual URL" on failed episode
4. Paste the YouTube URL (e.g., https://www.youtube.com/watch?v=l2sdZ1IyZx8)
5. System will download using YouTube strategy with cookies

### Option 3: Quick Mapping
For frequently used episodes, add to EPISODE_MAPPINGS:
```python
"American Optimist|keyword": "https://www.youtube.com/watch?v=VIDEO_ID",
```

## Testing
To test the fix:
```bash
python main.py 7  # Will now search YouTube automatically
```

## Notes
- YouTube cookies must be valid (check with `python test_youtube_cookies.py`)
- Episode numbers are the most reliable search method
- The system learns from successful downloads for future runs