# main.py - Renaissance Weekly Podcast Summary System
import os
import hashlib
import tempfile
import feedparser
from datetime import datetime, timedelta
from pathlib import Path
from urllib.request import urlretrieve
from urllib.parse import urlparse
import openai
from openai import OpenAI
from pydub import AudioSegment
from pydub.silence import detect_silence
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from dotenv import load_dotenv
import time
import re
import json
import asyncio
import aiohttp
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# Load environment variables
load_dotenv()

# Initialize clients
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
sendgrid_client = SendGridAPIClient(os.getenv("SENDGRID_API_KEY"))

# Configuration
TRANSCRIPT_DIR = Path("transcripts")
AUDIO_DIR = Path("audio")
SUMMARY_DIR = Path("summaries")

# Create directories
TRANSCRIPT_DIR.mkdir(exist_ok=True)
AUDIO_DIR.mkdir(exist_ok=True)
SUMMARY_DIR.mkdir(exist_ok=True)

# Email configuration
EMAIL_FROM = "insights@gistcapture.ai"
EMAIL_TO = os.getenv("EMAIL_TO", "caddington05@gmail.com")


class RenaissanceWeekly:
    def __init__(self):
        self.validate_env_vars()
    
    def validate_env_vars(self):
        """Validate that all required environment variables are set"""
        required_vars = ["OPENAI_API_KEY", "SENDGRID_API_KEY"]
        missing_vars = [var for var in required_vars if not os.getenv(var)]
        
        if missing_vars:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
        
        # Check if EMAIL_TO is set, provide helpful message if not
        if not EMAIL_TO or EMAIL_TO == "caddington05@gmail.com":
            print("ℹ️  Using default email: caddington05@gmail.com")
            print("💡 To change, set EMAIL_TO in your .env file")
    
    def slugify(self, text):
        """Convert text to filename-safe string"""
        return "".join(c if c.isalnum() or c in " ._-" else "_" for c in text)
    
    def extract_sponsors(self, description):
        """Extract sponsor information from episode description"""
        sponsors = []
        
        # Common sponsor patterns in Tim Ferriss show
        sponsor_patterns = [
            r'(?:Sponsored by|Brought to you by|This episode is brought to you by)\s+([^\.]+)',
            r'(?:Thanks to|Thank you to)\s+([^\.]+?)(?:\s+for\s+sponsoring)',
            r'([A-Z][a-zA-Z\s&]+?)(?:\s+\[.*?\])?(?:\s+at\s+|—\s*)?(?:https?://)?([a-zA-Z0-9\-]+\.[a-zA-Z]{2,})',
        ]
        
        # Common sponsors and their URLs (fallback if URL not in description)
        known_sponsors = {
            'Athletic Greens': 'https://athleticgreens.com',
            'AG1': 'https://drinkag1.com',
            'BetterHelp': 'https://betterhelp.com',
            'Helix Sleep': 'https://helixsleep.com',
            'ExpressVPN': 'https://expressvpn.com',
            'Wealthfront': 'https://wealthfront.com',
            'Eight Sleep': 'https://eightsleep.com',
            'LMNT': 'https://drinklmnt.com',
            'Shopify': 'https://shopify.com',
            'MasterClass': 'https://masterclass.com',
            'InsideTracker': 'https://insidetracker.com',
            'WHOOP': 'https://whoop.com',
            'Momentous': 'https://livemomentous.com',
        }
        
        # Clean description
        clean_desc = description.replace('\n', ' ').replace('\r', ' ')
        
        # Look for sponsors section
        sponsors_section = re.search(r'(?:Sponsors|Brought to you by|Thanks to our sponsors).*?(?=\n\n|\Z)', clean_desc, re.IGNORECASE | re.DOTALL)
        
        if sponsors_section:
            sponsors_text = sponsors_section.group()
            
            # Extract URLs and sponsor names
            url_pattern = r'(?:([A-Z][a-zA-Z\s&]+?)(?:\s+at\s+|\s*—\s*|\s*:\s*))?(?:https?://)?([a-zA-Z0-9\-]+\.[a-zA-Z]{2,}/?[a-zA-Z0-9\-/]*)'
            matches = re.findall(url_pattern, sponsors_text)
            
            for match in matches:
                name = match[0].strip() if match[0] else ""
                url = match[1]
                
                # Ensure URL has protocol
                if not url.startswith('http'):
                    url = f'https://{url}'
                
                # Try to get sponsor name from URL if not found
                if not name:
                    for sponsor, sponsor_url in known_sponsors.items():
                        if url.lower() in sponsor_url.lower() or sponsor_url.lower() in url.lower():
                            name = sponsor
                            break
                
                if name and url:
                    sponsors.append({'name': name, 'url': url})
        
        # Also check for inline sponsor mentions
        for pattern in sponsor_patterns:
            matches = re.findall(pattern, clean_desc, re.IGNORECASE)
            for match in matches:
                if isinstance(match, tuple):
                    name = match[0].strip()
                else:
                    name = match.strip()
                
                # Check if it's a known sponsor
                for sponsor, url in known_sponsors.items():
                    if sponsor.lower() in name.lower():
                        # Check if we already have this sponsor
                        if not any(s['name'].lower() == sponsor.lower() for s in sponsors):
                            sponsors.append({'name': sponsor, 'url': url})
                        break
        
        # Remove duplicates
        seen = set()
        unique_sponsors = []
        for sponsor in sponsors:
            key = sponsor['name'].lower()
            if key not in seen:
                seen.add(key)
                unique_sponsors.append(sponsor)
        
        return unique_sponsors[:6]  # Limit to 6 sponsors max
    
    def fetch_tim_ferriss_episodes(self, days_back=7):
        """Fetch recent Tim Ferriss podcast episodes"""
        FEED_URL = "https://rss.art19.com/tim-ferriss-show"
        print(f"🌐 Fetching episodes from: {FEED_URL}")
        print(f"📅 Looking for episodes from the last {days_back} days")
        
        try:
            feed = feedparser.parse(FEED_URL)
            
            if not feed.entries:
                print("❌ No entries found in RSS feed")
                return []
            
            print(f"📊 Found {len(feed.entries)} total episodes in feed")
            
            recent_eps = []
            cutoff = datetime.now() - timedelta(days=days_back)
            print(f"📅 Cutoff date: {cutoff.strftime('%Y-%m-%d %H:%M:%S')}")
            
            for entry in feed.entries[:10]:  # Check first 10 episodes
                # Parse publication date
                pub_date = None
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    try:
                        pub_date = datetime(*entry.published_parsed[:6])
                    except:
                        pass
                
                if not pub_date:
                    print(f"⚠️  Skipping episode (no date): {entry.title[:50]}...")
                    continue
                
                print(f"📅 Episode: {entry.title[:50]}... - {pub_date.strftime('%Y-%m-%d')}")
                
                if pub_date < cutoff:
                    print(f"   ⏰ Too old (before {cutoff.strftime('%Y-%m-%d')})")
                    continue
                
                # Get audio URL
                audio_url = None
                if hasattr(entry, 'enclosures') and entry.enclosures:
                    for enclosure in entry.enclosures:
                        if hasattr(enclosure, 'type') and 'audio' in enclosure.type.lower():
                            audio_url = enclosure.href
                            break
                
                if not audio_url:
                    print(f"   ❌ No audio URL found")
                    continue
                
                print(f"   ✅ Found audio URL: {audio_url[:50]}...")
                
                # Extract description for sponsor info
                description = ""
                if hasattr(entry, 'description'):
                    description = entry.description
                elif hasattr(entry, 'summary'):
                    description = entry.summary
                
                recent_eps.append({
                    "title": entry.title,
                    "url": audio_url,
                    "published": pub_date.strftime("%Y-%m-%d"),
                    "description": description,
                    "link": entry.link if hasattr(entry, 'link') else ""
                })
            
            print(f"✅ Found {len(recent_eps)} recent episode(s) to process")
            return recent_eps
            
        except Exception as e:
            print(f"❌ Error fetching episodes: {e}")
            import traceback
            print(f"Full error: {traceback.format_exc()}")
            return []
    
    def show_progress(self, stop_event, start_time, task_name="Processing", estimated_duration=None):
        """Show animated progress indicator in a separate thread"""
        spinner = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
        i = 0
        while not stop_event.is_set():
            elapsed = time.time() - start_time
            minutes = int(elapsed // 60)
            seconds = int(elapsed % 60)
            
            # Show estimated time remaining if available
            if estimated_duration and estimated_duration > 0:
                remaining = max(0, estimated_duration - elapsed)
                rem_minutes = int(remaining // 60)
                rem_seconds = int(remaining % 60)
                print(f'\r{spinner[i]} {task_name}... {minutes:02d}:{seconds:02d} elapsed (est. {rem_minutes:02d}:{rem_seconds:02d} remaining)', end='', flush=True)
            else:
                print(f'\r{spinner[i]} {task_name}... {minutes:02d}:{seconds:02d} elapsed', end='', flush=True)
            
            i = (i + 1) % len(spinner)
            time.sleep(0.1)
        # Clear the line
        print('\r' + ' ' * 80 + '\r', end='', flush=True)
    
    def download_and_process_audio(self, audio_url, title):
        """Download and process audio using smart chunking"""
        slug = self.slugify(title)
        hash_val = hashlib.md5(audio_url.encode()).hexdigest()[:6]
        
        # Final output files
        final_audio_filename = AUDIO_DIR / f"{slug[:50]}_{hash_val}_processed.mp3"
        final_transcript_filename = TRANSCRIPT_DIR / f"{slug[:50]}_{hash_val}_full.txt"
        
        # Check if we already have the transcript
        if final_transcript_filename.exists():
            print(f"⏩ Full transcript already exists: {final_transcript_filename}")
            with open(final_transcript_filename, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    print(f"✅ Loaded existing transcript ({len(content)} characters)")
                    return final_transcript_filename
        
        try:
            # Step 1: Download full audio
            print(f"⬇️  Downloading full audio...")
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp_file:
                tmp_path = tmp_file.name
            
            urlretrieve(audio_url, tmp_path)
            original_size = os.path.getsize(tmp_path)
            print(f"✅ Downloaded: {original_size/1000000:.1f}MB")
            
            # Check if the file is valid before processing
            try:
                # Load audio for processing
                print(f"🎵 Loading audio...")
                audio = AudioSegment.from_file(tmp_path)
                duration_min = len(audio) / 60000
                print(f"⏱️  Duration: {duration_min:.1f} minutes")
            except Exception as e:
                print(f"❌ Error loading audio file: {e}")
                print("🔍 This might be a corrupted or unsupported audio file")
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                return None
            
            # Step 2: Use smart chunking for all files
            print("\n🎯 Using intelligent chunking for optimal quality and reliability...")
            transcript = self._transcribe_with_smart_chunks(audio, final_transcript_filename)
            
            # Save a lightweight version of the audio for reference
            if not final_audio_filename.exists() and transcript:
                try:
                    print("💾 Saving compressed reference audio...")
                    light_audio = audio.set_frame_rate(8000).set_channels(1)
                    light_audio.export(final_audio_filename, format="mp3", bitrate="16k")
                except Exception as e:
                    print(f"⚠️  Could not save reference audio: {e}")
            
            if os.path.exists(tmp_path):
                os.remove(tmp_path)  # Clean up original
            
            return transcript
            
        except Exception as e:
            print(f"❌ Error processing audio: {e}")
            import traceback
            print(f"Full error: {traceback.format_exc()}")
            
            # Clean up any temporary files
            if 'tmp_path' in locals() and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except:
                    pass
            
            return None
    
    def _transcribe_with_smart_chunks(self, audio, transcript_filename):
        """Transcribe using intelligent chunking at natural boundaries"""
        print(f"🎯 Creating intelligent chunks...")
        
        # Create progress file path
        progress_filename = transcript_filename.parent / f"{transcript_filename.stem}_progress.json"
        
        # Check if we have existing progress
        existing_progress = None
        if progress_filename.exists():
            try:
                with open(progress_filename, 'r') as f:
                    existing_progress = json.load(f)
                print(f"📂 Found existing progress: {len(existing_progress['completed_chunks'])} chunks completed")
            except:
                existing_progress = None
        
        # First, detect silence periods (potential natural breaks)
        silence_breaks = self._detect_silence_breaks(audio)
        print(f"🔍 Using {len(silence_breaks)} break points")
        
        # Create chunks at natural boundaries
        chunks_info = self._create_smart_chunks(audio, silence_breaks)
        print(f"📦 Created {len(chunks_info)} chunks")
        
        # Show chunk layout
        print("\n📊 Chunk layout:")
        for chunk in chunks_info:
            print(f"   Chunk {chunk['num']+1}: {chunk['start_min']:.1f}-{chunk['end_min']:.1f} min ({chunk['duration_min']:.1f} min)")
        
        # Initialize or load progress
        if existing_progress and existing_progress.get('total_chunks') == len(chunks_info):
            chunk_texts = existing_progress['chunk_texts']
            completed_chunks = set(existing_progress['completed_chunks'])
            print(f"\n🔄 Resuming from chunk {len(completed_chunks)+1}")
        else:
            chunk_texts = []
            completed_chunks = set()
            # Save initial progress
            progress_data = {
                'episode_id': transcript_filename.stem,
                'total_chunks': len(chunks_info),
                'completed_chunks': [],
                'chunk_texts': []
            }
            with open(progress_filename, 'w') as f:
                json.dump(progress_data, f)
        
        # Transcribe each chunk
        for chunk_info in chunks_info:
            # Skip if already completed
            if chunk_info['num'] in completed_chunks:
                print(f"\n✅ Chunk {chunk_info['num']+1}/{len(chunks_info)}: Already completed")
                continue
                
            print(f"\n🎙️  Chunk {chunk_info['num']+1}/{len(chunks_info)}: "
                  f"{chunk_info['start_min']:.1f}-{chunk_info['end_min']:.1f} min "
                  f"({chunk_info['duration_min']:.1f} min)")
            
            chunk_path = None
            try:
                # Extract chunk
                chunk = audio[chunk_info['start']:chunk_info['end']]
                
                # Compress chunk for API
                chunk = chunk.set_frame_rate(16000).set_channels(1)
                
                with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp_file:
                    chunk_path = tmp_file.name
                    chunk.export(chunk_path, format="mp3", bitrate="64k")
                
                chunk_size = os.path.getsize(chunk_path)
                print(f"  Size: {chunk_size/1000000:.1f}MB")
                
                # Transcribe with progress
                start_time = time.time()
                stop_event = threading.Event()
                
                # Estimate time based on chunk size (usually 20-40 seconds per chunk)
                estimated_time = 30  # seconds
                
                progress_thread = threading.Thread(
                    target=self.show_progress,
                    args=(stop_event, start_time, f"Chunk {chunk_info['num']+1}", estimated_time)
                )
                progress_thread.start()
                
                try:
                    with open(chunk_path, "rb") as audio_file:
                        transcript_response = openai_client.audio.transcriptions.create(
                            model="whisper-1",
                            file=audio_file,
                            response_format="text"
                        )
                    
                    stop_event.set()
                    progress_thread.join()
                    
                    elapsed = time.time() - start_time
                    print(f"  ✅ Chunk transcribed in {elapsed:.1f} seconds")
                    
                    transcript = transcript_response.strip()
                    
                    # Store with metadata for intelligent merging
                    chunk_text_data = {
                        'text': transcript,
                        'start_min': chunk_info['start_min'],
                        'end_min': chunk_info['end_min'],
                        'num': chunk_info['num']
                    }
                    chunk_texts.append(chunk_text_data)
                    completed_chunks.add(chunk_info['num'])
                    
                    # Save progress after each successful chunk
                    progress_data = {
                        'episode_id': transcript_filename.stem,
                        'total_chunks': len(chunks_info),
                        'completed_chunks': list(completed_chunks),
                        'chunk_texts': chunk_texts
                    }
                    with open(progress_filename, 'w') as f:
                        json.dump(progress_data, f)
                    
                except Exception as e:
                    stop_event.set()
                    progress_thread.join()
                    print(f"  ❌ Error transcribing chunk: {e}")
                
            except Exception as e:
                print(f"  ❌ Error processing chunk: {e}")
            
            finally:
                # Clean up chunk file
                if chunk_path and os.path.exists(chunk_path):
                    try:
                        os.remove(chunk_path)
                    except:
                        pass
            
            # Small delay between API calls
            if chunk_info['num'] < len(chunks_info) - 1:
                time.sleep(2)
        
        # Merge transcripts intelligently
        print("\n🔄 Intelligently merging transcripts...")
        
        if len(chunk_texts) == 0:
            raise Exception("No chunks were successfully transcribed")
        
        # Sort chunks by number to ensure correct order
        chunk_texts.sort(key=lambda x: x['num'])
        
        # Smart merging: detect and remove duplicates from overlaps
        merged_transcript = self._smart_merge_transcripts(chunk_texts)
        
        # Save merged transcript
        with open(transcript_filename, "w", encoding="utf-8") as f:
            f.write(merged_transcript)
        
        print(f"✅ Merged transcript saved: {len(merged_transcript)} characters")
        
        # Clean up progress file on successful completion
        if progress_filename.exists():
            os.remove(progress_filename)
            print("🧹 Cleaned up progress tracking file")
        
        return transcript_filename
    
    def _detect_silence_breaks(self, audio, min_silence_len=1500, silence_thresh=-45):
        """Detect silence periods in chunks to avoid memory issues"""
        from pydub.silence import detect_silence
        
        print("  🔍 Detecting natural break points...")
        
        # Process in 5-minute chunks to avoid memory overload
        chunk_size = 5 * 60 * 1000  # 5 minutes
        all_breaks = []
        total_duration = len(audio)
        
        for i in range(0, total_duration, chunk_size):
            chunk_end = min(i + chunk_size, total_duration)
            chunk = audio[i:chunk_end]
            
            # Show progress
            progress = (i / total_duration) * 100
            print(f"    Analyzing: {progress:.0f}% complete...", end='\r')
            
            # Detect silence in this chunk
            silence_ranges = detect_silence(
                chunk, 
                min_silence_len=min_silence_len,
                silence_thresh=silence_thresh
            )
            
            # Adjust positions to absolute time
            for start, end in silence_ranges:
                break_point = i + (start + end) // 2
                all_breaks.append(break_point)
        
        print(f"\r  ✅ Found {len(all_breaks)} natural break points" + " " * 20)
        
        # If we found very few breaks in a long podcast, add some fixed intervals
        duration_min = total_duration / 60000
        if duration_min > 60 and len(all_breaks) < duration_min / 20:
            print(f"  📍 Adding fixed intervals (found too few natural breaks)")
            interval = 18 * 60 * 1000  # 18 minutes
            position = interval
            while position < total_duration:
                all_breaks.append(position)
                position += interval
            all_breaks.sort()  # Keep them in order
        
        return all_breaks
    
    def _create_smart_chunks(self, audio, silence_breaks, target_chunk_min=18, max_chunk_min=22):
        """Create chunks at natural boundaries, respecting size constraints"""
        duration_ms = len(audio)
        target_chunk_ms = target_chunk_min * 60 * 1000
        max_chunk_ms = max_chunk_min * 60 * 1000
        min_chunk_ms = 10 * 60 * 1000  # Minimum 10 minutes
        
        chunks = []
        current_start = 0
        chunk_num = 0
        
        while current_start < duration_ms:
            # Ideal end point
            ideal_end = current_start + target_chunk_ms
            
            # Don't go past the end
            if ideal_end >= duration_ms:
                chunks.append({
                    'num': chunk_num,
                    'start': current_start,
                    'end': duration_ms,
                    'start_min': current_start / 60000,
                    'end_min': duration_ms / 60000,
                    'duration_min': (duration_ms - current_start) / 60000
                })
                break
            
            # Find the best break point near our ideal end
            best_break = ideal_end
            min_distance = max_chunk_ms
            
            for break_point in silence_breaks:
                # Look for breaks within a reasonable window
                if (ideal_end - 2*60*1000) <= break_point <= (ideal_end + 3*60*1000):
                    distance = abs(break_point - ideal_end)
                    if distance < min_distance:
                        min_distance = distance
                        best_break = break_point
            
            # Ensure chunk isn't too small or too large
            chunk_end = best_break
            if chunk_end - current_start < min_chunk_ms:
                chunk_end = current_start + target_chunk_ms
            elif chunk_end - current_start > max_chunk_ms:
                chunk_end = current_start + max_chunk_ms
            
            # Add 30-second overlap for safety
            if chunk_end < duration_ms:
                chunk_end = min(chunk_end + 30000, duration_ms)
            
            chunks.append({
                'num': chunk_num,
                'start': current_start,
                'end': chunk_end,
                'start_min': current_start / 60000,
                'end_min': chunk_end / 60000,
                'duration_min': (chunk_end - current_start) / 60000
            })
            
            # Move to next chunk (with small overlap)
            current_start = chunk_end - 30000  # 30 second overlap
            chunk_num += 1
        
        return chunks
    
    def _smart_merge_transcripts(self, chunk_texts):
        """Intelligently merge transcripts by detecting and removing overlapping content"""
        if not chunk_texts:
            return ""
        
        if len(chunk_texts) == 1:
            return chunk_texts[0]['text']
        
        merged = chunk_texts[0]['text']
        
        for i in range(1, len(chunk_texts)):
            current_chunk = chunk_texts[i]['text']
            
            # Find overlap by looking for matching sequences
            overlap_found = False
            min_overlap_words = 10  # Minimum words to consider as overlap
            
            # Try to find where the previous chunk ends in the current chunk
            words_from_end = merged.split()[-50:]  # Last 50 words of merged text
            
            for j in range(len(words_from_end) - min_overlap_words):
                test_sequence = ' '.join(words_from_end[j:])
                if test_sequence in current_chunk:
                    # Found overlap! 
                    overlap_index = current_chunk.index(test_sequence) + len(test_sequence)
                    
                    # Add only the non-overlapping part
                    new_content = current_chunk[overlap_index:].strip()
                    if new_content:
                        merged += " " + new_content
                    overlap_found = True
                    break
            
            if not overlap_found:
                # No clear overlap found, just append with a marker
                merged += "\n\n" + current_chunk
        
        return merged
    
    def transcribe_audio(self, audio_file_path, title):
        """Main entry point for transcription - handles all strategies"""
        return self.download_and_process_audio(audio_file_path, title)
    
    def summarize_transcript(self, transcript_file_path, episode_title, episode_info):
        """Generate executive-focused summary with actionable insights"""
        slug = self.slugify(episode_title)
        hash_val = hashlib.md5(str(transcript_file_path).encode()).hexdigest()[:6]
        summary_filename = SUMMARY_DIR / f"{slug[:50]}_{hash_val}.md"
        
        if summary_filename.exists():
            print(f"⏩ Summary already exists: {summary_filename}")
            with open(summary_filename, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    print(f"✅ Loaded existing summary ({len(content)} characters)")
                    return content
                else:
                    print("⚠️  Existing summary is empty, re-generating...")
        
        try:
            with open(transcript_file_path, "r", encoding="utf-8") as f:
                transcript = f.read()
            
            if not transcript.strip():
                print("❌ Empty transcript file")
                return None
            
            print(f"📚 Generating executive-focused summary with GPT-4o...")
            print(f"   Transcript length: {len(transcript):,} characters")
            
            # Extract sponsors from description
            sponsors = self.extract_sponsors(episode_info.get('description', ''))
            
            # Check transcript size and chunk if needed
            max_chars = 100000
            
            if len(transcript) > max_chars:
                print(f"⚠️  Transcript too long ({len(transcript):,} chars), using chunked summarization...")
                return self._quality_summarize_long_transcript(transcript, episode_title, episode_info, summary_filename, sponsors)
            
            # Show progress for summarization
            start_time = time.time()
            stop_event = threading.Event()
            progress_thread = threading.Thread(
                target=self.show_progress,
                args=(stop_event, start_time, "Generating summary with GPT-4o", 45)
            )
            progress_thread.start()
            
            try:
                # NEW EXECUTIVE-FOCUSED PROMPT
                prompt = f"""EPISODE: {episode_title}
DESCRIPTION: {episode_info.get('description', '')}

TRANSCRIPT:
{transcript}

You are creating an executive briefing for Renaissance Weekly readers - busy professionals who want to extract maximum value from this podcast in minimum time.

Create a comprehensive yet scannable summary (1,000-1,200 words) structured as follows:

## Executive Summary
A 2-3 sentence overview of the most important takeaways from this episode. What's the ONE thing a reader should remember?

## Key Insights & Frameworks
• Extract 5-7 of the most valuable insights, mental models, or frameworks discussed
• Each bullet should be substantive (2-3 sentences) and actionable
• Focus on ideas that can be immediately applied or that shift perspective
• Include specific examples or data points when mentioned

## Notable Quotes
Pull 3-5 of the most powerful or crystallizing quotes from the conversation. Choose quotes that:
- Capture a key insight memorably
- Challenge conventional thinking
- Provide actionable wisdom
Format: "Quote here" - Speaker Name (with brief context if needed)

## Tactical Takeaways
• 4-6 specific, actionable items discussed (tools, techniques, habits, strategies)
• Include any specific recommendations with enough detail to be useful
• If percentages, timeframes, or metrics were mentioned, include them

## Resources Mentioned
• Books: Title by Author (with 1-line description of why it was recommended)
• Tools/Apps: Name (what it's used for)
• Concepts to explore further: Brief description
• People referenced: Name (why they matter)

## The Big Picture
A brief paragraph (3-4 sentences) connecting this conversation to broader trends in technology, business, health, or society. Why does this conversation matter now?

## Action Items for the Week
3 specific things a reader could implement this week based on the episode:
1. [Specific action with clear first step]
2. [Another actionable item]
3. [Third concrete action]

Remember: This is for executives and professionals who value their time. Be direct, specific, and practical. Avoid fluff and focus on extracting maximum insight per word."""

                # Try with retry logic for rate limits
                try:
                    response = openai_client.chat.completions.create(
                        model="gpt-4o",
                        messages=[
                            {
                                "role": "system",
                                "content": "You are a world-class executive briefing specialist. Your summaries help busy professionals extract maximum value from long-form content. You excel at identifying actionable insights and presenting them in a clear, scannable format."
                            },
                            {
                                "role": "user",
                                "content": prompt
                            }
                        ],
                        max_tokens=4000,
                        temperature=0.3
                    )
                except openai.RateLimitError as e:
                    stop_event.set()
                    progress_thread.join()
                    
                    print(f"\n⏰ Rate limit hit: {e}")
                    print("⏳ Waiting 65 seconds for rate limit reset...")
                    time.sleep(65)
                    
                    # Restart progress indicator
                    start_time = time.time()
                    stop_event = threading.Event()
                    progress_thread = threading.Thread(
                        target=self.show_progress,
                        args=(stop_event, start_time, "Generating summary (retry)", 45)
                    )
                    progress_thread.start()
                    
                    print("🔄 Retrying summary generation...")
                    response = openai_client.chat.completions.create(
                        model="gpt-4o",
                        messages=[
                            {
                                "role": "system",
                                "content": "You are a world-class executive briefing specialist. Your summaries help busy professionals extract maximum value from long-form content. You excel at identifying actionable insights and presenting them in a clear, scannable format."
                            },
                            {
                                "role": "user",
                                "content": prompt
                            }
                        ],
                        max_tokens=4000,
                        temperature=0.3
                    )
                
                stop_event.set()
                progress_thread.join()
                
                elapsed = time.time() - start_time
                print(f"✅ Summary generated in {elapsed/60:.1f} minutes")
                
                summary = response.choices[0].message.content
                
                if not summary or len(summary.strip()) < 100:
                    raise Exception("Generated summary is too short or empty")
                
                # Add enhanced episode metadata
                episode_footer = self._create_episode_footer(episode_info, sponsors)
                
                summary += episode_footer
                
                with open(summary_filename, "w", encoding="utf-8") as f:
                    f.write(summary)
                
                print(f"✅ Summary generated: {summary_filename} ({len(summary)} characters)")
                return summary
                
            finally:
                stop_event.set()
                progress_thread.join()
            
        except Exception as e:
            print(f"❌ Error generating summary: {e}")
            import traceback
            print(f"Full error: {traceback.format_exc()}")
            return None
    
    def _create_episode_footer(self, episode_info, sponsors):
        """Create attractive episode details footer"""
        footer = "\n\n---\n\n"
        
        # Episode metadata in a cleaner format
        footer += "### 📍 Episode Details\n\n"
        
        # Published date with icon
        footer += f"**📅 Published:** {episode_info['published']}\n\n"
        
        # Duration with icon
        footer += f"**⏱️ Duration:** 2-3 hours\n\n"
        
        # Listen on platforms with better formatting
        footer += "**🎧 Listen on:**\n"
        footer += "- [Apple Podcasts](https://podcasts.apple.com/us/podcast/the-tim-ferriss-show/id863897795)\n"
        footer += "- [Spotify](https://open.spotify.com/show/5qSUyCrk9KR69lEiXbjwXM)\n"
        footer += "- [YouTube](https://www.youtube.com/c/timferriss)\n"
        if episode_info.get('link'):
            footer += f"- [Episode Page]({episode_info['link']})\n"
        
        # Sponsors section if available
        if sponsors:
            footer += "\n**💼 Episode Sponsors:**\n"
            for sponsor in sponsors:
                footer += f"- [{sponsor['name']}]({sponsor['url']})\n"
        
        footer += "\n"
        
        return footer
    
    def _quality_summarize_long_transcript(self, transcript, episode_title, episode_info, summary_filename, sponsors):
        """
        Executive-focused summarization for very long transcripts (3+ hours).
        Uses a three-pass approach to extract actionable insights.
        """
        print("🎯 Engaging premium summarization protocol for extended episode...")
        
        # PASS 1: Intelligent Segmentation
        segments = self._create_conversation_segments(transcript)
        print(f"📊 Identified {len(segments)} natural conversation segments")
        
        # PASS 2: Extract Key Insights from Each Segment
        segment_insights = []
        for i, segment in enumerate(segments):
            print(f"\n🔍 Extracting insights from segment {i+1}/{len(segments)}...")
            
            start_time = time.time()
            stop_event = threading.Event()
            progress_thread = threading.Thread(
                target=self.show_progress,
                args=(stop_event, start_time, f"Analyzing segment {i+1}/{len(segments)}", 20)
            )
            progress_thread.start()
            
            try:
                analysis_prompt = f"""Analyze this segment of the podcast conversation for actionable insights.

SEGMENT {i+1} OF {len(segments)}:
{segment}

Extract the following from this segment:
1. KEY INSIGHTS: What are the 2-3 most valuable insights or frameworks discussed?
2. ACTIONABLE ITEMS: Any specific tools, techniques, or strategies mentioned?
3. POWERFUL QUOTES: 1-2 memorable quotes that crystallize key ideas
4. RESOURCES: Books, tools, or people mentioned
5. DATA POINTS: Any specific metrics, percentages, or timeframes mentioned

Focus on what would be most valuable for a busy executive. Be specific and practical."""

                response = openai_client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {
                            "role": "system",
                            "content": "You are extracting actionable insights from a podcast segment for busy executives. Focus on practical value and specific takeaways."
                        },
                        {
                            "role": "user",
                            "content": analysis_prompt
                        }
                    ],
                    max_tokens=2000,
                    temperature=0.3
                )
                
                segment_insights.append({
                    'segment_number': i + 1,
                    'insights': response.choices[0].message.content,
                    'approximate_time': f"{(i * 30)}-{((i + 1) * 30)} minutes"
                })
                
            finally:
                stop_event.set()
                progress_thread.join()
        
        # PASS 3: Synthesis into Executive Brief
        print("\n🎨 Synthesizing into Renaissance Weekly executive brief...")
        
        insights_text = "\n\n---\n\n".join([
            f"SEGMENT {s['segment_number']} (approx. {s['approximate_time']}):\n{s['insights']}"
            for s in segment_insights
        ])
        
        synthesis_prompt = f"""EPISODE: {episode_title}
DESCRIPTION: {episode_info.get('description', '')}

You have been provided with extracted insights from all segments of this extended podcast episode. Synthesize these into a single executive briefing.

SEGMENT INSIGHTS:
{insights_text}

Create a comprehensive executive summary (1,000-1,200 words) with this EXACT structure:

## Executive Summary
A 2-3 sentence overview capturing the absolute most important takeaways. What's the ONE thing to remember?

## Key Insights & Frameworks
• Synthesize the 5-7 most valuable insights across ALL segments
• Each bullet should be substantive (2-3 sentences) and actionable
• Combine related insights from different segments
• Focus on ideas with immediate application value
• Include specific examples or data points

## Notable Quotes
Select the 3-5 BEST quotes from across the entire conversation that:
- Capture essential insights memorably
- Challenge conventional thinking
- Provide actionable wisdom
Format: "Quote" - Speaker (context if needed)

## Tactical Takeaways
• 4-6 specific, actionable items from across the episode
• Include tools, techniques, habits, or strategies
• Merge similar recommendations from different segments
• Include any metrics or timeframes mentioned

## Resources Mentioned
Compile ALL resources from across segments:
• Books: Title by Author (why recommended)
• Tools/Apps: Name (purpose)
• Concepts: Brief description
• People: Name (relevance)

## The Big Picture
A paragraph connecting this conversation to broader trends. Why does this matter for Renaissance Weekly readers?

## Action Items for the Week
3 specific things to implement this week:
1. [Specific action with clear first step]
2. [Another actionable item]
3. [Third concrete action]

Remember: This is for time-constrained executives. Every word should deliver value. Be specific, practical, and actionable."""
        
        start_time = time.time()
        stop_event = threading.Event()
        progress_thread = threading.Thread(
            target=self.show_progress,
            args=(stop_event, start_time, "Crafting executive brief", 30)
        )
        progress_thread.start()
        
        try:
            response = openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": "You are creating executive briefings for Renaissance Weekly. Your readers are CEOs, investors, and professionals who need maximum insight in minimum time. Every section should be scannable and actionable."
                    },
                    {
                        "role": "user",
                        "content": synthesis_prompt
                    }
                ],
                max_tokens=4000,
                temperature=0.3
            )
            
            final_summary = response.choices[0].message.content
            
            # Add enhanced episode metadata
            episode_footer = self._create_episode_footer(episode_info, sponsors)
            
            final_summary += episode_footer
            
            with open(summary_filename, "w", encoding="utf-8") as f:
                f.write(final_summary)
            
            print(f"✅ Executive brief crafted: {len(final_summary)} characters")
            return final_summary
            
        finally:
            stop_event.set()
            progress_thread.join()
    
    def _create_conversation_segments(self, transcript, target_segment_size=80000):
        """
        Intelligently segment transcript at natural conversation boundaries.
        Looks for topic transitions, speaker changes, or natural breaks.
        """
        # First, try to identify natural break points
        lines = transcript.split('\n')
        
        # Look for patterns that indicate topic changes
        break_indicators = [
            r'^#{1,3}\s',  # Markdown headers (if present)
            r'^\[\d+:\d+:\d+\]',  # Timestamps
            r'^(Tim Ferriss:|Tim:)',  # Host introducing new topic
            r'^\s*\*\s*\*\s*\*\s*$',  # Scene breaks
            r'^(So |Now |Let\'s talk about|Moving on|I want to ask you about)',  # Transition phrases
        ]
        
        segments = []
        current_segment = []
        current_size = 0
        
        for i, line in enumerate(lines):
            # Check if this line indicates a natural break
            is_break = any(re.match(pattern, line, re.IGNORECASE) for pattern in break_indicators)
            
            # Add line to current segment
            current_segment.append(line)
            current_size += len(line)
            
            # Decide if we should start a new segment
            should_break = False
            
            if is_break and current_size > target_segment_size * 0.7:  # Natural break after 70% of target
                should_break = True
            elif current_size > target_segment_size * 1.3:  # Force break at 130% of target
                should_break = True
            
            if should_break and len(current_segment) > 50:  # Minimum segment size
                segments.append('\n'.join(current_segment))
                current_segment = []
                current_size = 0
        
        # Don't forget the last segment
        if current_segment:
            segments.append('\n'.join(current_segment))
        
        # If we ended up with too few segments, split more aggressively
        if len(segments) < 3 and len(transcript) > 200000:
            print("📝 Adjusting segmentation for better coverage...")
            return self._fallback_segmentation(transcript)
        
        return segments
    
    def _fallback_segmentation(self, transcript, num_segments=4):
        """Simple fallback segmentation when natural breaks aren't found"""
        segment_size = len(transcript) // num_segments
        segments = []
        
        for i in range(num_segments):
            start = i * segment_size
            end = start + segment_size if i < num_segments - 1 else len(transcript)
            
            # Try to end at a paragraph break
            if i < num_segments - 1:
                next_break = transcript.find('\n\n', end)
                if next_break != -1 and next_break < end + 5000:
                    end = next_break
            
            segments.append(transcript[start:end])
        
        return segments
    
    def process_episode(self, episode):
        """Process a single episode with smart chunking"""
        print(f"\n{'='*60}")
        print(f"🎧 Processing: {episode['title']}")
        print(f"📅 Published: {episode['published']}")
        print(f"{'='*60}")
        
        # Download and transcribe using smart chunking
        print("\n📥 Downloading and processing episode...")
        transcript_file = self.download_and_process_audio(episode["url"], episode["title"])
        
        if not transcript_file:
            print("❌ Failed to process audio")
            return None
        
        # Summarize
        print("\n📝 Generating comprehensive summary...")
        summary = self.summarize_transcript(transcript_file, episode["title"], episode)
        
        if not summary:
            print("❌ Failed to generate summary")
            return None
        
        print("✅ Episode processed successfully!")
        return summary
    
    async def process_episode_async(self, episode, semaphore):
        """Process a single episode asynchronously"""
        async with semaphore:  # Limit concurrent processing
            return await asyncio.to_thread(self.process_episode, episode)
    
    async def process_episodes_parallel(self, episodes, max_concurrent=3):
        """Process multiple episodes in parallel"""
        print(f"\n🚀 Processing {len(episodes)} episodes in parallel (max {max_concurrent} concurrent)")
        
        # Create semaphore to limit concurrent processing
        semaphore = asyncio.Semaphore(max_concurrent)
        
        # Create tasks for all episodes
        tasks = []
        for i, episode in enumerate(episodes):
            task = asyncio.create_task(
                self.process_episode_async(episode, semaphore)
            )
            tasks.append((i, episode, task))
        
        # Process and collect results
        summaries = []
        for i, episode, task in tasks:
            try:
                print(f"\n📍 Starting Episode {i+1}/{len(episodes)}: {episode['title'][:50]}...")
                summary = await task
                if summary:
                    titled_summary = f"# {episode['title']}\n\n{summary}"
                    summaries.append(titled_summary)
                    print(f"✅ Episode {i+1} completed successfully")
                else:
                    print(f"❌ Episode {i+1} failed")
            except Exception as e:
                print(f"❌ Error processing episode {i+1}: {e}")
        
        return summaries
    
    def create_renaissance_email(self, summaries):
        """Create elegant HTML email in Renaissance Weekly style"""
        # Combine all summaries with elegant dividers
        combined_content = ""
        for i, summary in enumerate(summaries):
            if i > 0:
                combined_content += '\n\n<div style="text-align: center; margin: 60px 0;"><span style="color: #d1d1d6; font-size: 24px;">•  •  •</span></div>\n\n'
            combined_content += summary
        
        # Convert markdown to HTML with elegant formatting
        html_content = combined_content
        
        # Headers - Clean typography
        html_content = re.sub(r'^#{1} (.*?)$', r'<h1 style="color: #1d1d1f; font-size: 36px; margin: 40px 0 24px 0; font-weight: 700; line-height: 1.1; letter-spacing: -0.03em; font-family: -apple-system, BlinkMacSystemFont, \'SF Pro Display\', \'Helvetica Neue\', Arial, sans-serif;">\1</h1>', html_content, flags=re.MULTILINE)
        html_content = re.sub(r'^#{2} (.*?)$', r'<h2 style="color: #1d1d1f; font-size: 28px; margin: 36px 0 20px 0; font-weight: 600; line-height: 1.2; letter-spacing: -0.02em; font-family: -apple-system, BlinkMacSystemFont, \'SF Pro Display\', \'Helvetica Neue\', Arial, sans-serif;">\1</h2>', html_content, flags=re.MULTILINE)
        html_content = re.sub(r'^#{3} (.*?)$', r'<h3 style="color: #1d1d1f; font-size: 22px; margin: 28px 0 16px 0; font-weight: 600; line-height: 1.3; letter-spacing: -0.01em; font-family: -apple-system, BlinkMacSystemFont, \'SF Pro Display\', \'Helvetica Neue\', Arial, sans-serif;">\1</h3>', html_content, flags=re.MULTILINE)
        
        # Bold and italic
        html_content = re.sub(r'\*\*(.*?)\*\*', r'<strong style="font-weight: 600; color: #1d1d1f;">\1</strong>', html_content)
        html_content = re.sub(r'\*(.*?)\*', r'<em style="font-style: italic;">\1</em>', html_content)
        
        # Links - Subtle blue
        html_content = re.sub(r'\[([^\]]+)\]\(([^\)]+)\)', r'<a href="\2" style="color: #0066CC; text-decoration: none; border-bottom: 1px solid rgba(0, 102, 204, 0.2); transition: all 0.2s ease;">\1</a>', html_content)
        
        # Blockquotes for quotes
        html_content = re.sub(r'^> (.*)$', r'<blockquote style="margin: 32px 0; padding: 0 0 0 24px; border-left: 3px solid #d1d1d6; color: #515154; font-style: italic; font-size: 19px; line-height: 1.6;">\1</blockquote>', html_content, flags=re.MULTILINE)
        
        # Horizontal rules
        html_content = re.sub(r'^---$', r'<hr style="border: none; border-top: 1px solid #d1d1d6; margin: 40px 0;">', html_content, flags=re.MULTILINE)
        
        # Bullet points with better spacing
        html_content = re.sub(r'^- (.*)$', r'<li style="margin: 12px 0; color: #1d1d1f; line-height: 1.6;">\1</li>', html_content, flags=re.MULTILINE)
        html_content = re.sub(r'(<li.*?</li>\n)+', r'<ul style="margin: 24px 0; padding-left: 28px; list-style: none;">\g<0></ul>', html_content)
        html_content = html_content.replace('<li style="margin: 12px 0; color: #1d1d1f; line-height: 1.6;">', '<li style="margin: 12px 0; color: #1d1d1f; line-height: 1.6; position: relative; padding-left: 20px;"><span style="position: absolute; left: 0; color: #86868b;">•</span>')
        
        # Paragraphs with optimal reading width
        paragraphs = html_content.split('\n\n')
        html_paragraphs = []
        
        for para in paragraphs:
            para = para.strip()
            if para and not para.startswith('<'):
                para = f'<p style="margin: 20px 0; line-height: 1.7; color: #1d1d1f; font-size: 18px; font-weight: 400; letter-spacing: -0.01em; font-family: -apple-system, BlinkMacSystemFont, \'SF Pro Text\', Georgia, serif;">{para}</p>'
            html_paragraphs.append(para)
        
        html_content = '\n'.join(html_paragraphs)
        
        # Renaissance Weekly email template
        return f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Renaissance Weekly - Cross-Disciplinary Intelligence</title>
    <!--[if mso]>
    <noscript>
        <xml>
            <o:OfficeDocumentSettings>
                <o:PixelsPerInch>96</o:PixelsPerInch>
            </o:OfficeDocumentSettings>
        </xml>
    </noscript>
    <![endif]-->
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', Georgia, serif; background-color: #fafafa; color: #1d1d1f; -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale;">
    <div style="background-color: #fafafa; padding: 40px 0;">
        <div style="max-width: 720px; margin: 0 auto; background-color: #ffffff; box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);">
            <!-- Header -->
            <div style="background-color: #ffffff; padding: 60px 40px 40px 40px; text-align: center; border-bottom: 1px solid #e5e5e7;">
                <!-- Renaissance Weekly Text Logo -->
                <div style="margin-bottom: 30px;">
                    <h1 style="margin: 0; font-family: Georgia, 'Times New Roman', serif; font-size: 36px; font-weight: 400; letter-spacing: 0.08em; color: #1d1d1f; line-height: 1.1;">RENAISSANCE<br>WEEKLY</h1>
                </div>
                
                <p style="color: #515154; margin: 0 0 12px 0; font-size: 18px; font-weight: 400; font-style: italic; letter-spacing: 0.05em;">
                    The smartest podcasts, distilled.
                </p>
                <p style="color: #86868b; margin: 0; font-size: 16px; font-weight: 400;">
                    {datetime.now().strftime('%A, %B %d, %Y')}
                </p>
            </div>
            
            <!-- Introduction -->
            <div style="padding: 50px;">
                <div style="background-color: #f8f8fa; padding: 32px; border-radius: 8px; margin-bottom: 50px; border: 1px solid #e5e5e7;">
                    <p style="margin: 0; color: #1d1d1f; font-size: 18px; line-height: 1.7; font-weight: 400; font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', Georgia, serif;">
                        In a world awash with conversation, the most valuable ideas are often buried inside hours of long-form podcasts. This week's Renaissance Weekly surfaces and distills the best of these discussions—preserving nuance, contextual insight, and the arc of ideas as they unfold.
                    </p>
                </div>
                
                <!-- Main Content -->
                <div style="max-width: 100%;">
                    {html_content}
                </div>
            </div>
            
            <!-- Footer -->
            <div style="background-color: #f8f8fa; padding: 40px 40px; text-align: center; border-top: 1px solid #e5e5e7;">
                <div style="margin-bottom: 20px; opacity: 0.4;">
                    <p style="margin: 0; font-family: Georgia, 'Times New Roman', serif; font-size: 20px; font-weight: 400; letter-spacing: 0.08em; color: #1d1d1f; line-height: 1.1;">RENAISSANCE<br>WEEKLY</p>
                </div>
                
                <p style="color: #86868b; margin: 0 0 20px 0; font-size: 14px; line-height: 1.6; font-style: italic;">
                    "For those who remain intellectually ambitious in an age of distraction."
                </p>
                
                <p style="color: #86868b; margin: 0 0 8px 0; font-size: 13px;">
                    © {datetime.now().year} Renaissance Weekly. All rights reserved.
                </p>
                
                <p style="color: #86868b; margin: 0; font-size: 13px;">
                    <a href="https://gistcapture.ai" style="color: #0066CC; text-decoration: none;">gistcapture.ai</a> · 
                    <a href="mailto:{EMAIL_FROM}" style="color: #0066CC; text-decoration: none;">Contact</a> · 
                    <a href="https://gistcapture.ai/preferences" style="color: #0066CC; text-decoration: none;">Preferences</a>
                </p>
            </div>
        </div>
    </div>
