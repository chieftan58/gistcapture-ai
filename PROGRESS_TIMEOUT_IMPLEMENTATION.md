# Progress-Based Download Timeout Implementation

## Overview
Implemented a progress-based timeout system to handle long podcast episodes (like Tim Ferriss's 2.5+ hour episodes) without premature timeouts.

## Key Changes

### 1. New Progress-Based Download Method
- Added `_download_with_progress()` method in `audio_downloader.py`
- Tracks download progress in real-time
- Continues as long as data is flowing (minimum 1KB/s)
- Only times out when truly stalled (no bytes for 60 seconds)

### 2. Timeout Configuration
- **Stall Timeout**: 60 seconds without progress → fail
- **Maximum Timeout**: 30 minutes absolute limit (safety net)
- **Minimum Speed**: 1KB/s to count as "making progress"
- **Progress Updates**: Every 10MB or 10% with speed and ETA

### 3. Updated All Download Methods
- All platform-specific methods now use progress-based downloads
- Removed fixed read timeouts from HTTP requests (`timeout=(30, None)`)
- Updated overall episode timeout from 10 to 30 minutes

### 4. Files Modified
- `renaissance_weekly/transcripts/audio_downloader.py` - Core implementation
- `renaissance_weekly/download_manager.py` - Increased timeout to 30 minutes
- `renaissance_weekly/app.py` - Increased episode timeout to 30 minutes

## How It Works

1. **Connection Phase**: 30-second timeout to establish connection
2. **Download Phase**: No fixed timeout, progress-based instead
3. **Progress Tracking**: 
   - Monitors bytes downloaded per second
   - Resets timeout when data flows above 1KB/s
   - Shows speed and ETA in logs
4. **Failure Conditions**:
   - No data for 60 seconds
   - Total time exceeds 30 minutes
   - Download speed below 1KB/s for extended period

## Benefits

- **Long Episodes**: 3-4 hour episodes can download without timeout
- **Slow Connections**: Adapts to network speed automatically  
- **Fast Failure**: Still fails quickly on truly stuck downloads
- **Better Visibility**: Shows download speed and ETA
- **Universal**: Works for all download strategies

## Testing

Use the provided test script:
```bash
python test_progress_download.py <long_episode_url>
```

## Example Log Output
```
🎵 Downloading audio from: https://example.com/episode.mp3...
📊 Using progress-based timeout: 60s stall timeout, 30min max timeout
📊 Progress: 10.2% (25.5MB/250.0MB) Speed: 2.34MB/s ETA: 0:01:36
📊 Progress: 20.4% (51.0MB/250.0MB) Speed: 2.41MB/s ETA: 0:01:22
✅ Download complete: 250.0MB in 104s (avg 2.40MB/s)
```