"""Episode selection UI with Apple-quality design"""

import json
import webbrowser
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from typing import List, Set
from html import escape
from datetime import datetime

from ..models import Episode
from ..config import PODCAST_CONFIGS
from ..utils.logging import get_logger

logger = get_logger(__name__)


class EpisodeSelector:
    """Handle episode selection UI with Apple-quality design"""
    
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
        """Create an Apple-quality HTML page for episode selection"""
        import re
        
        # Create podcast description lookup
        podcast_descriptions = {}
        configured_podcasts = set()
        for config in PODCAST_CONFIGS:
            podcast_descriptions[config["name"]] = config.get("description", "")
            configured_podcasts.add(config["name"])
        
        # Group episodes by podcast
        by_podcast = {}
        podcasts_with_episodes = set()
        
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
                
                podcasts_with_episodes.add(podcast)
                
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
                    display_desc = "No description available for this episode."
                
                # Format duration for display
                if isinstance(duration, str) and duration.isdigit():
                    seconds = int(duration)
                    hours = seconds // 3600
                    minutes = (seconds % 3600) // 60
                    if hours > 0:
                        duration_display = f"{hours}h {minutes}m"
                    else:
                        duration_display = f"{minutes}m"
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
        
        # Find podcasts with zero episodes
        zero_episode_podcasts = sorted(configured_podcasts - podcasts_with_episodes)
        
        # Sort podcasts alphabetically
        sorted_podcasts = sorted(by_podcast.keys())
        
        # Build HTML
        html = self._get_html_header(len(episodes), len(zero_episode_podcasts))
        
        # Add zero episodes section if there are any
        if zero_episode_podcasts:
            html += self._create_zero_episodes_section(zero_episode_podcasts)
        
        # Create HTML for each podcast group (alphabetically)
        for podcast in sorted_podcasts:
            podcast_episodes = by_podcast[podcast]
            podcast_desc = podcast_descriptions.get(podcast, "")
            
            html += f'''
<div class="podcast-section" data-podcast="{escape(podcast)}">
    <div class="podcast-header">
        <div class="podcast-info">
            <h3 class="podcast-title">{escape(podcast)}</h3>
            {f'<p class="podcast-description">{escape(podcast_desc)}</p>' if podcast_desc else ''}
        </div>
        <div class="episode-count">{len(podcast_episodes)} episode{'s' if len(podcast_episodes) != 1 else ''}</div>
    </div>
    <div class="episodes-container">
'''
            
            for ep_data in podcast_episodes:
                transcript_badge = '<span class="badge badge-transcript">Transcript</span>' if ep_data['has_transcript'] else ''
                
                html += f'''
        <div class="episode" id="episode-{ep_data['index']}" onclick="toggleEpisode({ep_data['index']})">
            <div class="episode-checkbox">
                <input type="checkbox" id="cb-{ep_data['index']}" value="{ep_data['index']}" 
                       onclick="event.stopPropagation();" onchange="updateSelection()">
            </div>
            <div class="episode-content">
                <div class="episode-header-row">
                    <h4 class="episode-title">{escape(ep_data['title'])}</h4>
                    {transcript_badge}
                </div>
                <div class="episode-meta">
                    <span class="meta-item">📅 {escape(str(ep_data['published']))}</span>
                    <span class="meta-separator">•</span>
                    <span class="meta-item">⏱ {escape(str(ep_data['duration']))}</span>
                </div>
                <p class="episode-description">{escape(ep_data['description'])}</p>
            </div>
        </div>
'''
            
            html += '''
    </div>
</div>
'''
        
        html += self._get_html_footer()
        
        return html
    
    def _create_zero_episodes_section(self, zero_podcasts: List[str]) -> str:
        """Create the zero episodes warning section"""
        return f'''
<div class="zero-episodes-section">
    <div class="zero-header">
        <svg class="warning-icon" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
            <line x1="12" y1="9" x2="12" y2="13"></line>
            <line x1="12" y1="17" x2="12.01" y2="17"></line>
        </svg>
        <h2>Podcasts with No Recent Episodes</h2>
        <span class="zero-count">{len(zero_podcasts)} podcast{'s' if len(zero_podcasts) != 1 else ''}</span>
    </div>
    <p class="zero-description">The following podcasts have no episodes in the selected time period. Check if they're still active or adjust your date range.</p>
    <div class="zero-grid">
        {''.join(f'<div class="zero-item">{escape(podcast)}</div>' for podcast in zero_podcasts)}
    </div>
</div>
'''
    
    def _get_html_header(self, total_episodes: int, zero_count: int) -> str:
        """Get HTML header with Apple-quality styles"""
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Renaissance Weekly - Episode Selection</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        :root {{
            --primary: #007AFF;
            --primary-hover: #0051D5;
            --secondary: #5856D6;
            --success: #34C759;
            --warning: #FF9500;
            --danger: #FF3B30;
            --background: #F2F2F7;
            --surface: #FFFFFF;
            --surface-secondary: #F9F9F9;
            --text-primary: #000000;
            --text-secondary: #3C3C43;
            --text-tertiary: #C7C7CC;
            --border: #E5E5EA;
            --border-selected: #007AFF;
            --shadow-sm: 0 1px 3px rgba(0, 0, 0, 0.06);
            --shadow-md: 0 4px 6px rgba(0, 0, 0, 0.07);
            --shadow-lg: 0 10px 15px rgba(0, 0, 0, 0.1);
            --transition: all 0.2s ease;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Helvetica Neue", Helvetica, Arial, sans-serif;
            background: var(--background);
            color: var(--text-primary);
            line-height: 1.5;
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
        }}
        
        .app-header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 60px 20px 40px;
            text-align: center;
            position: relative;
            overflow: hidden;
        }}
        
        .app-header::before {{
            content: '';
            position: absolute;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: radial-gradient(circle, rgba(255,255,255,0.1) 0%, transparent 70%);
            animation: pulse 20s ease-in-out infinite;
        }}
        
        @keyframes pulse {{
            0%, 100% {{ transform: scale(1); opacity: 0.3; }}
            50% {{ transform: scale(1.1); opacity: 0.5; }}
        }}
        
        .app-header h1 {{
            font-size: 48px;
            font-weight: 700;
            letter-spacing: -0.5px;
            margin-bottom: 10px;
            position: relative;
            z-index: 1;
        }}
        
        .app-header p {{
            font-size: 20px;
            opacity: 0.95;
            font-weight: 400;
            position: relative;
            z-index: 1;
        }}
        
        .stats-container {{
            display: flex;
            gap: 20px;
            justify-content: center;
            margin-top: 30px;
            position: relative;
            z-index: 1;
        }}
        
        .stat-card {{
            background: rgba(255, 255, 255, 0.2);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.3);
            padding: 15px 30px;
            border-radius: 16px;
            text-align: center;
        }}
        
        .stat-value {{
            font-size: 32px;
            font-weight: 700;
            display: block;
        }}
        
        .stat-label {{
            font-size: 14px;
            opacity: 0.9;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }}
        
        .controls {{
            position: sticky;
            top: 20px;
            background: var(--surface);
            padding: 20px 24px;
            border-radius: 16px;
            box-shadow: var(--shadow-md);
            margin: -40px 0 40px;
            z-index: 100;
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 20px;
            border: 1px solid var(--border);
        }}
        
        .control-group {{
            display: flex;
            gap: 10px;
            align-items: center;
        }}
        
        .button {{
            padding: 10px 20px;
            border: none;
            border-radius: 10px;
            font-size: 15px;
            font-weight: 600;
            cursor: pointer;
            transition: var(--transition);
            display: inline-flex;
            align-items: center;
            gap: 8px;
            text-decoration: none;
            outline: none;
        }}
        
        .button:active {{
            transform: scale(0.98);
        }}
        
        .button:focus-visible {{
            box-shadow: 0 0 0 4px rgba(0, 122, 255, 0.3);
        }}
        
        .button-primary {{
            background: var(--primary);
            color: white;
        }}
        
        .button-primary:hover:not(:disabled) {{
            background: var(--primary-hover);
            box-shadow: var(--shadow-md);
        }}
        
        .button-secondary {{
            background: var(--surface-secondary);
            color: var(--text-primary);
            border: 1px solid var(--border);
        }}
        
        .button-secondary:hover:not(:disabled) {{
            background: var(--background);
            border-color: var(--text-tertiary);
        }}
        
        .button:disabled {{
            opacity: 0.5;
            cursor: not-allowed;
        }}
        
        .selection-info {{
            font-size: 16px;
            color: var(--text-secondary);
            font-weight: 500;
        }}
        
        .selection-count {{
            color: var(--primary);
            font-weight: 700;
        }}
        
        .zero-episodes-section {{
            background: var(--surface);
            border-radius: 16px;
            padding: 24px;
            margin-bottom: 40px;
            border: 1px solid var(--warning);
            box-shadow: var(--shadow-sm);
        }}
        
        .zero-header {{
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 12px;
        }}
        
        .warning-icon {{
            color: var(--warning);
            flex-shrink: 0;
        }}
        
        .zero-header h2 {{
            font-size: 20px;
            font-weight: 600;
            color: var(--text-primary);
            flex: 1;
        }}
        
        .zero-count {{
            background: var(--warning);
            color: white;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 14px;
            font-weight: 600;
        }}
        
        .zero-description {{
            color: var(--text-secondary);
            margin-bottom: 20px;
            line-height: 1.6;
        }}
        
        .zero-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
            gap: 10px;
        }}
        
        .zero-item {{
            background: var(--surface-secondary);
            padding: 12px 16px;
            border-radius: 10px;
            font-weight: 500;
            color: var(--text-secondary);
            border: 1px solid var(--border);
            font-size: 14px;
        }}
        
        .podcast-section {{
            background: var(--surface);
            border-radius: 16px;
            margin-bottom: 20px;
            overflow: hidden;
            box-shadow: var(--shadow-sm);
            border: 1px solid var(--border);
            transition: var(--transition);
        }}
        
        .podcast-section:hover {{
            box-shadow: var(--shadow-md);
        }}
        
        .podcast-header {{
            padding: 20px 24px;
            border-bottom: 1px solid var(--border);
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: var(--surface-secondary);
        }}
        
        .podcast-info {{
            flex: 1;
        }}
        
        .podcast-title {{
            font-size: 22px;
            font-weight: 600;
            color: var(--text-primary);
            margin-bottom: 4px;
        }}
        
        .podcast-description {{
            font-size: 14px;
            color: var(--text-secondary);
            line-height: 1.5;
        }}
        
        .episode-count {{
            background: var(--primary);
            color: white;
            padding: 6px 16px;
            border-radius: 20px;
            font-size: 14px;
            font-weight: 600;
            white-space: nowrap;
        }}
        
        .episodes-container {{
            padding: 8px;
        }}
        
        .episode {{
            padding: 16px;
            margin: 8px;
            border: 1px solid var(--border);
            border-radius: 12px;
            transition: var(--transition);
            cursor: pointer;
            display: flex;
            gap: 16px;
            background: var(--surface);
        }}
        
        .episode:hover {{
            background: var(--surface-secondary);
            border-color: var(--primary);
            transform: translateY(-1px);
            box-shadow: var(--shadow-sm);
        }}
        
        .episode.selected {{
            background: #E3F2FD;
            border-color: var(--primary);
            box-shadow: 0 0 0 3px rgba(0, 122, 255, 0.1);
        }}
        
        .episode-checkbox {{
            padding-top: 2px;
        }}
        
        .episode-checkbox input[type="checkbox"] {{
            width: 20px;
            height: 20px;
            cursor: pointer;
            accent-color: var(--primary);
        }}
        
        .episode-content {{
            flex: 1;
            min-width: 0;
        }}
        
        .episode-header-row {{
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 8px;
        }}
        
        .episode-title {{
            font-size: 16px;
            font-weight: 600;
            color: var(--text-primary);
            line-height: 1.4;
            flex: 1;
        }}
        
        .badge {{
            padding: 3px 10px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            white-space: nowrap;
        }}
        
        .badge-transcript {{
            background: var(--success);
            color: white;
        }}
        
        .episode-meta {{
            font-size: 14px;
            color: var(--text-secondary);
            margin-bottom: 8px;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        
        .meta-separator {{
            color: var(--text-tertiary);
        }}
        
        .episode-description {{
            font-size: 14px;
            color: var(--text-secondary);
            line-height: 1.6;
        }}
        
        .loading {{
            display: none;
            text-align: center;
            padding: 60px;
            font-size: 18px;
            color: var(--text-secondary);
        }}
        
        .loading-spinner {{
            width: 48px;
            height: 48px;
            border: 3px solid var(--border);
            border-top-color: var(--primary);
            border-radius: 50%;
            margin: 0 auto 20px;
            animation: spin 1s linear infinite;
        }}
        
        @keyframes spin {{
            to {{ transform: rotate(360deg); }}
        }}
        
        .error-message {{
            color: var(--danger);
            padding: 16px;
            margin: 20px 0;
            background: #FFF3F3;
            border: 1px solid #FFD6D6;
            border-radius: 12px;
            display: none;
            font-weight: 500;
        }}
        
        @media (max-width: 768px) {{
            .app-header h1 {{
                font-size: 36px;
            }}
            
            .app-header p {{
                font-size: 18px;
            }}
            
            .stats-container {{
                flex-direction: column;
                gap: 10px;
            }}
            
            .controls {{
                flex-direction: column;
                position: static;
                margin: 20px 0;
            }}
            
            .control-group {{
                width: 100%;
                justify-content: center;
            }}
            
            .button {{
                flex: 1;
            }}
            
            .zero-grid {{
                grid-template-columns: 1fr;
            }}
            
            .podcast-header {{
                flex-direction: column;
                align-items: flex-start;
                gap: 10px;
            }}
        }}
    </style>
</head>
<body>
    <div class="app-header">
        <h1>🎙 Renaissance Weekly</h1>
        <p>Curate your weekly podcast intelligence digest</p>
        <div class="stats-container">
            <div class="stat-card">
                <span class="stat-value">{total_episodes}</span>
                <span class="stat-label">Episodes Found</span>
            </div>
            {f'''<div class="stat-card">
                <span class="stat-value">{zero_count}</span>
                <span class="stat-label">Empty Podcasts</span>
            </div>''' if zero_count > 0 else ''}
        </div>
    </div>
    
    <div class="container">
        <div class="controls">
            <div class="control-group">
                <button class="button button-primary" onclick="processSelected()">
                    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="4 8 7 11 12 5"></polyline>
                    </svg>
                    Process Selected
                </button>
                <button class="button button-secondary" onclick="selectAll()">Select All</button>
                <button class="button button-secondary" onclick="selectNone()">Clear</button>
            </div>
            <div class="selection-info">
                <span class="selection-count">0</span> episodes selected
            </div>
        </div>
        
        <div class="error-message" id="error-message"></div>
        
        <div class="loading" id="loading">
            <div class="loading-spinner"></div>
            Processing your selection... This window will close automatically.
        </div>
        
        <div id="content">
"""
    
    def _get_html_footer(self) -> str:
        """Get HTML footer with scripts"""
        return """
        </div>
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
            
            document.querySelector('.selection-count').textContent = count;
            
            // Update button state
            const processBtn = document.querySelector('.button-primary');
            if (count === 0) {
                processBtn.disabled = true;
            } else {
                processBtn.disabled = false;
            }
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
            document.getElementById('content').style.display = 'none';
            
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
                document.getElementById('content').style.display = 'block';
                document.querySelectorAll('.button').forEach(btn => btn.disabled = false);
                showError('Failed to process selection. Please try again.');
                updateSelection();
            });
        }
        
        // Initialize on load
        document.addEventListener('DOMContentLoaded', function() {
            updateSelection();
            
            // Add smooth scroll behavior
            document.querySelectorAll('a[href^="#"]').forEach(anchor => {
                anchor.addEventListener('click', function (e) {
                    e.preventDefault();
                    const target = document.querySelector(this.getAttribute('href'));
                    if (target) {
                        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
                    }
                });
            });
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