"""Two-stage episode selection UI with minimalist design"""

import json
import webbrowser
import threading
import uuid
import socket
import time
import queue
from http.server import HTTPServer, SimpleHTTPRequestHandler
from typing import List, Dict, Tuple, Callable
from html import escape
from datetime import datetime
from collections import defaultdict

from ..models import Episode
from ..config import PODCAST_CONFIGS, TESTING_MODE
from ..utils.logging import get_logger

logger = get_logger(__name__)


class EpisodeSelector:
    """Handle two-stage selection: podcasts first, then episodes with loading screen"""
    
    def __init__(self):
        self.loading_status = {}
        self.episode_cache = {}
        self.server_port = None
    
    def run_podcast_selection(self, days_back: int = 7) -> Tuple[List[str], Dict]:
        """Stage 1: Select which podcasts to fetch episodes for"""
        selected_podcasts = []
        configuration = {
            'lookback_days': days_back,
            'transcription_mode': 'test' if TESTING_MODE else 'full',
            'max_transcription_minutes': 10 if TESTING_MODE else float('inf')
        }
        server_running = True
        session_id = str(uuid.uuid4())
        parent_instance = self
        
        class Handler(SimpleHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/':
                    self.send_response(200)
                    self.send_header('Content-type', 'text/html')
                    self.end_headers()
                    html = parent_instance._create_podcast_selection_html(days_back, session_id)
                    self.wfile.write(html.encode())
                else:
                    self.send_error(404)
            
            def do_POST(self):
                if self.path == '/select':
                    content_length = int(self.headers['Content-Length'])
                    post_data = self.rfile.read(content_length)
                    data = json.loads(post_data.decode('utf-8'))
                    
                    configuration['lookback_days'] = data.get('lookback_days', 7)
                    configuration['transcription_mode'] = data.get('transcription_mode', 'test')
                    configuration['max_transcription_minutes'] = 10 if data.get('transcription_mode') == 'test' else float('inf')
                    
                    selected_podcasts.extend(data.get('selected_podcasts', []))
                    
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        'session_id': session_id,
                        'redirect_port': parent_instance.server_port or 8888
                    }).encode())
                    
                    nonlocal server_running
                    server_running = False
            
            def log_message(self, format, *args):
                pass
        
        self.server_port = self._find_available_port()
        server = HTTPServer(('localhost', self.server_port), Handler)
        
        url = f'http://localhost:{self.server_port}'
        logger.info(f"🌐 Opening podcast selection at {url}")
        
        try:
            webbrowser.open(url)
        except:
            logger.warning(f"Please open: {url}")
        
        logger.info("⏳ Stage 1: Waiting for podcast selection...")
        
        try:
            while server_running:
                server.handle_request()
        except KeyboardInterrupt:
            logger.warning("Selection cancelled")
            selected_podcasts = []
        finally:
            server.server_close()
        
        configuration['session_id'] = session_id
        return selected_podcasts, configuration
    
    def show_loading_screen_and_fetch(self, selected_podcasts: List[str], configuration: Dict, 
                                     fetch_episodes_callback: Callable) -> List[Episode]:
        """Show loading screen while fetching episodes"""
        session_id = configuration.get('session_id')
        self.loading_status[session_id] = {'status': 'loading', 'progress': 0, 'total': len(selected_podcasts)}
        
        port = self.server_port if self.server_port else self._find_available_port()
        parent_instance = self
        
        # Use a queue for thread-safe communication
        result_queue = queue.Queue()
        server_stop_event = threading.Event()
        
        class Handler(SimpleHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/':
                    self._send_html(parent_instance._create_loading_html(session_id, selected_podcasts, configuration))
                elif self.path == f'/status/{session_id}':
                    self._send_json(parent_instance.loading_status.get(session_id, {'status': 'unknown'}))
                elif self.path == f'/episodes/{session_id}':
                    if session_id in parent_instance.episode_cache:
                        self._send_html(parent_instance._create_episode_selection_html(
                            parent_instance.episode_cache[session_id], selected_podcasts, configuration
                        ))
                    else:
                        self.send_error(404)
                else:
                    self.send_error(404)
            
            def do_POST(self):
                if self.path == '/select':
                    try:
                        content_length = int(self.headers['Content-Length'])
                        post_data = self.rfile.read(content_length)
                        data = json.loads(post_data.decode('utf-8'))
                        
                        logger.info(f"📥 Received selection: {len(data.get('selected_episodes', []))} episodes")
                        
                        # Process selected episodes
                        selected_indices = data.get('selected_episodes', [])
                        selected_episodes = []
                        for idx in selected_indices:
                            if idx < len(parent_instance.episode_cache[session_id]):
                                selected_episodes.append(parent_instance.episode_cache[session_id][idx])
                        
                        logger.info(f"✅ Processed {len(selected_episodes)} episodes")
                        
                        # Send success response with redirect
                        self.send_response(200)
                        self.send_header('Content-type', 'application/json')
                        self.end_headers()
                        self.wfile.write(json.dumps({
                            'status': 'success',
                            'redirect': '/complete'
                        }).encode())
                        
                        # Put result in queue and signal completion
                        result_queue.put(selected_episodes)
                        server_stop_event.set()
                        
                    except Exception as e:
                        logger.error(f"Error processing selection: {e}")
                        self.send_response(500)
                        self.send_header('Content-type', 'application/json')
                        self.end_headers()
                        self.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode())
                
                elif self.path == '/complete':
                    # Handle the completion redirect
                    complete_html = """<!DOCTYPE html>
<html><head><title>Complete</title></head>
<body style="font-family: system-ui; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0;">
<div style="text-align: center;">
<h2>✅ Selection Complete</h2>
<p>Processing your episodes...</p>
<p style="color: #666;">This window will close automatically.</p>
<script>setTimeout(() => window.close(), 2000);</script>
</div>
</body></html>"""
                    self._send_html(complete_html)
            
            def _send_html(self, content):
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                if isinstance(content, str):
                    content = content.encode()
                self.wfile.write(content)
            
            def _send_json(self, data):
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(data).encode())
            
            def log_message(self, format, *args):
                if 'select' in format or 'complete' in format:
                    logger.debug(f"Server: {format % args}")
        
        # Set up server
        server = HTTPServer(('localhost', port), Handler)
        server.timeout = 0.5  # Allow checking for completion
        
        # Start server in background thread
        def run_server():
            logger.debug(f"Starting server on port {port}")
            while not server_stop_event.is_set():
                server.handle_request()
            logger.debug("Server stopping - selection completed")
        
        server_thread = threading.Thread(target=run_server)
        server_thread.daemon = True
        server_thread.start()
        
        logger.info(f"📡 Loading screen ready at http://localhost:{port}")
        
        # Progress callback for episode fetching
        def progress_callback(podcast_name, index, total):
            self.loading_status[session_id] = {
                'status': 'loading',
                'progress': index,
                'total': total,
                'current_podcast': podcast_name
            }
        
        # Fetch episodes in separate thread
        def fetch_episodes():
            try:
                logger.info("📡 Fetching episodes...")
                episodes = fetch_episodes_callback(selected_podcasts, configuration['lookback_days'], progress_callback)
                
                # Update cache and status
                self.episode_cache[session_id] = episodes
                self.loading_status[session_id] = {'status': 'ready', 'episode_count': len(episodes)}
                logger.info(f"✅ Fetched {len(episodes)} episodes total")
            except Exception as e:
                logger.error(f"Error fetching episodes: {e}", exc_info=True)
                self.loading_status[session_id] = {'status': 'error', 'error': str(e)}
                server_stop_event.set()  # Stop on error
        
        fetch_thread = threading.Thread(target=fetch_episodes)
        fetch_thread.daemon = True
        fetch_thread.start()
        
        # Wait for fetching to complete
        fetch_thread.join()
        
        if self.loading_status[session_id].get('status') == 'error':
            logger.error("Episode fetching failed")
            server_stop_event.set()
            server_thread.join(timeout=2)
            server.shutdown()
            return []
        
        logger.info("✅ Episodes ready, waiting for user to proceed...")
        
        # Wait for selection with timeout
        try:
            selected_episodes = result_queue.get(timeout=300)  # 5 minute timeout
            logger.info(f"✅ Got {len(selected_episodes)} episodes from queue")
        except queue.Empty:
            logger.warning("Selection timeout - no episodes selected")
            selected_episodes = []
        
        # Ensure server stops
        server_stop_event.set()
        
        # Give the server thread time to finish
        server_thread.join(timeout=5)
        
        # Force shutdown if needed
        try:
            server.shutdown()
            server.server_close()
        except:
            pass
        
        # Cleanup
        if session_id in self.loading_status:
            del self.loading_status[session_id]
        if session_id in self.episode_cache:
            del self.episode_cache[session_id]
        
        logger.info(f"✅ Returning {len(selected_episodes)} selected episodes")
        return selected_episodes
    
    def run_selection_server(self, episodes: List[Episode]) -> List[Episode]:
        """Legacy single-stage selection for backward compatibility"""
        # Convert to two-stage approach
        all_podcasts = list(set(ep.podcast for ep in episodes))
        
        # Simulate first stage - select all podcasts
        configuration = {
            'lookback_days': 7,
            'transcription_mode': 'test' if TESTING_MODE else 'full',
            'session_id': str(uuid.uuid4())
        }
        
        # Skip directly to episode selection
        self.episode_cache[configuration['session_id']] = episodes
        
        selected_episodes = []
        server_running = True
        parent_instance = self
        
        class Handler(SimpleHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/':
                    self.send_response(200)
                    self.send_header('Content-type', 'text/html')
                    self.end_headers()
                    html = parent_instance._create_episode_selection_html(
                        episodes, all_podcasts, configuration
                    )
                    self.wfile.write(html.encode())
                else:
                    self.send_error(404)
            
            def do_POST(self):
                if self.path == '/select':
                    content_length = int(self.headers['Content-Length'])
                    post_data = self.rfile.read(content_length)
                    data = json.loads(post_data.decode('utf-8'))
                    
                    for idx in data.get('selected_episodes', []):
                        selected_episodes.append(episodes[idx])
                    
                    self.send_response(200)
                    self.end_headers()
                    
                    nonlocal server_running
                    server_running = False
            
            def log_message(self, format, *args):
                pass
        
        port = self._find_available_port()
        server = HTTPServer(('localhost', port), Handler)
        
        url = f'http://localhost:{port}'
        logger.info(f"🌐 Opening episode selection at {url}")
        
        try:
            webbrowser.open(url)
        except:
            logger.warning(f"Please open: {url}")
        
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
    
    def _find_available_port(self, start_port: int = 8888) -> int:
        """Find an available port"""
        for port in range(start_port, start_port + 10):
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.bind(('', port))
                s.close()
                return port
            except:
                continue
        return start_port
    
    def _get_css(self) -> str:
        """Get minimalist CSS styles"""
        return """
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        :root {
            --black: #000000;
            --white: #FFFFFF;
            --gray-100: #F7F7F7;
            --gray-200: #E5E5E5;
            --gray-300: #D4D4D4;
            --gray-400: #A3A3A3;
            --gray-500: #737373;
            --gray-600: #525252;
            --gray-700: #404040;
            --transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            --shadow-subtle: 0 1px 2px rgba(0, 0, 0, 0.05);
            --shadow-soft: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
            --shadow-medium: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
            background: var(--white);
            color: var(--black);
            line-height: 1.6;
            -webkit-font-smoothing: antialiased;
        }
        
        .header {
            padding: 48px 0;
            text-align: center;
            border-bottom: 1px solid var(--gray-200);
        }
        
        .logo {
            width: 40px;
            height: 40px;
            background: var(--black);
            border-radius: 8px;
            margin: 0 auto 24px;
            display: flex;
            align-items: center;
            justify-content: center;
            color: var(--white);
            font-size: 12px;
            font-weight: 600;
        }
        
        .header-text {
            font-size: 16px;
            color: var(--gray-600);
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 64px 48px 120px;
        }
        
        .stage-indicator {
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 32px;
            margin-bottom: 80px;
        }
        
        .stage-wrapper {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 8px;
        }
        
        .stage-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--gray-300);
            transition: var(--transition);
        }
        
        .stage-dot.active {
            background: var(--black);
            transform: scale(1.5);
        }
        
        .stage-label {
            font-size: 12px;
            color: var(--gray-400);
            font-weight: 500;
        }
        
        .stage-label.active {
            color: var(--black);
        }
        
        .stage-connector {
            width: 32px;
            height: 1px;
            background: var(--gray-300);
            margin-bottom: 20px;
        }
        
        .config-section {
            margin-bottom: 80px;
        }
        
        .config-row {
            display: flex;
            gap: 120px;
            margin-bottom: 40px;
        }
        
        .config-group {
            flex: 1;
        }
        
        .config-label {
            font-size: 14px;
            font-weight: 500;
            color: var(--gray-700);
            margin-bottom: 16px;
        }
        
        .radio-group {
            display: flex;
            gap: 2px;
            background: var(--gray-100);
            border-radius: 8px;
            padding: 2px;
        }
        
        .radio-option {
            flex: 1;
            position: relative;
        }
        
        .radio-option input {
            position: absolute;
            opacity: 0;
        }
        
        .radio-option label {
            display: block;
            padding: 12px 24px;
            text-align: center;
            font-size: 14px;
            color: var(--gray-600);
            cursor: pointer;
            transition: var(--transition);
            border-radius: 6px;
        }
        
        .radio-option input:checked + label {
            background: var(--white);
            color: var(--black);
            box-shadow: var(--shadow-subtle);
        }
        
        .content-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
            gap: 24px;
            margin-bottom: 80px;
        }
        
        .card {
            background: var(--white);
            border: 1px solid var(--gray-200);
            border-radius: 12px;
            padding: 32px;
            cursor: pointer;
            transition: var(--transition);
            position: relative;
        }
        
        .card:hover {
            border-color: var(--gray-400);
            transform: translateY(-2px);
            box-shadow: var(--shadow-soft);
        }
        
        .card.selected {
            border-color: var(--black);
            background: var(--gray-100);
        }
        
        .card-checkbox {
            width: 20px;
            height: 20px;
            border: 2px solid var(--gray-400);
            border-radius: 50%;
            position: absolute;
            top: 32px;
            right: 32px;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: var(--transition);
        }
        
        .card.selected .card-checkbox {
            background: var(--black);
            border-color: var(--black);
        }
        
        .card.selected .card-checkbox::after {
            content: '';
            width: 6px;
            height: 6px;
            background: var(--white);
            border-radius: 50%;
        }
        
        .card-title {
            font-size: 18px;
            font-weight: 500;
            margin-bottom: 8px;
            padding-right: 40px;
        }
        
        .card-description {
            font-size: 14px;
            color: var(--gray-600);
            line-height: 1.5;
            margin-bottom: 16px;
        }
        
        .card-meta {
            display: flex;
            gap: 16px;
            font-size: 12px;
            color: var(--gray-500);
        }
        
        .stats-bar {
            display: flex;
            gap: 80px;
            margin-bottom: 64px;
            padding-bottom: 48px;
            border-bottom: 1px solid var(--gray-200);
        }
        
        .stat {
            text-align: left;
        }
        
        .stat-value {
            font-size: 32px;
            font-weight: 300;
            color: var(--black);
            line-height: 1;
            margin-bottom: 4px;
        }
        
        .stat-label {
            font-size: 14px;
            color: var(--gray-500);
        }
        
        .notice {
            background: var(--gray-100);
            border-left: 2px solid var(--black);
            padding: 16px 24px;
            margin-bottom: 48px;
            font-size: 14px;
            color: var(--gray-700);
        }
        
        .episode-section {
            margin-bottom: 48px;
        }
        
        .episode-header {
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            margin-bottom: 24px;
            padding-bottom: 16px;
            border-bottom: 1px solid var(--gray-200);
        }
        
        .episode-podcast-name {
            font-size: 20px;
            font-weight: 500;
        }
        
        .episode-count {
            font-size: 14px;
            color: var(--gray-500);
        }
        
        .episode-item {
            display: flex;
            align-items: flex-start;
            gap: 24px;
            padding: 24px 0;
            border-bottom: 1px solid var(--gray-100);
            cursor: pointer;
            transition: var(--transition);
        }
        
        .episode-item:hover {
            background: var(--gray-100);
            margin: 0 -24px;
            padding: 24px;
        }
        
        .episode-item.selected {
            background: var(--gray-100);
            margin: 0 -24px;
            padding: 24px;
        }
        
        .episode-checkbox {
            width: 20px;
            height: 20px;
            border: 2px solid var(--gray-400);
            border-radius: 50%;
            flex-shrink: 0;
            margin-top: 2px;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: var(--transition);
        }
        
        .episode-item.selected .episode-checkbox {
            background: var(--black);
            border-color: var(--black);
        }
        
        .episode-item.selected .episode-checkbox::after {
            content: '';
            width: 6px;
            height: 6px;
            background: var(--white);
            border-radius: 50%;
        }
        
        .episode-content {
            flex: 1;
        }
        
        .episode-title {
            font-size: 16px;
            font-weight: 500;
            margin-bottom: 4px;
        }
        
        .episode-meta {
            font-size: 14px;
            color: var(--gray-500);
            margin-bottom: 8px;
        }
        
        .episode-description {
            font-size: 14px;
            color: var(--gray-600);
            line-height: 1.5;
        }
        
        .transcript-indicator {
            display: inline-block;
            width: 6px;
            height: 6px;
            background: var(--black);
            border-radius: 50%;
            margin-left: 8px;
        }
        
        .action-bar {
            position: fixed;
            bottom: 48px;
            left: 50%;
            transform: translateX(-50%);
            background: var(--white);
            border: 1px solid var(--gray-200);
            border-radius: 16px;
            padding: 16px 24px;
            display: flex;
            align-items: center;
            gap: 48px;
            box-shadow: var(--shadow-medium);
            z-index: 100;
        }
        
        .selection-info {
            font-size: 14px;
            color: var(--gray-600);
        }
        
        .selection-count {
            color: var(--black);
            font-weight: 500;
        }
        
        .button-group {
            display: flex;
            gap: 12px;
        }
        
        .button {
            padding: 12px 32px;
            border: none;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 500;
            cursor: pointer;
            transition: var(--transition);
            outline: none;
        }
        
        .button-text {
            background: transparent;
            color: var(--gray-600);
            padding: 12px 20px;
        }
        
        .button-text:hover {
            color: var(--black);
        }
        
        .button-primary {
            background: var(--black);
            color: var(--white);
        }
        
        .button-primary:hover:not(:disabled) {
            transform: scale(0.98);
        }
        
        .button:disabled {
            opacity: 0.3;
            cursor: not-allowed;
        }
        
        .loading-screen {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: var(--white);
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            z-index: 1000;
        }
        
        .loading-content {
            text-align: center;
            max-width: 480px;
        }
        
        .loading-spinner {
            width: 48px;
            height: 48px;
            border: 2px solid var(--gray-200);
            border-top-color: var(--black);
            border-radius: 50%;
            margin: 0 auto 32px;
            animation: spin 0.8s ease-in-out infinite;
        }
        
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        
        .loading-title {
            font-size: 24px;
            font-weight: 500;
            margin-bottom: 8px;
        }
        
        .loading-status {
            font-size: 16px;
            color: var(--gray-600);
            margin-bottom: 48px;
        }
        
        .progress-track {
            width: 320px;
            height: 2px;
            background: var(--gray-200);
            border-radius: 1px;
            margin: 0 auto 48px;
            overflow: hidden;
        }
        
        .progress-fill {
            height: 100%;
            background: var(--black);
            transition: width 0.3s ease;
            border-radius: 1px;
        }
        
        .podcast-progress-list {
            text-align: left;
        }
        
        .progress-item {
            display: flex;
            align-items: center;
            gap: 16px;
            padding: 12px 0;
            font-size: 14px;
            color: var(--gray-500);
            transition: var(--transition);
        }
        
        .progress-item.active {
            color: var(--black);
        }
        
        .progress-item.complete {
            color: var(--gray-400);
        }
        
        .progress-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--gray-300);
            transition: var(--transition);
        }
        
        .progress-item.active .progress-dot {
            background: var(--black);
            animation: pulse 1.2s ease-in-out infinite;
        }
        
        .progress-item.complete .progress-dot {
            background: var(--gray-400);
        }
        
        @keyframes pulse {
            0%, 100% { transform: scale(1); opacity: 1; }
            50% { transform: scale(1.5); opacity: 0.5; }
        }
        
        .hidden {
            display: none;
        }
        
        @media (max-width: 768px) {
            .container {
                padding: 32px 24px 120px;
            }
            
            .config-row {
                flex-direction: column;
                gap: 32px;
            }
            
            .content-grid {
                grid-template-columns: 1fr;
            }
            
            .action-bar {
                left: 24px;
                right: 24px;
                transform: none;
                flex-direction: column;
                gap: 16px;
            }
            
            .stats-bar {
                flex-direction: column;
                gap: 24px;
            }
        }
        """
    
    def _create_podcast_selection_html(self, current_days_back: int, session_id: str) -> str:
        """Create HTML for Stage 1: Podcast Selection"""
        podcasts_html = ""
        for config in PODCAST_CONFIGS:
            name = escape(config['name'])
            desc = escape(config.get('description', f"Podcast: {config['name']}"))
            has_apple = 'Apple' if config.get('apple_id') else ''
            has_rss = 'RSS' if config.get('rss_feeds', []) else ''
            meta = ' · '.join(filter(None, [has_apple, has_rss]))
            
            podcasts_html += f'''
                <div class="card" onclick="toggleCard(this, '{name}')">
                    <div class="card-checkbox"></div>
                    <div class="card-title">{name}</div>
                    <div class="card-description">{desc}</div>
                    <div class="card-meta">{meta}</div>
                </div>'''
        
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Select Podcasts - Renaissance Weekly</title>
    <style>{self._get_css()}</style>
</head>
<body>
    <div class="header">
        <div class="logo">RW</div>
        <div class="header-text">Choose podcasts to monitor</div>
    </div>
    
    <div class="container">
        <div class="stage-indicator">
            <div class="stage-wrapper">
                <div class="stage-dot active"></div>
                <div class="stage-label active">Podcasts</div>
            </div>
            <div class="stage-connector"></div>
            <div class="stage-wrapper">
                <div class="stage-dot"></div>
                <div class="stage-label">Episodes</div>
            </div>
            <div class="stage-connector"></div>
            <div class="stage-wrapper">
                <div class="stage-dot"></div>
                <div class="stage-label">Process</div>
            </div>
        </div>
        
        <div class="config-section">
            <div class="config-row">
                <div class="config-group">
                    <div class="config-label">Lookback period</div>
                    <div class="radio-group">
                        <div class="radio-option">
                            <input type="radio" name="lookback" id="week" value="7" {'checked' if current_days_back == 7 else ''}>
                            <label for="week">1 Week</label>
                        </div>
                        <div class="radio-option">
                            <input type="radio" name="lookback" id="twoweek" value="14" {'checked' if current_days_back == 14 else ''}>
                            <label for="twoweek">2 Weeks</label>
                        </div>
                        <div class="radio-option">
                            <input type="radio" name="lookback" id="month" value="30" {'checked' if current_days_back == 30 else ''}>
                            <label for="month">1 Month</label>
                        </div>
                    </div>
                </div>
                
                <div class="config-group">
                    <div class="config-label">Transcription mode</div>
                    <div class="radio-group">
                        <div class="radio-option">
                            <input type="radio" name="transcription" id="test" value="test" {'checked' if TESTING_MODE else ''}>
                            <label for="test">Test</label>
                        </div>
                        <div class="radio-option">
                            <input type="radio" name="transcription" id="full" value="full" {'checked' if not TESTING_MODE else ''}>
                            <label for="full">Full</label>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="content-grid">{podcasts_html}</div>
        
        <div class="action-bar">
            <div class="button-group">
                <button class="button button-text" onclick="selectAll()">All</button>
                <button class="button button-text" onclick="selectNone()">None</button>
            </div>
            <div class="selection-info">
                <span class="selection-count">0</span> selected
            </div>
            <button class="button button-primary" onclick="submitSelection()" disabled>
                Continue
            </button>
        </div>
    </div>
    
    <div class="loading-screen hidden" id="loadingScreen">
        <div class="loading-content">
            <div class="loading-spinner"></div>
            <div class="loading-title">Preparing</div>
            <div class="loading-status">Setting up your selection...</div>
        </div>
    </div>
    
    <script>
        const sessionId = '{session_id}';
        const selectedPodcasts = new Set();
        
        function toggleCard(card, name) {{
            if (selectedPodcasts.has(name)) {{
                selectedPodcasts.delete(name);
                card.classList.remove('selected');
            }} else {{
                selectedPodcasts.add(name);
                card.classList.add('selected');
            }}
            updateSelection();
        }}
        
        function selectAll() {{
            document.querySelectorAll('.card').forEach(card => {{
                const name = card.querySelector('.card-title').textContent;
                selectedPodcasts.add(name);
                card.classList.add('selected');
            }});
            updateSelection();
        }}
        
        function selectNone() {{
            selectedPodcasts.clear();
            document.querySelectorAll('.card').forEach(card => {{
                card.classList.remove('selected');
            }});
            updateSelection();
        }}
        
        function updateSelection() {{
            const count = selectedPodcasts.size;
            document.querySelector('.selection-count').textContent = count;
            document.querySelector('.button-primary').disabled = count === 0;
        }}
        
        function submitSelection() {{
            if (selectedPodcasts.size === 0) return;
            
            document.getElementById('loadingScreen').classList.remove('hidden');
            
            fetch('/select', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{
                    selected_podcasts: Array.from(selectedPodcasts),
                    lookback_days: parseInt(document.querySelector('input[name="lookback"]:checked').value),
                    transcription_mode: document.querySelector('input[name="transcription"]:checked').value
                }})
            }})
            .then(response => response.json())
            .then(data => {{
                window.location.reload();
            }})
            .catch(error => {{
                document.getElementById('loadingScreen').classList.add('hidden');
                console.error('Error:', error);
            }});
        }}
    </script>
