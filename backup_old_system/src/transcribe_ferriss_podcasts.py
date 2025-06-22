import os
from datetime import datetime, timedelta
from pathlib import Path
from fetch_ferriss_content import fetch_recent_ferriss_episodes
from transcribe import transcribe_podcast_audio
from summarize import summarize_transcript
from email_sender import send_email

TRANSCRIPT_DIR = Path("transcripts")
TRANSCRIPT_DIR.mkdir(exist_ok=True)

def episode_to_filename(title: str) -> str:
    return "".join(c if c.isalnum() or c in " _-" else "_" for c in title) + ".txt"

def main():
    print("📡 Fetching recent Tim Ferriss podcast episodes...")
    recent_eps = fetch_recent_ferriss_episodes(days_back=7)

    if not recent_eps:
        print("⚠️ No recent episodes found.")
        return

    print(f"✅ Found {len(recent_eps)} unique episode(s):\n")
    for i, ep in enumerate(recent_eps, 1):
        print(f"{i}. {ep['title']} ({ep['published']})\n   {ep['url']}\n")

    for i, ep in enumerate(recent_eps, 1):
        print(f"\n🎧 Transcribing episode {i}/{len(recent_eps)}: {ep['title']}")
        filename = episode_to_filename(ep['title'])
        filepath = TRANSCRIPT_DIR / filename

        if filepath.exists():
            print(f"📄 Transcript already exists: {filepath}")
        else:
            transcript_path = transcribe_podcast_audio(ep['url'], ep['title'], limit_minutes=30)
            if not transcript_path:
                print("❌ Transcription failed or empty.")
                continue
            filepath = Path(transcript_path)

        print("📚 Summarizing with GPT...")
        with open(filepath, "r", encoding="utf-8") as f:
            transcript_text = f.read()

        if not transcript_text.strip():
            print("❌ Empty transcript file. Skipping...")
            continue

        summary = summarize_transcript(transcript_text, ep['title'], ep['url'])

        print("\n📨 Summary:")
        print(summary)

        send_email(
            subject=f"GistCapture AI: {ep['title']}",
            html_content=summary
        )

if __name__ == "__main__":
    main()
