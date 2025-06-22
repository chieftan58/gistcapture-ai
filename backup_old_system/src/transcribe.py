import os
import hashlib
import tempfile
from pathlib import Path
from urllib.request import urlretrieve
from openai import OpenAI
from pydub import AudioSegment

# Initialize OpenAI client using environment variable
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

TRANSCRIPT_DIR = Path("transcripts")
AUDIO_DIR = Path("audio")
TRANSCRIPT_DIR.mkdir(exist_ok=True)
AUDIO_DIR.mkdir(exist_ok=True)

def slugify(text):
    return "".join(c if c.isalnum() or c in " ._-" else "_" for c in text)

def transcribe_podcast_audio(audio_url, title, limit_minutes=30):
    slug = slugify(title)
    hash_val = hashlib.md5(audio_url.encode()).hexdigest()[:6]
    audio_filename = AUDIO_DIR / f"{slug[:50]}_{hash_val}.mp3"
    transcript_filename = TRANSCRIPT_DIR / f"{slug[:50]}_{hash_val}.txt"

    if transcript_filename.exists():
        print(f"⏩ Transcript already exists at {transcript_filename}. Skipping transcription.")
        return transcript_filename

    print("🧠 Transcribing first 30 minutes with Whisper API...")

    if not audio_filename.exists():
        print("⬇️  Downloading audio...")
        tmp_file, _ = urlretrieve(audio_url)
        audio = AudioSegment.from_file(tmp_file)
        first_30_min = audio[:limit_minutes * 60 * 1000]
        first_30_min.export(audio_filename, format="mp3")
        os.remove(tmp_file)

    with open(audio_filename, "rb") as audio_file:
        transcript_response = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            response_format="text"
        )

    transcript_text = transcript_response.strip()
    with open(transcript_filename, "w", encoding="utf-8") as f:
        f.write(transcript_text)

    return transcript_filename
