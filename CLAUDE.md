# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **Note**: This file was cleaned up on 2025-07-14, reducing it from 59k to 6k characters. Detailed update history has been preserved in [CHANGELOG.md](./CHANGELOG.md).

## Project Overview

Renaissance Weekly is a Python-based podcast intelligence system that automatically fetches, transcribes, and summarizes episodes from 19 curated podcasts, then sends email digests via SendGrid.

### Key Features
- **95%+ Success Rate**: Multi-strategy download system with fallbacks
- **32x Faster Transcription**: AssemblyAI integration (vs Whisper)
- **Production Ready**: Comprehensive testing infrastructure and monitoring
- **Smart Retry System**: Different strategies based on failure type
- **Test/Full Modes**: Quick testing (15 min) or complete episode processing

## Key Commands

### Running the Application
```bash
# Process last N days of episodes (default: 7)
python main.py [days]

# Run verification report
python main.py verify [days]

# Check single podcast
python main.py check "Podcast Name" [days]

# Pre-flight check before processing
python main.py pre-flight [days]

# Run system health check
python main.py health

# Force regenerate summaries
python main.py regenerate-summaries [days]
```

### Testing Commands
```bash
# Quick verification (5 core tests)
python simple_test.py

# Full test suite
pytest

# Test with coverage
pytest --cov=renaissance_weekly --cov-report=html

# Security scanning
bandit -r renaissance_weekly
safety check
```

### Development Commands
```bash
# Test only episode fetching
python main.py --test-fetch [days]

# Test summarization with transcript
python main.py --test-summarize <transcript_file>

# Test email generation
python main.py --test-email

# Run without API calls
python main.py --dry-run [days]

# Save/load test datasets
python main.py --save-dataset <name>
python main.py --load-dataset <name>
```

## Quick Start

1. **Install Dependencies**:
   ```bash
   # System dependencies
   sudo apt-get update && sudo apt-get install -y ffmpeg
   
   # Python dependencies
   pip install -e .
   
   # Optional: Full yt-dlp support
   ./install_ytdlp_full.sh
   
   # Optional: Browser automation
   playwright install chromium
   ```

2. **Configure Environment** (.env file):
   ```
   # Required
   OPENAI_API_KEY=your_key
   SENDGRID_API_KEY=your_key
   
   # Optional - Enhanced functionality
   ASSEMBLYAI_API_KEY=your_key  # 32x faster transcription
   YOUTUBE_API_KEY=your_key      # Better YouTube search
   PODCASTINDEX_API_KEY=your_key # Transcript discovery
   ```

3. **Run the Application**:
   ```bash
   python main.py 7  # Process last 7 days
   ```

## Architecture

### Core Components
- **app.py**: Main application with resource-aware concurrency
- **database.py**: SQLite database with mode-aware caching
- **download_manager.py**: Smart download orchestration with retry logic
- **config.py**: Configuration and environment management

### Key Directories
- `/fetchers/`: Episode fetching (RSS, Apple Podcasts, YouTube)
- `/transcripts/`: Multi-source transcript finding
- `/processing/`: AI-powered summarization
- `/email/`: Email generation and sending
- `/ui/`: Web-based episode selection interface
- `/download_strategies/`: Bulletproof download system

### Processing Pipeline
1. **Fetching**: Episodes from RSS/Apple Podcasts
2. **UI Selection**: Web interface for episode selection
3. **Download Stage**: Smart routing with multiple strategies
4. **Transcript Finding**: 10+ sources checked before audio transcription
5. **Summarization**: GPT-4 with 20x concurrency
6. **Email Delivery**: SendGrid with preview

## Current System Status

### Performance Metrics
- **Overall Success Rate**: 95%+
- **Transcription Speed**: 15-30 minutes (vs 2 hours with Whisper)
- **Download Strategies**: 4 independent pathways
- **Concurrency**: Memory-aware with dynamic scaling
  - Episode processing: 2 concurrent (CPU/memory limited)
  - AssemblyAI: 32x concurrent transcriptions
  - GPT-4 summaries: 20 concurrent
  - YouTube downloads: 2 concurrent (separate semaphore)

### Multi-Strategy Download System
1. **Direct Download**: Platform-specific headers and validation
2. **YouTube Strategy**: Bypass Cloudflare protection
3. **Apple Podcasts**: Reliable fallback
4. **Browser Automation**: Last resort with Playwright

### Enhanced Features
- **Test/Full Modes**: Separate caching, visual mode indicators
- **Manual URL Support**: Accepts URLs or local file paths
- **Health Checks**: Pre-flight validation of services
- **Processing Time Estimation**: Accurate ETA before starting
- **State Persistence**: Resume capability on interruption

## Important Notes

