import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI()

def read_transcript(transcript_path):
    with open(transcript_path, "r", encoding="utf-8") as f:
        return f.read()

def summarize_transcript(transcript_path, episode_title, audio_url):
    transcript = read_transcript(transcript_path)

    prompt = f"""
You are a professional podcast summarizer. Please create a detailed 1-page summary of the following podcast episode transcript.

Episode Title: {episode_title}

Transcript:
\"\"\"
{transcript[:12000]}
\"\"\"

Requirements:
1. Provide key insights and guest commentary.
2. Include detailed discussion highlights as bullet points or short paragraphs.
3. At the end, add:
    - Sponsors mentioned during the episode
    - A line like: "To view the original source of this summarized media, visit: [audio_url]"

Output format:
Return clean markdown or plain text. Do not include anything outside the summary itself.
"""

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are a concise and insightful podcast summarizer."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7
    )

    return response.choices[0].message.content.strip()
