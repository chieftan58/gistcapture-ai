# Test Mode Audio Trimming Fix

## Problem
The system was downloading full-length episodes even in test mode, resulting in 100-300MB files with `_test.mp3` suffix that should have been 5-15MB for 15-minute clips.

## Root Cause
Audio trimming was only happening during transcription, not during download:
1. Download manager downloaded full episodes and saved them with `_test.mp3` suffix
2. Transcriber trimmed audio during transcription, but only created temporary files
3. Original full-length audio files remained saved to disk

## Solution
Modified the download manager to trim audio files immediately after download in test mode:

### 1. Enhanced `download_manager.py`
- Added `MAX_TRANSCRIPTION_MINUTES` import
- Added `_trim_downloaded_audio()` method that uses ffmpeg (preferred) or pydub (fallback)
- Modified download flow to trim audio immediately after successful download in test mode
- Applied trimming to both smart router downloads and manual URL downloads

### 2. Updated transcription components
- Modified `transcriber.py` to check audio duration before trimming
- Updated `assemblyai_transcriber.py` to avoid re-trimming already trimmed files
- Both components now skip trimming if audio is already short enough

### 3. Key Features
- **FFmpeg preferred**: Uses ffmpeg for efficient trimming without re-encoding
- **Pydub fallback**: Uses pydub if ffmpeg not available
- **Size checks**: Prevents OOM by checking file size before processing
- **Cross-device handling**: Uses shutil.move() to handle temp file moves
- **Duplicate prevention**: Checks audio duration before trimming

## Files Modified
1. `/renaissance_weekly/download_manager.py` - Main trimming logic
2. `/renaissance_weekly/transcripts/transcriber.py` - Avoid duplicate trimming
3. `/renaissance_weekly/transcripts/assemblyai_transcriber.py` - Avoid duplicate trimming

## Results
- **Before**: Test mode files were 100-300MB (full episodes)
- **After**: Test mode files are 5-20MB (15-minute clips)
- **Duration**: Exactly 15 minutes (900 seconds) as configured
- **Quality**: No re-encoding when using ffmpeg, preserves audio quality

## Testing
Tested with existing audio files:
- 70.1MB file trimmed to 20.6MB
- 3060.5 seconds reduced to 900.0 seconds
- Confirmed exact 15-minute duration

## Configuration
Test mode behavior controlled by:
- `TESTING_MODE=true` in .env
- `MAX_TRANSCRIPTION_MINUTES=15` in .env
- Files automatically get `_test.mp3` suffix and are trimmed to specified duration

## Backwards Compatibility
- Existing full-length `_test.mp3` files remain unchanged
- New downloads in test mode are automatically trimmed
- Full mode (`TESTING_MODE=false`) remains unchanged