- The project directory (`gistcapture-ai`) differs from package name (`renaissance-weekly`)
- Summaries are cached separately by mode - test mode (15 min) vs full mode (complete episodes)
- Minimum 1 episode required for email sending (previously 20)
- Browser cookies automatically used for YouTube authentication

## Common Tasks

### Adding a New Podcast
1. Add entry to `podcasts.yaml` with RSS feed and Apple Podcast ID
2. Configure download strategy if needed
3. Run `python main.py 30` to fetch recent episodes

### Debugging Failed Episodes
1. Check `renaissance_weekly.log` for errors
2. Run `python main.py verify` for processing status
3. Use `python main.py check "Podcast Name"` for specific issues
4. Check monitoring data in `monitoring_data/`

### Viewing Transcripts
Transcripts are stored in SQLite database:
```bash
# View all transcripts
sqlite3 renaissance_weekly.db "SELECT podcast, title, LENGTH(transcript) FROM episodes WHERE transcript IS NOT NULL;"

# Export specific transcript
sqlite3 renaissance_weekly.db "SELECT transcript FROM episodes WHERE title LIKE '%keyword%';"
```

### YouTube Authentication & Cookie Management
For YouTube-protected content:
1. Ensure you're logged into YouTube in a browser
2. System auto-detects browser cookies
3. Or use manual download + local file in UI

#### Cookie Expiration Alerts
The UI now displays automatic alerts when YouTube authentication expires:
- **Detection**: Monitors for YouTube auth errors (sign-in required, bot detection, 403 errors)
- **Alert Location**: Download page shows prominent yellow banner with cookie icon
- **Instructions**: Step-by-step guide to refresh cookies
- **Protection**: Use `python protect_cookies_now.py` to prevent cookie overwriting

#### Manual Cookie Export (if needed)
1. Install browser extension:
   - Firefox: "cookies.txt" by Lennon Hill
   - Chrome: "Get cookies.txt LOCALLY"
2. Export from youtube.com while signed in
3. Save as: `~/.config/renaissance-weekly/cookies/youtube_cookies.txt`
4. Run: `python protect_cookies_now.py`

## API Integrations

### Required APIs
- **OpenAI**: GPT-4 for summarization
- **SendGrid**: Email delivery

### Optional APIs (Enhanced Features)
- **AssemblyAI**: 32x faster transcription
- **YouTube API**: Better episode search
- **Podcast Index**: Transcript discovery
- **Spotify**: Additional audio sources (OAuth required)

## Update History

For detailed update history and version information, see [CHANGELOG.md](./CHANGELOG.md).

### Latest Improvements (2025-07-15)
- Fixed unclosed aiohttp client sessions that were causing memory leaks:
  - Added proper cleanup in SubstackEnhancedFetcher context manager
  - Implemented cleanup method in DownloadManager
  - Ensured AudioSourceFinder sessions are properly closed
  - Fixed remaining unclosed session in youtube_transcript.py
- Fixed AssemblyAI configuration display bug:
  - Corrected reference from self.assemblyai_transcriber to self.transcriber.assemblyai_transcriber
  - Now correctly shows "Yes (32x speed)" when AssemblyAI is available
- Enhanced Download UI for better user experience:
  - Reordered episodes to show: Downloaded → In Queue → Failed
  - Changed button label from "Continue to Processing" to "Continue"
  - Disabled Continue button until all episodes are processed
  - Added helpful message explaining when button will be enabled
- **Implemented mode-specific summary and transcript storage**:
  - Added separate database columns: `transcript_test`, `summary_test` for test mode
  - Full mode uses: `transcript`, `summary` columns (production data)
  - Test mode uses: `transcript_test`, `summary_test` columns (15-minute previews)
  - Complete separation prevents stale test summaries from appearing in production
  - All existing summaries/transcripts cleared during migration for clean start
  - `regenerate-summaries` command now respects current mode
  - Matches the existing pattern used for audio files (audio_file_path vs audio_file_path_test)

### Previous Improvements (2025-07-14)
- Fixed critical transcription mode bug
- Added comprehensive testing infrastructure
- Enhanced UI with persistent mode indicators
- Achieved production readiness with 95%+ success rate
- Added cookie expiration alerts with detailed fix instructions
- Implemented cookie protection system to prevent overwriting
- Fixed memory management issues:
  - Resolved OOM kills caused by pydub loading entire audio files
  - Replaced with metadata-only extraction using mutagen
  - Added continuous memory monitoring during downloads
  - Reduced UI polling frequency (1s → 3-5s)
  - Fixed YouTube URL mapping for correct episode matching
- Suppressed verbose HTTP logging from AssemblyAI client
- Enhanced concurrency controls with YouTube-specific limits