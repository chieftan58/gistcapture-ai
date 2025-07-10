# Manual Download Instructions for American Optimist Episodes

Since YouTube authentication is failing, here are your options:

## Option 1: Manual Download with yt-dlp (Command Line)

If you have yt-dlp installed locally with working YouTube authentication:

```bash
# Episode 117 - Dave Rubin
yt-dlp -x --audio-format mp3 -o "american_optimist_ep117.mp3" https://www.youtube.com/watch?v=w1FRqBOxS8g

# Episode 116 - California Revolution
yt-dlp -x --audio-format mp3 -o "american_optimist_ep116.mp3" https://www.youtube.com/watch?v=TVg_DK8-kMw

# Episode 115 - Scott Wu
yt-dlp -x --audio-format mp3 -o "american_optimist_ep115.mp3" https://www.youtube.com/watch?v=YwmQzWGyrRQ
```

## Option 2: Online YouTube to MP3 Converters

Use any of these services:
- https://yt1s.com
- https://y2mate.com
- https://ytmp3.cc

YouTube URLs:
- Episode 117: https://www.youtube.com/watch?v=w1FRqBOxS8g
- Episode 116: https://www.youtube.com/watch?v=TVg_DK8-kMw  
- Episode 115: https://www.youtube.com/watch?v=YwmQzWGyrRQ

## Option 3: Browser Extensions

Install a YouTube downloader extension and download directly from YouTube.

## Using Downloaded Files in Renaissance Weekly

1. After downloading the MP3 files, note their location (e.g., `/home/user/downloads/american_optimist_ep117.mp3`)

2. In the Renaissance Weekly UI:
   - Click on the failed episode to expand details
   - Click "Manual URL"
   - Enter the full path to your downloaded MP3 file
   - The system will copy the file and continue processing

## Alternative: Skip These Episodes

If you prefer, you can proceed without these episodes. The system requires at least 1 successful download to continue, which you already have.

## Fix YouTube Authentication (For Future Runs)

To fix YouTube authentication for future runs:

1. Install a cookie export extension in your browser
2. Sign in to YouTube
3. Export cookies to: `~/.config/renaissance-weekly/cookies/youtube_cookies.txt`
4. Make sure the file is in Netscape cookie format

This will allow automatic YouTube downloads in future runs.