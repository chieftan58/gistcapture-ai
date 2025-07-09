# Performance Optimization Summary

## Speed Improvements

### Before (Conservative Fix)
- **Concurrency**: 2 episodes at a time
- **Memory per task**: 1200MB (accounting for full 287MB files)
- **Expected time**: 2.5-5 hours for 29 episodes

### After (Optimized Fix)
- **Concurrency**: 6 episodes at a time (3x improvement)
- **Memory per task**: 600MB (only need space for 15-min clips)
- **Expected time**: 45-90 minutes for 29 episodes

## Key Optimizations

1. **ffmpeg Priority**
   - Streams audio without loading entire file into memory
   - Trims directly to 15 minutes during processing
   - Only ~20MB in memory vs 287MB

2. **Increased Concurrency**
   - Test mode: 2 → 6 concurrent episodes
   - Full mode: 2 → 3 concurrent episodes
   - 3x faster processing in test mode

3. **Smarter Memory Allocation**
   - Reduced from 1200MB to 600MB per task in test mode
   - More episodes can process simultaneously
   - 75% of memory available for tasks (was 60%)

4. **Safety Measures**
   - ffmpeg availability check on startup
   - Warning if ffmpeg not installed
   - Fallback to pydub only for files <100MB
   - Garbage collection after large operations

## Performance Expectations

With ffmpeg installed:
- **6 concurrent episodes** in test mode
- **~8-15 minutes per episode** (download + trim + transcribe + summarize)
- **Total time: ~45-90 minutes** for 29 episodes

Without ffmpeg (not recommended):
- Falls back to 2 concurrent to prevent OOM
- Large files may fail trimming
- Consider installing: `sudo apt-get install ffmpeg`

## Monitoring
Watch the logs for:
- "✅ ffmpeg available for memory-efficient audio trimming"
- "Episode concurrency limit: 6 (memory-aware)"
- "Audio trimmed successfully with ffmpeg"

This gives you 3x better performance while still preventing OOM!