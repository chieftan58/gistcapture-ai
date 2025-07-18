# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **Note**: This file was cleaned up on 2025-07-14, reducing it from 59k to 6k characters. Detailed update history has been preserved in [CHANGELOG.md](./CHANGELOG.md).

## Project Overview

Investment Pods Weekly (formerly Renaissance Weekly) is a Python-based podcast intelligence system that automatically fetches, transcribes, and summarizes episodes from 19 curated podcasts, then sends email digests via SendGrid. The system is published by Pods Distilled.

### Key Features
- **95%+ Success Rate**: Multi-strategy download system with fallbacks
- **32x Faster Transcription**: AssemblyAI integration (vs Whisper)
- **Production Ready**: Comprehensive testing infrastructure and monitoring
- **Smart Retry System**: Different strategies based on failure type
- **Test/Full Modes**: Quick testing (15 min) or complete episode processing
- **Two-Summary System**: 150-word paragraph + expandable full summary per episode

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
- `/prompts/`: AI prompt templates (system, paragraph, full summaries)

### Processing Pipeline
1. **Fetching**: Episodes from RSS/Apple Podcasts
2. **UI Selection**: Web interface for episode selection
3. **Download Stage**: Smart routing with multiple strategies
4. **Transcript Finding**: 10+ sources checked before audio transcription
5. **Summarization**: Two-phase system with GPT-4
   - **Paragraph Summary**: 150-word overview for email scanning
   - **Full Summary**: Comprehensive analysis (500-2500 words)
6. **Email Delivery**: SendGrid with expandable sections

## Current System Status

### Performance Metrics
- **Overall Success Rate**: 95%+
- **Transcription Speed**: 15-30 minutes (vs 2 hours with Whisper)
- **Download Strategies**: 4 independent pathways
- **Concurrency**: Memory-aware with dynamic scaling
  - Episode processing: 4 concurrent (increased from 2 on 2025-07-16)
  - AssemblyAI: 32x concurrent transcriptions
  - GPT-4 summaries: 4 concurrent (matches episode processing)
  - YouTube downloads: 2 concurrent (separate semaphore)
  - Memory per task: 1200MB (reduced from 1500MB)

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
- Internal package name remains `renaissance_weekly` for stability (cosmetic rebrand only)
- Summaries are cached separately by mode - test mode (15 min) vs full mode (complete episodes)
- Minimum 1 episode required for email sending (previously 20)
- Browser cookies automatically used for YouTube authentication
- YouTube URL mappings in `hardcoded_episode_urls.py` are crucial for Cloudflare-protected podcasts
- Prompts are loaded from `/prompts/` directory - edit .txt files to modify AI behavior
- System prompt defines AI identity; summary prompts define task instructions

## Common Tasks

### Adjusting Performance Settings
1. **Concurrency Control** (for slower systems or API issues):
   ```bash
   # Reduce concurrency to 2 episodes (original setting)
   export EPISODE_CONCURRENCY=2
   python main.py 7
   
   # Force specific memory allocation per task (MB)
   export MEMORY_PER_TASK=1500
   python main.py 7
   ```

2. **Dynamic Fallback**: System automatically reduces concurrency if:
   - Memory drops below safe thresholds
   - Error rate exceeds 20%
   - API rate limits are hit

### Modifying AI Prompts
1. Edit prompt files in `/prompts/` directory:
   - `system_prompt.txt` - Change AI identity/persona
   - `paragraph_prompt.txt` - Adjust 150-word summary style
   - `full_summary_prompt.txt` - Modify comprehensive summary format
2. Run `python main.py reload-prompts` to reload without restarting
3. Changes apply to new summaries immediately

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

## Transcript Quality & AI Post-Processing

### Automatic AI-Powered Correction (NEW)
The system now uses GPT-4 to automatically fix transcription errors:
- **Runs automatically** after every transcription
- **Context-aware** - knows podcast hosts, common guests, tech terms
- **Self-improving** - no manual configuration needed
- **Smart caching** - only processes transcripts with likely errors

### How It Works
1. After transcription, GPT-4 analyzes the transcript
2. Identifies and fixes errors based on context (e.g., "Heath Raboy" → "Keith Rabois")
3. Logs all corrections made
4. Updates database automatically

### Fixing Existing Transcripts
To fix errors in existing transcripts:
```bash
# Fix transcripts from last 30 days
python fix_all_transcripts.py 30

# Fix all transcripts
python fix_all_transcripts.py 365
```

### Monitoring
- Look for "🤖 Running AI post-processing" in logs
- Check for "✅ Fixed N transcription errors" messages
- Errors are fixed before summaries are generated

