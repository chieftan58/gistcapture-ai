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
- `prompts/summarizer_prompt.txt` - AI summarization instructions
- `renaissance_weekly.db` - SQLite database (auto-created)

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
Set `TESTING_MODE=true` to limit audio transcription to 10 minutes for faster testing.

## Important Notes

- The `requirements.txt` file appears to contain Python code instead of dependencies. Use `setup.py` for dependency information.
- No test suite exists currently - be careful when making changes.
- The project directory name (`gistcapture-ai`) differs from the package name (`renaissance-weekly`).