</body>
</html>"""
    
    def _create_loading_html(self, session_id: str, selected_podcasts: List[str], configuration: Dict) -> str:
        """Create loading screen HTML"""
        podcast_items = ''.join(f'''
            <div class="progress-item" id="podcast-{i}">
                <div class="progress-dot"></div>
                <span>{escape(p)}</span>
            </div>''' for i, p in enumerate(selected_podcasts))
        
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Loading - Renaissance Weekly</title>
    <style>{self._get_css()}</style>
    <style>.loading-screen {{ position: static; }} .container {{ display: flex; align-items: center; justify-content: center; min-height: calc(100vh - 200px); }}</style>
</head>
<body>
    <div class="header">
        <div class="logo">RW</div>
        <div class="header-text">Please wait</div>
    </div>
    
    <div class="container">
        <div class="loading-content">
            <div class="loading-spinner"></div>
            <h2 class="loading-title">Fetching episodes</h2>
            <p class="loading-status" id="status">Connecting to feeds...</p>
            
            <div class="progress-track">
                <div class="progress-fill" id="progress"></div>
            </div>
            
            <div class="podcast-progress-list">
                {podcast_items}
            </div>
        </div>
    </div>
    
    <script>
        const sessionId = '{session_id}';
        let checkInterval;
        
        function updateStatus() {{
            fetch(`/status/${{sessionId}}`)
                .then(response => response.json())
                .then(data => {{
                    if (data.status === 'loading') {{
                        const progress = Math.max(5, ((data.progress + 1) / data.total) * 100);
                        document.getElementById('progress').style.width = progress + '%';
                        
                        if (data.current_podcast) {{
                            document.getElementById('status').textContent = `Fetching from ${{data.current_podcast}}...`;
                            
                            const allPodcasts = document.querySelectorAll('.progress-item');
                            allPodcasts.forEach((item, idx) => {{
                                const podcastName = item.querySelector('span').textContent;
                                
                                if (podcastName === data.current_podcast) {{
                                    item.classList.remove('complete');
                                    item.classList.add('active');
                                }} else if (item.classList.contains('active')) {{
                                    item.classList.remove('active');
                                    item.classList.add('complete');
                                }}
                            }});
                        }}
                    }} else if (data.status === 'ready') {{
                        clearInterval(checkInterval);
                        
                        document.querySelectorAll('.progress-item').forEach(item => {{
                            item.classList.remove('active');
                            item.classList.add('complete');
                        }});
                        
                        document.getElementById('progress').style.width = '100%';
                        
                        const statusEl = document.getElementById('status');
                        const titleEl = document.querySelector('.loading-title');
                        
                        titleEl.textContent = 'Complete';
                        statusEl.textContent = `Found ${{data.episode_count}} episodes`;
                        
                        document.querySelector('.loading-spinner').style.display = 'none';
                        
                        setTimeout(() => {{
                            window.location.href = '/episodes/' + sessionId;
                        }}, 2000);
                    }} else if (data.status === 'error') {{
                        clearInterval(checkInterval);
                        
                        const statusEl = document.getElementById('status');
                        const titleEl = document.querySelector('.loading-title');
                        
                        titleEl.textContent = 'Error';
                        statusEl.textContent = data.error || 'Failed to fetch episodes';
                        statusEl.style.color = '#DC2626';
                        
                        document.querySelector('.loading-spinner').style.display = 'none';
                    }}
                }})
                .catch(error => console.error('Status check error:', error));
        }}
        
        checkInterval = setInterval(updateStatus, 1000);
        updateStatus();
    </script>
</body>
</html>"""
    
    def _create_episode_selection_html(self, episodes: List[Episode], selected_podcasts: List[str], 
                                      configuration: Dict) -> str:
        """Create HTML for Stage 2: Episode Selection"""
        episodes_by_podcast = defaultdict(list)
        for i, ep in enumerate(episodes):
            podcast_name = ep.podcast if isinstance(ep, Episode) else ep.get('podcast', 'Unknown')
            episodes_by_podcast[podcast_name].append((i, ep))
        
        total_episodes = len(episodes)
        total_podcasts = len(episodes_by_podcast)
        transcription_mode = configuration.get('transcription_mode', 'test')
        
        stats_html = f'''
            <div class="stats-bar">
                <div class="stat">
                    <div class="stat-value">{configuration.get('lookback_days', 7)}</div>
                    <div class="stat-label">Days</div>
                </div>
                <div class="stat">
                    <div class="stat-value">{total_podcasts}</div>
                    <div class="stat-label">Podcasts</div>
                </div>
                <div class="stat">
                    <div class="stat-value">{total_episodes}</div>
                    <div class="stat-label">Episodes</div>
                </div>
            </div>'''
        
        if transcription_mode == 'test':
            stats_html += '''
                <div class="notice">
                    Test mode: Transcriptions limited to 10 minutes
                </div>'''
        
        episodes_html = ""
        for podcast_name in sorted(episodes_by_podcast.keys()):
            podcast_episodes = episodes_by_podcast[podcast_name]
            
            episodes_list = ""
            for idx, ep in podcast_episodes:
                if isinstance(ep, Episode):
                    title = escape(ep.title)
                    published = ep.published.strftime('%b %d')
                    duration = ep.duration
                    has_transcript = ep.transcript_url is not None
                    description = escape(ep.description[:150] + '...' if ep.description else '')
                else:
                    title = escape(ep.get('title', 'Unknown'))
                    published = str(ep.get('published', 'Unknown'))[:10]
                    duration = ep.get('duration', 'Unknown')
                    has_transcript = ep.get('transcript_url') is not None
                    description = escape(str(ep.get('description', ''))[:150] + '...')
                
                transcript_indicator = '<span class="transcript-indicator"></span>' if has_transcript else ''
                
                episodes_list += f'''
                    <div class="episode-item" id="episode-{idx}" onclick="toggleEpisode({idx})">
                        <div class="episode-checkbox"></div>
                        <div class="episode-content">
                            <div class="episode-title">{title}{transcript_indicator}</div>
                            <div class="episode-meta">{published} · {duration}</div>
                            <div class="episode-description">{description}</div>
                        </div>
                    </div>'''
            
            episodes_html += f'''
                <div class="episode-section">
                    <div class="episode-header">
                        <h3 class="episode-podcast-name">{escape(podcast_name)}</h3>
                        <div class="episode-count">{len(podcast_episodes)} episode{'s' if len(podcast_episodes) != 1 else ''}</div>
                    </div>
                    <div class="episodes-list">
                        {episodes_list}
                    </div>
                </div>'''
        
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Select Episodes - Renaissance Weekly</title>
    <style>{self._get_css()}</style>