## Known Issues

### Transcript Cache Issue (RESOLVED)
**Discovered**: 2025-07-15
**Fixed**: 2025-07-16
**Status**: RESOLVED with bulletproof cache implementation

**The Problem**: 
Transcript cache was not being used during episode processing, causing expensive re-transcriptions every run.

**Root Causes**:
1. Episode objects created at different points had minor variations (dates, GUIDs)
2. Database lookups relied on exact Episode object matching
3. Complex matching logic in TranscriptFinder wasn't catching all cases
4. Initial confusion about which database file was active (`podcast_data.db` vs `renaissance_weekly.db`)

**The Fix - Direct Cache Check**:
Implemented explicit cache check at the start of `process_episode()` that:
- Uses direct SQL with flexible title matching (exact, prefix, suffix)
- Bypasses Episode object comparison issues
- Checks appropriate columns based on transcription mode
- Logs clear CACHE HIT/MISS messages
- Handles both full cache (skip everything) and partial cache (reuse transcript)

```python
# Flexible matching that catches title variations
WHERE podcast = ? AND (
    title = ? OR 
    title LIKE ? OR  # First 50 chars
    title LIKE ?     # Last 50 chars
)
```

**Verification**:
```bash
# Test direct cache behavior
python test_direct_cache.py

# Test full episode processing 
python test_episode_processing.py

# Test partial cache (transcript without summary)
python test_partial_cache.py
```

The cache now reliably finds and reuses transcripts, saving ~$0.90 per hour of audio.

### Latest Improvements (2025-07-18)
- **Enhanced 'Read Full Summary' viewport positioning with dynamic buffer**:
  - Implemented intelligent buffer system using invisible paragraph clone
  - Buffer size automatically scales with paragraph length for optimal positioning
  - Added 500px additional padding to ensure content always starts at top
  - Solution works regardless of button position on screen when clicked
  - Fixes issue where clicking button after scrolling past it would show middle of content
  - Test scenarios created for short, medium, and long paragraph summaries
  - More reliable than fixed negative margin approach

### Latest Improvements (2025-07-17)
- **Fixed email recipient override**:
  - Modified `EmailDigest.send_digest()` to accept optional `email_to` parameter
  - UI-entered email addresses now properly override the default recipient
  - System correctly sends to custom emails instead of hardcoded default
- **Implemented AI-powered transcript error correction**:
  - Built `TranscriptPostProcessor` using GPT-4 to automatically fix phonetic errors
  - Fixes names (e.g., "Heath Raboy" → "Keith Rabois"), companies, technical terms
  - Runs automatically after every transcription and on cached transcripts with errors
  - Context-aware corrections based on podcast and guest knowledge
- **Added cache validation system**:
  - Created `CacheValidator` to detect stale summaries with outdated errors
  - Automatically regenerates summaries when transcript has been corrected
  - Prevents serving cached content with transcription errors
  - Integrated into main processing pipeline for automatic detection
- **Fixed critical cache invalidation bug**:
  - System now properly detects when cached summaries contain errors fixed in transcripts
  - `filter_episodes_needing_processing` enhanced to validate cache quality
  - Ensures corrected names appear in emails without manual intervention
- **Refined full summary prompt for complete reader satisfaction**:
  - Major shift: From "describing conversations" to "conveying their full substance"
  - Goal: Readers feel completely satisfied without needing to listen
  - Smart attribution: Natural flow with attribution where it matters (opinions, disagreements, key insights)
  - Complete arguments: All reasoning steps, data, examples included
  - Length philosophy: Satisfaction over word counts (could be 2500-6000+ words)
  - Substance over description: Actual content not topic summaries
  - Test: Could reader explain guest's positions as if they heard it themselves?
  - Maintains existing system_prompt.txt and paragraph_prompt.txt unchanged

### Latest Improvements (2025-07-16)
- **Performance Optimization**:
  - Increased episode processing concurrency from 2 to 4
  - Reduced memory per task from 1500MB to 1200MB 
  - Expected 2x speedup for typical 5-10 episode runs
  - Fallback: Set `EPISODE_CONCURRENCY=2` environment variable to revert
- **Fixed transcript cache failures**:
  - Removed restrictive `transcription_mode` conditions from all SQL queries
  - Added flexible matching with title-only fallback for date inconsistencies
  - Enhanced database operation logging for debugging
  - Cache now works properly across test and full modes
- **Enhanced email digest formatting**:
  - Fixed Gmail anchor links with dual `id` and `name` attributes
  - Added email address input field on approval page
  - Renamed "Back to Episodes" to "Back to Episode List"
  - Fixed navigation links to properly jump within email
