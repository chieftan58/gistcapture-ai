#!/bin/bash
# Comprehensive setup script for Renaissance Weekly
# Installs all system and Python dependencies

set -e  # Exit on error

echo "🚀 Renaissance Weekly Setup Script"
echo "================================="
echo ""

# Detect OS
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    OS="linux"
    DISTRO=$(lsb_release -si 2>/dev/null || echo "Unknown")
elif [[ "$OSTYPE" == "darwin"* ]]; then
    OS="macos"
else
    echo "❌ Unsupported OS: $OSTYPE"
    exit 1
fi

echo "📍 Detected OS: $OS ($DISTRO)"
echo ""

# Function to check if a command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Install system dependencies for Linux
install_linux_deps() {
    echo "📦 Installing system dependencies for Linux..."
    
    # Update package list
    sudo apt-get update
    
    # Core dependencies
    sudo apt-get install -y \
        ffmpeg \
        build-essential \
        python3-dev \
        python3-pip \
        python3-venv
    
    # Libraries for Python packages
    sudo apt-get install -y \
        libssl-dev \
        libffi-dev \
        libjpeg-dev \
        zlib1g-dev \
        libfreetype6-dev \
        libatlas-base-dev \
        gfortran \
        libopenblas-dev \
        libcurl4-openssl-dev \
        libbrotli-dev \
        libsecret-1-0
    
    # Additional media libraries
    sudo apt-get install -y \
        libavcodec-dev \
        libavformat-dev \
        libswscale-dev \
        libavutil-dev
    
    echo "✅ Linux system dependencies installed"
}

# Install system dependencies for macOS
install_macos_deps() {
    echo "📦 Installing system dependencies for macOS..."
    
    # Check if Homebrew is installed
    if ! command_exists brew; then
        echo "❌ Homebrew not found. Please install it first:"
        echo "   /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
        exit 1
    fi
    
    # Update Homebrew
    brew update
    
    # Install dependencies
    brew install \
        ffmpeg \
        openssl \
        libffi \
        jpeg \
        freetype \
        openblas \
        curl \
        brotli
    
    echo "✅ macOS system dependencies installed"
}

# Install system dependencies based on OS
echo "🔧 Step 1: Installing system dependencies"
echo "----------------------------------------"
if [[ "$OS" == "linux" ]]; then
    install_linux_deps
elif [[ "$OS" == "macos" ]]; then
    install_macos_deps
fi
echo ""

# Create virtual environment if it doesn't exist
echo "🐍 Step 2: Setting up Python environment"
echo "---------------------------------------"
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    echo "✅ Virtual environment created"
else
    echo "✅ Virtual environment already exists"
fi

# Activate virtual environment
source venv/bin/activate
echo "✅ Virtual environment activated"
echo ""

# Upgrade pip
echo "📦 Step 3: Upgrading pip"
echo "-----------------------"
pip install --upgrade pip setuptools wheel
echo "✅ pip upgraded"
echo ""

# Install Python dependencies
echo "📦 Step 4: Installing Python dependencies"
echo "----------------------------------------"
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
    echo "✅ Python dependencies installed"
else
    echo "❌ requirements.txt not found!"
    exit 1
fi
echo ""

# Install Playwright browsers
echo "🌐 Step 5: Installing Playwright browsers"
echo "----------------------------------------"
playwright install chromium
playwright install-deps
echo "✅ Playwright browsers installed"
echo ""

# Run the existing yt-dlp installation script
echo "📼 Step 6: Installing yt-dlp with full dependencies"
echo "--------------------------------------------------"
if [ -f "install_ytdlp_full.sh" ]; then
    chmod +x install_ytdlp_full.sh
    ./install_ytdlp_full.sh
else
    echo "⚠️  install_ytdlp_full.sh not found, skipping..."
fi
echo ""

# Create necessary directories
echo "📁 Step 7: Creating project directories"
echo "--------------------------------------"
mkdir -p transcripts audio summaries cache temp
echo "✅ Directories created"
echo ""

# Check for .env file
echo "🔐 Step 8: Checking configuration"
echo "---------------------------------"
if [ ! -f ".env" ]; then
    echo "⚠️  .env file not found!"
    echo "   Please create a .env file with the following keys:"
    echo ""
    echo "   # Required"
    echo "   OPENAI_API_KEY=your_key"
    echo "   SENDGRID_API_KEY=your_key"
    echo ""
    echo "   # Optional"
    echo "   OPENAI_MODEL=gpt-4o"
    echo "   OPENAI_TEMPERATURE=0.3"
    echo "   OPENAI_MAX_TOKENS=4000"
    echo ""
    echo "   # Enhanced Discovery APIs (optional)"
    echo "   YOUTUBE_API_KEY=your_key"
    echo "   SPOTIFY_CLIENT_ID=your_client_id"
    echo "   SPOTIFY_CLIENT_SECRET=your_client_secret"
    echo "   PODCASTINDEX_API_KEY=your_key"
    echo "   PODCASTINDEX_API_SECRET=your_secret"
    echo ""
    echo "   # Transcription Service APIs (optional)"
    echo "   ASSEMBLYAI_API_KEY=your_key"
    echo "   REVAI_API_KEY=your_key"
    echo "   DEEPGRAM_API_KEY=your_key"
else
    echo "✅ .env file found"
fi
echo ""

# Verify installations
echo "🔍 Step 9: Verifying installations"
echo "---------------------------------"
echo -n "Python version: "
python --version

echo -n "pip version: "
pip --version

echo -n "ffmpeg: "
if command_exists ffmpeg; then
    ffmpeg -version 2>&1 | head -n1
else
    echo "❌ NOT FOUND"
fi

echo -n "yt-dlp: "
if command_exists yt-dlp; then
    yt-dlp --version
else
    echo "❌ NOT FOUND"
fi

echo -n "playwright: "
python -c "import playwright; print('✅', playwright.__version__)" 2>/dev/null || echo "❌ NOT FOUND"

echo ""

# Final message
echo "✨ Setup Complete!"
echo "=================="
echo ""
echo "Next steps:"
echo "1. Ensure your .env file contains the required API keys"
echo "2. Run 'source venv/bin/activate' to activate the virtual environment"
echo "3. Run 'python main.py test' to verify the installation"
echo ""
echo "To process podcasts:"
echo "  python main.py [days]    # Process last N days of episodes"
echo ""
echo "Happy podcasting! 🎧"