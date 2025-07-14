#!/bin/bash

echo "YouTube Cookie Setup for Renaissance Weekly"
echo "==========================================="
echo ""
echo "This script will help you set up YouTube cookies that won't be overwritten."
echo ""

# Create directories if needed
mkdir -p ~/.config/renaissance-weekly/cookies

# Check if manual cookie file exists
if [ -f ~/.config/renaissance-weekly/cookies/youtube_manual_do_not_overwrite.txt ]; then
    echo "✅ Manual cookie file already exists!"
    echo "   Location: ~/.config/renaissance-weekly/cookies/youtube_manual_do_not_overwrite.txt"
    echo ""
    echo "To update it:"
else
    echo "To set up YouTube cookies:"
fi

echo ""
echo "1. Install a browser extension:"
echo "   - Firefox: 'cookies.txt' by Lennon Hill"
echo "   - Chrome: 'Get cookies.txt LOCALLY'"
echo ""
echo "2. Go to YouTube.com and make sure you're logged in"
echo ""
echo "3. Click the extension and export cookies"
echo ""
echo "4. Save the file as:"
echo "   ~/.config/renaissance-weekly/cookies/youtube_manual_do_not_overwrite.txt"
echo ""
echo "5. Run this command to protect it from being overwritten:"
echo "   chmod 444 ~/.config/renaissance-weekly/cookies/youtube_manual_do_not_overwrite.txt"
echo ""

# If old cookie file exists, offer to copy it
if [ -f ~/.config/renaissance-weekly/cookies/youtube_cookies.txt ]; then
    echo "Found existing cookie file. Do you want to copy it as your manual file? (y/n)"
    read -r response
    if [[ "$response" =~ ^[Yy]$ ]]; then
        cp ~/.config/renaissance-weekly/cookies/youtube_cookies.txt ~/.config/renaissance-weekly/cookies/youtube_manual_do_not_overwrite.txt
        chmod 444 ~/.config/renaissance-weekly/cookies/youtube_manual_do_not_overwrite.txt
        echo "✅ Copied and protected cookie file!"
    fi
fi

echo ""
echo "The system will now always use youtube_manual_do_not_overwrite.txt first."
echo "This file won't be overwritten by yt-dlp."