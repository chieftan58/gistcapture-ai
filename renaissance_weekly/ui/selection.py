"""Single-page episode selection UI with seamless transitions"""

import json
import webbrowser
import threading
import uuid
import socket
import time
import asyncio
import traceback
from http.server import HTTPServer, SimpleHTTPRequestHandler
from typing import List, Dict, Tuple, Callable, Optional
from html import escape
from datetime import datetime
from collections import defaultdict

from ..models import Episode
from ..config import PODCAST_CONFIGS, TESTING_MODE
from ..utils.logging import get_logger

logger = get_logger(__name__)


class EpisodeSelector:
    """Single-page selection UI with seamless state transitions"""
    
    def __init__(self):
        self.state = "podcast_selection"
        self.selected_podcasts = []
        self.configuration = {}
        self.episode_cache = []
        self.loading_status = {}
        self.session_id = str(uuid.uuid4())
        self._selection_complete = threading.Event()
        self._selected_episode_indices = []
        self._server = None
        self._server_thread = None
        self._fetch_callback = None
        self._fetch_thread = None
        self._fetch_exception = None
        self._correlation_id = str(uuid.uuid4())[:8]
    
    def run_complete_selection(self, days_back: int = 7, fetch_callback: Callable = None) -> Tuple[List[Episode], Dict]:
        """Run the complete selection process in a single page"""
        logger.info(f"[{self._correlation_id}] Starting episode selection UI")
        
        self._fetch_callback = fetch_callback
        self.configuration = {
            'lookback_days': days_back,
            'transcription_mode': 'test' if TESTING_MODE else 'full',
            'session_id': self.session_id
        }
        
        # Reset state
        self.state = "podcast_selection"
        self.selected_podcasts = []
        self.episode_cache = []
        self._selection_complete.clear()
        self._fetch_exception = None
        
        # Create and start server
        port = self._find_available_port()
        self._server = self._create_unified_server(port)
        self._server_thread = threading.Thread(target=self._run_server, daemon=True)
        self._server_thread.start()
        
        # Open browser once
        url = f'http://localhost:{port}/'
        logger.info(f"[{self._correlation_id}] 🌐 Opening selection UI at {url}")
        try:
            webbrowser.open(url)
        except:
            logger.warning(f"[{self._correlation_id}] Please open: {url}")
        
        # Wait for completion
        logger.info(f"[{self._correlation_id}] ⏳ Waiting for selection process to complete...")
        if self._selection_complete.wait(timeout=600):  # 10 minute timeout
            logger.info(f"[{self._correlation_id}] ✅ Selection event received")
        else:
            logger.warning(f"[{self._correlation_id}] ⏰ Selection timeout")
        
        # Check for fetch exceptions
        if self._fetch_exception:
            logger.error(f"[{self._correlation_id}] Fetch thread error: {self._fetch_exception}")
            raise self._fetch_exception
        
        # Get selected episodes
        selected_episodes = []
        if self._selected_episode_indices:
            logger.info(f"[{self._correlation_id}] 📋 Processing {len(self._selected_episode_indices)} selected episode indices")
            for idx in self._selected_episode_indices:
                if 0 <= idx < len(self.episode_cache):
                    selected_episodes.append(self.episode_cache[idx])
                else:
                    logger.warning(f"[{self._correlation_id}] Invalid episode index: {idx}")
        
        # Cleanup
        self._shutdown_server()
        
        logger.info(f"[{self._correlation_id}] ✅ Selection complete: {len(selected_episodes)} episodes")
        return selected_episodes, self.configuration
    
    def _create_unified_server(self, port: int) -> HTTPServer:
        """Create a single server that handles all states"""
        parent = self
        
        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                try:
                    super().__init__(*args, **kwargs)
                except Exception as e:
                    logger.error(f"Handler init error: {e}")
                    raise
            
            def do_GET(self):
                if self.path == '/':
                    self._send_html(parent._generate_html())
                elif self.path == '/api/state':
                    # Include episode data when ready
                    response_data = {
                        'state': parent.state,
                        'selected_podcasts': len(parent.selected_podcasts),
                        'episode_count': len(parent.episode_cache)
                    }
                    
                    if parent.state == 'episode_selection' and parent.episode_cache:
                        response_data['episodes'] = [{
                            'podcast': ep.podcast,
                            'title': ep.title,
                            'published': ep.published.isoformat() if hasattr(ep.published, 'isoformat') else str(ep.published),
                            'duration': ep.duration,
                            'has_transcript': ep.transcript_url is not None,
                            'description': ep.description[:200] if ep.description else ''
                        } for ep in parent.episode_cache]
                    
                    self._send_json(response_data)
                elif self.path == f'/api/status':
                    self._send_json(parent.loading_status)
                elif self.path == '/api/error':
                    # Check if there was an error
                    if parent._fetch_exception:
                        self._send_json({
                            'error': True,
                            'message': str(parent._fetch_exception)
                        })
                    else:
                        self._send_json({'error': False})
                else:
                    self._send_json({'status': 'error', 'message': 'Not found'})
                    return
            
            def do_POST(self):
                try:
                    content_length = int(self.headers.get('Content-Length', 0))
                    if content_length == 0:
                        self._send_json({'status': 'error', 'message': 'No content provided'})
                        return
                    
                    post_data = self.rfile.read(content_length)
                    if not post_data:
                        self._send_json({'status': 'error', 'message': 'Empty request body'})
                        return
                    
                    try:
                        data = json.loads(post_data.decode('utf-8'))
                    except json.JSONDecodeError as e:
                        self._send_json({'status': 'error', 'message': f'Invalid JSON: {str(e)}'})
                        return
                except Exception as e:
                    logger.error(f"Error processing POST request: {e}")
                    self._send_json({'status': 'error', 'message': 'Request processing failed'})
                    return
                
                if self.path == '/api/select-podcasts':
                    # Handle podcast selection
                    parent.selected_podcasts = data.get('selected_podcasts', [])
                    parent.configuration['lookback_days'] = data.get('lookback_days', 7)
                    parent.configuration['transcription_mode'] = data.get('transcription_mode', 'test')
                    
                    parent.state = "loading"
                    parent.loading_status = {
                        'status': 'loading',
                        'progress': 0,
                        'total': len(parent.selected_podcasts)
                    }
                    
                    self._send_json({'status': 'success'})
                    
                    # Start fetching episodes in background
                    parent._fetch_thread = threading.Thread(
                        target=parent._fetch_episodes_background,
                        daemon=True,
                        name=f"fetch-{parent._correlation_id}"
                    )
                    parent._fetch_thread.start()
                    
                elif self.path == '/api/select-episodes':
                    try:
                        # Handle episode selection
                        parent._selected_episode_indices = data.get('selected_episodes', [])
                        parent.state = "complete"
                        
                        logger.info(f"[{parent._correlation_id}] 📥 Received episode selection: {len(parent._selected_episode_indices)} episodes")
                        
                        self._send_json({'status': 'success', 'count': len(parent._selected_episode_indices)})
                        
                        # Signal completion after response is sent
                        threading.Thread(
                            target=lambda: (time.sleep(0.1), parent._selection_complete.set()),
                            daemon=True
                        ).start()
                        
                    except Exception as e:
                        logger.error(f"[{parent._correlation_id}] Error in episode selection: {e}", exc_info=True)
                        self._send_json({'status': 'error', 'message': str(e)})
                    
                else:
                    self._send_json({'status': 'error', 'message': 'Not found'})
                    return
            
            def _send_html(self, content):
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(content.encode())
            
            def _send_json(self, data):
                try:
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.send_header('Content-Length', str(len(json.dumps(data))))
                    self.end_headers()
                    self.wfile.write(json.dumps(data).encode())
                except Exception as e:
                    logger.error(f"Error sending JSON response: {e}")
                    # Try to send error response if possible
                    try:
                        error_data = {'status': 'error', 'message': 'Internal server error'}
                        self.send_response(500)
                        self.send_header('Content-type', 'application/json')
                        self.end_headers()
                        self.wfile.write(json.dumps(error_data).encode())
                    except:
                        pass  # Can't recover
            
            def log_message(self, format, *args):
                pass  # Suppress logs
        
        server = HTTPServer(('localhost', port), Handler)
        server.timeout = 0.5
        return server
    
    def _run_server(self):
        """Run server until completion"""
        logger.debug(f"[{self._correlation_id}] Server thread started")
        while not self._selection_complete.is_set():
            try:
                self._server.handle_request()
            except Exception as e:
                if not self._selection_complete.is_set():
                    logger.debug(f"[{self._correlation_id}] Server error: {e}")
        logger.debug(f"[{self._correlation_id}] Server thread ending")
    
    def _shutdown_server(self):
        """Shutdown server cleanly"""
        logger.debug(f"[{self._correlation_id}] Shutting down server...")
        
        # Signal server to stop
        self._selection_complete.set()
        
        # Wait for server thread to finish
        if self._server_thread and self._server_thread.is_alive():
            self._server_thread.join(timeout=2)
            logger.debug(f"[{self._correlation_id}] Server thread joined")
        
        # Wait for fetch thread to finish
        if self._fetch_thread and self._fetch_thread.is_alive():
            logger.debug(f"[{self._correlation_id}] Waiting for fetch thread...")
            self._fetch_thread.join(timeout=5)
            logger.debug(f"[{self._correlation_id}] Fetch thread joined")
        
        # Close server
        if self._server:
            try:
                self._server.server_close()
                logger.debug(f"[{self._correlation_id}] Server closed")
            except Exception as e:
                logger.debug(f"[{self._correlation_id}] Server close error: {e}")
    
    def _fetch_episodes_background(self):
        """Fetch episodes in background with proper event loop management"""
        loop = None
        
        try:
            if not self._fetch_callback:
                raise Exception("No fetch callback provided")
            
            logger.info(f"[{self._correlation_id}] 📡 Background fetch started for {len(self.selected_podcasts)} podcasts")
            
            def progress_callback(podcast_name, index, total):
                self.loading_status = {
                    'status': 'loading',
                    'progress': index,
                    'total': total,
                    'current_podcast': podcast_name
                }
                logger.debug(f"[{self._correlation_id}] Progress: {podcast_name} ({index+1}/{total})")
            
            # Create a new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                # Call the fetch callback (it handles its own async execution)
                episodes = self._fetch_callback(
                    self.selected_podcasts,
                    self.configuration['lookback_days'],
                    progress_callback
                )
                
                # Store episodes
                self.episode_cache = episodes
                self.state = "episode_selection"
                self.loading_status = {
                    'status': 'ready',
                    'episode_count': len(episodes)
                }
                
                logger.info(f"[{self._correlation_id}] ✅ Background fetch complete: {len(episodes)} episodes")
                
            except Exception as e:
                logger.error(f"[{self._correlation_id}] Error in fetch callback: {e}", exc_info=True)
                self._fetch_exception = e
                self.state = "error"
                self.loading_status = {
                    'status': 'error',
                    'error': str(e)
                }
                # Signal completion even on error
                self._selection_complete.set()
                raise
            
        except Exception as e:
            logger.error(f"[{self._correlation_id}] Error fetching episodes: {e}", exc_info=True)
            self._fetch_exception = e
            self.state = "error"
            self.loading_status = {
                'status': 'error',
                'error': str(e)
            }
            # Signal completion even on error
            self._selection_complete.set()
            
        finally:
            # Clean up event loop
            if loop:
                try:
                    # Cancel any pending tasks
                    pending = asyncio.all_tasks(loop)
                    for task in pending:
                        task.cancel()
                    
                    # Wait for cancellation
                    if pending:
                        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                    
                    # Close the loop
                    loop.close()
                    asyncio.set_event_loop(None)
                    
                    logger.debug(f"[{self._correlation_id}] Event loop cleaned up in fetch thread")
                    
                except Exception as e:
                    logger.debug(f"[{self._correlation_id}] Error cleaning up event loop: {e}")
    
    def _find_available_port(self, start_port: int = 8888) -> int:
        """Find an available port"""
        for port in range(start_port, start_port + 100):
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.bind(('', port))
                s.close()
                return port
            except:
                continue
        return start_port
    
    def _js_escape(self, text: str) -> str:
        """Escape text for safe use in JavaScript strings"""
        return (text.replace('\\', '\\\\')
                    .replace("'", "\\'")
                    .replace('"', '\\"')
                    .replace('\n', '\\n')
                    .replace('\r', '\\r'))
    
    def _generate_html(self) -> str:
        """Generate single-page HTML that handles all states"""
        # Pre-process podcast data with proper escaping
        sorted_podcasts = sorted(PODCAST_CONFIGS, key=lambda x: x['name'].lower())
        podcast_data = []
        for p in sorted_podcasts:
            podcast_data.append({
                'name': p['name'],
                'name_escaped': self._js_escape(p['name']),
                'description': p.get('description', ''),
                'has_apple': bool(p.get('apple_id')),
                'has_rss': bool(p.get('rss_feeds'))
            })
        
        return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Renaissance Weekly</title>
    <style>{self._get_css()}</style>
