#!/bin/bash
# Fix YouTube download authentication issues

echo "🎥 Renaissance Weekly - YouTube Download Fix"
echo "=========================================="
echo

# Test if yt-dlp is installed
if ! command -v yt-dlp &> /dev/null; then
    echo "❌ yt-dlp not found. Installing..."
    pip install -U yt-dlp
fi

# Remove the malformed cookie file
COOKIE_FILE="$HOME/.config/renaissance-weekly/cookies/youtube_cookies.txt"
if [ -f "$COOKIE_FILE" ]; then
    echo "🗑️  Removing malformed cookie file..."
    rm "$COOKIE_FILE"
    echo "✅ Removed old cookie file"
fi

echo
echo "Testing browser authentication..."
python3 test_youtube_auth.py

echo
echo "Quick Test - American Optimist Episode 118 (Marc Andreessen):"
echo "============================================================="
echo

# Try to download a test clip
TEST_URL="https://www.youtube.com/watch?v=pRoKi4VL_5s"
OUTPUT="/tmp/test_american_optimist.mp3"

echo "Attempting download with available browsers..."
if yt-dlp --cookies-from-browser firefox -x --audio-format mp3 -o "$OUTPUT" "$TEST_URL" 2>/dev/null; then
    echo "✅ SUCCESS with Firefox! Download method confirmed working."
    rm -f "$OUTPUT"
elif yt-dlp --cookies-from-browser chrome -x --audio-format mp3 -o "$OUTPUT" "$TEST_URL" 2>/dev/null; then
    echo "✅ SUCCESS with Chrome! Download method confirmed working."
    rm -f "$OUTPUT"
else
    echo "❌ Automatic download failed. You'll need to:"
    echo
    echo "1. Sign into YouTube in Firefox or Chrome"
    echo "2. OR manually download episodes and use 'Manual URL' feature"
    echo
    echo "Manual download command:"
    echo "yt-dlp -x --audio-format mp3 -o 'episode.mp3' '$TEST_URL'"
fi

echo
echo "Ready to run Renaissance Weekly again!"