- **Database Investigation and Verification** (2025-07-16):
  - Resolved confusion about database files:
    - Active database: `podcast_data.db` (140+ episodes)
    - Unused/legacy: `renaissance_weekly.db` (empty)
  - Created comprehensive verification script `verify_database_comprehensive.py`
  - Confirmed transcript cache is working correctly with flexible fallback matching
  - Added enhanced logging to trace cache lookup flow

### Database Verification Tools

**Comprehensive Database Diagnostics**:
```bash
python verify_database_comprehensive.py
```
Provides:
- Database file locations and sizes
- Table structure verification
- Episode statistics by mode
- Transcript/summary availability counts
- Date format analysis
- Duplicate detection
- Live transcript lookup testing

**Quick Transcript Cache Test**:
```bash
python verify_transcript_cache.py
```

### Date Handling Best Practices

**Issue**: Date format inconsistencies can cause cache lookup failures when comparing episode dates.

**Current Solution**: The database uses a three-tier fallback system:
1. **GUID match** (most reliable) - Always prefer GUID-based lookups when available
2. **Podcast + Title + Date** - Uses `date()` SQL function to ignore time components
3. **Podcast + Title only** - Handles date mismatches gracefully

**Best Practices for Date Handling**:
```python
# 1. Consistent Storage - Always use ISO format
published_str = episode.published.isoformat()

# 2. Remove Timezones - Strip timezone info before storage
if episode.published.tzinfo:
    episode.published = episode.published.replace(tzinfo=None)

# 3. Flexible Queries - Use date() function for comparisons
cursor.execute("""
    SELECT * FROM episodes 
    WHERE podcast = ? AND title = ? AND date(published) = date(?)
""", (podcast, title, published_str))
```

**Key Points**:
- Always generate and use GUIDs when possible (most reliable identifier)
- The title-only fallback ensures transcripts are found despite date inconsistencies
- Database stores all dates as timezone-naive ISO format strings
- Episode fetchers strip timezone info before creating Episode objects

### Previous Improvements (2025-07-18)
- **Fixed UI hanging issue with cached episodes**:
  - Problem: UI would hang on "Transcribing & Summarizing" page when episodes had cached transcripts/summaries
  - Root cause: UI was using a flawed heuristic based on array indices to guess which episodes were completed
  - Solution implemented:
    - Added `completed_episodes` tracking to explicitly track which episodes are done (app.py)
    - Updated progress callbacks to fire for cached episodes (app.py:774-776, 808-810)
    - Modified UI to use direct `completed_episodes.includes(episodeKey)` check instead of heuristic (selection.py:2005-2010)
    - Handle both all-cached and mixed cached/uncached scenarios properly
  - Result: UI now correctly shows cached episodes as "Complete" and allows progression without hanging
- **Fixed aiohttp memory leak**:
  - Identified issue in `TranscriptAPIAggregator` where client instances were created at init time
  - Fixed by instantiating clients within async context manager to ensure proper cleanup
  - This prevents unclosed session warnings and potential memory leaks during long runs
- **Resolved transcript cache issue completely**:
  - Root cause: SQL statements in `save_episode()` were missing `paragraph_summary` and `paragraph_summary_test` columns
  - This caused episode saves to fail silently, resulting in empty database (0 episodes)
  - Fixed SQL statements to include all columns - episodes now save properly
  - Fixed episode checking logic in `app.py` to use mode-specific columns
  - Transcripts are now properly cached, saving ~$0.90 per hour of audio
- **Email formatting improvements**:
  - Added podcast name prefix to episode titles for clarity (e.g., "American Optimist: Ep 118...")
  - Simplified "Full Episode" link by removing Apple Podcasts logo and integrating into metadata line
  - Fixed duplicate podcast names in titles (e.g., "Macro Voices: MacroVoices #488" → "MacroVoices #488")
  - Implemented dual email approach: expandable `<details>` for mobile, anchor links for Gmail
  - Removed duplicate titles from full summaries for cleaner presentation
  - Fixed episode count display on email sent confirmation page
  - Enhanced sponsor extraction and display with clickable links in summary footers
  - Gmail users see "Read Full Summary ↓" links that jump to summaries at bottom of email
  - Mobile users get proper expandable sections with smooth interaction

