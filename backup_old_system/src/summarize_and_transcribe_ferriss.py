import os
from transcribe import transcribe_podcast_audio
from summarize import summarize_transcript
from send_email import send_email
from fetch_ferriss_content import fetch_tim_ferriss_content

SUMMARY_DIR = "summaries"
os.makedirs(SUMMARY_DIR, exist_ok=True)

def main():
    episodes = fetch_tim_ferriss_content(days_back=7)

    if not episodes:
        print("❌ No recent episodes found.")
        return

    for ep in episodes:
        print(f"\n🎧 Transcribing: {ep['title']}")
        transcript_path = transcribe_podcast_audio(ep["url"], ep["title"], limit_minutes=30)

        if not transcript_path:
            print("⚠️ Skipping episode due to failed transcription.")
            continue

        summary = summarize_transcript(transcript_path, episode_title=ep["title"], audio_url=ep["url"])

        # Save summary locally
        safe_title = ep["title"].replace(' ', '_').replace(':', '').replace('/', '_')
        summary_path = os.path.join(SUMMARY_DIR, f"{safe_title}.txt")
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(summary)
        print(f"✅ Summary saved to {summary_path}")

        # Send summary via email
        send_email(
            to_email="caddington05@gmail.com",
            subject=f"GistCapture Summary: {ep['title']}",
            plain_text=summary,
            html_content=summary.replace("\n", "<br>")
        )

if __name__ == "__main__":
    main()
