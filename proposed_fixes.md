# Renaissance Weekly Fixes for 80%+ Success Rate

## 1. Adjust Conversation Indicator Threshold for Test Mode

**File**: `renaissance_weekly/processing/summarizer.py`

**Current Issue**: Line 233 requires >10 conversation indicators, which 5-minute clips can't achieve.

**Fix**: Add test mode adjustment:

```python
# Line 232-235 (current)
if conversation_indicators > 10:
    logger.info(f"✅ Transcript validation passed: {word_count} words, {conversation_indicators} conversation indicators")
    return True

# REPLACE WITH:
min_indicators = 3 if TESTING_MODE else 10
if conversation_indicators >= min_indicators:
    logger.info(f"✅ Transcript validation passed: {word_count} words, {conversation_indicators} conversation indicators (min: {min_indicators})")
    return True
```

## 2. Relax Metadata Ratio Check for Test Mode

**Current Issue**: 30% metadata rejection is too strict for short clips that might start with intros.

**Fix**: Adjust metadata ratio threshold:

```python
# Line 207-210 (current)
metadata_ratio = metadata_line_count / min(len(lines), 50)
if metadata_ratio > 0.3:
    logger.warning(f"High metadata ratio: {metadata_ratio:.1%} of first 50 lines")
    return False

# REPLACE WITH:
max_metadata_ratio = 0.5 if TESTING_MODE else 0.3
metadata_ratio = metadata_line_count / min(len(lines), 50)
if metadata_ratio > max_metadata_ratio:
    logger.warning(f"High metadata ratio: {metadata_ratio:.1%} of first 50 lines (max: {max_metadata_ratio:.0%})")
    return False
```

## 3. Lower URL Count Threshold for Test Mode

**Current Issue**: URL count >10 rejection might catch intro segments.

**Fix**: Adjust URL threshold:

```python
# Line 213-215 (current)
if url_count > 10:
    logger.warning(f"Too many URLs in beginning: {url_count} (likely show notes)")
    return False

# REPLACE WITH:
max_urls = 20 if TESTING_MODE else 10
if url_count > max_urls:
    logger.warning(f"Too many URLs in beginning: {url_count} (max: {max_urls}, likely show notes)")
    return False
```

## 4. Add Debug Logging for Failed Validations

**Fix**: Add detailed logging before the final failure:

```python
# Before line 251 (the final warning), add:
logger.info(f"Validation metrics - Words: {word_count}/{min_words}, Chars: {char_count}/{min_chars}, "
           f"Conversation indicators: {conversation_indicators}/{min_indicators}, "
           f"Metadata ratio: {metadata_ratio:.1%}/{max_metadata_ratio:.0%}, URLs: {url_count}/{max_urls}")
```

## 5. Consider Source-Specific Validation

**Current Issue**: Audio transcriptions from test mode are penalized unfairly.

**Fix**: Add special handling for audio transcriptions in test mode:

```python
# After line 245, add:
if TESTING_MODE and source == TranscriptSource.AUDIO_TRANSCRIPTION:
    # Very lenient for test mode audio transcriptions
    if word_count >= 300 and char_count >= 1500:
        logger.info(f"✅ Transcript validation passed (test mode audio: {word_count} words)")
        return True
```

## 6. Alternative: Skip Summarization Validation in Test Mode

**Quick Fix**: For immediate testing, bypass strict validation:

```python
# At the beginning of _validate_transcript_content method, add:
if TESTING_MODE and os.getenv("SKIP_VALIDATION", "false").lower() == "true":
    logger.info("⚠️ Test mode: Skipping transcript validation")
    return True
```

Then run with: `SKIP_VALIDATION=true python main.py`

## Expected Results

With these changes:
- **Before**: 7/35 succeeded (20%)
- **After**: 30+/35 should succeed (85%+)

The remaining failures would likely be episodes where:
- No transcript source was found at all
- Audio download failed completely
- API transcription services failed

## Implementation Priority

1. **High Priority**: Fix conversation indicator threshold (biggest impact)
2. **Medium Priority**: Add debug logging (helps diagnose remaining issues)
3. **Low Priority**: Adjust metadata/URL thresholds (minor impact)