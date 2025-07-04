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
from ..config import PODCAST_CONFIGS, TESTING_MODE, EMAIL_TO
from ..utils.logging import get_logger

logger = get_logger(__name__)


class EpisodeSelector:
    """Single-page selection UI with seamless state transitions"""
    
    def __init__(self, db=None):
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
        self._last_episode_info = {}
        self._processing_cancelled = False
        self._email_approved = False
        self._process_thread = None
        self.db = db
        self._status_lock = threading.Lock()
    
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
        # Wait indefinitely for selection - user controls when to proceed
        self._selection_complete.wait()
        logger.info(f"[{self._correlation_id}] ✅ Selection event received")
        
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
        
        # Check if email was approved
        if self._email_approved and hasattr(self, '_final_summaries'):
            logger.info(f"[{self._correlation_id}] 📧 Email approved - returning with summaries")
            self.configuration['email_approved'] = True
            self.configuration['final_summaries'] = self._final_summaries
        
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
                            'description': ep.description if ep.description else ''
                        } for ep in parent.episode_cache]
                        response_data['selected_podcasts'] = parent.selected_podcasts
                        # Convert episode info with datetime objects to ISO format strings
                        last_info = {}
                        if hasattr(parent, '_last_episode_info') and parent._last_episode_info:
                            logger.info(f"[{parent._correlation_id}] 📋 Processing {len(parent._last_episode_info)} last episode info items")
                            for podcast, info in parent._last_episode_info.items():
                                if info and info.get('date'):
                                    last_info[podcast] = {
                                        'date': info['date'].isoformat() if hasattr(info['date'], 'isoformat') else str(info['date']),
                                        'title': info.get('title', 'Unknown')
                                    }
                                else:
                                    last_info[podcast] = None
                        else:
                            logger.warning(f"[{parent._correlation_id}] ⚠️ No _last_episode_info available on parent")
                        
                        logger.info(f"[{parent._correlation_id}] 📤 Sending last_episode_info to client: {len(last_info)} items")
                        for podcast, info in last_info.items():
                            if info:
                                logger.info(f"[{parent._correlation_id}]   ✓ {podcast}: has data")
                            else:
                                logger.info(f"[{parent._correlation_id}]   ✗ {podcast}: None")
                        response_data['last_episode_info'] = last_info
                    
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
                elif self.path == '/api/processing-status':
                    # Return current processing status
                    with parent._status_lock:
                        status = getattr(parent, '_processing_status', None)
                        if status is None:
                            status = {
                                'total': 0,
                                'completed': 0,
                                'failed': 0,
                                'currently_processing': [],
                                'errors': []
                            }
                        # Make a copy to avoid modification during serialization
                        status_copy = {
                            'total': status.get('total', 0),
                            'completed': status.get('completed', 0),
                            'failed': status.get('failed', 0),
                            'currently_processing': list(status.get('currently_processing', [])),
                            'errors': list(status.get('errors', []))
                        }
                    self._send_json(status_copy)
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
                    with parent._status_lock:
                        parent._processing_status = {
                            'total': len(data.get('episodes', [])),
                            'completed': 0,
                            'failed': 0,
                            'currently_processing': [],
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
                    
                elif self.path == '/api/cancel-processing':
                    # Cancel ongoing processing
                    parent._processing_cancelled = True
                    self._send_json({'status': 'success'})
                    
                elif self.path == '/api/email-preview':
                    # Generate email preview
                    preview = parent._generate_email_preview()
                    self._send_json({'preview': preview})
                    
                elif self.path == '/api/update-state':
                    # Update server state to match client state
                    new_state = data.get('state')
                    if new_state in ['cost_estimate', 'processing', 'results', 'email_approval']:
                        parent.state = new_state
                        self._send_json({'status': 'success', 'state': parent.state})
                    else:
                        self._send_json({'status': 'error', 'message': 'Invalid state'})
                    
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
                
                # Fetch last episode info for all selected podcasts
                if self.db and self.selected_podcasts:
                    try:
                        logger.info(f"[{self._correlation_id}] 🔍 Fetching last episode info for selected podcasts: {self.selected_podcasts}")
                        self._last_episode_info = self.db.get_last_episode_info(self.selected_podcasts)
                        logger.info(f"[{self._correlation_id}] 📅 Fetched last episode info for {len(self._last_episode_info)} podcasts")
                        # Log the actual data for debugging
                        logger.info(f"[{self._correlation_id}] 📊 Last episode info data:")
                        for podcast, info in self._last_episode_info.items():
                            if info:
                                logger.info(f"[{self._correlation_id}]   ✓ {podcast}: {info['date']} - {info['title'][:50]}...")
                            else:
                                logger.info(f"[{self._correlation_id}]   ✗ {podcast}: No episode info found")
                    except Exception as e:
                        logger.error(f"[{self._correlation_id}] ❌ Failed to fetch last episode info: {e}")
                        self._last_episode_info = {}
                
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
        console.log('Script starting...');
        
        const APP_STATE = {{
            state: '{self.state}',
            selectedPodcasts: new Set(),
            selectedEpisodes: new Set(),
            selectedPodcastNames: [],
            lastEpisodeInfo: {{}},
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
                currently_processing: [],
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
        
        console.log('APP_STATE initialized:', APP_STATE);
        
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
                        <div style="font-size: 60px; color: var(--gray-700); margin-bottom: 20px;">✗</div>
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
            
            // Find podcasts with no recent episodes
            const podcastsWithNoEpisodes = [];
            if (APP_STATE.selectedPodcastNames && APP_STATE.selectedPodcastNames.length > 0) {{
                APP_STATE.selectedPodcastNames.forEach(podcastName => {{
                    if (!episodesByPodcast[podcastName]) {{
                        podcastsWithNoEpisodes.push(podcastName);
                    }}
                }});
            }}
            console.log('Episode selection debug:');
            console.log('  - Episodes by podcast:', Object.keys(episodesByPodcast));
            console.log('  - Selected podcast names:', APP_STATE.selectedPodcastNames);
            console.log('  - Podcasts with no episodes:', podcastsWithNoEpisodes);
            console.log('  - Last episode info available:', APP_STATE.lastEpisodeInfo);
            
            // Debug: Log what lastEpisodeInfo contains for each podcast with no episodes
            podcastsWithNoEpisodes.forEach(podcast => {{
                const info = APP_STATE.lastEpisodeInfo && APP_STATE.lastEpisodeInfo[podcast];
                console.log(`Last episode info for "${{podcast}}":`, info);
            }});
            
            return `
                <div class="header">
                    <div class="logo">RW</div>
                    <div class="header-text">Choose episodes to process</div>
                </div>
                
                <div class="container">
                    ${{renderStageIndicator('episodes')}}
                    
                    ${{(function() {{
                        // Calculate and show verification banner
                        const foundPodcasts = new Set(Object.keys(episodesByPodcast));
                        const missingPodcasts = [];
                        
                        if (APP_STATE.selectedPodcastNames && APP_STATE.selectedPodcastNames.length > 0) {{
                            APP_STATE.selectedPodcastNames.forEach(podcastName => {{
                                if (!foundPodcasts.has(podcastName)) {{
                                    missingPodcasts.push(podcastName);
                                }}
                            }});
                            
                            if (missingPodcasts.length > 0) {{
                                return `
                                    <div class="verification-banner warning">
                                        <div class="verification-icon">!</div>
                                        <div class="verification-text">
                                            <strong>Some podcasts have no recent episodes</strong>
                                            <div style="margin-top: 8px; font-weight: normal;">
                                                Missing: ${{missingPodcasts.map(podcast => `<span class="missing-podcast">${{podcast}}</span>`).join(' ')}}
                                            </div>
                                        </div>
                                    </div>
                                `;
                            }} else {{
                                return `
                                    <div class="verification-banner success">
                                        <div class="verification-icon">✓</div>
                                        <div class="verification-text">
                                            <strong>All podcasts verified</strong>
                                            Episodes found for all selected podcasts in the specified time period
                                        </div>
                                    </div>
                                `;
                            }}
                        }}
                        return ''; // No banner if no selected podcasts data
                    }})()}}
                    
                    <div class="stats-bar">
                        <div class="stat">
                            <div class="stat-value">${{APP_STATE.configuration.lookback_days}}</div>
                            <div class="stat-label">Days</div>
                        </div>
                        <div class="stat">
                            <div class="stat-value">${{APP_STATE.selectedPodcastNames ? APP_STATE.selectedPodcastNames.length : 0}}</div>
                            <div class="stat-label">Podcasts Selected</div>
                        </div>
                        <div class="stat">
                            <div class="stat-value">${{Object.keys(episodesByPodcast).length}}</div>
                            <div class="stat-label">Podcasts with Episodes</div>
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
                                        <div class="episode-item ${{APP_STATE.selectedEpisodes.has(ep.id) ? 'selected' : ''}}" id="episode-${{ep.id.replace(/[|:]/g, '_')}}" onclick="toggleEpisode('${{ep.id.replace(/'/g, "\\'").replace(/"/g, '\\"')}}')">
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
                        
                        ${{podcastsWithNoEpisodes.length > 0 ? `
                            <div class="episode-section" style="opacity: 0.7;">
                                <div class="episode-header">
                                    <h3 class="episode-podcast-name">No Recent Episodes</h3>
                                    <div class="episode-count">${{podcastsWithNoEpisodes.length}} podcast${{podcastsWithNoEpisodes.length !== 1 ? 's' : ''}}</div>
                                </div>
                                <div class="episodes-list" style="padding: 16px; color: #666;">
                                    <p style="margin-bottom: 8px;">The following podcasts have no episodes in the last ${{APP_STATE.configuration.lookback_days}} days:</p>
                                    <ul style="margin: 0; padding-left: 20px;">
                                        ${{podcastsWithNoEpisodes.map(podcast => {{
                                            const episodeInfo = APP_STATE.lastEpisodeInfo && APP_STATE.lastEpisodeInfo[podcast];
                                            if (episodeInfo && episodeInfo.date) {{
                                                const date = new Date(episodeInfo.date);
                                                const daysAgo = Math.floor((new Date() - date) / (1000 * 60 * 60 * 24));
                                                const dateStr = date.toLocaleDateString('en-US', {{ month: 'long', day: 'numeric', year: 'numeric' }});
                                                return `<li><strong>${{podcast}}</strong><br>
                                                    <span style="color: #999; font-size: 0.9em; margin-left: 20px;">
                                                        Last episode: ${{dateStr}} (${{daysAgo}} days ago)<br>
                                                        <span style="margin-left: 20px;">"${{episodeInfo.title}}"</span>
                                                    </span></li>`;
                                            }} else {{
                                                return `<li><strong>${{podcast}}</strong> <span style="color: #999; font-size: 0.9em;">(no episodes found)</span></li>`;
                                            }}
                                        }}).join('')}}
                                    </ul>
                                </div>
                            </div>
                        ` : ''}}
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
                                <div class="estimate-value">$${{totalCost.toFixed(2)}}</div>
                            </div>
                            
                            <div class="estimate-item">
                                <div class="estimate-label">Estimated Time</div>
                                <div class="estimate-value">${{formatDuration(totalTime)}}</div>
                            </div>
                            
                            <div class="estimate-item">
                                <div class="estimate-label">Cost per Episode</div>
                                <div class="estimate-value">$${{costPerEpisode.toFixed(2)}}</div>
                            </div>
                        </div>
                        
                        <div class="estimate-breakdown">
                            <h3>Cost Breakdown</h3>
                            <div class="breakdown-item">
                                <span>Audio Transcription (Whisper API)</span>
                                <span>$${{(episodeCount * 0.006 * (mode === 'test' ? 15 : 60)).toFixed(2)}}</span>
                            </div>
                            <div class="breakdown-item">
                                <span>Summarization (GPT-4)</span>
                                <span>$${{(episodeCount * 0.03).toFixed(2)}}</span>
                            </div>
                            <div class="breakdown-item">
                                <span>Other API Calls</span>
                                <span>$${{(episodeCount * 0.01).toFixed(2)}}</span>
                            </div>
                            <div class="breakdown-item" style="border-top: 2px solid #e0e0e0; margin-top: 12px; padding-top: 12px; font-weight: bold;">
                                <span>Total Estimated Cost to Run</span>
                                <span>$${{totalCost.toFixed(2)}}</span>
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
            const {{ total, completed, failed, currently_processing = [], errors }} = APP_STATE.processingStatus;
            const progress = total > 0 ? ((completed + failed) / total * 100) : 0;
            const remaining = total - completed - failed;
            const estimatedMinutesRemaining = remaining * (APP_STATE.configuration.transcription_mode === 'test' ? 0.5 : 5);
            
            // Get selected episodes for display
            const selectedEpisodesArray = [];
            if (APP_STATE.selectedEpisodes.size > 0) {{
                APP_STATE.episodes.forEach(ep => {{
                    if (APP_STATE.selectedEpisodes.has(ep.id)) {{
                        selectedEpisodesArray.push(ep);
                    }}
                }});
            }}
            
            return `
                <div class="header">
                    <div class="logo">RW</div>
                    <div class="header-text">Processing Episodes</div>
                </div>
                
                <div class="container">
                    ${{renderStageIndicator('processing')}}
                    
                    <div class="progress-overview">
                        <div class="progress-ring-container">
                            <svg class="progress-ring" width="120" height="120">
                                <circle cx="60" cy="60" r="54" fill="none" stroke="var(--gray-200)" stroke-width="8"/>
                                <circle cx="60" cy="60" r="54" fill="none" stroke="var(--gray-700)" stroke-width="8"
                                    stroke-dasharray="${{339.292}}"
                                    stroke-dashoffset="${{339.292 - (339.292 * progress / 100)}}"
                                    transform="rotate(-90 60 60)"
                                    style="transition: stroke-dashoffset 0.5s ease"/>
                            </svg>
                            <div class="progress-percentage">${{Math.round(progress)}}%</div>
                        </div>
                        
                        <div class="progress-stats">
                            <div class="stat-row">
                                <span class="stat-label">Completed:</span>
                                <span class="stat-value">${{completed}} / ${{total}}</span>
                            </div>
                            <div class="stat-row">
                                <span class="stat-label">Failed:</span>
                                <span class="stat-value">${{failed}}</span>
                            </div>
                            <div class="stat-row">
                                <span class="stat-label">Remaining:</span>
                                <span class="stat-value">${{remaining}}</span>
                            </div>
                            <div class="stat-row">
                                <span class="stat-label">Est. time:</span>
                                <span class="stat-value">${{estimatedMinutesRemaining < 60 ? 
                                    Math.round(estimatedMinutesRemaining) + ' min' : 
                                    Math.round(estimatedMinutesRemaining / 60) + ' hr'}}</span>
                            </div>
                        </div>
                        
                        <div class="progress-actions">
                            <button class="button danger" onclick="cancelProcessing()">
                                Cancel Processing
                            </button>
                        </div>
                    </div>
                    
                    ${{currently_processing.length > 0 ? `
                        <div class="current-episode">
                            <div class="current-label">Currently processing (${{currently_processing.length}}):</div>
                            ${{currently_processing.map(episodeKey => {{
                                const [podcast, ...titleParts] = episodeKey.split(':');
                                const title = titleParts.join(':');
                                return `
                                    <div class="current-info">
                                        <strong>${{podcast}}</strong>
                                        <span>${{title}}</span>
                                    </div>
                                `;
                            }}).join('')}}
                        </div>
                    ` : ''}}
                    
                    <div class="episodes-progress-list">
                        <h3>Episode Status</h3>
                        ${{selectedEpisodesArray.map(ep => {{
                            // Determine status
                            let status = 'pending';
                            let statusIcon = '○';
                            let statusClass = 'pending';
                            let errorMessage = '';
                            
                            const episodeKey = `${{ep.podcast}}:${{ep.title}}`;
                            if (currently_processing.includes(episodeKey)) {{
                                status = 'processing';
                                statusIcon = '◐';
                                statusClass = 'processing';
                            }} else if (errors && errors.find(err => err.episode && err.episode.includes(ep.title))) {{
                                status = 'failed';
                                statusIcon = '✗';
                                statusClass = 'failed';
                                const error = errors.find(err => err.episode && err.episode.includes(ep.title));
                                errorMessage = error ? error.message : 'Unknown error';
                            }} else if (completed > 0) {{
                                // Simple heuristic - mark as complete if we've processed enough
                                const processedCount = completed + failed;
                                const episodeIndex = selectedEpisodesArray.indexOf(ep);
                                if (episodeIndex < processedCount && !errors.find(err => err.episode && err.episode.includes(ep.title))) {{
                                    status = 'completed';
                                    statusIcon = '✓';
                                    statusClass = 'completed';
                                }}
                            }}
                            
                            return `
                                <div class="episode-progress-item ${{statusClass}}">
                                    <div class="episode-status-icon">${{statusIcon}}</div>
                                    <div class="episode-info">
                                        <div class="episode-title">${{ep.title}}</div>
                                        <div class="episode-podcast">${{ep.podcast}}</div>
                                        ${{errorMessage ? `<div class="episode-error">${{errorMessage}}</div>` : ''}}
                                    </div>
                                </div>
                            `;
                        }}).join('')}}
                    </div>
                    
                    <style>
                        .progress-overview {{
                            display: flex;
                            align-items: center;
                            gap: 48px;
                            padding: 32px;
                            background: var(--white);
                            border: 1px solid var(--gray-200);
                            border-radius: 12px;
                            margin-bottom: 32px;
                        }}
                        
                        .progress-ring-container {{
                            position: relative;
                            flex-shrink: 0;
                        }}
                        
                        .progress-percentage {{
                            position: absolute;
                            top: 50%;
                            left: 50%;
                            transform: translate(-50%, -50%);
                            font-size: 20px;
                            font-weight: 600;
                            color: var(--black);
                        }}
                        
                        .progress-stats {{
                            flex: 1;
                        }}
                        
                        .stat-row {{
                            display: flex;
                            justify-content: space-between;
                            padding: 8px 0;
                            font-size: 14px;
                        }}
                        
                        .stat-label {{
                            color: var(--gray-600);
                        }}
                        
                        .stat-value {{
                            font-weight: 600;
                            color: var(--black);
                        }}
                        
                        .current-episode {{
                            background: var(--white);
                            padding: 16px 20px;
                            border-radius: 8px;
                            margin-bottom: 24px;
                            border: 1px solid var(--gray-200);
                            border-left: 3px solid var(--black);
                        }}
                        
                        .current-label {{
                            font-size: 12px;
                            color: var(--gray-600);
                            margin-bottom: 4px;
                        }}
                        
                        .current-info {{
                            font-size: 14px;
                            margin-bottom: 8px;
                        }}
                        
                        .current-info:last-child {{
                            margin-bottom: 0;
                        }}
                        
                        .current-info strong {{
                            color: var(--black);
                            margin-right: 8px;
                        }}
                        
                        .episodes-progress-list {{
                            margin-top: 48px;
                        }}
                        
                        .episodes-progress-list h3 {{
                            font-size: 14px;
                            font-weight: 600;
                            margin-bottom: 16px;
                            color: var(--gray-600);
                            text-transform: uppercase;
                            letter-spacing: 0.05em;
                        }}
                        
                        .episode-progress-item {{
                            display: flex;
                            align-items: flex-start;
                            gap: 12px;
                            padding: 12px 16px;
                            border-radius: 8px;
                            margin-bottom: 8px;
                            transition: all 0.3s ease;
                            background: var(--white);
                            border: 1px solid var(--gray-200);
                        }}
                        
                        .episode-progress-item.completed {{
                            opacity: 0.6;
                        }}
                        
                        .episode-progress-item.processing {{
                            border-color: var(--black);
                            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
                        }}
                        
                        .episode-progress-item.failed {{
                            border-color: var(--gray-400);
                        }}
                        
                        .episode-status-icon {{
                            font-size: 16px;
                            width: 20px;
                            text-align: center;
                            color: var(--gray-500);
                        }}
                        
                        .episode-progress-item.completed .episode-status-icon {{
                            color: var(--gray-700);
                        }}
                        
                        .episode-progress-item.processing .episode-status-icon {{
                            animation: pulse 1.5s ease-in-out infinite;
                        }}
                        
                        .episode-progress-item.failed .episode-status-icon {{
                            color: var(--black);
                        }}
                        
                        @keyframes pulse {{
                            0%, 100% {{ opacity: 1; }}
                            50% {{ opacity: 0.3; }}
                        }}
                        
                        .episode-info {{
                            flex: 1;
                        }}
                        
                        .episode-title {{
                            font-size: 14px;
                            font-weight: 500;
                            color: var(--black);
                            margin-bottom: 2px;
                        }}
                        
                        .episode-podcast {{
                            font-size: 12px;
                            color: var(--gray-600);
                        }}
                        
                        .episode-error {{
                            font-size: 12px;
                            color: var(--gray-700);
                            margin-top: 4px;
                            font-style: italic;
                        }}
                        
                        .button.danger {{
                            background: var(--gray-700);
                            color: var(--white);
                        }}
                        
                        .button.danger:hover {{
                            background: var(--black);
                        }}
                    </style>
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
                    
                    <div style="max-width: 800px; margin: 48px auto;">
                        <div style="text-align: center; margin-bottom: 48px;">
                            <h2 style="font-size: 28px; font-weight: 600; margin-bottom: 8px;">Processing Complete</h2>
                            <div style="font-size: 18px; color: ${{successRate >= 90 ? '#007AFF' : successRate >= 70 ? '#FF9500' : '#FF3B30'}};">
                                ${{successRate}}% Success Rate
                            </div>
                        </div>
                        
                        <div style="display: flex; gap: 24px; margin-bottom: 48px;">
                            <div style="flex: 1; background: #F7F7F7; border-radius: 12px; padding: 32px; text-align: center;">
                                <div style="font-size: 48px; color: #34C759; margin-bottom: 8px;">✓</div>
                                <div style="font-size: 36px; font-weight: 600; margin-bottom: 4px;">${{completed}}</div>
                                <div style="font-size: 16px; color: #666;">Successful Episodes</div>
                            </div>
                            
                            <div style="flex: 1; background: #F7F7F7; border-radius: 12px; padding: 32px; text-align: center;">
                                <div style="font-size: 48px; color: #FF3B30; margin-bottom: 8px;">✗</div>
                                <div style="font-size: 36px; font-weight: 600; margin-bottom: 4px;">${{failed}}</div>
                                <div style="font-size: 16px; color: #666;">Failed Episodes</div>
                            </div>
                        </div>
                        
                        ${{failed > 0 ? `
                            <div style="background: #FFF5F5; border: 1px solid #FFDDDD; border-radius: 12px; padding: 24px; margin-bottom: 48px;">
                                <h3 style="font-size: 18px; font-weight: 600; margin-bottom: 16px; color: #FF3B30;">Failed Episodes</h3>
                                ${{errors.map(err => `
                                    <div style="padding: 12px 0; border-bottom: 1px solid #FFDDDD;">
                                        <div style="font-weight: 500; margin-bottom: 4px;">${{err.episode}}</div>
                                        <div style="font-size: 14px; color: #666;">${{err.message}}</div>
                                    </div>
                                `).join('')}}
                            </div>
                        ` : ''}}
                        
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <button class="button secondary" onclick="cancelAndExit()">
                                Cancel & Exit
                            </button>
                            
                            <button class="button primary" onclick="proceedToEmail()">
                                Proceed to Email →
                            </button>
                        </div>
                    </div>
                </div>
            `;
        }}
        
        function renderEmailApproval() {{
            const {{ emailPreview }} = APP_STATE;
            const {{ completed, failed }} = APP_STATE.processingStatus;
            
            // Handle both old text format and new object format
            let previewContent = '';
            if (emailPreview) {{
                if (typeof emailPreview === 'object' && emailPreview.type === 'html') {{
                    // HTML preview - render in iframe for isolation
                    previewContent = `
                        <iframe 
                            id="email-preview-iframe"
                            style="width: 100%; height: 600px; border: 1px solid #ddd; border-radius: 4px; background: white;"
                            srcdoc="${{emailPreview.content.replace(/"/g, '&quot;')}}"
                        ></iframe>`;
                }} else if (typeof emailPreview === 'object' && emailPreview.type === 'text') {{
                    // Text preview
                    previewContent = `<pre style="white-space: pre-wrap; font-family: inherit;">${{emailPreview.content}}</pre>`;
                }} else {{
                    // Legacy text format
                    previewContent = `<pre style="white-space: pre-wrap; font-family: inherit;">${{emailPreview}}</pre>`;
                }}
            }} else {{
                previewContent = 'Loading preview...';
            }}
            
            return `
                <div class="header">
                    <div class="logo">RW</div>
                    <div class="header-text">Email Approval</div>
                </div>
                
                <div class="container">
                    ${{renderStageIndicator('email')}}
                    
                    <div style="max-width: 1000px; margin: 48px auto;">
                        <div style="text-align: center; margin-bottom: 32px;">
                            <h2 style="font-size: 28px; font-weight: 600;">Review & Send Email</h2>
                        </div>
                        
                        <div style="display: flex; gap: 24px; margin-bottom: 32px; justify-content: center;">
                            <div style="background: #F7F7F7; border-radius: 12px; padding: 16px 24px; text-align: center;">
                                <span style="font-size: 14px; color: #666; margin-right: 8px;">Episodes in digest:</span>
                                <span style="font-size: 18px; font-weight: 600;">${{completed}}</span>
                            </div>
                            ${{failed > 0 ? `
                                <div style="background: #FFF5F5; border-radius: 12px; padding: 16px 24px; text-align: center;">
                                    <span style="font-size: 14px; color: #666; margin-right: 8px;">Episodes excluded:</span>
                                    <span style="font-size: 18px; font-weight: 600; color: #FF3B30;">${{failed}}</span>
                                </div>
                            ` : ''}}
                        </div>
                        
                        <div style="margin-bottom: 32px;">
                            <h3 style="font-size: 18px; font-weight: 600; margin-bottom: 16px;">Email Preview</h3>
                            <div style="background: #F7F7F7; border-radius: 12px; padding: 24px; min-height: 400px;">
                                ${{previewContent}}
                            </div>
                        </div>
                        
                        <div style="display: flex; justify-content: space-between; align-items: center; gap: 16px;">
                            <button class="button secondary" style="font-size: 16px; padding: 12px 24px;" onclick="goBackToResults()">
                                ← Back to Results
                            </button>
                            
                            <button class="button primary" style="font-size: 16px; padding: 12px 32px;" onclick="sendEmail()">
                                Send Email
                            </button>
                        </div>
                    </div>
                </div>
            `;
        }}
        
        function renderComplete() {{
            // Get email from configuration or use default
            const emailTo = '{EMAIL_TO or "your email"}';
            
            return `
                <div class="header">
                    <div class="logo">RW</div>
                    <div class="header-text">Email Sent</div>
                </div>
                
                <div class="container">
                    <div class="loading-content" style="margin: 100px auto;">
                        <div style="font-size: 60px; color: #34C759; margin-bottom: 20px;">✓</div>
                        <h2>Sending email digest to ${{emailTo}}...</h2>
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
                structuredDesc += `<strong>Host:</strong> ${{hostInfo}}<br>`;
            }} else if (hostMatch && hostMatch[1]) {{
                structuredDesc += `<strong>Host:</strong> ${{hostMatch[1].trim()}}<br>`;
            }}
            
            // Add guest info
            if (guestName) {{
                structuredDesc += `<strong>Guest:</strong> ${{guestName}}<br>`;
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
                // Capitalize first letter of each sentence
                const capitalizedTopic = topic.replace(/(^\\w|\\.\\s+\\w)/g, letter => letter.toUpperCase());
                structuredDesc += `<strong>Topic:</strong> ${{capitalizedTopic}}<br>`;
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
                ).slice(0, 4);
                
                if (relevantSentences.length > 0) {{
                    structuredDesc += '<br>' + relevantSentences.join(' ').trim();
                }}
                
                return structuredDesc;
            }}
            
            // Fall back to original description with sentence limit
            const sentences = description.match(/[^.!?]+[.!?]+/g) || [];
            const cleanSentences = sentences.filter(s => 
                !s.match(/subscribe/i) && 
                !s.match(/follow us/i) && 
                !s.match(/support the show/i)
            );
            
            // Ensure we have a full paragraph worth of content
            const fullDescription = cleanSentences.join(' ').trim();
            if (fullDescription.length < 150 && description.length > fullDescription.length) {{
                // If filtered description is too short, use the original but clean it up
                return description.replace(/\\s+/g, ' ').trim();
            }}
            return fullDescription || description;
        }}
        
        function generateDescriptionFromTitle(title, podcast) {{
            let desc = '';
            
            // Get host info
            const host = getHostForPodcast(podcast);
            if (host) {{
                desc += `<strong>Host:</strong> ${{host}}<br>`;
            }}
            
            // Extract guest from title
            const guestMatch = title.match(/(?:with|ft\\.?|featuring)\\s+([A-Z][a-zA-Z\\s]+?)(?:\\s*[-–—|,]|$)/i) ||
                              title.match(/^([A-Z][a-zA-Z\\s]+?):\\s+/) ||
                              title.match(/[-–—]\\s*([A-Z][a-zA-Z\\s]+?)(?:\\s*[-–—|,]|$)/);
            
            if (guestMatch && guestMatch[1]) {{
                desc += `<strong>Guest:</strong> ${{guestMatch[1].trim()}}<br>`;
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
                // Capitalize first letter of each sentence
                const capitalizedTopic = topic.replace(/(^\\w|\\.\\s+\\w)/g, letter => letter.toUpperCase());
                desc += `<strong>Topic:</strong> ${{capitalizedTopic}}<br>`;
            }}
            
            // Always add podcast-specific context for better understanding
            const context = getPodcastContext(podcast);
            if (context) {{
                desc += `<br>This episode of ${{podcast}} explores ${{context.toLowerCase()}} `;
                
                // Add more context based on the topic
                if (topic && topic.length > 10) {{
                    desc += `The discussion focuses on ${{topic.toLowerCase()}}, providing insights and perspectives relevant to the show's core themes.`;
                }}
            }}
            
            // Ensure we have a full paragraph
            if (desc.length < 100) {{
                desc += `Episode details extracted from the title. Full description may be available in the original podcast feed.`;
            }}
            
            return desc;
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
                // Store the selected podcast names immediately so they're available in all subsequent states
                APP_STATE.selectedPodcastNames = Array.from(APP_STATE.selectedPodcasts);
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
                    console.log('Selected podcasts from server:', stateData.selected_podcasts);
                    // Only update state if we're still in loading state
                    if (APP_STATE.state === 'loading') {{
                        APP_STATE.state = 'episode_selection';
                        APP_STATE.episodes = stateData.episodes;
                        if (stateData.selected_podcasts) {{
                            APP_STATE.selectedPodcastNames = stateData.selected_podcasts;
                            console.log('Updated selectedPodcastNames:', APP_STATE.selectedPodcastNames);
                        }}
                        if (stateData.last_episode_info) {{
                            APP_STATE.lastEpisodeInfo = stateData.last_episode_info;
                            console.log('Last episode info received:', APP_STATE.lastEpisodeInfo);
                        }}
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
                                    if (stateData.selected_podcasts) {{
                                        APP_STATE.selectedPodcastNames = stateData.selected_podcasts;
                                    }}
                                    if (stateData.last_episode_info) {{
                                        APP_STATE.lastEpisodeInfo = stateData.last_episode_info;
                                    }}
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
        
        // Helper function for Apple Podcasts verification banner
        function renderVerificationBanner() {{
            console.log('Rendering verification banner.');
            console.log('  - Last episode info:', APP_STATE.lastEpisodeInfo);
            console.log('  - Selected podcast names:', APP_STATE.selectedPodcastNames);
            console.log('  - Episodes:', APP_STATE.episodes.length);
            
            // Check which podcasts were selected vs what episodes we found
            const foundPodcasts = new Set(APP_STATE.episodes.map(ep => ep.podcast));
            console.log('  - Found podcasts:', Array.from(foundPodcasts));
            
            const missingPodcasts = [];
            
            // Check each selected podcast
            if (APP_STATE.selectedPodcastNames && APP_STATE.selectedPodcastNames.length > 0) {{
                console.log('  - Checking for missing podcasts:');
                APP_STATE.selectedPodcastNames.forEach(podcastName => {{
                    if (!foundPodcasts.has(podcastName)) {{
                        console.log(`    ❌ ${{podcastName}} - NO episodes found`);
                        missingPodcasts.push(podcastName);
                    }} else {{
                        console.log(`    ✓ ${{podcastName}} - episodes found`);
                    }}
                }});
            }} else {{
                console.log('  - WARNING: selectedPodcastNames is empty, cannot check for missing podcasts');
            }}
            
            // List of sources checked for all podcasts
            const sourcesChecked = [
                'RSS Feeds',
                'Apple Podcasts API',
                'Podcast Index',
                'YouTube Transcripts',
                'Publisher Websites',
                'Spotify API'
            ];
            
            // If we don't have selected podcast names yet, don't show banner
            if (!APP_STATE.selectedPodcastNames || APP_STATE.selectedPodcastNames.length === 0) {{
                console.log('  - Not showing banner: selectedPodcastNames is empty');
                return '';
            }}
            
            // If all podcasts have episodes, show success
            if (missingPodcasts.length === 0) {{
                return `
                    <div class="verification-banner success">
                        <div class="verification-icon">✓</div>
                        <div class="verification-text">
                            <strong>All podcasts verified</strong>
                            Episodes found for all selected podcasts in the specified time period
                        </div>
                    </div>
                `;
            }}
            
            // Otherwise show warning with missing podcasts
            return `
                <div class="verification-banner warning">
                    <div class="verification-icon">!</div>
                    <div class="verification-text">
                        <strong>Some podcasts have no recent episodes</strong>
                        <div style="margin-top: 8px; font-weight: normal;">
                            Missing: ${{missingPodcasts.map(podcast => `<span class="missing-podcast">${{podcast}}</span>`).join(' ')}}
                        </div>
                    </div>
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
        async function proceedToCostEstimate() {{
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
            
            // Update server state to prevent reversion
            try {{
                await fetch('/api/update-state', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{state: 'cost_estimate'}})
                }});
            }} catch (e) {{
                console.error('Failed to update server state:', e);
            }}
            
            console.log('Moving to cost estimate stage');
            APP_STATE.state = 'cost_estimate';
            render();
        }}
        
        async function goBackToEpisodes() {{
            // Update server state when going back
            try {{
                await fetch('/api/update-state', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{state: 'episode_selection'}})
                }});
            }} catch (e) {{
                console.error('Failed to update server state:', e);
            }}
            
            APP_STATE.state = 'episode_selection';
            
            // Restart global polling when returning to server-controlled state
            if (!APP_STATE.globalPollInterval) {{
                APP_STATE.globalPollInterval = setInterval(async () => {{
                    const serverControlledStates = ['podcast_selection', 'loading'];
                    // Only include episode_selection if we haven't loaded episodes yet
                    if (APP_STATE.episodes.length === 0) {{
                        serverControlledStates.push('episode_selection');
                    }}
                    
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
            // Update server state
            try {{
                await fetch('/api/update-state', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{state: 'processing'}})
                }});
            }} catch (e) {{
                console.error('Failed to update server state:', e);
            }}
            
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
                
                // Update the display
                if (APP_STATE.state === 'processing') {{
                    render();
                }}
                
                // Check if processing is complete
                if (status.completed + status.failed >= status.total && status.total > 0) {{
                    clearInterval(APP_STATE.statusInterval);
                    
                    // Update server state
                    try {{
                        await fetch('/api/update-state', {{
                            method: 'POST',
                            headers: {{'Content-Type': 'application/json'}},
                            body: JSON.stringify({{state: 'results'}})
                        }});
                    }} catch (e) {{
                        console.error('Failed to update server state:', e);
                    }}
                    
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
        
        async function proceedToEmail() {{
            // Update server state
            try {{
                await fetch('/api/update-state', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{state: 'email_approval'}})
                }});
            }} catch (e) {{
                console.error('Failed to update server state:', e);
            }}
            
            APP_STATE.state = 'email_approval';
            loadEmailPreview();
            render();
        }}
        
        async function loadEmailPreview() {{
            try {{
                const response = await fetch('/api/email-preview', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{}})
                }});
                const data = await response.json();
                APP_STATE.emailPreview = data.preview;
                render();
            }} catch (error) {{
                console.error('Failed to load email preview:', error);
            }}
        }}
        
        async function goBackToResults() {{
            // Update server state
            try {{
                await fetch('/api/update-state', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{state: 'results'}})
                }});
            }} catch (e) {{
                console.error('Failed to update server state:', e);
            }}
            
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
                const serverControlledStates = ['podcast_selection', 'loading'];
                // Only include episode_selection if we haven't loaded episodes yet
                if (APP_STATE.state === 'episode_selection' && APP_STATE.episodes.length === 0) {{
                    serverControlledStates.push('episode_selection');
                }}
                
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
            gap: 60px;
            margin-bottom: 64px;
            padding-bottom: 48px;
            border-bottom: 1px solid var(--gray-200);
        }
        
        .stat {
            text-align: center;
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
        
        .verification-banner {
            display: flex;
            gap: 16px;
            padding: 16px 20px;
            margin-bottom: 24px;
            border-radius: 12px;
            font-size: 13px;
            align-items: flex-start;
            background: var(--gray-100);
            border: none;
            color: var(--gray-700);
            position: relative;
            overflow: hidden;
        }
        
        .verification-banner::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: linear-gradient(135deg, rgba(0,0,0,0.02) 0%, rgba(0,0,0,0) 100%);
            pointer-events: none;
        }
        
        .verification-banner.success {
            background: var(--gray-100);
        }
        
        .verification-banner.warning {
            background: var(--gray-100);
            box-shadow: inset 0 0 0 1px var(--gray-300);
        }
        
        .verification-icon {
            width: 20px;
            height: 20px;
            flex-shrink: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 14px;
            font-weight: 600;
            background: var(--gray-300);
            border-radius: 50%;
            color: var(--gray-700);
        }
        
        .verification-banner.warning .verification-icon {
            background: var(--gray-400);
            color: var(--white);
        }
        
        .verification-text {
            flex: 1;
            line-height: 1.6;
        }
        
        .verification-text strong {
            font-weight: 600;
            color: var(--black);
            display: block;
            margin-bottom: 4px;
        }
        
        .verification-sources {
            margin-top: 12px;
            display: flex;
            flex-wrap: wrap;
            gap: 12px;
        }
        
        .verification-source {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            font-size: 12px;
            color: var(--gray-600);
            background: var(--white);
            padding: 4px 10px;
            border-radius: 6px;
            border: 1px solid var(--gray-200);
        }
        
        .source-check {
            width: 14px;
            height: 14px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            font-size: 10px;
            color: var(--gray-500);
        }
        
        .missing-podcasts {
            margin: 8px 0;
            font-weight: 500;
        }
        
        .missing-podcast {
            display: inline-block;
            background: rgba(0, 0, 0, 0.1);
            padding: 2px 8px;
            border-radius: 4px;
            margin-right: 8px;
        }
        
        .verification-note {
            margin-top: 4px;
            font-size: 12px;
            color: var(--gray-500);
            font-weight: 400;
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
            from { transform: scale(1); opacity: 1; }
            to { transform: scale(1.5); opacity: 0.5; }
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
            background: white;
            border: 1px solid var(--gray-200);
            border-radius: 8px;
            overflow: hidden;
        }
        
        .preview-content pre {
            padding: 20px;
            margin: 0;
            background: var(--gray-100);
            font-family: monospace;
            font-size: 13px;
            line-height: 1.6;
            max-height: 300px;
            overflow-y: auto;
        }
        
        .preview-content iframe {
            display: block;
            width: 100%;
            border: none;
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
                    
                    with self._status_lock:
                        if status == 'processing':
                            self._processing_status['currently_processing'].append(f"{episode.podcast}:{episode.title}")
                        elif status == 'completed':
                            self._processing_status['completed'] += 1
                            episode_key = f"{episode.podcast}:{episode.title}"
                            if episode_key in self._processing_status['currently_processing']:
                                self._processing_status['currently_processing'].remove(episode_key)
                        elif status == 'failed':
                            self._processing_status['failed'] += 1
                            self._processing_status['errors'].append({
                                'episode': f"{episode.podcast}|{episode.title}",
                                'message': str(error) if error else 'Failed to process episode'
                            })
                            episode_key = f"{episode.podcast}:{episode.title}"
                            if episode_key in self._processing_status['currently_processing']:
                                self._processing_status['currently_processing'].remove(episode_key)
                    
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
            with self._status_lock:
                self._processing_status['failed'] = len(self._processing_episodes)
                self._processing_status['errors'].append({
                    'episode': 'all',
                    'message': f'Processing error: {str(e)}'
                })
    
    def _generate_email_preview(self):
        """Generate a preview of the email that will be sent"""
        completed = self._processing_status.get('completed', 0) if self._processing_status else 0
        failed = self._processing_status.get('failed', 0) if self._processing_status else 0
        
        # Check if we have summaries to preview
        if hasattr(self, '_processed_summaries') and self._processed_summaries:
            # Generate HTML preview using EmailDigest
            from ..email.digest import EmailDigest
            email_digest = EmailDigest()
            html_preview = email_digest.generate_html_preview(self._processed_summaries)
            
            # Return both text and HTML versions
            return {
                'type': 'html',
                'content': html_preview,
                'stats': {
                    'completed': completed,
                    'failed': failed
                }
            }
        else:
            # Fallback text preview if no summaries yet
            preview_text = f"""Subject: Renaissance Weekly - Your AI Podcast Digest

Hello,

Your weekly podcast digest is ready with {completed} episodes successfully processed.

{f"Note: {failed} episodes could not be processed and were excluded." if failed > 0 else ""}

Processing is still in progress...

Best regards,
Renaissance Weekly
"""
            return {
                'type': 'text',
                'content': preview_text,
                'stats': {
                    'completed': completed,
                    'failed': failed
                }
            }
    
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