</head>
<body>
    <div id="app"></div>
    
    <script>
        const APP_STATE = {{
            state: '{self.state}',
            selectedPodcasts: new Set(),
            selectedEpisodes: new Set(),
            configuration: {{
                lookback_days: {self.configuration.get('lookback_days', 7)},
                transcription_mode: '{self.configuration.get('transcription_mode', 'test')}'
            }},
            episodes: [],
            statusInterval: null,
            errorCheckInterval: null
        }};
        
        // Render functions for each state
        function renderPodcastSelection() {{
            const podcasts = {json.dumps(podcast_data)};
            
            return `
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
                                        <input type="radio" name="lookback" id="week" value="7" ${{APP_STATE.configuration.lookback_days === 7 ? 'checked' : ''}}>
                                        <label for="week">1 Week</label>
                                    </div>
                                    <div class="radio-option">
                                        <input type="radio" name="lookback" id="twoweek" value="14" ${{APP_STATE.configuration.lookback_days === 14 ? 'checked' : ''}}>
                                        <label for="twoweek">2 Weeks</label>
                                    </div>
                                    <div class="radio-option">
                                        <input type="radio" name="lookback" id="month" value="30" ${{APP_STATE.configuration.lookback_days === 30 ? 'checked' : ''}}>
                                        <label for="month">1 Month</label>
                                    </div>
                                </div>
                            </div>
                            
                            <div class="config-group">
                                <div class="config-label">Transcription mode</div>
                                <div class="radio-group">
                                    <div class="radio-option">
                                        <input type="radio" name="transcription" id="test" value="test" ${{APP_STATE.configuration.transcription_mode === 'test' ? 'checked' : ''}}>
                                        <label for="test">Test</label>
                                    </div>
                                    <div class="radio-option">
                                        <input type="radio" name="transcription" id="full" value="full" ${{APP_STATE.configuration.transcription_mode === 'full' ? 'checked' : ''}}>
                                        <label for="full">Full</label>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                    
                    <div class="content-grid">
                        ${{podcasts.map(p => `
                            <div class="card ${{APP_STATE.selectedPodcasts.has(p.name) ? 'selected' : ''}}" onclick="togglePodcast('${{p.name_escaped}}')">
                                <div class="card-checkbox"></div>
                                <div class="card-title">${{p.name}}</div>
                                <div class="card-description">${{p.description || 'Podcast: ' + p.name}}</div>
                                <div class="card-meta">${{[p.has_apple ? 'Apple' : '', p.has_rss ? 'RSS' : ''].filter(Boolean).join(' · ')}}</div>
                            </div>
                        `).join('')}}
                    </div>
                    
                    <div class="action-bar">
                        <div class="button-group">
                            <button class="button button-text" onclick="selectAllPodcasts()">All</button>
                            <button class="button button-text" onclick="selectNonePodcasts()">None</button>
                        </div>
                        <div class="selection-info">
                            <span class="selection-count">${{APP_STATE.selectedPodcasts.size}}</span> selected
                        </div>
                        <button class="button button-primary" onclick="submitPodcasts()" ${{APP_STATE.selectedPodcasts.size === 0 ? 'disabled' : ''}}>
                            Continue
                        </button>
                    </div>
                </div>
            `;
        }}
        
        function renderLoading() {{
            // Sort podcasts alphabetically
            const podcasts = Array.from(APP_STATE.selectedPodcasts).sort((a, b) => a.toLowerCase().localeCompare(b.toLowerCase()));
            return `
                <div class="header">
                    <div class="logo">RW</div>
                    <div class="header-text">Please wait</div>
                </div>
                
                <div class="container">
                    <div class="loading-content" style="margin: 100px auto;">
                        <div class="loading-spinner"></div>
                        <h2 class="loading-title">Fetching episodes</h2>
                        <p class="loading-status" id="status">Connecting to feeds...</p>
                        
                        <div class="progress-track">
                            <div class="progress-fill" id="progress"></div>
                        </div>
                        
                        <div class="podcast-progress-list">
                            ${{podcasts.map((p, i) => `
                                <div class="progress-item" id="podcast-${{i}}">
                                    <div class="progress-dot"></div>
                                    <span>${{p}}</span>
                                </div>
                            `).join('')}}
                        </div>
                    </div>
                </div>
            `;
        }}
        
        function renderError() {{
            return `
                <div class="header">
                    <div class="logo">RW</div>
                    <div class="header-text">Error</div>
                </div>
                
                <div class="container">
                    <div class="loading-content" style="margin: 100px auto;">
                        <div style="font-size: 60px; color: #dc3545; margin-bottom: 20px;">✗</div>
                        <h2>Something went wrong</h2>
                        <p style="margin-top: 20px; color: #666;">An error occurred while fetching episodes. Please try again.</p>
                        <p style="margin-top: 10px; color: #999; font-size: 14px;">${{APP_STATE.loading_status.error || 'Unknown error'}}</p>
                        <button class="button button-primary" style="margin-top: 30px;" onclick="location.reload()">Try Again</button>
                    </div>
                </div>
            `;
        }}
        
        function renderEpisodeSelection() {{
            if (!APP_STATE.episodes || APP_STATE.episodes.length === 0) {{
                return `
                    <div class="header">
                        <div class="logo">RW</div>
                        <div class="header-text">Loading episodes...</div>
                    </div>
                    
                    <div class="container">
                        <div class="loading-content" style="margin: 100px auto;">
                            <div class="loading-spinner"></div>
                            <p>Loading episode data...</p>
                        </div>
                    </div>
                `;
            }}
            
            // Group episodes by podcast
            const episodesByPodcast = {{}};
            APP_STATE.episodes.forEach((ep, idx) => {{
                if (!episodesByPodcast[ep.podcast]) {{
                    episodesByPodcast[ep.podcast] = [];
                }}
                episodesByPodcast[ep.podcast].push({{...ep, index: idx}});
            }});
            
            // Sort episodes within each podcast by date descending
            Object.keys(episodesByPodcast).forEach(podcast => {{
                episodesByPodcast[podcast].sort((a, b) => new Date(b.published) - new Date(a.published));
            }});
            
            // Sort podcast names alphabetically
            const sortedPodcasts = Object.keys(episodesByPodcast).sort((a, b) => a.toLowerCase().localeCompare(b.toLowerCase()));
            
            return `
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
                    
                    <div class="stats-bar">
                        <div class="stat">
                            <div class="stat-value">${{APP_STATE.configuration.lookback_days}}</div>
                            <div class="stat-label">Days</div>
                        </div>
                        <div class="stat">
                            <div class="stat-value">${{Object.keys(episodesByPodcast).length}}</div>
                            <div class="stat-label">Podcasts</div>
                        </div>
                        <div class="stat">
                            <div class="stat-value">${{APP_STATE.episodes.length}}</div>
                            <div class="stat-label">Episodes</div>
                        </div>
                    </div>
                    
                    ${{APP_STATE.configuration.transcription_mode === 'test' ? `
                        <div class="notice">
                            Test mode: Transcriptions limited to 20 minutes
                        </div>
                    ` : ''}}
                    
                    <div id="content">
                        ${{sortedPodcasts.map(podcast => `
                            <div class="episode-section">
                                <div class="episode-header">
                                    <h3 class="episode-podcast-name">${{podcast}}</h3>
                                    <div class="episode-count">${{episodesByPodcast[podcast].length}} episode${{episodesByPodcast[podcast].length !== 1 ? 's' : ''}}</div>
                                </div>
                                <div class="episodes-list">
                                    ${{episodesByPodcast[podcast].map(ep => `
                                        <div class="episode-item ${{APP_STATE.selectedEpisodes.has(ep.index) ? 'selected' : ''}}" id="episode-${{ep.index}}" onclick="toggleEpisode(${{ep.index}})">
                                            <div class="episode-checkbox"></div>
                                            <div class="episode-content">
                                                <div class="episode-title">${{ep.title}}${{ep.has_transcript ? '<span class="transcript-indicator"></span>' : ''}}</div>
                                                <div class="episode-meta">${{formatDate(ep.published)}} · ${{ep.duration}}</div>
                                                <div class="episode-description">${{(ep.description || '').substring(0, 150)}}...</div>
                                            </div>
                                        </div>
                                    `).join('')}}
                                </div>
                            </div>
                        `).join('')}}
                    </div>
                    
                    <div class="action-bar">
                        <div class="button-group">
                            <button class="button button-text" onclick="selectAllEpisodes()">All</button>
                            <button class="button button-text" onclick="selectNoneEpisodes()">None</button>
                        </div>
                        <div class="selection-info">
                            <span class="selection-count">${{APP_STATE.selectedEpisodes.size}}</span> selected
                        </div>
                        <button class="button button-primary" onclick="submitEpisodes()" ${{APP_STATE.selectedEpisodes.size === 0 ? 'disabled' : ''}}>
                            Process
                        </button>
                    </div>
                </div>
            `;
        }}
        
        function renderComplete() {{
            return `
                <div class="header">
                    <div class="logo">RW</div>
                    <div class="header-text">Selection Complete</div>
                </div>
                
                <div class="container">
                    <div class="loading-content" style="margin: 100px auto;">
                        <div style="font-size: 60px; color: #28a745; margin-bottom: 20px;">✓</div>
                        <h2>Processing ${{APP_STATE.selectedEpisodes.size}} episodes...</h2>
                        <p style="margin-top: 20px; color: #666;">This window will close automatically.</p>
                    </div>
                </div>
            `;
        }}
        
        // Helper functions
        function formatDate(dateStr) {{
            const date = new Date(dateStr);
            const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
            return months[date.getMonth()] + ' ' + date.getDate();
        }}
        
        function togglePodcast(name) {{
            const card = event.currentTarget;
            if (APP_STATE.selectedPodcasts.has(name)) {{
                APP_STATE.selectedPodcasts.delete(name);
                card.classList.remove('selected');
            }} else {{
                APP_STATE.selectedPodcasts.add(name);
                card.classList.add('selected');
            }}
            updatePodcastCount();
        }}
        
        function selectAllPodcasts() {{
            document.querySelectorAll('.card').forEach(card => {{
                const name = card.querySelector('.card-title').textContent;
                APP_STATE.selectedPodcasts.add(name);
                card.classList.add('selected');
            }});
            updatePodcastCount();
        }}
        
        function selectNonePodcasts() {{
            APP_STATE.selectedPodcasts.clear();
            document.querySelectorAll('.card').forEach(card => {{
                card.classList.remove('selected');
            }});
            updatePodcastCount();
        }}
        
        function updatePodcastCount() {{
            document.querySelector('.selection-count').textContent = APP_STATE.selectedPodcasts.size;
            document.querySelector('.button-primary').disabled = APP_STATE.selectedPodcasts.size === 0;
        }}
        
        function toggleEpisode(index) {{
            const episode = document.getElementById('episode-' + index);
            if (APP_STATE.selectedEpisodes.has(index)) {{
                APP_STATE.selectedEpisodes.delete(index);
                episode.classList.remove('selected');
            }} else {{
                APP_STATE.selectedEpisodes.add(index);
                episode.classList.add('selected');
            }}
            updateEpisodeCount();
        }}
        
        function selectAllEpisodes() {{
            document.querySelectorAll('.episode-item').forEach(episode => {{
                const index = parseInt(episode.id.split('-')[1]);
                APP_STATE.selectedEpisodes.add(index);
                episode.classList.add('selected');
            }});
            updateEpisodeCount();
        }}
        
        function selectNoneEpisodes() {{
            APP_STATE.selectedEpisodes.clear();
            document.querySelectorAll('.episode-item').forEach(episode => {{
                episode.classList.remove('selected');
            }});
            updateEpisodeCount();
        }}
        
        function updateEpisodeCount() {{
            document.querySelector('.selection-count').textContent = APP_STATE.selectedEpisodes.size;
            document.querySelector('.button-primary').disabled = APP_STATE.selectedEpisodes.size === 0;
        }}
        
        // API functions
        async function submitPodcasts() {{
            APP_STATE.configuration.lookback_days = parseInt(document.querySelector('input[name="lookback"]:checked').value);
            APP_STATE.configuration.transcription_mode = document.querySelector('input[name="transcription"]:checked').value;
            
            const response = await fetch('/api/select-podcasts', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{
                    selected_podcasts: Array.from(APP_STATE.selectedPodcasts),
                    lookback_days: APP_STATE.configuration.lookback_days,
                    transcription_mode: APP_STATE.configuration.transcription_mode
                }})
            }});
            
            if (response.ok) {{
                APP_STATE.state = 'loading';
                render();
                startStatusPolling();
                startErrorChecking();
            }}
        }}
        
        // Helper function for fetch with timeout
        async function fetchWithTimeout(url, options = {{}}, timeout = 5000) {{
            const controller = new AbortController();
            const id = setTimeout(() => controller.abort(), timeout);
            
            try {{
                const response = await fetch(url, {{
                    ...options,
                    signal: controller.signal
                }});
                clearTimeout(id);
                return response;
            }} catch (error) {{
                clearTimeout(id);
                if (error.name === 'AbortError') {{
                    throw new Error(\'Request timed out\');
                }}
                throw error;
            }}
        }}
        
        async function submitEpisodes() {{
            console.log('Submitting episodes:', Array.from(APP_STATE.selectedEpisodes));
            
            try {{
                const response = await fetchWithTimeout('/api/select-episodes', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{
                        selected_episodes: Array.from(APP_STATE.selectedEpisodes)
                    }})
                }});
                
                console.log('Response status:', response.status);
                
                // Check if response has content before parsing JSON
                const contentType = response.headers.get('content-type');
                if (!contentType || !contentType.includes('application/json')) {{
                    throw new Error(\'Server did not return JSON response\');
                }}
                
                const text = await response.text();
                if (!text) {{
                    throw new Error(\'Empty response from server\');
                }}
                
                let data;
                try {{
                    data = JSON.parse(text);
                }} catch (e) {{
                    console.error('Failed to parse JSON:', text);
                    throw new Error(\'Invalid JSON response from server\');
                }}
                console.log('Response data:', data);
                
                if (response.ok && data.status === 'success') {{
                    APP_STATE.state = 'complete';
                    render();
                    setTimeout(() => window.close(), 3000);
                }} else {{
                    alert('Failed to submit episodes');
                }}
            }} catch (error) {{
                console.error('Submit error:', error);
                alert('Error submitting episodes: ' + error.message);
            }}
        }}
        
        function startErrorChecking() {{
            // Check for errors periodically
            APP_STATE.errorCheckInterval = setInterval(async () => {{
                try {{
                    const response = await fetchWithTimeout('/api/error', {{}}, 3000);
                    
                    // Safe JSON parsing
                    let data;
                    try {{
                        data = await response.json();
                    }} catch (e) {{
                        console.error('Failed to parse error response');
                        return;
                    }}
                    
                    if (data && data.error) {{
                        clearInterval(APP_STATE.statusInterval);
                        clearInterval(APP_STATE.errorCheckInterval);
                        
                        APP_STATE.state = 'error';
                        APP_STATE.loading_status = {{
                            status: 'error',
                            error: data.message
                        }};
                        render();
                    }}
                }} catch (e) {{
                    console.error('Error check failed:', e);
                }}
            }}, 1000);
        }}
        
        function startStatusPolling() {{
            APP_STATE.statusInterval = setInterval(async () => {{
                try {{
                    const response = await fetchWithTimeout('/api/status', {{}}, 3000);
                    
                    // Safe JSON parsing
                    let status;
                    try {{
                        status = await response.json();
                    }} catch (e) {{
                        console.error('Failed to parse status response:', e);
                        return;
                    }}
                
                if (status.status === 'loading') {{
                    const progress = Math.max(5, ((status.progress + 1) / status.total) * 100);
                    document.getElementById('progress').style.width = progress + '%';
                    
                    if (status.current_podcast) {{
                        document.getElementById('status').textContent = `Fetching from ${{status.current_podcast}}...`;
                        
                        // Update podcast items
                        const items = document.querySelectorAll('.progress-item');
                        items.forEach((item, idx) => {{
                            if (idx < status.progress) {{
                                item.classList.remove('active');
                                item.classList.add('complete');
                            }} else if (idx === status.progress) {{
                                item.classList.add('active');
                                item.classList.remove('complete');
                            }} else {{
                                item.classList.remove('active', 'complete');
                            }}
                        }});
                    }}
                }} else if (status.status === 'ready') {{
                    clearInterval(APP_STATE.statusInterval);
                    clearInterval(APP_STATE.errorCheckInterval);
                    
                    // Update all progress items to complete
                    document.querySelectorAll('.progress-item').forEach(item => {{
                        item.classList.remove('active');
                        item.classList.add('complete');
                    }});
                    
                    document.getElementById('progress').style.width = '100%';
                    document.getElementById('status').textContent = `Found ${{status.episode_count}} episodes`;
                    document.querySelector('.loading-title').textContent = 'Loading episodes...';
                    
                    // Wait a moment then check for episode data
                    setTimeout(async () => {{
                        try {{
                            const stateResponse = await fetchWithTimeout('/api/state', {{}}, 5000);
                            let stateData;
                            try {{
                                stateData = await stateResponse.json();
                            }} catch (e) {{
                                console.error('Failed to parse state data:', e);
                                return;
                            }}
                            if (stateData.state === 'episode_selection' && stateData.episodes) {{
                                APP_STATE.state = 'episode_selection';
                                APP_STATE.episodes = stateData.episodes;
                                render();
                            }}
                        }} catch (e) {{
                            console.error('Error fetching state:', e);
                        }}
                    }}, 1000);
                }} else if (status.status === 'error') {{
                    clearInterval(APP_STATE.statusInterval);
                    clearInterval(APP_STATE.errorCheckInterval);
                    
                    APP_STATE.state = 'error';
                    APP_STATE.loading_status = status;
                    render();
                }}
                }} catch (e) {{
                    console.error('Status polling error:', e);
                }}
            }}, 1000);
        }}
        
        // Main render function
        function render() {{
            const app = document.getElementById('app');
            
            switch (APP_STATE.state) {{
                case 'podcast_selection':
                    app.innerHTML = renderPodcastSelection();
                    break;
                case 'loading':
                    app.innerHTML = renderLoading();
                    break;
                case 'episode_selection':
                    app.innerHTML = renderEpisodeSelection();
                    break;
                case 'complete':
                    app.innerHTML = renderComplete();
                    break;
                case 'error':
                    app.innerHTML = renderError();
                    break;
            }}
        }}
        
        // Initial render
        render();
        
        // Start checking for state updates after a brief delay
        setTimeout(() => {{
            setInterval(async () => {{
                if (APP_STATE.state !== 'loading' && APP_STATE.state !== 'complete' && APP_STATE.state !== 'error') {{
                    const response = await fetch('/api/state');
                    const data = await response.json();
                    if (data.state !== APP_STATE.state || (data.episodes && data.episodes.length > 0 && APP_STATE.episodes.length === 0)) {{
                        APP_STATE.state = data.state;
                        if (data.episodes) {{
                            APP_STATE.episodes = data.episodes;
                        }}
                        render();
                    }}
                }}
            }}, 1000);
        }}, 500);
    </script>
</body>
</html>'''
    
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
    
    # Backward compatibility methods
    def run_podcast_selection(self, days_back: int = 7) -> Tuple[List[str], Dict]:
        """Backward compatibility - now handled in single flow"""
        # Return empty results as this is now part of the unified flow
        return [], {'lookback_days': days_back, 'transcription_mode': 'test' if TESTING_MODE else 'full'}
    
    def show_loading_screen_and_fetch(self, selected_podcasts: List[str], configuration: Dict, 
                                     fetch_episodes_callback: Callable) -> List[Episode]:
        """Backward compatibility - now handled in single flow"""
        # If this is called, just run the complete selection
        episodes, _ = self.run_complete_selection(
            configuration.get('lookback_days', 7),
            fetch_episodes_callback
        )
        return episodes