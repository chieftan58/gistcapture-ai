"""Episode selection UI"""

import json
import webbrowser
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from typing import List
from html import escape

from ..models import Episode
from ..config import PODCAST_CONFIGS
from ..utils.logging import get_logger

logger = get_logger(__name__)


class EpisodeSelector:
    """Handle episode selection UI"""
    
    def run_selection_server(self, episodes: List[Episode]) -> List[Episode]:
        """Run a temporary web server for episode selection"""
        selected_episodes = []
        server_running = True
        parent_instance = self
        
        class SelectionHandler(SimpleHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/':
                    self.send_response(200)
                    self.send_header('Content-type', 'text/html')
                    self.end_headers()
                    html = parent_instance.create_selection_html(episodes)
                    self.wfile.write(html.encode())
                else:
                    self.send_error(404)
            
            def do_POST(self):
                if self.path == '/select':
                    content_length = int(self.headers['Content-Length'])
                    post_data = self.rfile.read(content_length)
                    data = json.loads(post_data.decode('utf-8'))
                    
                    for idx in data['selected']:
                        selected_episodes.append(episodes[idx])
                    
                    self.send_response(200)
                    self.end_headers()
                    
                    nonlocal server_running
                    server_running = False
            
            def log_message(self, format, *args):
                pass  # Suppress logs
        
        # Find available port
        port = 8888
        server = None
        
        for attempt in range(5):
            try:
                server = HTTPServer(('localhost', port), SelectionHandler)
                break
            except OSError:
                port += 1
                if attempt == 4:
                    logger.error("Could not start web server")
                    return self._fallback_text_selection(episodes)
        
        if not server:
            return self._fallback_text_selection(episodes)
        
        # Open browser
        url = f'http://localhost:{port}'
        logger.info(f"🌐 Opening episode selection at {url}")
        
        try:
            webbrowser.open(url)
        except:
            logger.warning(f"Please open: {url}")
        
        # Run server
        logger.info("⏳ Waiting for episode selection...")
        
        try:
            while server_running:
                server.handle_request()
        except KeyboardInterrupt:
            logger.warning("Selection cancelled")
            selected_episodes = []
        finally:
            server.server_close()
        
        return selected_episodes
    
    def create_selection_html(self, episodes: List[Episode]) -> str:
        """Create an HTML page for episode selection with full descriptions"""
        import re
        from datetime import datetime
        
        # Create podcast description lookup
        podcast_descriptions = {}
        for config in PODCAST_CONFIGS:
            podcast_descriptions[config["name"]] = config.get("description", "")
        
        html = self._get_html_header()
        
        # Group episodes by podcast
        by_podcast = {}
        for i, ep in enumerate(episodes):
            try:
                if isinstance(ep, Episode):
                    podcast = ep.podcast
                    title = ep.title
                    published = ep.published.strftime('%Y-%m-%d')
                    duration = ep.duration
                    has_transcript = ep.transcript_url is not None
                    description = ep.description
                else:
                    podcast = ep.get('podcast', 'Unknown')
                    title = ep.get('title', 'Unknown')
                    published = ep.get('published', 'Unknown')
                    if isinstance(published, datetime):
                        published = published.strftime('%Y-%m-%d')
                    duration = ep.get('duration', 'Unknown')
                    has_transcript = ep.get('transcript_url') is not None
                    description = ep.get('description', '')
                
                if podcast not in by_podcast:
                    by_podcast[podcast] = []
                
                # Process description to get first two sentences
                if description:
                    # Clean HTML/Markdown first
                    clean_desc = re.sub(r'<[^>]+>', '', description)  # Remove HTML tags
                    clean_desc = re.sub(r'\*{1,2}([^\*]+)\*{1,2}', r'\1', clean_desc)  # Remove markdown bold/italic
                    clean_desc = clean_desc.strip()
                    
                    # Split into sentences and take first two
                    sentences = re.split(r'(?<=[.!?])\s+', clean_desc)
                    if len(sentences) >= 2:
                        display_desc = ' '.join(sentences[:2])
                        # Ensure it ends with punctuation
                        if display_desc and display_desc[-1] not in '.!?':
                            display_desc += '.'
                    else:
                        display_desc = clean_desc
                        if display_desc and display_desc[-1] not in '.!?':
                            display_desc += '.'
                else:
                    display_desc = "No description available for this episode. Click to select for processing."
                
                # Format duration for display
                if isinstance(duration, str) and duration.isdigit():
                    seconds = int(duration)
                    hours = seconds // 3600
                    minutes = (seconds % 3600) // 60
                    if hours > 0:
                        duration_display = f"{hours} hour{'s' if hours > 1 else ''}, {minutes} minute{'s' if minutes != 1 else ''}"
                    else:
                        duration_display = f"{minutes} minute{'s' if minutes != 1 else ''}"
                else:
                    duration_display = duration
                
                by_podcast[podcast].append({
                    'index': i,
                    'title': title,
                    'published': published,
                    'duration': duration_display,
                    'has_transcript': has_transcript,
                    'description': display_desc
                })
            except Exception as e:
                logger.error(f"Error processing episode {i}: {e}")
                continue
        
        # Create HTML for each podcast group
        for podcast, podcast_episodes in by_podcast.items():
            podcast_desc = podcast_descriptions.get(podcast, "")
            
            html += f'<div class="podcast-group">\n'
            html += f'<div class="podcast-header">\n'
            html += f'<div class="podcast-title">{escape(podcast)}</div>\n'
            if podcast_desc:
                html += f'<div class="podcast-description">— {escape(podcast_desc)}</div>\n'
            html += f'</div>\n'
            
            for ep_data in podcast_episodes:
                transcript_badge = '<span class="transcript-badge">TRANSCRIPT</span>' if ep_data['has_transcript'] else ''
                
                html += f'''<div class="episode" id="episode-{ep_data['index']}" onclick="toggleEpisode({ep_data['index']})">
    <div class="episode-header">
        <input type="checkbox" id="cb-{ep_data['index']}" value="{ep_data['index']}" onclick="event.stopPropagation();" onchange="updateSelection()">
        <div class="episode-content">
            <div class="episode-title">{escape(ep_data['title'])}{transcript_badge}</div>
            <div class="episode-meta">📅 {escape(str(ep_data['published']))} | ⏱️ {escape(str(ep_data['duration']))}</div>
            <div class="episode-description">{escape(ep_data['description'])}</div>
        </div>
    </div>
</div>\n'''
            
            html += '</div>\n'
        
        html += self._get_html_footer()
        
        return html
    
    def _get_html_header(self) -> str:
        """Get HTML header with styles and scripts"""
        return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Renaissance Weekly - Episode Selection</title>
    <style>
        * { box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
            color: #333;
        }
        h1 { 
            color: #333; 
            margin-bottom: 10px;
            font-size: 36px;
        }
        .subtitle { 
            color: #666; 
            margin-bottom: 30px; 
            font-size: 18px; 
        }
        .podcast-group {
            background: white;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .podcast-header {
            display: flex;
            align-items: baseline;
            gap: 15px;
            margin-bottom: 15px;
            border-bottom: 2px solid #e0e0e0;
            padding-bottom: 10px;
        }
        .podcast-title {
            font-size: 20px;
            font-weight: 600;
            color: #2c3e50;
        }
        .podcast-description {
            font-size: 14px;
            color: #666;
            font-style: italic;
        }
        .episode {
            padding: 15px;
            margin-bottom: 10px;
            border: 1px solid #e0e0e0;
            border-radius: 6px;
            transition: all 0.2s ease;
            cursor: pointer;
        }
        .episode:hover { 
            background-color: #f8f9fa; 
            border-color: #4a90e2; 
        }
        .episode.selected { 
            background-color: #e3f2fd; 
            border-color: #2196f3; 
        }
        .episode-header { 
            display: flex; 
            align-items: flex-start; 
            gap: 15px; 
        }
        input[type="checkbox"] { 
            width: 20px; 
            height: 20px; 
            margin-top: 2px; 
            cursor: pointer;
            flex-shrink: 0;
        }
        .episode-content { 
            flex: 1;
            min-width: 0; /* Allow text to wrap */
        }
        .episode-title { 
            font-weight: 500; 
            color: #333; 
            margin-bottom: 5px; 
            font-size: 16px;
            word-wrap: break-word;
        }
        .episode-meta { 
            font-size: 14px; 
            color: #666; 
            margin-bottom: 8px; 
        }
        .episode-description { 
            font-size: 14px; 
            color: #555; 
            line-height: 1.6;
            word-wrap: break-word;
        }
        .transcript-badge {
            display: inline-block;
            padding: 2px 8px;
            background: #4CAF50;
            color: white;
            font-size: 12px;
            border-radius: 4px;
            margin-left: 10px;
            font-weight: normal;
        }
        .controls {
            position: sticky;
            top: 20px;
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            margin-bottom: 30px;
            z-index: 100;
        }
        .button {
            padding: 12px 24px;
            margin: 5px;
            border: none;
            border-radius: 6px;
            font-size: 16px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s ease;
        }
        .button:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        .button-primary { 
            background-color: #4a90e2; 
            color: white; 
        }
        .button-primary:hover:not(:disabled) { 
            background-color: #357abd; 
        }
        .button-secondary { 
            background-color: #6c757d; 
            color: white; 
        }
        .button-secondary:hover:not(:disabled) { 
            background-color: #545b62; 
        }
        .selection-count { 
            font-size: 16px; 
            color: #666; 
            margin-left: 20px; 
        }
        .loading {
            display: none;
            text-align: center;
            padding: 40px;
            font-size: 18px;
            color: #666;
        }
        .error-message {
            color: #d32f2f;
            padding: 10px;
            margin: 10px 0;
            background: #ffebee;
            border-radius: 4px;
            display: none;
        }
        @media (max-width: 768px) {
            body { padding: 10px; }
            h1 { font-size: 28px; }
            .controls { position: static; }
            .button { 
                display: block; 
                width: 100%; 
                margin: 5px 0; 
            }
            .podcast-header {
                flex-direction: column;
                gap: 5px;
            }
        }
    </style>
</head>
<body>
    <h1>🎙️ Renaissance Weekly</h1>
    <p class="subtitle">Select episodes to process for this week's digest</p>
    
    <div class="controls">
        <button class="button button-primary" onclick="processSelected()">Process Selected Episodes</button>
        <button class="button button-secondary" onclick="selectAll()">Select All</button>
        <button class="button button-secondary" onclick="selectNone()">Clear All</button>
        <span class="selection-count">0 episodes selected</span>
    </div>
    
    <div class="error-message" id="error-message"></div>
    
    <div class="loading" id="loading">
        Processing your selection... This window will close automatically.
    </div>
    
    <div id="episodes">
"""
    
    def _get_html_footer(self) -> str:
        """Get HTML footer with scripts"""
        return """
    </div>
    
    <script>
        function toggleEpisode(index) {
            const checkbox = document.getElementById('cb-' + index);
            checkbox.checked = !checkbox.checked;
            updateSelection();
        }
        
        function updateSelection() {
            const checkboxes = document.querySelectorAll('input[type="checkbox"]');
            let count = 0;
            checkboxes.forEach(cb => {
                const episode = document.getElementById('episode-' + cb.value);
                if (cb.checked) {
                    count++;
                    episode.classList.add('selected');
                } else {
                    episode.classList.remove('selected');
                }
            });
            document.querySelector('.selection-count').textContent = count + ' episode' + (count !== 1 ? 's' : '') + ' selected';
        }
        
        function selectAll() {
            document.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = true);
            updateSelection();
        }
        
        function selectNone() {
            document.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = false);
            updateSelection();
        }
        
        function showError(message) {
            const errorDiv = document.getElementById('error-message');
            errorDiv.textContent = message;
            errorDiv.style.display = 'block';
            setTimeout(() => {
                errorDiv.style.display = 'none';
            }, 5000);
        }
        
        function processSelected() {
            const selected = [];
            document.querySelectorAll('input[type="checkbox"]:checked').forEach(cb => {
                selected.push(parseInt(cb.value));
            });
            
            if (selected.length === 0) {
                showError('Please select at least one episode to process.');
                return;
            }
            
            // Disable all buttons
            document.querySelectorAll('.button').forEach(btn => btn.disabled = true);
            
            document.getElementById('loading').style.display = 'block';
            document.getElementById('episodes').style.display = 'none';
            document.querySelector('.controls').style.display = 'none';
            
            fetch('/select', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({selected: selected})
            })
            .then(response => {
                if (!response.ok) {
                    throw new Error('Server error');
                }
                setTimeout(() => window.close(), 1000);
            })
            .catch(error => {
                document.getElementById('loading').style.display = 'none';
                document.getElementById('episodes').style.display = 'block';
                document.querySelector('.controls').style.display = 'block';
                document.querySelectorAll('.button').forEach(btn => btn.disabled = false);
                showError('Failed to process selection. Please try again.');
            });
        }
        
        // Initialize on load
        document.addEventListener('DOMContentLoaded', function() {
            updateSelection();
        });
    </script>
