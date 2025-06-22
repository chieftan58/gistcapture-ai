# main.py - Renaissance Weekly Podcast Summary System
import os
import hashlib
import tempfile
import feedparser
from datetime import datetime, timedelta
from pathlib import Path
from urllib.request import urlretrieve
from urllib.parse import urlparse
from openai import OpenAI
from pydub import AudioSegment
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from dotenv import load_dotenv
import time
import re
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
        
        # Transcribe each chunk
        all_transcripts = []
        chunk_texts = []  # Store text with metadata for smart merging
        
        for chunk_info in chunks_info:
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
                    chunk_texts.append({
                        'text': transcript,
                        'start_min': chunk_info['start_min'],
                        'end_min': chunk_info['end_min'],
                        'num': chunk_info['num']
                    })
                    
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
        
        # Smart merging: detect and remove duplicates from overlaps
        merged_transcript = self._smart_merge_transcripts(chunk_texts)
        
        # Save merged transcript
        with open(transcript_filename, "w", encoding="utf-8") as f:
            f.write(merged_transcript)
        
        print(f"✅ Merged transcript saved: {len(merged_transcript)} characters")
        return transcript_filename
    
    def _detect_silence_breaks(self, audio, min_silence_len=1500, silence_thresh=-45):
        """TEMPORARY: Use fixed intervals instead of silence detection"""
        print("  📍 Using fixed 18-minute intervals (optimized for speed)")
        
        breaks = []
        duration_ms = len(audio)
        interval = 18 * 60 * 1000  # 18 minutes
        
        position = interval
        while position < duration_ms:
            breaks.append(position)
            position += interval
        
        return breaks
    
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
        """Generate comprehensive two-page summary in Renaissance Weekly style"""
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
            
            print(f"📚 Generating comprehensive summary with GPT-4...")
            print(f"   Transcript length: {len(transcript):,} characters")
            
            # Show progress for summarization too
            start_time = time.time()
            stop_event = threading.Event()
            progress_thread = threading.Thread(
                target=self.show_progress,
                args=(stop_event, start_time, "Generating summary")
            )
            progress_thread.start()
            
            try:
                # Enhanced prompt for Renaissance Weekly style
                prompt = f"""EPISODE: {episode_title}
DESCRIPTION: {episode_info.get('description', '')}

TRANSCRIPT:
{transcript}

You are the lead writer for Renaissance Weekly, a curated cross-disciplinary digest for intellectually ambitious professionals. Your task is to create a comprehensive two-page summary that captures the full substance and nuance of this podcast episode.

Note: This is a FULL episode transcript (2-3 hours). Focus on extracting the most compelling and actionable insights while maintaining the narrative arc of the entire conversation.

This is NOT a brief recap or bullet-point summary. Instead, craft a narrative-driven piece that:

1. **Preserves the arc of ideas** as they unfolded in conversation
2. **Maintains contextual insight and nuance** - don't oversimplify complex concepts
3. **Captures the intellectual texture** of the discussion, including digressions that prove illuminating
4. **Highlights connections** to broader themes in technology, science, investing, or culture
5. **Includes key quotes** that crystallize important insights (properly attributed)
6. **Identifies actionable frameworks or principles** the guest shares
7. **Notes any book recommendations, tools, or resources** mentioned

The writing should be:
- **Substantive**: Roughly 1,200-1,500 words (approximately 2 pages)
- **Narrative-driven**: Tell the story of the conversation, not just list facts
- **Intellectually rigorous**: Match the depth of the source material
- **Editorially polished**: Like The Atlantic or a premier Substack newsletter
- **Structured for clarity**: Use thoughtful section breaks and headers

Format with:
- A compelling opening that frames why this conversation matters
- Clear section headers that guide the reader through major themes
- Short paragraphs for readability
- A conclusion that synthesizes the key takeaways

Remember: Renaissance Weekly readers are polymathic professionals who toggle between AI research, investment analysis, health optimization, and geopolitics. Write for this sophisticated audience that values both time-efficiency AND intellectual depth."""

                response = openai_client.chat.completions.create(
                    model="gpt-4-turbo-preview",
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a world-class writer for Renaissance Weekly, crafting comprehensive yet accessible summaries of long-form podcast conversations for intellectually curious professionals. Your summaries preserve nuance while respecting readers' time."
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
                
                # Add episode metadata and links
                episode_footer = f"\n\n---\n\n**Episode Details**\n"
                episode_footer += f"- Published: {episode_info['published']}\n"
                episode_footer += f"- Original Length: 2+ hours\n"
                episode_footer += f"- Listen: [Apple Podcasts](https://podcasts.apple.com/us/podcast/the-tim-ferriss-show/id863897795) | "
                episode_footer += f"[Spotify](https://open.spotify.com/show/5qSUyCrk9KR69lEiXbjwXM) | "
                episode_footer += f"[YouTube](https://www.youtube.com/c/timferriss)"
                if episode_info.get('link'):
                    episode_footer += f" | [Episode Page]({episode_info['link']})"
                episode_footer += "\n"
                
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