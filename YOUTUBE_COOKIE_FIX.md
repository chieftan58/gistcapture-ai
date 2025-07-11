# YouTube Cookie Authentication Fix

## The Problem
Your current cookie file is not in the standard Netscape format that yt-dlp expects. It appears to be exported from browser DevTools or a non-standard extension.

## Quick Solution: Use Browser Cookies Directly

Instead of using a cookie file, let yt-dlp access your browser cookies directly:

```bash
# Test if Firefox cookies work
yt-dlp --cookies-from-browser firefox "https://www.youtube.com/watch?v=pRoKi4VL_5s" --simulate

# Test if Chrome cookies work  
yt-dlp --cookies-from-browser chrome "https://www.youtube.com/watch?v=pRoKi4VL_5s" --simulate
```

## Option 2: Export Proper Cookie File

### For Firefox:
1. Install "cookies.txt" extension by Lennon Hill
   - https://addons.mozilla.org/en-US/firefox/addon/cookies-txt/
2. Visit https://www.youtube.com and ensure you're logged in
3. Click the extension icon
4. Select "Current Site" 
5. Save as: `~/.config/renaissance-weekly/cookies/youtube_cookies.txt`

### For Chrome:
1. Install "Get cookies.txt LOCALLY" extension
   - https://chrome.google.com/webstore/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc
2. Visit https://www.youtube.com and ensure you're logged in
3. Click the extension icon
4. Click "Export"
5. Save as: `~/.config/renaissance-weekly/cookies/youtube_cookies.txt`

## Option 3: Manual Download Workaround

Since you already have the YouTube URLs for American Optimist episodes, you can:

1. Download manually using yt-dlp with browser cookies:
```bash
cd /tmp
yt-dlp --cookies-from-browser firefox -x --audio-format mp3 \
  -o "american_optimist_ep118.mp3" \
  "https://www.youtube.com/watch?v=pRoKi4VL_5s"
```

2. In the UI, click "Manual URL" and provide the local file path:
```
/tmp/american_optimist_ep118.mp3
```

## Verify Cookie File Format

A properly formatted cookies.txt file should look like this:
```
# Netscape HTTP Cookie File
.youtube.com	TRUE	/	TRUE	2147483647	VISITOR_INFO1_LIVE	abcdef123456
.youtube.com	TRUE	/	TRUE	2147483647	PREF	f5=30000
.youtube.com	TRUE	/	TRUE	2147483647	YSC	xyz789
```

Each line has exactly 7 tab-separated fields:
1. Domain
2. Include subdomains (TRUE/FALSE)  
3. Path
4. Secure (TRUE/FALSE)
5. Expiration timestamp
6. Name
7. Value

Your current file has extra fields and special characters that break this format.

## Recommended Action

Use Option 1 (browser cookies directly) - it's the most reliable:

1. Update the code to use `--cookies-from-browser firefox` instead of cookie files
2. Or manually download with the command above and use local file paths