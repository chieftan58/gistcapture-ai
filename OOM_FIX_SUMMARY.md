# OOM (Out of Memory) Fix Summary

## Problem
The process was getting killed after processing 16/29 episodes due to Out of Memory errors when handling large audio files (287.3MB) in test mode.

## Root Causes
1. **Full audio files downloaded in test mode**: The 287MB files were downloaded completely before trimming
2. **pydub loads entire file into memory**: When trimming audio, pydub's `AudioSegment.from_file()` loads the entire file into memory
3. **High concurrency**: Multiple 287MB files being processed simultaneously (4 concurrent tasks)
4. **Insufficient memory buffer**: Only keeping 20% memory free was not enough

## Fixes Applied

### 1. Reduced Concurrency (app.py)
- **Test mode**: Reduced from 4 to 2 concurrent tasks
- **Memory per task**: Increased from 800MB to 1200MB 
- **Safety buffer**: Increased from 20% to 40% free memory
- **Minimum concurrency**: Changed from 2 to 1 to ensure progress even with low memory

### 2. Prioritized ffmpeg over pydub (transcriber.py)
- ffmpeg can stream audio files without loading them entirely into memory
- Added better logging when ffmpeg fails
- Added explicit check for ffmpeg availability with fallback warning

### 3. Added Safety Check for pydub (transcriber.py & assemblyai_transcriber.py)
- Check file size before using pydub (100MB threshold)
- For files > 100MB, skip pydub to avoid OOM
- Added ffmpeg trimming to AssemblyAI transcriber for large files
- Return original file rather than risk OOM if trimming fails

### 4. Added Aggressive Garbage Collection
- Added `import gc` to both transcriber files
- Force garbage collection after:
  - Processing each episode (already in app.py)
  - Transcribing audio files
  - pydub operations (after deleting audio objects)
- Explicitly delete large objects (`del audio, del trimmed`)

### 5. Enhanced Logging
- Better visibility into memory calculations
- Show when using ffmpeg vs pydub for trimming
- Log file sizes when making decisions

## Expected Results
- Process should complete without getting killed
- Memory usage should stay within safe limits
- ffmpeg will handle large files efficiently without loading them into memory
- If ffmpeg is not available, pydub will skip files > 100MB to prevent OOM

## Monitoring
Watch for these log messages:
- "Available memory: XXMB"
- "Memory calculations: 1200MB per task"
- "Episode concurrency limit: 2 (memory-aware)"
- "Audio trimmed successfully with ffmpeg" (good)
- "File too large for pydub" (safety check working)

## Next Steps if Still Having Issues
1. Further reduce concurrency to 1 in test mode
2. Increase memory per task to 1500MB
3. Consider streaming audio processing to avoid downloading full files
4. Implement audio chunking to process files in smaller pieces