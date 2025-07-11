#!/bin/bash
# Quick start script to implement bulletproof downloads

echo "🚀 Renaissance Weekly - Bulletproof Download Implementation"
echo "=========================================================="
echo

# Step 1: Install Dependencies
echo "📦 Step 1: Installing dependencies..."
pip install playwright
playwright install chromium
pip install -U yt-dlp
echo "✅ Dependencies installed"
echo

# Step 2: Create directory structure
echo "📁 Step 2: Creating directory structure..."
mkdir -p renaissance_weekly/download_strategies
touch renaissance_weekly/download_strategies/__init__.py
echo "✅ Directory structure created"
echo

# Step 3: Test current state
echo "🔍 Step 3: Testing current download success..."
echo "This will show which podcasts are currently failing:"
echo

# Create a simple test to show current failures
cat > test_current_state.py << 'EOF'
import asyncio
from renaissance_weekly.database import PodcastDatabase
from renaissance_weekly.monitoring import monitor

db = PodcastDatabase()

# Get recent failure stats
print("Current Download Failure Analysis:")
print("-" * 50)

# Check monitoring data
failures = monitor.get_failure_summary()
for podcast, stats in failures.items():
    if stats.get('audio_download', {}).get('failure_count', 0) > 0:
        success_rate = stats['audio_download'].get('success_rate', 0)
        print(f"{podcast}: {success_rate:.0f}% success rate")

print("\nMost common failure reasons:")
reasons = monitor.get_failure_reasons('audio_download')
for reason, count in list(reasons.items())[:5]:
    print(f"- {reason}: {count} failures")
EOF

python test_current_state.py
rm test_current_state.py

echo
echo "📋 Step 4: Next Actions"
echo "====================="
echo
echo "1. Create strategy files:"
echo "   - Copy code from IMPLEMENTATION_STEPS.md sections 2.1-2.4"
echo "   - Save to renaissance_weekly/download_strategies/"
echo
echo "2. Update DownloadManager:"
echo "   - Edit renaissance_weekly/download_manager.py"
echo "   - Add SmartDownloadRouter integration (section 3.1)"
echo
echo "3. Test with problem podcasts:"
echo "   python test_bulletproof_downloads.py"
echo
echo "4. Run full system:"
echo "   python main.py 7"
echo
echo "Expected improvement: 60% → 85%+ success rate immediately!"
echo
echo "💡 The key insight: Stop fighting Cloudflare, use YouTube instead!"