</body>
</html>"""
    
    def generate_preview_text(self, summaries, episode_titles):
        """Generate email preview text from summaries"""
        try:
            # Extract key topics from first 2-3 summaries
            preview_parts = []
            
            for i, (summary, title) in enumerate(zip(summaries[:3], episode_titles[:3])):
                # Extract guest name from title if possible
                guest_match = re.search(r'(?:with|featuring|w/|:)\s*([^,\-–—]+)', title, re.IGNORECASE)
                guest_name = guest_match.group(1).strip() if guest_match else title.split()[0]
                
                # Find key topics in summary (look for bold text, headers, or key phrases)
                bold_topics = re.findall(r'\*\*(.*?)\*\*', summary[:500])
                
                if bold_topics:
                    # Take first 2-3 key topics
                    topics = [t for t in bold_topics[:3] if len(t) < 30]
                    if topics:
                        preview_parts.append(f"{guest_name}: {', '.join(topics[:2])}")
                
                if len(preview_parts) >= 2:
                    break
            
            # Create preview text
            if preview_parts:
                preview = " | ".join(preview_parts)
            else:
                # Fallback preview
                preview = "This week: breakthrough insights on AI, longevity, investing strategies, and global trends"
            
            # Ensure it's within 100-120 characters
            if len(preview) > 120:
                preview = preview[:117] + "..."
            
            return preview
            
        except Exception as e:
            print(f"Warning: Could not generate preview text: {e}")
            return "This week's smartest podcast conversations, expertly distilled for the intellectually ambitious"
    
    def send_summary_email(self, summaries, episode_data):
        """Send Renaissance Weekly digest"""
        try:
            print(f"📧 Preparing Renaissance Weekly digest...")
            
            # Extract episode titles for preview text
            episode_titles = [ep['title'] for ep in episode_data]
            
            # Generate preview text
            preview_text = self.generate_preview_text(summaries, episode_titles)
            print(f"📝 Preview text: {preview_text}")
            
            # Create elegant HTML email
            html_content = self.create_renaissance_email(summaries)
            
            # Add preview text as hidden element at start of HTML
            html_with_preview = f"""<div style="display:none;font-size:1px;color:#333333;line-height:1px;max-height:0px;max-width:0px;opacity:0;overflow:hidden;">
{preview_text}
</div>
{html_content}"""
            
            # Create plain text version
            plain_content = "RENAISSANCE WEEKLY\nThe smartest podcasts, distilled.\n\n"
            plain_content += f"{datetime.now().strftime('%A, %B %d, %Y')}\n\n"
            plain_content += "="*60 + "\n\n"
            
            for summary in summaries:
                plain_text = re.sub(r'\*\*(.*?)\*\*', r'\1', summary)
                plain_text = re.sub(r'\*(.*?)\*', r'\1', plain_text)
                plain_text = re.sub(r'\[([^\]]+)\]\(([^\)]+)\)', r'\1 (\2)', plain_text)
                plain_text = re.sub(r'^#+\s+(.*)', r'\1', plain_text, flags=re.MULTILINE)
                plain_content += plain_text + "\n\n" + "="*60 + "\n\n"
            
            plain_content += "© Renaissance Weekly\nFor those who remain intellectually ambitious in an age of distraction.\n"
            plain_content += "gistcapture.ai"
            
            # Create message with custom sender name
            message = Mail(
                from_email=(EMAIL_FROM, "Renaissance Weekly"),  # This sets the sender name
                to_emails=EMAIL_TO,
                subject="This Week in Ideas: AI, Health, Investing, Geopolitics, and More",
                plain_text_content=plain_content,
                html_content=html_with_preview
            )
            
            # Send email
            response = sendgrid_client.send(message)
            
            print(f"📬 Email Status: {response.status_code}")
            if response.status_code == 202:
                print("✅ Renaissance Weekly digest sent successfully!")
                print(f"📨 Message ID: {response.headers.get('X-Message-Id', 'N/A')}")
                return True
            else:
                print(f"⚠️ Unexpected status: {response.status_code}")
                return False
            
        except Exception as e:
            print(f"❌ Failed to send email: {e}")
            print(f"   Error details: {str(e)}")
            return False
    
    def run(self, days_back=7):
        """Main execution function"""
        print("🚀 Starting Renaissance Weekly System...")
        print(f"📧 Email delivery via: {EMAIL_FROM}")
        print(f"📬 Sending to: {EMAIL_TO}")
        print(f"📅 Looking for episodes from the last {days_back} days")
        
        # Fetch episodes
        print(f"\n📡 Fetching recent Tim Ferriss episodes...")
        episodes = self.fetch_tim_ferriss_episodes(days_back)
        
        if not episodes:
            print("❌ No recent episodes found.")
            print("💡 Try increasing days_back or check RSS feed")
            return
        
        print(f"\n📋 Found {len(episodes)} recent episode(s):")
        for i, ep in enumerate(episodes, 1):
            print(f"   {i}. {ep['title'][:60]}... ({ep['published']})")
        
        # Process episodes
        if len(episodes) == 1:
            # Single episode - process normally
            print("\n🎯 Processing single episode...")
            summaries = []
            summary = self.process_episode(episodes[0])
            if summary:
                titled_summary = f"# {episodes[0]['title']}\n\n{summary}"
                summaries.append(titled_summary)
        else:
            # Multiple episodes - use async processing
            print(f"\n⚡ Multiple episodes detected - using parallel processing...")
            summaries = asyncio.run(self.process_episodes_parallel(episodes))
        
        print(f"\n🎉 Processing Complete!")
        print(f"✅ Successfully processed: {len(summaries)}/{len(episodes)} episodes")
        
        # Send combined summary email
        if summaries:
            print("\n📧 Sending Renaissance Weekly digest...")
            # Only include episodes that were successfully processed
            successful_episodes = [ep for ep in episodes if any(ep['title'] in s for s in summaries)]
            if self.send_summary_email(summaries, successful_episodes):
                print("📧 Check your inbox for this week's Renaissance Weekly!")
            else:
                print("⚠️ Failed to send digest email")
        else:
            print("⚠️ No episodes were successfully processed")


def main():
    """Entry point"""
    try:
        print("🎯 Renaissance Weekly - Cross-Disciplinary Podcast Intelligence")
        print("=" * 60)
        
        renaissance = RenaissanceWeekly()
        renaissance.run(days_back=7)  # Look back 7 days
        
    except ValueError as e:
        print(f"❌ Configuration error: {e}")
        print("\n📝 Please ensure you have a .env file with:")
        print("OPENAI_API_KEY=your_openai_api_key")
        print("SENDGRID_API_KEY=your_sendgrid_api_key") 
        print("EMAIL_TO=your_email@domain.com  # Optional, defaults to caddington05@gmail.com")
        
    except KeyboardInterrupt:
        print("\n⚠️ Process interrupted by user")
        
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        import traceback
        print(f"Full traceback: {traceback.format_exc()}")


if __name__ == "__main__":
    main()