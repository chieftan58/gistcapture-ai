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
        self._processing_status = None
        self._processing_episodes = []
        self._processing_mode = 'test'
        self._processing_cancelled = False
        self._email_approved = False
        self._process_thread = None
    
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
            logger.info(f"[{self._correlation_id}] 📋 Processing {len(self._selected_episode_indices)} selected episodes")
            # Create a lookup map for episodes by their ID
            episode_map = {}
            for ep in self.episode_cache:
                ep_id = f"{ep.podcast}|{ep.title}|{ep.published}"
                episode_map[ep_id] = ep
            
            # Map selected IDs to episodes
            for ep_id in self._selected_episode_indices:
                if ep_id in episode_map:
                    selected_episodes.append(episode_map[ep_id])
                else:
                    logger.warning(f"[{self._correlation_id}] Episode not found for ID: {ep_id}")
        
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
                            'id': f"{ep.podcast}|{ep.title}|{ep.published}",  # Unique identifier
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
                        # Handle episode selection - now just saves for later processing
                        parent._selected_episode_indices = data.get('selected_episodes', [])
                        
                        logger.info(f"[{parent._correlation_id}] 📥 Received episode selection: {len(parent._selected_episode_indices)} episodes")
                        
                        self._send_json({'status': 'success', 'count': len(parent._selected_episode_indices)})
                        
                    except Exception as e:
                        logger.error(f"[{parent._correlation_id}] Error in episode selection: {e}", exc_info=True)
                        self._send_json({'status': 'error', 'message': str(e)})
                    
                elif self.path == '/api/start-processing':
                    # Start processing with the selected episodes
                    parent._processing_status = {
                        'total': len(data.get('episodes', [])),
                        'completed': 0,
                        'failed': 0,
                        'current': None,
                        'errors': []
                    }
                    parent._processing_episodes = data.get('episodes', [])
                    parent._processing_mode = data.get('mode', 'test')
                    parent._processing_cancelled = False
                    
                    # Start actual processing in background
                    if not hasattr(parent, '_process_thread') or parent._process_thread is None or not parent._process_thread.is_alive():
                        parent._process_thread = threading.Thread(
                            target=parent._process_episodes_background,
                            daemon=True
                        )
                        parent._process_thread.start()
                    
                    self._send_json({'status': 'success'})
                    
                elif self.path == '/api/processing-status':
                    # Return current processing status
                    status = getattr(parent, '_processing_status', {
                        'total': 0,
                        'completed': 0,
                        'failed': 0,
                        'current': None,
                        'errors': []
                    })
                    self._send_json(status)
                    
                elif self.path == '/api/cancel-processing':
                    # Cancel ongoing processing
                    parent._processing_cancelled = True
                    self._send_json({'status': 'success'})
                    
                elif self.path == '/api/email-preview':
                    # Generate email preview
                    preview = parent._generate_email_preview()
                    self._send_json({'preview': preview})
                    
                elif self.path == '/api/send-email':
                    # Mark email as approved and ready to send
                    parent._email_approved = True
                    parent.state = "complete"
                    
                    # Store the processed summaries for the main app
                    if hasattr(parent, '_processed_summaries'):
                        parent._final_summaries = parent._processed_summaries
                    
                    self._send_json({'status': 'success'})
                    
                    # Signal completion after response is sent
                    threading.Thread(
                        target=lambda: (time.sleep(0.1), parent._selection_complete.set()),
                        daemon=True
                    ).start()
                    
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
                logger.info(f"[{self._correlation_id}] 📦 Stored {len(episodes)} episodes in cache")
                
                # Update state to episode_selection
                old_state = self.state
                self.state = "episode_selection"
                logger.info(f"[{self._correlation_id}] 🔄 State transition: {old_state} → episode_selection")
                
                self.loading_status = {
                    'status': 'ready',
                    'episode_count': len(episodes)
                }
                
                logger.info(f"[{self._correlation_id}] ✅ Background fetch complete: {len(episodes)} episodes ready for selection")
                
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
            errorCheckInterval: null,
            globalPollInterval: null,
            processingStatus: {{
                total: 0,
                completed: 0,
                failed: 0,
                current: null,
                startTime: null,
                errors: []
            }},
            costEstimate: {{
                episodes: 0,
                estimatedCost: 0,
                estimatedTime: 0,
                breakdown: {{}}
            }},
            emailPreview: null,
            processingCancelled: false
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
                    ${{renderStageIndicator('podcasts')}}
                    
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
            APP_STATE.episodes.forEach((ep) => {{
                if (!episodesByPodcast[ep.podcast]) {{
                    episodesByPodcast[ep.podcast] = [];
                }}
                episodesByPodcast[ep.podcast].push(ep);
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
                    ${{renderStageIndicator('episodes')}}
                    
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
                            Test Mode: 15 Minutes - Transcriptions limited to 15 minutes per episode
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
                                        <div class="episode-item ${{APP_STATE.selectedEpisodes.has(ep.id) ? 'selected' : ''}}" id="episode-${{ep.id.replace(/[|:]/g, '_')}}" onclick="toggleEpisode('${{ep.id}}')">
                                            <div class="episode-checkbox"></div>
                                            <div class="episode-content">
                                                <div class="episode-title">${{formatEpisodeTitle(ep.title)}}${{ep.has_transcript ? '<span class="transcript-indicator"></span>' : ''}}</div>
                                                <div class="episode-meta">${{formatDate(ep.published)}} · ${{ep.duration}}</div>
                                                <div class="episode-description">${{formatEpisodeDescription(ep.description, ep.title, ep.podcast)}}</div>
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
                        <button class="button button-primary" onclick="proceedToCostEstimate()" ${{APP_STATE.selectedEpisodes.size === 0 ? 'disabled' : ''}}>
                            Next →
                        </button>
                    </div>
                </div>
            `;
        }}
        
        function renderCostEstimate() {{
            const episodeCount = APP_STATE.selectedEpisodes.size;
            const mode = APP_STATE.configuration.transcription_mode;
            
            // Calculate estimates
            const costPerEpisode = mode === 'test' ? 0.10 : 1.50;
            const timePerEpisode = mode === 'test' ? 0.5 : 5; // minutes
            const totalCost = episodeCount * costPerEpisode;
            const totalTime = episodeCount * timePerEpisode;
            
            return `
                <div class="header">
                    <div class="logo">RW</div>
                    <div class="header-text">Cost & Time Estimate</div>
                </div>
                
                <div class="container">
                    ${{renderStageIndicator('estimate')}}
                    
                    <div class="estimate-card">
                        <div class="estimate-header">
                            <h2>Processing Estimate</h2>
                            <div class="mode-badge ${{mode}}">${{mode.toUpperCase()}} MODE</div>
                        </div>
                        
                        <div class="estimate-grid">
                            <div class="estimate-item">
                                <div class="estimate-label">Episodes Selected</div>
                                <div class="estimate-value">${{episodeCount}}</div>
                            </div>
                            
                            <div class="estimate-item">
                                <div class="estimate-label">Estimated Cost</div>
                                <div class="estimate-value">${{totalCost.toFixed(2)}}</div>
                            </div>
                            
                            <div class="estimate-item">
                                <div class="estimate-label">Estimated Time</div>
                                <div class="estimate-value">${{formatDuration(totalTime)}}</div>
                            </div>
                            
                            <div class="estimate-item">
                                <div class="estimate-label">Cost per Episode</div>
                                <div class="estimate-value">~${{costPerEpisode.toFixed(2)}}</div>
                            </div>
                        </div>
                        
                        <div class="estimate-breakdown">
                            <h3>Cost Breakdown</h3>
                            <div class="breakdown-item">
                                <span>Audio Transcription (Whisper API)</span>
                                <span>${{(episodeCount * 0.006 * (mode === 'test' ? 15 : 60)).toFixed(2)}}</span>
                            </div>
                            <div class="breakdown-item">
                                <span>Summarization (GPT-4)</span>
                                <span>${{(episodeCount * 0.03).toFixed(2)}}</span>
                            </div>
                            <div class="breakdown-item">
                                <span>Other API Calls</span>
                                <span>${{(episodeCount * 0.01).toFixed(2)}}</span>
                            </div>
                        </div>
                        
                        <div class="action-section">
                            <button class="button secondary" onclick="goBackToEpisodes()">
                                ← Back to Episodes
                            </button>
                            <button class="button primary" onclick="startProcessing()">
                                Start Processing →
                            </button>
                        </div>
                    </div>
                </div>
            `;
        }}
        
        function renderProcessing() {{
            const {{ total, completed, failed, current, startTime, errors }} = APP_STATE.processingStatus;
            const progress = total > 0 ? (completed + failed) / total * 100 : 0;
            const elapsed = startTime ? (Date.now() - startTime) / 1000 : 0;
            const rate = completed > 0 ? elapsed / completed : 0;
            const remaining = (total - completed - failed) * rate;
            
            return `
                <div class="header">
                    <div class="logo">RW</div>
                    <div class="header-text">Processing Episodes</div>
                </div>
                
                <div class="container">
                    ${{renderStageIndicator('processing')}}
                    
                    <div class="progress-card">
                        <div class="progress-header">
                            <h2>Processing Progress</h2>
                            <button class="button danger small" onclick="cancelProcessing()">
                                Cancel Processing
                            </button>
                        </div>
                        
                        <div class="progress-bar-container">
                            <div class="progress-bar" style="width: ${{progress}}%"></div>
                            <div class="progress-text">${{completed + failed}}/${{total}} episodes</div>
                        </div>
                        
                        <div class="stats-grid">
                            <div class="stat-item success">
                                <div class="stat-value">${{completed}}</div>
                                <div class="stat-label">Successful</div>
                            </div>
                            
                            <div class="stat-item danger">
                                <div class="stat-value">${{failed}}</div>
                                <div class="stat-label">Failed</div>
                            </div>
                            
                            <div class="stat-item">
                                <div class="stat-value">${{formatDuration(elapsed / 60)}}</div>
                                <div class="stat-label">Elapsed</div>
                            </div>
                            
                            <div class="stat-item">
                                <div class="stat-value">${{formatDuration(remaining / 60)}}</div>
                                <div class="stat-label">Remaining</div>
                            </div>
                        </div>
                        
                        ${{current ? `
                            <div class="current-episode">
                                <div class="current-label">Currently Processing:</div>
                                <div class="current-title">${{current.podcast}}: ${{current.title}}</div>
                                <div class="current-status">${{current.status}}</div>
                            </div>
                        ` : ''}}
                        
                        ${{errors.length > 0 ? `
                            <div class="error-section">
                                <h3>Failed Episodes</h3>
                                <div class="error-list">
                                    ${{errors.map(err => `
                                        <div class="error-item">
                                            <div class="error-title">${{err.episode}}</div>
                                            <div class="error-message">${{err.message}}</div>
                                        </div>
                                    `).join('')}}
                                </div>
                            </div>
                        ` : ''}}
                    </div>
                </div>
            `;
        }}
        
        function renderResults() {{
            const {{ total, completed, failed, errors }} = APP_STATE.processingStatus;
            const successRate = total > 0 ? (completed / total * 100).toFixed(1) : 0;
            
            return `
                <div class="header">
                    <div class="logo">RW</div>
                    <div class="header-text">Processing Results</div>
                </div>
                
                <div class="container">
                    ${{renderStageIndicator('results')}}
                    
                    <div class="results-card">
                        <div class="results-header">
                            <h2>Processing Complete</h2>
                            <div class="success-rate ${{successRate >= 90 ? 'good' : successRate >= 70 ? 'warning' : 'poor'}}">
                                ${{successRate}}% Success Rate
                            </div>
                        </div>
                        
                        <div class="results-summary">
                            <div class="result-stat success">
                                <div class="result-icon">✓</div>
                                <div class="result-count">${{completed}}</div>
                                <div class="result-label">Successful Episodes</div>
                            </div>
                            
                            <div class="result-stat danger">
                                <div class="result-icon">✗</div>
                                <div class="result-count">${{failed}}</div>
                                <div class="result-label">Failed Episodes</div>
                            </div>
                        </div>
                        
                        ${{failed > 0 ? `
                            <div class="failed-episodes">
                                <h3>Failed Episodes</h3>
                                ${{errors.map(err => `
                                    <div class="failed-item">
                                        <div class="failed-title">${{err.episode}}</div>
                                        <div class="failed-reason">${{err.message}}</div>
                                    </div>
                                `).join('')}}
                            </div>
                        ` : ''}}
                        
                        <div class="action-section">
                            <button class="button primary" onclick="proceedToEmail()">
                                Continue to Email →
                            </button>
                            
                            <button class="button text" onclick="cancelAndExit()">
                                Cancel & Exit
                            </button>
                        </div>
                    </div>
                </div>
            `;
        }}
        
        function renderEmailApproval() {{
            const {{ emailPreview }} = APP_STATE;
            const {{ completed, failed }} = APP_STATE.processingStatus;
            
            return `
                <div class="header">
                    <div class="logo">RW</div>
                    <div class="header-text">Email Approval</div>
                </div>
                
                <div class="container">
                    ${{renderStageIndicator('email')}}
                    
                    <div class="email-card">
                        <div class="email-header">
                            <h2>Review & Send Email</h2>
                        </div>
                        
                        <div class="email-stats">
                            <div class="email-stat">
                                <span class="stat-label">Episodes in digest:</span>
                                <span class="stat-value">${{completed}}</span>
                            </div>
                            ${{failed > 0 ? `
                                <div class="email-stat warning">
                                    <span class="stat-label">Episodes excluded:</span>
                                    <span class="stat-value">${{failed}}</span>
                                </div>
                            ` : ''}}
                        </div>
                        
                        <div class="email-preview">
                            <h3>Email Preview</h3>
                            <div class="preview-content">
                                ${{emailPreview ? emailPreview : 'Loading preview...'}}
                            </div>
                        </div>
                        
                        <div class="action-section">
                            <button class="button secondary" onclick="goBackToResults()">
                                ← Back to Results
                            </button>
                            
                            <button class="button primary large" onclick="sendEmail()">
                                Send Email
                            </button>
                        </div>
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
        
        function formatEpisodeTitle(title) {{
            // Extract episode number if present
            const epMatch = title.match(/^(#?\\d+\\s*[-–—|:]?\\s*|episode\\s+\\d+\\s*[-–—|:]?\\s*|ep\\.?\\s*\\d+\\s*[-–—|:]?\\s*)/i);
            if (epMatch) {{
                // Episode number found at start
                return title;
            }}
            
            // Check if there's an episode number elsewhere in the title
            const numberMatch = title.match(/(#\\d+|episode\\s+\\d+|ep\\.?\\s*\\d+)/i);
            if (numberMatch) {{
                // Move it to the front
                const num = numberMatch[0];
                const cleanTitle = title.replace(numberMatch[0], '').replace(/\\s*[-–—|:]\\s*/, ' ').trim();
                return `${{num}} - ${{cleanTitle}}`;
            }}
            
            // No episode number found, return as is
            return title;
        }}
        
        function formatEpisodeDescription(description, epTitle, podcastName) {{
            // If no description or very short, generate one from title and podcast context
            if (!description || description.length < 50) {{
                return generateDescriptionFromTitle(epTitle, podcastName);
            }}
            
            // First, try to extract key information
            let enhanced = description;
            
            // Look for host/guest patterns in description
            const guestMatch = description.match(/with\\s+([A-Z][a-zA-Z\\s]+?)(?:\\.|,|;|\\s+discusses|\\s+talks|\\s+on)/);
            const hostMatch = description.match(/hosted by\\s+([A-Z][a-zA-Z\\s]+?)(?:\\.|,|;)/i);
            
            // If no guest found in description, try to extract from title
            let guestName = null;
            if (!guestMatch) {{
                // Common patterns: "Name Name:", "with Name Name", "ft. Name Name", "featuring Name Name"
                const titleGuestMatch = epTitle.match(/(?:with|ft\\.?|featuring)\\s+([A-Z][a-zA-Z\\s]+?)(?:\\s*[-–—|,]|$)/i) ||
                                       epTitle.match(/^([A-Z][a-zA-Z\\s]+?):\\s+/) ||
                                       epTitle.match(/[-–—]\\s*([A-Z][a-zA-Z\\s]+?)(?:\\s*[-–—|,]|$)/);
                if (titleGuestMatch && titleGuestMatch[1]) {{
                    guestName = titleGuestMatch[1].trim();
                }}
            }} else {{
                guestName = guestMatch[1].trim();
            }}
            
            // Create a structured description
            let structuredDesc = '';
            
            // Add podcast-specific host info
            const hostInfo = getHostForPodcast(podcastName);
            if (hostInfo) {{
                structuredDesc += `Host: ${{hostInfo}}. `;
            }} else if (hostMatch && hostMatch[1]) {{
                structuredDesc += `Host: ${{hostMatch[1].trim()}}. `;
            }}
            
            // Add guest info
            if (guestName) {{
                structuredDesc += `Guest: ${{guestName}}. `;
            }}
            
            // Extract main topic - look for key phrases
            const topicPatterns = [
                /discusses?\\s+(.+?)(?:\\.|;|,\\s+and)/i,
                /talks?\\s+about\\s+(.+?)(?:\\.|;|,\\s+and)/i,
                /explores?\\s+(.+?)(?:\\.|;|,\\s+and)/i,
                /on\\s+(.+?)(?:\\.|;|,\\s+and)/i,
                /covering\\s+(.+?)(?:\\.|;|,\\s+and)/i,
                /about\\s+(.+?)(?:\\.|;|,\\s+and)/i
            ];
            
            let topic = null;
            for (const pattern of topicPatterns) {{
                const match = description.match(pattern);
                if (match && match[1]) {{
                    topic = match[1].trim();
                    break;
                }}
            }}
            
            // If no topic found in description, extract from title
            if (!topic) {{
                // Remove guest name and episode number from title to get topic
                let cleanTitle = epTitle;
                if (guestName) {{
                    cleanTitle = cleanTitle.replace(new RegExp(guestName + '\\\\s*:?', 'i'), '');
                }}
                cleanTitle = cleanTitle.replace(/^(#?\\d+\\s*[-–—|:]?\\s*|episode\\s+\\d+\\s*[-–—|:]?\\s*|ep\\.?\\s*\\d+\\s*[-–—|:]?\\s*)/i, '');
                cleanTitle = cleanTitle.replace(/^\\s*[-–—|:]\\s*/, '').trim();
                if (cleanTitle && cleanTitle.length > 10) {{
                    topic = cleanTitle;
                }}
            }}
            
            if (topic) {{
                structuredDesc += `Topic: ${{topic}}. `;
            }}
            
            // If we have good structured content, use it
            if (structuredDesc.length > 30) {{
                // Add any additional context from original description
                const sentences = description.match(/[^.!?]+[.!?]+/g) || [];
                const relevantSentences = sentences.filter(s => 
                    !s.match(/subscribe/i) && 
                    !s.match(/follow us/i) && 
                    !s.match(/support the show/i) &&
                    s.length > 20
                ).slice(0, 2);
                
                if (relevantSentences.length > 0) {{
                    structuredDesc += relevantSentences.join(' ').trim();
                }}
                
                return structuredDesc;
            }}
            
            // Fall back to original description with sentence limit
            const sentences = description.match(/[^.!?]+[.!?]+/g) || [];
            const cleanSentences = sentences.filter(s => 
                !s.match(/subscribe/i) && 
                !s.match(/follow us/i) && 
                !s.match(/support the show/i)
            ).slice(0, 5);
            
            return cleanSentences.join(' ').trim() || description.substring(0, 400) + '...';
        }}
        
        function generateDescriptionFromTitle(title, podcast) {{
            let desc = '';
            
            // Get host info
            const host = getHostForPodcast(podcast);
            if (host) {{
                desc += `Host: ${{host}}. `;
            }}
            
            // Extract guest from title
            const guestMatch = title.match(/(?:with|ft\\.?|featuring)\\s+([A-Z][a-zA-Z\\s]+?)(?:\\s*[-–—|,]|$)/i) ||
                              title.match(/^([A-Z][a-zA-Z\\s]+?):\\s+/) ||
                              title.match(/[-–—]\\s*([A-Z][a-zA-Z\\s]+?)(?:\\s*[-–—|,]|$)/);
            
            if (guestMatch && guestMatch[1]) {{
                desc += `Guest: ${{guestMatch[1].trim()}}. `;
            }}
            
            // Extract topic from title
            let topic = title;
            // Remove episode numbers
            topic = topic.replace(/^(#?\\d+\\s*[-–—|:]?\\s*|episode\\s+\\d+\\s*[-–—|:]?\\s*|ep\\.?\\s*\\d+\\s*[-–—|:]?\\s*)/i, '');
            // Remove guest name if found
            if (guestMatch && guestMatch[1]) {{
                topic = topic.replace(new RegExp(guestMatch[1] + '\\\\s*:?', 'i'), '');
                topic = topic.replace(/(?:with|ft\\.?|featuring)\\s*/i, '');
            }}
            topic = topic.replace(/^\\s*[-–—|:]\\s*/, '').trim();
            
            if (topic && topic.length > 10) {{
                desc += `Topic: ${{topic}}. `;
            }}
            
            // Add podcast-specific context
            const context = getPodcastContext(podcast);
            if (context && desc.length < 200) {{
                desc += context;
            }}
            
            return desc || 'Episode information not available. Check title for details.';
        }}
        
        function getHostForPodcast(podcast) {{
            const hosts = {{
                'Tim Ferriss': 'Tim Ferriss',
                'The Drive': 'Dr. Peter Attia',
                'Huberman Lab': 'Dr. Andrew Huberman',
                'Modern Wisdom': 'Chris Williamson',
                'Knowledge Project': 'Shane Parrish',
                'Dwarkesh Podcast': 'Dwarkesh Patel',
                'All-In': 'Chamath, Jason, Sacks & Friedberg',
                'No Priors': 'Elad Gil & Sarah Guo',
                'Cognitive Revolution': 'Nathan Labenz',
                'American Optimist': 'Joe Lonsdale',
                'BG2 Pod': 'Bill Gurley & Brad Gerstner',
                'Founders': 'David Senra',
                'The Doctor\\'s Farmacy': 'Dr. Mark Hyman',
                'Odd Lots': 'Joe Weisenthal & Tracy Alloway',
                'Macro Voices': 'Erik Townsend',
                'Market Huddle': 'Patrick Ceresna & Kevin Muir',
                'We Study Billionaires': 'The Investors Podcast Team',
                'Forward Guidance': 'Forward Guidance Team',
                'A16Z': 'Various a16z Partners'
            }};
            return hosts[podcast] || null;
        }}
        
        function getPodcastContext(podcast) {{
            const contexts = {{
                'Tim Ferriss': 'Deconstructing world-class performers.',
                'The Drive': 'Longevity, health optimization, and medical science.',
                'Huberman Lab': 'Neuroscience and health optimization.',
                'Modern Wisdom': 'Philosophy, psychology, and productivity.',
                'Knowledge Project': 'Decision-making and mental models.',
                'Dwarkesh Podcast': 'AI, science, and technology futures.',
                'All-In': 'Tech, markets, politics, and current events.',
                'No Priors': 'AI and startup insights.',
                'Cognitive Revolution': 'AI capabilities and impacts.',
                'American Optimist': 'Innovation, policy, and building.',
                'BG2 Pod': 'Technology and venture capital.',
                'Founders': 'Lessons from entrepreneur biographies.',
                'The Doctor\\'s Farmacy': 'Functional medicine and nutrition.',
                'Odd Lots': 'Finance, economics, and markets.',
                'Macro Voices': 'Global macro investing.',
                'Market Huddle': 'Trading and market analysis.',
                'We Study Billionaires': 'Value investing principles.',
                'Forward Guidance': 'Macro economics analysis.',
                'A16Z': 'Technology and startup insights.'
            }};
            return contexts[podcast] || '';
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
        
        function toggleEpisode(id) {{
            const safeId = id.replace(/[|:]/g, '_');
            const episode = document.getElementById('episode-' + safeId);
            if (APP_STATE.selectedEpisodes.has(id)) {{
                APP_STATE.selectedEpisodes.delete(id);
                episode.classList.remove('selected');
            }} else {{
                APP_STATE.selectedEpisodes.add(id);
                episode.classList.add('selected');
            }}
            updateEpisodeCount();
        }}
        
        function selectAllEpisodes() {{
            APP_STATE.selectedEpisodes.clear();
            APP_STATE.episodes.forEach(ep => {{
                APP_STATE.selectedEpisodes.add(ep.id);
            }});
            document.querySelectorAll('.episode-item').forEach(episode => {{
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
        
        // Function to wait for episode fetch to complete
        async function waitForEpisodeFetch() {{
            // Stop polling if we've moved past loading state
            if (APP_STATE.state !== 'loading') {{
                console.log('Stopping episode fetch polling - state is:', APP_STATE.state);
                return;
            }}
            
            try {{
                console.log('Checking if episodes are ready...');
                const stateResponse = await fetchWithTimeout('/api/state', {{}}, 5000);
                const stateData = await stateResponse.json();
                
                if (stateData.state === 'episode_selection' && stateData.episodes) {{
                    console.log(`Episodes ready! Transitioning with ${{stateData.episodes.length}} episodes`);
                    // Only update state if we're still in loading state
                    if (APP_STATE.state === 'loading') {{
                        APP_STATE.state = 'episode_selection';
                        APP_STATE.episodes = stateData.episodes;
                        render();
                    }}
                }} else {{
                    console.log('Episodes not ready yet, will check again...');
                    setTimeout(() => {{
                        waitForEpisodeFetch();
                    }}, 2000);
                }}
            }} catch (e) {{
                console.error('Error checking for episodes:', e);
                setTimeout(() => {{
                    waitForEpisodeFetch();
                }}, 2000);
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
                // Stop polling if we've moved past loading state
                if (APP_STATE.state !== 'loading') {{
                    clearInterval(APP_STATE.statusInterval);
                    APP_STATE.statusInterval = null;
                    return;
                }}
                
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
                    console.log('Fetching complete, waiting for episode data...');
                    setTimeout(async () => {{
                        try {{
                            console.log('Checking for episode selection state...');
                            const stateResponse = await fetchWithTimeout('/api/state', {{}}, 5000);
                            let stateData;
                            try {{
                                stateData = await stateResponse.json();
                            }} catch (e) {{
                                console.error('Failed to parse state data:', e);
                                return;
                            }}
                            console.log('State data received:', stateData);
                            if (stateData.state === 'episode_selection' && stateData.episodes) {{
                                console.log(`Transitioning to episode selection with ${{stateData.episodes.length}} episodes`);
                                // Only update state if we're still in loading state
                                if (APP_STATE.state === 'loading') {{
                                    APP_STATE.state = 'episode_selection';
                                    APP_STATE.episodes = stateData.episodes;
                                    render();
                                }}
                            }} else {{
                                console.log('Not ready for episode selection yet, state:', stateData.state);
                                // Retry after a delay
                                setTimeout(() => {{
                                    waitForEpisodeFetch();
                                }}, 2000);
                            }}
                        }} catch (e) {{
                            console.error('Error fetching state:', e);
                            // Retry after a delay
                            setTimeout(() => {{
                                waitForEpisodeFetch();
                            }}, 2000);
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
                case 'cost_estimate':
                    app.innerHTML = renderCostEstimate();
                    break;
                case 'processing':
                    app.innerHTML = renderProcessing();
                    break;
                case 'results':
                    app.innerHTML = renderResults();
                    break;
                case 'email_approval':
                    app.innerHTML = renderEmailApproval();
                    break;
                case 'complete':
                    app.innerHTML = renderComplete();
                    break;
                case 'error':
                    app.innerHTML = renderError();
                    break;
            }}
        }}
        
        // Helper function for stage indicator
        function renderStageIndicator(currentStage) {{
            const stages = [
                {{ id: 'podcasts', label: 'Podcasts' }},
                {{ id: 'episodes', label: 'Episodes' }},
                {{ id: 'estimate', label: 'Estimate' }},
                {{ id: 'processing', label: 'Process' }},
                {{ id: 'results', label: 'Results' }},
                {{ id: 'email', label: 'Email' }}
            ];
            
            const currentIndex = stages.findIndex(s => s.id === currentStage);
            
            return `
                <div class="stage-indicator-enhanced">
                    ${{stages.map((stage, index) => `
                        <div class="stage-wrapper">
                            <div class="stage-dot ${{index <= currentIndex ? 'active' : ''}} ${{index === currentIndex ? 'current' : ''}}"></div>
                            <div class="stage-label ${{index <= currentIndex ? 'active' : ''}}">${{stage.label}}</div>
                        </div>
                        ${{index < stages.length - 1 ? '<div class="stage-connector"></div>' : ''}}
                    `).join('')}}
                </div>
            `;
        }}
        
        // Utility functions
        function formatDuration(minutes) {{
            if (minutes < 60) {{
                return `${{Math.round(minutes)}} min`;
            }}
            const hours = Math.floor(minutes / 60);
            const mins = Math.round(minutes % 60);
            return `${{hours}}h ${{mins}}m`;
        }}
        
        // New navigation functions
        function proceedToCostEstimate() {{
            // Stop any ongoing polling
            if (APP_STATE.statusInterval) {{
                clearInterval(APP_STATE.statusInterval);
                APP_STATE.statusInterval = null;
            }}
            
            // Stop global polling when moving to client-controlled states
            if (APP_STATE.globalPollInterval) {{
                clearInterval(APP_STATE.globalPollInterval);
                APP_STATE.globalPollInterval = null;
            }}
            
            console.log('Moving to cost estimate stage');
            APP_STATE.state = 'cost_estimate';
            render();
        }}
        
        function goBackToEpisodes() {{
            APP_STATE.state = 'episode_selection';
            
            // Restart global polling when returning to server-controlled state
            if (!APP_STATE.globalPollInterval) {{
                APP_STATE.globalPollInterval = setInterval(async () => {{
                    const serverControlledStates = ['podcast_selection', 'loading', 'episode_selection'];
                    
                    if (!serverControlledStates.includes(APP_STATE.state) || 
                        APP_STATE.state === 'complete' || 
                        APP_STATE.state === 'error') {{
                        return;
                    }}
                    
                    try {{
                        const response = await fetch('/api/state');
                        const data = await response.json();
                        
                        if (serverControlledStates.includes(APP_STATE.state)) {{
                            if (data.state !== APP_STATE.state || (data.episodes && data.episodes.length > 0 && APP_STATE.episodes.length === 0)) {{
                                APP_STATE.state = data.state;
                                if (data.episodes) {{
                                    APP_STATE.episodes = data.episodes;
                                }}
                                render();
                            }}
                        }}
                    }} catch (e) {{
                        console.error('State polling error:', e);
                    }}
                }}, 1000);
            }}
            
            render();
        }}
        
        async function startProcessing() {{
            APP_STATE.state = 'processing';
            APP_STATE.processingStatus.startTime = Date.now();
            APP_STATE.processingStatus.total = APP_STATE.selectedEpisodes.size;
            render();
            
            // Start polling for status updates
            APP_STATE.statusInterval = setInterval(updateProcessingStatus, 2000);
            
            // Send start request with selected episodes
            try {{
                const response = await fetch('/api/start-processing', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{
                        episodes: Array.from(APP_STATE.selectedEpisodes),
                        mode: APP_STATE.configuration.transcription_mode
                    }})
                }});
                
                if (!response.ok) {{
                    throw new Error('Failed to start processing');
                }}
            }} catch (error) {{
                console.error('Failed to start processing:', error);
                clearInterval(APP_STATE.statusInterval);
                APP_STATE.state = 'error';
                render();
            }}
        }}
        
        async function updateProcessingStatus() {{
            try {{
                const response = await fetch('/api/processing-status');
                const status = await response.json();
                
                APP_STATE.processingStatus = {{
                    ...APP_STATE.processingStatus,
                    ...status
                }};
                
                // Check if processing is complete
                if (status.completed + status.failed >= status.total && status.total > 0) {{
                    clearInterval(APP_STATE.statusInterval);
                    APP_STATE.state = 'results';
                }}
                
                render();
            }} catch (error) {{
                console.error('Failed to update status:', error);
            }}
        }}
        
        async function cancelProcessing() {{
            if (confirm('Are you sure you want to cancel processing? This will stop all remaining episodes.')) {{
                clearInterval(APP_STATE.statusInterval);
                APP_STATE.processingCancelled = true;
                
                try {{
                    await fetch('/api/cancel-processing', {{
                        method: 'POST'
                    }});
                }} catch (error) {{
                    console.error('Failed to cancel:', error);
                }}
                
                APP_STATE.state = 'results';
                render();
            }}
        }}
        
        function proceedToEmail() {{
            APP_STATE.state = 'email_approval';
            loadEmailPreview();
            render();
        }}
        
        async function loadEmailPreview() {{
            try {{
                const response = await fetch('/api/email-preview');
                const data = await response.json();
                APP_STATE.emailPreview = data.preview;
                render();
            }} catch (error) {{
                console.error('Failed to load email preview:', error);
            }}
        }}
        
        function goBackToResults() {{
            APP_STATE.state = 'results';
            render();
        }}
        
        async function sendEmail() {{
            if (confirm('Send the email digest?')) {{
                try {{
                    const response = await fetch('/api/send-email', {{
                        method: 'POST'
                    }});
                    
                    if (response.ok) {{
                        APP_STATE.state = 'complete';
                        render();
                        setTimeout(() => window.close(), 3000);
                    }} else {{
                        alert('Failed to send email');
                    }}
                }} catch (error) {{
                    console.error('Failed to send email:', error);
                    alert('Error sending email: ' + error.message);
                }}
            }}
        }}
        
        function cancelAndExit() {{
            if (confirm('Cancel and exit? No email will be sent.')) {{
                window.close();
            }}
        }}
        
        // Initial render
        render();
        
        // Start checking for state updates after a brief delay
        setTimeout(() => {{
            APP_STATE.globalPollInterval = setInterval(async () => {{
                // Only poll server state when in server-controlled states
                const serverControlledStates = ['podcast_selection', 'loading', 'episode_selection'];
                
                if (!serverControlledStates.includes(APP_STATE.state) || 
                    APP_STATE.state === 'complete' || 
                    APP_STATE.state === 'error') {{
                    return;
                }}
                
                try {{
                    const response = await fetch('/api/state');
                    const data = await response.json();
                    
                    // Only update if we're still in a server-controlled state
                    if (serverControlledStates.includes(APP_STATE.state)) {{
                        if (data.state !== APP_STATE.state || (data.episodes && data.episodes.length > 0 && APP_STATE.episodes.length === 0)) {{
                            APP_STATE.state = data.state;
                            if (data.episodes) {{
                                APP_STATE.episodes = data.episodes;
                            }}
                            render();
                        }}
                    }}
                }} catch (e) {{
                    console.error('State polling error:', e);
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
        
        /* Enhanced UI Styles */
        .stage-indicator-enhanced {
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 32px 0;
            padding: 24px;
        }
        
        .stage-wrapper {
            display: flex;
            flex-direction: column;
            align-items: center;
            position: relative;
        }
        
        .stage-dot {
            width: 12px;
            height: 12px;
            border-radius: 50%;
            background: var(--gray-300);
            margin-bottom: 8px;
            transition: all 0.3s ease;
        }
        
        .stage-dot.active {
            background: var(--black);
        }
        
        .stage-dot.current {
            width: 16px;
            height: 16px;
            background: var(--black);
            box-shadow: 0 0 0 4px rgba(0, 0, 0, 0.1);
        }
        
        .stage-connector {
            width: 60px;
            height: 2px;
            background: var(--gray-300);
            margin: 0 8px;
            margin-top: -20px;
        }
        
        .stage-label {
            font-size: 12px;
            color: var(--gray-500);
            font-weight: 500;
        }
        
        .stage-label.active {
            color: var(--black);
            font-weight: 600;
        }
        
        /* Cost Estimate Styles */
        .estimate-card {
            background: white;
            border-radius: 16px;
            padding: 32px;
            margin: 24px auto;
            max-width: 600px;
            box-shadow: var(--shadow-medium);
        }
        
        .estimate-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 24px;
        }
        
        .estimate-header h2 {
            font-size: 24px;
            font-weight: 600;
        }
        
        .mode-badge {
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
            text-transform: uppercase;
        }
        
        .mode-badge.test {
            background: #e0f2fe;
            color: #0369a1;
        }
        
        .mode-badge.full {
            background: #dcfce7;
            color: #15803d;
        }
        
        .estimate-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-bottom: 32px;
        }
        
        .estimate-item {
            text-align: center;
            padding: 20px;
            background: var(--gray-100);
            border-radius: 12px;
        }
        
        .estimate-label {
            font-size: 14px;
            color: var(--gray-500);
            margin-bottom: 8px;
        }
        
        .estimate-value {
            font-size: 28px;
            font-weight: 600;
            color: var(--black);
        }
        
        .estimate-breakdown {
            margin-top: 24px;
            padding-top: 24px;
            border-top: 1px solid var(--gray-200);
        }
        
        .estimate-breakdown h3 {
            font-size: 16px;
            margin-bottom: 16px;
        }
        
        .breakdown-item {
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            font-size: 14px;
        }
        
        /* Progress Styles */
        .progress-card {
            background: white;
            border-radius: 16px;
            padding: 32px;
            margin: 24px auto;
            max-width: 800px;
            box-shadow: var(--shadow-medium);
        }
        
        .progress-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 24px;
        }
        
        .button.danger {
            background: #dc2626;
            color: white;
        }
        
        .button.danger:hover {
            background: #b91c1c;
        }
        
        .button.small {
            padding: 6px 16px;
            font-size: 14px;
        }
        
        .progress-bar-container {
            height: 32px;
            background: var(--gray-100);
            border-radius: 16px;
            position: relative;
            overflow: hidden;
            margin-bottom: 32px;
        }
        
        .progress-bar {
            height: 100%;
            background: var(--black);
            border-radius: 16px;
            transition: width 0.3s ease;
        }
        
        .progress-text {
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            font-weight: 600;
            color: var(--gray-700);
        }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 16px;
            margin-bottom: 32px;
        }
        
        .stat-item {
            text-align: center;
            padding: 20px;
            background: var(--gray-100);
            border-radius: 12px;
        }
        
        .stat-item.success {
            background: #dcfce7;
        }
        
        .stat-item.danger {
            background: #fee2e2;
        }
        
        .stat-value {
            font-size: 32px;
            font-weight: 700;
            margin-bottom: 4px;
        }
        
        .stat-item.success .stat-value {
            color: #15803d;
        }
        
        .stat-item.danger .stat-value {
            color: #dc2626;
        }
        
        .stat-label {
            font-size: 14px;
            color: var(--gray-500);
        }
        
        .current-episode {
            background: var(--gray-100);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 24px;
        }
        
        .current-label {
            font-size: 12px;
            color: var(--gray-500);
            margin-bottom: 8px;
        }
        
        .current-title {
            font-weight: 600;
            margin-bottom: 4px;
        }
        
        .current-status {
            font-size: 14px;
            color: var(--gray-600);
        }
        
        .error-section {
            margin-top: 24px;
            padding-top: 24px;
            border-top: 1px solid var(--gray-200);
        }
        
        .error-list {
            margin-top: 16px;
        }
        
        .error-item {
            background: #fee2e2;
            border: 1px solid #fecaca;
            border-radius: 8px;
            padding: 12px;
            margin-bottom: 8px;
        }
        
        .error-title {
            font-weight: 600;
            color: #991b1b;
            margin-bottom: 4px;
        }
        
        .error-message {
            font-size: 14px;
            color: #7f1d1d;
        }
        
        /* Results Styles */
        .results-card {
            background: white;
            border-radius: 16px;
            padding: 32px;
            margin: 24px auto;
            max-width: 700px;
            box-shadow: var(--shadow-medium);
        }
        
        .results-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 32px;
        }
        
        .success-rate {
            font-size: 20px;
            font-weight: 600;
            padding: 8px 16px;
            border-radius: 24px;
        }
        
        .success-rate.good {
            background: #dcfce7;
            color: #15803d;
        }
        
        .success-rate.warning {
            background: #fef3c7;
            color: #d97706;
        }
        
        .success-rate.poor {
            background: #fee2e2;
            color: #dc2626;
        }
        
        .results-summary {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 24px;
            margin-bottom: 32px;
        }
        
        .result-stat {
            text-align: center;
            padding: 32px;
            border-radius: 12px;
        }
        
        .result-stat.success {
            background: #dcfce7;
            border: 2px solid #86efac;
        }
        
        .result-stat.danger {
            background: #fee2e2;
            border: 2px solid #fecaca;
        }
        
        .result-icon {
            font-size: 48px;
            margin-bottom: 16px;
        }
        
        .result-stat.success .result-icon {
            color: #22c55e;
        }
        
        .result-stat.danger .result-icon {
            color: #ef4444;
        }
        
        .result-count {
            font-size: 36px;
            font-weight: 700;
            margin-bottom: 8px;
        }
        
        .result-label {
            font-size: 14px;
            color: var(--gray-500);
        }
        
        .failed-episodes {
            margin-top: 32px;
            padding-top: 32px;
            border-top: 1px solid var(--gray-200);
        }
        
        .failed-item {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 12px;
            background: var(--gray-100);
            border-radius: 8px;
            margin-bottom: 8px;
        }
        
        .failed-title {
            font-weight: 600;
            flex: 1;
        }
        
        .failed-reason {
            font-size: 14px;
            color: var(--gray-500);
            margin: 0 16px;
        }
        
        /* Email Approval Styles */
        .email-card {
            background: white;
            border-radius: 16px;
            padding: 32px;
            margin: 24px auto;
            max-width: 700px;
            box-shadow: var(--shadow-medium);
        }
        
        .email-header {
            margin-bottom: 24px;
        }
        
        .email-stats {
            display: flex;
            gap: 24px;
            margin-bottom: 32px;
            padding: 16px;
            background: var(--gray-100);
            border-radius: 12px;
        }
        
        .email-stat {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .email-stat.warning {
            color: #d97706;
        }
        
        .email-preview {
            margin-bottom: 32px;
        }
        
        .preview-content {
            margin-top: 16px;
            padding: 20px;
            background: var(--gray-100);
            border: 1px solid var(--gray-200);
            border-radius: 8px;
            font-family: monospace;
            font-size: 13px;
            line-height: 1.6;
            max-height: 300px;
            overflow-y: auto;
        }
        
        /* Button Enhancements */
        .button.large {
            padding: 16px 32px;
            font-size: 18px;
        }
        
        .button.text {
            background: none;
            color: var(--gray-500);
            padding: 12px 24px;
        }
        
        .button.text:hover {
            color: var(--gray-700);
            background: var(--gray-100);
        }
        
        .action-section {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-top: 32px;
            padding-top: 24px;
            border-top: 1px solid var(--gray-200);
        }
        """
    
    def _process_episodes_background(self):
        """Process episodes using the real processing pipeline"""
        if not self._processing_status:
            return
            
        try:
            # Import the main app to use its processing logic
            from renaissance_weekly.app import RenaissanceWeekly
            
            # Create a new app instance for processing
            app = RenaissanceWeekly()
            
            # Map episode IDs back to Episode objects
            episode_map = {}
            for ep in self.episode_cache:
                ep_id = f"{ep.podcast}|{ep.title}|{ep.published}"
                episode_map[ep_id] = ep
            
            selected_episodes = []
            for ep_id in self._processing_episodes:
                if ep_id in episode_map:
                    selected_episodes.append(episode_map[ep_id])
            
            if not selected_episodes:
                logger.error("No episodes found for processing")
                return
            
            # Store configuration for processing
            app.current_transcription_mode = self._processing_mode
            app.concurrency_manager.is_full_mode = (self._processing_mode == 'full')
            
            # Create event loop for async processing
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                # Define progress callback
                def progress_callback(episode, status, error=None):
                    if self._processing_cancelled:
                        return False  # Signal to stop processing
                    
                    if status == 'processing':
                        self._processing_status['current'] = {
                            'podcast': episode.podcast,
                            'title': episode.title,
                            'status': 'Processing...'
                        }
                    elif status == 'completed':
                        self._processing_status['completed'] += 1
                        self._processing_status['current'] = None
                    elif status == 'failed':
                        self._processing_status['failed'] += 1
                        self._processing_status['errors'].append({
                            'episode': f"{episode.podcast}|{episode.title}",
                            'message': str(error) if error else 'Failed to process episode'
                        })
                        self._processing_status['current'] = None
                    
                    return True  # Continue processing
                
                # Process episodes with progress tracking
                summaries = loop.run_until_complete(
                    app._process_episodes_with_progress(selected_episodes, progress_callback)
                )
                
                # Store summaries for email generation
                self._processed_summaries = summaries
                
            finally:
                loop.close()
                asyncio.set_event_loop(None)
                
        except Exception as e:
            logger.error(f"Processing thread error: {e}", exc_info=True)
            self._processing_status['failed'] = len(self._processing_episodes)
            self._processing_status['errors'].append({
                'episode': 'all',
                'message': f'Processing error: {str(e)}'
            })
    
    def _generate_email_preview(self):
        """Generate a preview of the email that will be sent"""
        completed = self._processing_status.get('completed', 0) if self._processing_status else 0
        failed = self._processing_status.get('failed', 0) if self._processing_status else 0
        
        # Build episode list from actual summaries
        episode_list = []
        if hasattr(self, '_processed_summaries') and self._processed_summaries:
            for item in self._processed_summaries[:5]:  # Show first 5
                episode = item['episode']
                episode_list.append(f"- {episode.podcast}: {episode.title}")
            
            if len(self._processed_summaries) > 5:
                episode_list.append(f"... and {len(self._processed_summaries) - 5} more")
        else:
            # Fallback if no summaries yet
            episode_list = ["Episodes are being processed..."]
        
        episodes_text = '\n'.join(episode_list)
        
        preview = f"""Subject: Renaissance Weekly - Your AI Podcast Digest

Hello,

Your weekly podcast digest is ready with {completed} episodes successfully processed.

Episodes included:
{episodes_text}

{f"Note: {failed} episodes could not be processed and were excluded." if failed > 0 else ""}

Best regards,
Renaissance Weekly
"""
        return preview
    
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