</body>
</html>
"""
    
    def _fallback_text_selection(self, episodes: List[Episode]) -> List[Episode]:
        """Text-based fallback selection method"""
        print("\n" + "="*80)
        print("📻 RECENT PODCAST EPISODES (Text Selection)")
        print("="*80)
        
        episode_map = {}
        for i, ep in enumerate(episodes):
            if isinstance(ep, Episode):
                print(f"\n[{i+1}] {ep.podcast}: {ep.title}")
                print(f"    📅 {ep.published.strftime('%Y-%m-%d')} | ⏱️  {ep.duration}")
                if ep.transcript_url:
                    print(f"    ✅ Transcript available")
            else:
                print(f"\n[{i+1}] {ep['podcast']}: {ep['title']}")
                print(f"    📅 {ep['published']} | ⏱️  {ep['duration']}")
            episode_map[i+1] = ep
        
        print("\n" + "="*80)
        print("Enter episode numbers separated by commas (e.g., 1,3,5)")
        print("Or type 'all' for all episodes, 'none' to exit")
        
        while True:
            selection = input("\n🎯 Your selection: ").strip().lower()
            
            if selection == 'none':
                return []
            
            if selection == 'all':
                return episodes
            
            try:
                if not selection:
                    print("❌ Please enter episode numbers or 'all'/'none'")
                    continue
                
                selected_indices = [int(x.strip()) for x in selection.split(',') if x.strip()]
                
                invalid = [i for i in selected_indices if i not in episode_map]
                if invalid:
                    print(f"❌ Invalid episode numbers: {invalid}")
                    continue
                
                selected_episodes = [episode_map[i] for i in selected_indices]
                
                print(f"\n✅ Selected {len(selected_episodes)} episode(s)")
                return selected_episodes
                
            except ValueError:
                print("❌ Invalid input. Please enter numbers separated by commas.")