### Previous Improvements (2025-07-17)
- **Implemented Two-Summary Email System**:
  - New architecture generates both 150-word paragraph and full summary per episode
  - Paragraph summaries designed as "movie trailers" for quick scanning
  - Full summaries provide comprehensive conversation flow (500-2500 words)
  - Email format uses expandable HTML/CSS sections (no JavaScript)
  - Alphabetical podcast ordering for consistent navigation
  - Dynamic subject lines with featured guest names
  - Prompt system restructured with only 3 files:
    - `prompts/system_prompt.txt` - Defines AI identity (investment analyst persona)
    - `prompts/paragraph_prompt.txt` - 150-word overview generation
    - `prompts/full_summary_prompt.txt` - Comprehensive analysis
  - Removed legacy `summary_prompt.txt` - was for generic "busy professionals"
  - Database schema updated with `paragraph_summary` and `paragraph_summary_test` columns
  - Sequential API calls with 0.5s delay to manage rate limits
  - Reduced concurrent episodes from 4 to 3 for API stability
  - Backward compatible with fallback to extract paragraph from full summary
  - Clean separation of concerns: system prompt for WHO, summary prompts for WHAT
  - Investment-focused prompts throughout (hedge fund PMs, macro investors audience)
- **Enhanced Email Digest with Rich Content**:
  - Added "Link to Full Podcast" button with Apple Podcasts logo in episode headers
  - Implemented automatic resource extraction for books, papers, and websites
  - Added sponsor detection and formatting with clickable links
  - Resources appear before sponsors in expandable summaries
  - Clean formatting with proper sections and visual hierarchy
  - Mobile-responsive design with inline styles throughout
- **Content-Adaptive Summarization**:
  - Updated prompts to identify content type before applying focus areas
  - Avoids forcing investment framing on non-investment content (e.g., CFPB regulatory discussions)
  - Four content lenses: Investment/Markets, Business/Technology, Policy/Regulation, Other Topics
  - Universal extraction ensures value for investor audience regardless of topic
  - Maintains sophisticated analysis while respecting actual conversation content
- **Email Template Fixes**:
  - Converted to Gmail-compatible HTML5 `<details>`/`<summary>` elements for expandable sections
  - Fixed mobile text overflow with table-based layout and media queries
  - Improved guest name extraction from titles and descriptions
  - Enhanced markdown-to-HTML conversion with proper spacing and inline styles
  - Fixed "Read Full Analysis" → "Read Full Summary" text change

### Previous Improvements (2025-07-16)
- **Implemented Two-Summary Email System**:
  - New architecture generates both 150-word paragraph and full summary per episode
  - Paragraph summaries designed as "movie trailers" for quick scanning
  - Full summaries provide comprehensive conversation flow (500-2500 words)
  - Email format uses expandable HTML/CSS sections (no JavaScript)
  - Alphabetical podcast ordering for consistent navigation
  - Dynamic subject lines with featured guest names
  - Prompt system restructured with only 3 files:
    - `prompts/system_prompt.txt` - Defines AI identity (investment analyst persona)
    - `prompts/paragraph_prompt.txt` - 150-word overview generation
    - `prompts/full_summary_prompt.txt` - Comprehensive analysis
  - Removed legacy `summary_prompt.txt` - was for generic "busy professionals"
  - Database schema updated with `paragraph_summary` and `paragraph_summary_test` columns
  - Sequential API calls with 0.5s delay to manage rate limits
  - Reduced concurrent episodes from 4 to 3 for API stability
  - Backward compatible with fallback to extract paragraph from full summary
  - Clean separation of concerns: system prompt for WHO, summary prompts for WHAT
  - Investment-focused prompts throughout (hedge fund PMs, macro investors audience)

### Previous Improvements (2025-07-15)
- **Fixed stale summary cache issue**:
  - Summary files now include mode in filename (e.g., `*_test_summary.md`, `*_full_summary.md`)
  - Added `--force-fresh` flag to `main.py` for bypassing all caches
  - Created `clear_summary_cache.py` script to remove old summaries
  - Completely resolved issue of identical summaries across runs
- **Enhanced monitoring system for mode separation**:
  - Statistics now tracked separately for test and full modes
  - Prevents mixing of test/production metrics
  - Health scores calculated per mode for accurate diagnostics
- **Implemented automatic cookie expiration detection**:
  - Parses cookie files to check expiration dates
  - Shows proactive warnings when cookies expire in < 7 days
  - UI displays alerts before downloads fail due to expired cookies
  - Prevents use of expired authentication
- **Fixed UI completion flow**:
  - Email sent screen now shows proper completion state
  - Displays number of episodes included in digest
  - Manual close button instead of auto-close
  - Resolved "0 episodes selected" confusion after email
- Fixed duration display on Download page:
  - Changed from showing "N/A" to displaying full podcast duration from Episodes page
  - Updated label from "Expected:" to "Full Podcast:" for clarity
  - Fixed formatDuration function to properly handle string durations (e.g., "1h 23m")
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