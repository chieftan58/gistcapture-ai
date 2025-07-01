#!/bin/bash
# Install yt-dlp with all dependencies for maximum compatibility

echo "Installing yt-dlp with full dependencies for maximum reliability..."

# Update pip
pip install --upgrade pip

# Install yt-dlp with all optional dependencies
pip install --upgrade yt-dlp[default]

# Install additional dependencies for impersonation and browser support
pip install --upgrade \
    curl-cffi \
    websockets \
    brotli \
    certifi \
    mutagen \
    pycryptodomex \
    secretstorage

# Install browser cookie extraction dependencies
pip install --upgrade \
    browser-cookie3 \
    keyring

# Install dependencies for specific sites
pip install --upgrade \
    pycountry

# For better SSL/TLS handling
pip install --upgrade \
    pyOpenSSL \
    cryptography

# Install ffmpeg if not present (required for audio conversion)
if ! command -v ffmpeg &> /dev/null; then
    echo "Installing ffmpeg..."
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        sudo apt-get update && sudo apt-get install -y ffmpeg
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        brew install ffmpeg
    fi
fi

echo "yt-dlp installation complete!"
echo "Testing yt-dlp..."
yt-dlp --version

echo ""
echo "Available extractors:"
yt-dlp --list-extractors | grep -E "(podcast|substack|soundcloud|spotify)" | head -20

echo ""
echo "Browser cookie support:"
python -c "import browser_cookie3; print('✓ browser_cookie3 installed')"

echo ""
echo "All dependencies installed successfully!"