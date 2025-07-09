"""AssemblyAI transcription service for high-performance audio transcription"""

import os
import asyncio
import aiohttp
from pathlib import Path
from typing import Optional, Tuple
import time
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
        self.semaphore = asyncio.Semaphore(32)  # 32 concurrent transcriptions
        
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
                
                # Upload audio file
                upload_url = await self._upload_audio(audio_path)
                if not upload_url:
                    self.failure_count += 1
                    self.last_failure_time = time.time()
                    return None
                    
                # Configure transcription options
                config = aai.TranscriptionConfig(
                    audio_url=upload_url,
                    speaker_labels=True,  # Enable speaker diarization
                    auto_chapters=True,   # Enable chapter detection
                    entity_detection=True, # Detect entities
                    sentiment_analysis=True, # Analyze sentiment
                    language_detection=True, # Auto-detect language
                    punctuate=True,
                    format_text=True,
                )
                
                # In test mode, limit transcription time
                if mode == 'test' and TESTING_MODE:
                    max_minutes = MAX_TRANSCRIPTION_MINUTES or 15
                    config.audio_end_at = max_minutes * 60 * 1000  # Convert to milliseconds
                    logger.info(f"Test mode: Limiting transcription to first {max_minutes} minutes")
                
                # Create transcription job
                transcriber = aai.Transcriber()
                transcript = await asyncio.to_thread(transcriber.transcribe, config)
                
                # Check for errors
                if transcript.status == aai.TranscriptStatus.error:
                    logger.error(f"AssemblyAI transcription failed: {transcript.error}")
                    self.failure_count += 1
                    self.last_failure_time = time.time()
                    return None
                    
                # Wait for completion with timeout
                max_wait = 600  # 10 minutes max
                poll_interval = 5  # Check every 5 seconds
                waited = 0
                
                while transcript.status not in [aai.TranscriptStatus.completed, aai.TranscriptStatus.error]:
                    if waited >= max_wait:
                        logger.error(f"AssemblyAI transcription timeout after {max_wait} seconds")
                        self.failure_count += 1
                        self.last_failure_time = time.time()
                        return None
                        
                    await asyncio.sleep(poll_interval)
                    waited += poll_interval
                    
                    # Refresh transcript status
                    transcript = await asyncio.to_thread(aai.Transcript.get_by_id, transcript.id)
                    
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
                
                # Return formatted transcript with speaker labels
                return self._format_transcript(transcript)
                
        except Exception as e:
            logger.error(f"AssemblyAI transcription error: {str(e)}", exc_info=True)
            self.failure_count += 1
            self.last_failure_time = time.time()
            return None
            
    async def _upload_audio(self, audio_path: Path) -> Optional[str]:
        """Upload audio file to AssemblyAI and return URL"""
        try:
            logger.info(f"Uploading {audio_path.name} to AssemblyAI ({audio_path.stat().st_size / 1024 / 1024:.1f} MB)")
            
            # Use AssemblyAI's upload function
            upload_url = await asyncio.to_thread(aai.upload_file, str(audio_path))
            
            logger.info(f"Successfully uploaded audio to AssemblyAI")
            return upload_url
            
        except Exception as e:
            logger.error(f"Failed to upload audio to AssemblyAI: {str(e)}")
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