</head>
<body>
    <div class="header">
        <div class="logo">RW</div>
        <div class="header-text">Choose episodes to process</div>
    </div>
    
    <div class="container">
        <div class="stage-indicator">
            <div class="stage-wrapper">
                <div class="stage-dot" style="background: var(--black);"></div>
                <div class="stage-label" style="color: var(--gray-600);">Podcasts</div>
            </div>
            <div class="stage-connector"></div>
            <div class="stage-wrapper">
                <div class="stage-dot active"></div>
                <div class="stage-label active">Episodes</div>
            </div>
            <div class="stage-connector"></div>
            <div class="stage-wrapper">
                <div class="stage-dot"></div>
                <div class="stage-label">Process</div>
            </div>
        </div>
        
        {stats_html}
        
        <div id="content">
            {episodes_html}
        </div>
        
        <div class="action-bar">
            <div class="button-group">
                <button class="button button-text" onclick="selectAll()">All</button>
                <button class="button button-text" onclick="selectNone()">None</button>
            </div>
            <div class="selection-info">
                <span class="selection-count">0</span> selected
            </div>
            <button class="button button-primary" onclick="submitSelection()" disabled>
                Process
            </button>
        </div>
    </div>
    
    <div class="loading-screen hidden" id="loadingScreen">
        <div class="loading-content">
            <div class="loading-spinner"></div>
            <div class="loading-title">Processing</div>
            <div class="loading-status">Preparing your selection...</div>
        </div>
    </div>
    
    <script>
        const selectedEpisodes = new Set();
        
        function toggleEpisode(index) {{
            const episode = document.getElementById('episode-' + index);
            if (selectedEpisodes.has(index)) {{
                selectedEpisodes.delete(index);
                episode.classList.remove('selected');
            }} else {{
                selectedEpisodes.add(index);
                episode.classList.add('selected');
            }}
            updateSelection();
        }}
        
        function selectAll() {{
            document.querySelectorAll('.episode-item').forEach(episode => {{
                const index = parseInt(episode.id.split('-')[1]);
                selectedEpisodes.add(index);
                episode.classList.add('selected');
            }});
            updateSelection();
        }}
        
        function selectNone() {{
            selectedEpisodes.clear();
            document.querySelectorAll('.episode-item').forEach(episode => {{
                episode.classList.remove('selected');
            }});
            updateSelection();
        }}
        
        function updateSelection() {{
            const count = selectedEpisodes.size;
            document.querySelector('.selection-count').textContent = count;
            document.querySelector('.button-primary').disabled = count === 0;
        }}
        
        function submitSelection() {{
            if (selectedEpisodes.size === 0) return;
            
            console.log('Submitting', selectedEpisodes.size, 'episodes');
            document.getElementById('loadingScreen').classList.remove('hidden');
            
            const data = {{selected_episodes: Array.from(selectedEpisodes)}};
            console.log('Sending data:', data);
            
            fetch('/select', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify(data)
            }})
            .then(response => {{
                console.log('Response status:', response.status);
                if (!response.ok) {{
                    return response.text().then(text => {{
                        throw new Error(`Server error: ${{response.status}} - ${{text}}`);
                    }});
                }}
                return response.json();
            }})
            .then(data => {{
                console.log('Response data:', data);
                if (data.status === 'success') {{
                    console.log('Selection successful');
                    // Handle redirect if provided
                    if (data.redirect) {{
                        window.location.href = data.redirect;
                    }}
                }} else {{
                    throw new Error(data.message || 'Unknown error');
                }}
            }})
            .catch(error => {{
                console.error('Error:', error);
                document.getElementById('loadingScreen').classList.add('hidden');
                alert('Failed to submit selection: ' + error.message);
            }});
        }}
    </script>
</body>
</html>"""
    
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