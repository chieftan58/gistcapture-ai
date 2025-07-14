# Memory Fix Summary

## Issue Identified
The `extract_audio_info()` method in `download_manager.py` was using `pydub.AudioSegment.from_file()` to extract audio duration. This loads the entire audio file into memory, which can cause Out of Memory (OOM) errors when processing multiple large audio files concurrently.

## Root Cause
- `AudioSegment.from_file()` loads the entire audio file into memory
- With multiple 287MB+ audio files being processed concurrently, this quickly exhausts available memory
- The issue compounds when multiple episodes are marked as "Using existing audio file" simultaneously

## Fix Applied
Replaced the memory-intensive pydub approach with two more efficient alternatives:

1. **Primary Method: Mutagen**
   - Uses the `mutagen` library (already in requirements.txt)
   - Reads only metadata headers, not the entire file
   - Memory usage: ~2-3 MB regardless of file size

2. **Fallback Method: ffprobe**
   - Uses ffprobe to extract metadata if mutagen fails
   - Also reads only metadata, not the entire file
   - Requires ffmpeg to be installed (already a dependency)

## Code Changes
In `renaissance_weekly/download_manager.py`, the `extract_audio_info()` method now:
```python
# OLD: Loads entire file into memory
audio = AudioSegment.from_file(str(self.audio_path))
self.downloaded_duration = len(audio) / (1000 * 60)

# NEW: Reads only metadata
from mutagen import File
audio_file = File(str(self.audio_path))
if audio_file and audio_file.info:
    self.downloaded_duration = audio_file.info.length / 60
```

## Benefits
1. **Memory Efficiency**: Uses ~2MB instead of full file size (287MB+)
2. **Speed**: Metadata extraction is much faster than loading entire file
3. **Scalability**: Can process many files concurrently without OOM
4. **Reliability**: Two methods (mutagen + ffprobe) ensure robustness

## Testing
Created `test_memory_fix.py` to verify the fix:
- Memory increase: 2.12 MB (efficient!)
- Successfully extracts file size and format
- No OOM errors even with large files

## Related Optimizations
The codebase already has other memory-efficient practices:
- Audio trimming uses ffmpeg (stream processing) with pydub fallback
- File size checks before using pydub (200MB threshold)
- Proper garbage collection after pydub operations
- Memory-aware concurrency limiting

## Recommendation
This fix should significantly reduce memory usage during the "Using existing audio file" phase, preventing OOM errors when processing multiple cached episodes.