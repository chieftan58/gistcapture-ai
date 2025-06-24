"""Audio transcription using OpenAI Whisper"""

import os
import re
import asyncio
import hashlib
import aiohttp
import aiofiles
from pathlib import Path
from typing import Optional, List
from pydub import AudioSegment

from ..models import Episode
from ..config import AUDIO_DIR, TRANSCRIPT_DIR, TEMP_DIR, TESTING_MODE, MAX_TRANSCRIPTION_MINUTES
from ..utils.logging import get_logger
from ..utils.helpers import slugify
from ..utils.clients import openai_client
import openai

logger = get_logger(__name__)


class AudioTranscriber:
    """Handle audio download and transcription"""
    
    def __init__(self):
        self.session = None
    
    async def transcribe_episode(self, episode: Episode) -> Optional[str]:
        """Download and transcribe audio for an episode"""
        if not episode.audio_url:
            logger.error("❌ No audio URL available")
            return None
        
        try:
            # Create unique filename with readable format
            date_str = episode.published.strftime('%Y%m%d')
            safe_podcast = slugify(episode.podcast)[:30]
            safe_title = slugify(episode.title)[:50]
            transcript_file = TRANSCRIPT_DIR / f"{date_str}_{safe_podcast}_{safe_title}_transcript.txt"
            
            # Check if already transcribed
            if transcript_file.exists():
                logger.info("✅ Found existing transcription")
                with open(transcript_file, 'r', encoding='utf-8') as f:
                    return f.read()
            
            # Download audio
            logger.info("⬇️  Downloading audio...")
            audio_path = await self._download_audio(episode.audio_url)
            
            if not audio_path:
                return None
            
            # Transcribe with Whisper
            logger.info("🎯 Transcribing with Whisper...")
            transcript = await self._transcribe_with_whisper(audio_path)
            
            # Save transcript
            if transcript:
                async with aiofiles.open(transcript_file, 'w', encoding='utf-8') as f:
                    await f.write(transcript)
                logger.info(f"✅ Transcript saved: {transcript_file}")
                
                # Clean up audio file
                try:
                    os.remove(audio_path)
                except:
                    pass
                
                return transcript
            
        except Exception as e:
            logger.error(f"❌ Transcription error: {e}")
            import traceback
            logger.error(traceback.format_exc())
        
        return None
    
    async def _download_audio(self, audio_url: str) -> Optional[Path]:
        """Download audio file with better headers to avoid 403 errors"""
        try:
            # Create temp file
            temp_file = AUDIO_DIR / f"temp_{hashlib.md5(audio_url.encode()).hexdigest()[:8]}.mp3"
            
            # Better headers to avoid 403 errors
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'audio/mpeg, audio/mp4, audio/*;q=0.9, */*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'audio',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Cache-Control': 'max-age=0'
            }
            
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(audio_url, allow_redirects=True) as response:
                    if response.status == 200:
                        total_size = int(response.headers.get('content-length', 0))
                        
                        async with aiofiles.open(temp_file, 'wb') as f:
                            downloaded = 0
                            async for chunk in response.content.iter_chunked(8192):
                                await f.write(chunk)
                                downloaded += len(chunk)
                                
                                if total_size > 0:
                                    progress = (downloaded / total_size) * 100
                                    print(f"\r  Progress: {progress:.1f}%", end='', flush=True)
                        
                        print()  # New line after progress
                        logger.info(f"✅ Downloaded: {downloaded/1_000_000:.1f}MB")
                        return temp_file
                    else:
                        logger.error(f"❌ Download failed: HTTP {response.status}")
                        # Try alternate download method if 403
                        if response.status == 403:
                            return await self._alternate_download(audio_url)
                        
        except Exception as e:
            logger.error(f"❌ Download error: {e}")
        
        return None
    
    async def _alternate_download(self, audio_url: str) -> Optional[Path]:
        """Alternate download method using requests library"""
        try:
            import requests
            logger.info("🔄 Trying alternate download method...")
            
            # Create temp file
            temp_file = AUDIO_DIR / f"temp_{hashlib.md5(audio_url.encode()).hexdigest()[:8]}.mp3"
            
            # Use requests with session
            session = requests.Session()
            session.headers.update({
                'User-Agent': 'Renaissance Weekly Podcast Bot/2.0 (Compatible; Like iTunes)',
                'Accept': '*/*',
                'Accept-Encoding': 'identity',
                'Connection': 'keep-alive',
            })
            
            response = session.get(audio_url, stream=True, allow_redirects=True)
            
            if response.status_code == 200:
                total_size = int(response.headers.get('content-length', 0))
                downloaded = 0
                
                with open(temp_file, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            
                            if total_size > 0:
                                progress = (downloaded / total_size) * 100
                                print(f"\r  Progress: {progress:.1f}%", end='', flush=True)
                
                print()  # New line after progress
                logger.info(f"✅ Downloaded via alternate method: {downloaded/1_000_000:.1f}MB")
                return temp_file
            else:
                logger.error(f"❌ Alternate download failed: HTTP {response.status_code}")
                
        except Exception as e:
            logger.error(f"❌ Alternate download error: {e}")
        
        return None
    
    async def _transcribe_with_whisper(self, audio_path: Path) -> Optional[str]:
        """Transcribe audio using OpenAI Whisper with better error handling and retry logic"""
        try:
            # Load and process audio
            audio = AudioSegment.from_file(audio_path)
            duration_min = len(audio) / 60000
            
            logger.info(f"⏱️  Duration: {duration_min:.1f} minutes")
            
            # Apply testing limit if enabled
            if TESTING_MODE and duration_min > MAX_TRANSCRIPTION_MINUTES:
                logger.info(f"🧪 TESTING MODE: Limiting to {MAX_TRANSCRIPTION_MINUTES} minutes")
                audio = audio[:MAX_TRANSCRIPTION_MINUTES * 60 * 1000]
            
            # Create chunks for Whisper (25MB limit, but we'll use 20MB to be safe)
            chunks = self._create_audio_chunks(audio)
            logger.info(f"📦 Created {len(chunks)} chunks for transcription")
            
            transcripts = []
            
            for i, chunk_path in enumerate(chunks):
                logger.info(f"🎙️  Transcribing chunk {i+1}/{len(chunks)}...")
                
                # Retry logic for each chunk
                max_retries = 3
                retry_delay = 5  # seconds
                
                for attempt in range(max_retries):
                    try:
                        with open(chunk_path, 'rb') as audio_file:
                            # Use the client with timeout already configured
                            transcript = openai_client.audio.transcriptions.create(
                                model="whisper-1",
                                file=audio_file,
                                response_format="text"
                            )
                        
                        transcripts.append(transcript.strip())
                        logger.info(f"   ✅ Chunk {i+1} transcribed successfully")
                        break  # Success, exit retry loop
                        
                    except openai.APITimeoutError as e:
                        logger.warning(f"   ⏱️ Timeout on chunk {i+1}, attempt {attempt+1}/{max_retries}")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_delay)
                            retry_delay *= 2  # Exponential backoff
                        else:
                            logger.error(f"   ❌ Failed to transcribe chunk {i+1} after {max_retries} attempts")
                            raise
                            
                    except openai.RateLimitError as e:
                        logger.warning(f"   ⚡ Rate limit hit on chunk {i+1}")
                        wait_time = 60  # Default wait time
                        # Try to parse wait time from error message
                        if 'Please try again in' in str(e):
                            try:
                                wait_match = re.search(r'in (\d+)s', str(e))
                                if wait_match:
                                    wait_time = int(wait_match.group(1)) + 1
                            except:
                                pass
                        logger.info(f"   ⏳ Waiting {wait_time} seconds before retry...")
                        await asyncio.sleep(wait_time)
                        
                    except openai.APIError as e:
                        logger.error(f"   ❌ API error on chunk {i+1}: {e}")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_delay)
                        else:
                            raise
                            
                    except Exception as e:
                        logger.error(f"   ❌ Unexpected error on chunk {i+1}: {e}")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_delay)
                        else:
                            raise
                
                # Clean up chunk after successful transcription
                try:
                    os.remove(chunk_path)
                except:
                    pass
                
                # Small delay between chunks to avoid rate limits
                if i < len(chunks) - 1:
                    await asyncio.sleep(2)
            
            # Merge transcripts with better handling
            if not transcripts:
                logger.error("❌ No transcripts generated")
                return None
                
            full_transcript = " ".join(transcripts)
            
            # Basic quality check
            if len(full_transcript) < 100:
                logger.warning(f"⚠️  Transcript seems too short: {len(full_transcript)} characters")
                
            logger.info(f"✅ Transcription complete: {len(full_transcript)} characters")
            
            return full_transcript
            
        except Exception as e:
            logger.error(f"❌ Whisper transcription error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            
            # Clean up any remaining chunks
            try:
                for file in TEMP_DIR.glob("chunk_*.mp3"):
                    file.unlink()
            except:
                pass
                
            return None
    
    def _create_audio_chunks(self, audio: AudioSegment, max_size_mb: int = 20) -> List[Path]:
        """Split audio into chunks for Whisper API"""
        chunks = []
        chunk_duration_ms = 20 * 60 * 1000  # 20 minutes
        
        for i in range(0, len(audio), chunk_duration_ms):
            chunk = audio[i:i + chunk_duration_ms]
            
            # Export chunk
            chunk_path = TEMP_DIR / f"chunk_{i//chunk_duration_ms}.mp3"
            chunk.export(chunk_path, format="mp3", bitrate="64k")
            
            # Check size
            if os.path.getsize(chunk_path) > max_size_mb * 1024 * 1024:
                # Re-export with lower quality
                os.remove(chunk_path)
                chunk.export(chunk_path, format="mp3", bitrate="32k")
            
            chunks.append(chunk_path)
        
        return chunks