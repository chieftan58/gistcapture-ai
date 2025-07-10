"""AssemblyAI transcription service for high-performance audio transcription"""

import os
import asyncio
import aiohttp
from pathlib import Path
from typing import Optional, Tuple
import time
import tempfile
from pydub import AudioSegment
import assemblyai as aai

from ..models import Episode
from ..config import TESTING_MODE, MAX_TRANSCRIPTION_MINUTES
from ..utils.logging import get_logger

logger = get_logger(__name__)


class AssemblyAITranscriber:
    """High-performance transcription using AssemblyAI with 32x concurrency"""
    
    def __init__(self):
        self.api_key = os.getenv('ASSEMBLYAI_API_KEY')
        if not self.api_key:
            raise ValueError("ASSEMBLYAI_API_KEY not found in environment")
            
        # Configure AssemblyAI
        aai.settings.api_key = self.api_key
        
        # Track failures for simple reliability
        self.failure_count = 0
        self.max_failures = 5
        self.last_failure_time = None
        
        # Semaphore for controlling concurrency (AssemblyAI supports high concurrency)
        # Dynamic based on mode - will be updated by app.py if needed
        self.semaphore = asyncio.Semaphore(10)  # Default: balanced for test mode
        
        # Track active jobs for monitoring
        self.active_jobs = {}
        
    async def transcribe_episode(self, episode: Episode, audio_path: Path, mode: str = 'test') -> Optional[str]:
        """
        Transcribe audio file using AssemblyAI
        
        Args:
            episode: Episode object
            audio_path: Path to audio file
            mode: 'test' or 'full' mode
            
        Returns:
            Transcript text or None if failed
        """
        if not audio_path.exists():
            logger.error(f"Audio file not found: {audio_path}")
            return None
            
        try:
            async with self.semaphore:
                # Check if we've had too many failures
                if self.failure_count >= self.max_failures:
                    if self.last_failure_time and (time.time() - self.last_failure_time) < 300:  # 5 minutes
                        logger.warning("AssemblyAI has too many failures, skipping transcription")
                        return None
                    else:
                        # Reset after 5 minutes
                        self.failure_count = 0
                    
                logger.info(f"Starting AssemblyAI transcription for {episode.title}")
                start_time = time.time()
                    
                # Configure transcription options
                config = aai.TranscriptionConfig(
                    speaker_labels=True,  # Enable speaker diarization
                    auto_chapters=True,   # Enable chapter detection
                    entity_detection=True, # Detect entities
                    sentiment_analysis=True, # Analyze sentiment
                    language_detection=True, # Auto-detect language
                    punctuate=True,
                    format_text=True,
                )
                
                # In test mode, trim the audio file before uploading
                audio_to_transcribe = audio_path
                if mode == 'test' and TESTING_MODE:
                    max_minutes = MAX_TRANSCRIPTION_MINUTES or 15
                    logger.info(f"Test mode: Trimming audio to {max_minutes} minutes")
                    
                    # Trim the audio file
                    trimmed_path = await self._trim_audio(audio_path, max_minutes)
                    if trimmed_path:
                        audio_to_transcribe = trimmed_path
                    else:
                        logger.warning("Failed to trim audio, using full file")
                
                # Create transcription job - pass the file path directly
                transcriber = aai.Transcriber()
                transcript = await asyncio.to_thread(transcriber.transcribe, str(audio_to_transcribe), config)
                
                # Check for errors
                if transcript.status == aai.TranscriptStatus.error:
                    logger.error(f"AssemblyAI transcription failed: {transcript.error}")
                    self.failure_count += 1
                    self.last_failure_time = time.time()
                    return None
                    
                # Wait for completion with timeout and exponential backoff
                max_wait = 480  # 8 minutes max (less than episode timeout of 10 minutes)
                poll_interval = 2  # Start with 2 seconds
                max_poll_interval = 30  # Cap at 30 seconds
                waited = 0
                
                logger.info(f"Polling AssemblyAI transcription status for {episode.title} (ID: {transcript.id[:8]}...)")
                
                while transcript.status not in [aai.TranscriptStatus.completed, aai.TranscriptStatus.error]:
                    if waited >= max_wait:
                        logger.error(f"AssemblyAI transcription timeout after {max_wait} seconds for {episode.title}")
                        self.failure_count += 1
                        self.last_failure_time = time.time()
                        # Important: Record the failure in monitoring
                        from ..monitoring import monitor
                        monitor.record_failure('audio_transcription', episode.podcast, episode.title,
                                             'Timeout', f'AssemblyAI timeout after {max_wait}s')
                        return None
                        
                    await asyncio.sleep(poll_interval)
                    waited += poll_interval
                    
                    # Refresh transcript status
                    transcript = await asyncio.to_thread(aai.Transcript.get_by_id, transcript.id)
                    
                    # Log status less frequently as interval increases
                    if poll_interval <= 5 or waited % 30 == 0:
                        logger.debug(f"AssemblyAI status: {transcript.status} (waited {waited}s, next poll in {poll_interval}s)")
                    
                    # Exponential backoff: increase interval by 50% each time, capped at max
                    poll_interval = min(int(poll_interval * 1.5), max_poll_interval)
                    
                if transcript.status == aai.TranscriptStatus.error:
                    logger.error(f"AssemblyAI transcription error: {transcript.error}")
                    self.failure_count += 1
                    self.last_failure_time = time.time()
                    return None
                    
                # Success!
                elapsed = time.time() - start_time
                logger.info(f"AssemblyAI transcription completed in {elapsed:.1f}s for {episode.title}")
                
                # Record success
                # Reset failure count on success
                self.failure_count = 0
                
                # Clean up trimmed audio file if we created one
                if audio_to_transcribe != audio_path and audio_to_transcribe.exists():
                    try:
                        audio_to_transcribe.unlink()
                        logger.debug(f"Cleaned up trimmed audio file: {audio_to_transcribe}")
                    except Exception as e:
                        logger.warning(f"Failed to clean up trimmed audio: {e}")
                
                # Return formatted transcript with speaker labels
                return self._format_transcript(transcript)
                
        except Exception as e:
            logger.error(f"AssemblyAI transcription error: {str(e)}", exc_info=True)
            self.failure_count += 1
            self.last_failure_time = time.time()
            return None
    
    async def _trim_audio(self, audio_path: Path, max_minutes: int) -> Optional[Path]:
        """Trim audio file to specified duration"""
        try:
            # Check file size first to avoid OOM
            file_size_mb = audio_path.stat().st_size / (1024 * 1024)
            if file_size_mb > 100:  # 100MB threshold
                logger.warning(f"File too large for pydub ({file_size_mb:.1f}MB), attempting ffmpeg trim")
                # Try ffmpeg first for large files
                import shutil
                if shutil.which('ffmpeg'):
                    temp_dir = Path(tempfile.gettempdir())
                    trimmed_path = temp_dir / f"trimmed_{audio_path.name}"
                    max_seconds = max_minutes * 60
                    
                    cmd = [
                        'ffmpeg', '-i', str(audio_path),
                        '-t', str(max_seconds),
                        '-c', 'copy',  # Copy codec to avoid re-encoding
                        '-y',  # Overwrite output
                        str(trimmed_path)
                    ]
                    
                    process = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    
                    stdout, stderr = await process.communicate()
                    
                    if process.returncode == 0 and trimmed_path.exists():
                        logger.info(f"Audio trimmed successfully with ffmpeg")
                        return trimmed_path
                    else:
                        logger.error(f"ffmpeg trim failed: {stderr.decode()}")
                        return None
                else:
                    logger.error(f"File too large and ffmpeg not available")
                    return None
            
            # Load audio file
            audio = AudioSegment.from_file(str(audio_path))
            
            # Calculate trimming duration in milliseconds
            max_duration_ms = max_minutes * 60 * 1000
            
            # If audio is already shorter, return original
            if len(audio) <= max_duration_ms:
                del audio
                return audio_path
            
            # Trim the audio
            trimmed_audio = audio[:max_duration_ms]
            
            # Create temporary file for trimmed audio
            temp_dir = Path(tempfile.gettempdir())
            trimmed_path = temp_dir / f"trimmed_{audio_path.name}"
            
            # Export trimmed audio
            trimmed_audio.export(str(trimmed_path), format="mp3")
            
            logger.info(f"Trimmed audio from {len(audio)/1000:.1f}s to {len(trimmed_audio)/1000:.1f}s")
            
            # Clean up
            del audio
            del trimmed_audio
            import gc
            gc.collect()
            
            return trimmed_path
            
        except Exception as e:
            logger.error(f"Failed to trim audio: {str(e)}")
            return None
            
    def _format_transcript(self, transcript) -> str:
        """Format transcript with speaker labels and timestamps"""
        if not transcript.words:
            return transcript.text or ""
            
        # If speaker labels are available, format with speakers
        if transcript.utterances:
            formatted_lines = []
            for utterance in transcript.utterances:
                speaker = f"Speaker {utterance.speaker}"
                text = utterance.text.strip()
                formatted_lines.append(f"{speaker}: {text}")
                
            return "\n\n".join(formatted_lines)
            
        # Otherwise return plain text
        return transcript.text or ""
        
    async def get_transcript_status(self, transcript_id: str) -> Optional[dict]:
        """Check status of a transcript job"""
        try:
            transcript = await asyncio.to_thread(aai.Transcript.get_by_id, transcript_id)
            return {
                'id': transcript.id,
                'status': transcript.status,
                'error': transcript.error,
            }
        except Exception as e:
            logger.error(f"Failed to get transcript status: {str(e)}")
            return None