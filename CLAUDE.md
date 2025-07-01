# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Renaissance Weekly is a Python-based podcast intelligence system that automatically fetches, transcribes, and summarizes episodes from 19 curated podcasts, then sends email digests via SendGrid.

## Key Commands

### Running the Application
```bash
# Process last N days of episodes (default: 7)
python main.py [days]

# Run verification report
python main.py verify [days]

# Check single podcast
python main.py check "Podcast Name" [days]

# Reload prompts for A/B testing
python main.py reload-prompts

# Force regenerate summaries with current prompt
python main.py regenerate-summaries [days]

# Run system diagnostics
python main.py test
```

### Testing Commands
```bash
# Test only episode fetching
python main.py --test-fetch [days]

# Test summarization with a transcript file
python main.py --test-summarize <transcript_file>

# Test email generation with cached data
python main.py --test-email

# Run full pipeline without API calls
python main.py --dry-run [days]

# Save current cache as test dataset
python main.py --save-dataset <name>

# Load test dataset into cache
python main.py --load-dataset <name>
```

### Development Setup
```bash
# Install dependencies
pip install -e .

# Create .env file with required API keys:
# OPENAI_API_KEY=your_key
# SENDGRID_API_KEY=your_key
# OPENAI_MODEL=gpt-4o (optional)
# OPENAI_TEMPERATURE=0.3 (optional)
# OPENAI_MAX_TOKENS=4000 (optional)
```

## Architecture

### Core Flow
1. **Fetching**: Retrieves episodes from RSS feeds and Apple Podcasts API
2. **Transcript Finding**: Multi-source approach (RSS, web scraping, APIs, audio transcription)
3. **Summarization**: Uses OpenAI GPT-4 to create executive summaries
4. **Email Delivery**: Sends HTML digests via SendGrid

### Key Directories
- `/renaissance_weekly/` - Main application package
  - `app.py` - Core application with resource-aware concurrency
  - `config.py` - Configuration management
  - `database.py` - SQLite database operations
  - `/email/` - Email generation and sending
  - `/fetchers/` - Episode fetching logic
  - `/transcripts/` - Transcript finding and generation
  - `/processing/` - AI-powered summarization
  - `/ui/` - Web-based episode selection

### Important Files
- `podcasts.yaml` - List of 19 monitored podcasts
- `prompts/summary_prompt.txt` - AI summarization instructions (dynamic headers)
- `prompts/system_prompt.txt` - System prompt for AI context
- `renaissance_weekly.db` - SQLite database (auto-created)
- `requirements.txt` - Python package dependencies (fixed)

## Key Technical Details

### Rate Limiting
The system includes built-in OpenAI API rate limiting with exponential backoff and circuit breaker pattern for 100% reliability.

### Concurrency
Resource-aware concurrency adapts to available CPU/memory for optimal performance.

### Error Handling
Comprehensive exception aggregation and reporting ensures visibility into failures.

### Database Schema
Episodes are tracked with status (pending, transcribed, summarized, emailed) and transcript sources.

## Common Tasks

### Adding a New Podcast
1. Add entry to `podcasts.yaml` with RSS feed and Apple Podcast ID
2. Run `python main.py 30` to fetch recent episodes

### Debugging Failed Episodes
1. Check `renaissance_weekly.log` for errors
2. Run `python main.py verify` to see processing status
3. Use `python main.py check "Podcast Name"` for specific podcast issues

### Testing Summarization
Set `TESTING_MODE=true` to limit audio transcription to 5 minutes for faster testing.

## Important Notes

- The project directory name (`gistcapture-ai`) differs from the package name (`renaissance-weekly`).
- No test suite exists currently - be careful when making changes.
- Summary caching: Summaries are cached to disk. If you update `prompts/summary_prompt.txt`, use `python main.py regenerate-summaries` to force regeneration.
- Audio downloads may fail with 403 errors on some platforms. The system has multiple fallback strategies including platform-specific headers and yt-dlp.
- Test datasets can be saved/loaded to speed up development cycles without re-downloading content.

## Enhanced Reliability Features

### Multi-Layer Transcript Finding
The system now searches for transcripts in this order:
1. Database cache
2. RSS feed transcript URLs
3. Podcast Index API
4. Podcast-specific scrapers (Tim Ferriss blog, Substack)
5. YouTube transcripts
6. Web page scraping
7. Audio transcription (last resort)

### Robust Audio Download
- Platform-specific strategies for major podcast hosts
- yt-dlp integration with browser cookie extraction (Chrome, Firefox, Safari, Edge)
- Multiple retry strategies with exponential backoff
- Comprehensive file validation

### System Monitoring
- Run `python main.py health` to see system health report
- Tracks success/failure rates by component and podcast
- Identifies problematic podcasts
- Persistent monitoring data between runs

### API Integrations
- **YouTube API**: Set `YOUTUBE_API_KEY` in .env for better YouTube search
- **Podcast Index API**: Set `PODCASTINDEX_API_KEY` and `PODCASTINDEX_API_SECRET` for transcript discovery
- Get free API keys at:
  - YouTube: https://console.cloud.google.com/
  - Podcast Index: https://api.podcastindex.org/