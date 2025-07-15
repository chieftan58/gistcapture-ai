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
        self._fetch_cancelled = False
        self._email_approved = False
        self._process_thread = None
        self.db = db
        self._status_lock = threading.Lock()
        self._retry_episodes = []
        self._use_alternative_sources = True
        self._process_callback = None
        self._download_status = None
        self._download_thread = None
        self._episodes_to_download = []
        self._manual_download_queue = []
        self._browser_download_queue = []
        self._download_app = None  # Will hold reference to the running app
        self._expanded_episodes = set()  # Track which episodes have expanded details
    
    def run_complete_selection(self, days_back: int = 7, fetch_callback: Callable = None) -> Tuple[List[Episode], Dict]:
        """Run the complete selection process in a single page"""
        logger.info(f"[{self._correlation_id}] Starting episode selection UI")
        
        self._fetch_callback = fetch_callback
        self.configuration = {
            'lookback_days': days_back,
            'transcription_mode': 'test',  # Always start with test, user can select Full
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
                        currently_processing = status.get('currently_processing', [])
                        # Convert set to list if needed
                        if isinstance(currently_processing, set):
                            currently_processing = list(currently_processing)
                        
                        status_copy = {
                            'total': status.get('total', 0),
                            'completed': status.get('completed', 0),
                            'failed': status.get('failed', 0),
                            'currently_processing': currently_processing,
                            'errors': list(status.get('errors', []))
                        }
                    self._send_json(status_copy)
                elif self.path == '/api/download-status':
                    # Return current download status
                    with parent._status_lock:
                        status = getattr(parent, '_download_status', None)
                        if status is None:
                            status = {
                                'total': 0,
                                'downloaded': 0,
                                'retrying': 0,
                                'failed': 0,
                                'episodeDetails': {},
                                'startTime': time.time()
                            }
                        # Make a copy to avoid modification during serialization
                        status_copy = dict(status)
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
                    
                    # Reset cancellation flag and start fetching episodes in background
                    parent._fetch_cancelled = False
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
                
                elif self.path == '/api/reset-selection':
                    # Reset to initial state
                    logger.info(f"[{parent._correlation_id}] 🔄 Resetting selection state")
                    parent.state = 'podcast_selection'
                    parent._episodes = []
                    parent._selected_podcasts = []
                    parent._selected_episodes = []
                    self._send_json({'status': 'success', 'state': parent.state})
                    
                elif self.path == '/api/cancel-fetch':
                    # Cancel episode fetching
                    logger.info(f"[{parent._correlation_id}] ⏹️ Cancelling episode fetch")
                    
                    # Set cancellation flag to stop fetch thread
                    parent._fetch_cancelled = True
                    
                    # Reset state
                    parent.state = 'podcast_selection'
                    parent._episodes = []
                    parent._selected_podcasts = []
                    parent._selected_episodes = []
                    
                    self._send_json({'status': 'success', 'message': 'Fetch cancelled'})
                    
                elif self.path == '/api/retry-episodes':
                    # Retry failed episodes with alternative sources
                    failed_episodes = data.get('episodes', [])
                    use_alternative = data.get('use_alternative_sources', True)
                    
                    # Store retry request info
                    parent._retry_episodes = failed_episodes
                    parent._use_alternative_sources = use_alternative
                    parent._processing_status = {
                        'total': len(failed_episodes),
                        'completed': 0,
                        'failed': 0,
                        'currently_processing': [],
                        'errors': []
                    }
                    
                    # Start retry processing in background
                    if parent._process_callback:
                        parent._process_thread = threading.Thread(
                            target=parent._run_retry_processing,
                            args=(failed_episodes,),
                            daemon=True
                        )
                        parent._process_thread.start()
                    
                    self._send_json({'status': 'processing_started'})
                    
                elif self.path == '/api/send-email':
                    # Actually send the email instead of just setting flags
                    logger.info(f"[{parent._correlation_id}] 📧 Email send requested by user")
                    
                    # Prepare response variables
                    result = {'success': False}
                    error_message = None
                    
                    # Get summaries to send
                    summaries_to_send = []
                    
                    if hasattr(parent, '_processed_summaries') and parent._processed_summaries:
                        summaries_to_send = parent._processed_summaries
                        logger.info(f"[{parent._correlation_id}] ✅ Using {len(parent._processed_summaries)} processed summaries")
                    else:
                        # Fallback: retrieve summaries from database for successfully processed episodes
                        logger.info(f"[{parent._correlation_id}] No processed summaries in memory, retrieving from database")
                        logger.info(f"[{parent._correlation_id}] Configuration: {parent.configuration}")
                        from ..database import PodcastDatabase
                        from ..config import DB_PATH
                        logger.info(f"[{parent._correlation_id}] Using database at: {DB_PATH}")
                        db = PodcastDatabase()
                        
                        # Get recent episodes with summaries
                        lookback_days = parent.configuration.get('lookback_days', 7)
                        transcription_mode = parent.configuration.get('transcription_mode', 'test')
                        logger.info(f"[{parent._correlation_id}] Looking for episodes from last {lookback_days} days")
                        episodes_with_summaries = db.get_episodes_with_summaries(
                            days_back=lookback_days,
                            transcription_mode=transcription_mode
                        )
                        logger.info(f"[{parent._correlation_id}] Found {len(episodes_with_summaries)} episodes with summaries in database")
                        
                        # Convert database records to summary format expected by email digest
                        summaries = []
                        for i, ep in enumerate(episodes_with_summaries):
                            logger.info(f"[{parent._correlation_id}] Processing episode {i+1}: {ep.get('podcast')} - {ep.get('title', 'No title')[:50]}...")
                            # Include all episodes with summaries from the database
                            # (The user has already reviewed them on the results page)
                            # Create Episode object from database record
                            from ..models import Episode
                            from datetime import datetime
                            
                            # Parse the published date
                            published = ep['published']
                            if isinstance(published, str):
                                published = datetime.fromisoformat(published.replace('Z', '+00:00'))
                            
                            episode_obj = Episode(
                                podcast=ep['podcast'],
                                title=ep['title'],
                                published=published,
                                audio_url=ep.get('audio_url'),
                                transcript_url=ep.get('transcript_url'),
                                description=ep.get('description', ''),
                                link=ep.get('link', ''),
                                duration=ep.get('duration', ''),
                                guid=ep.get('guid', '')
                            )
                            
                            summaries.append({
                                'episode': episode_obj,
                                'summary': ep['summary']
                            })
                        
                        logger.info(f"[{parent._correlation_id}] Converted {len(summaries)} database records to summary format")
                        summaries_to_send = summaries
                    
                    # Actually send the email
                    email_sent = False
                    error_message = None
                    
                    if not summaries_to_send:
                        logger.error(f"[{parent._correlation_id}] ❌ No summaries to send! Cannot send empty email.")
                        error_message = "No content to send - no summaries found"
                    else:
                        try:
                            # Import email digest module
                            from ..email.digest import EmailDigest
                            from ..config import EMAIL_TO, EMAIL_FROM
                            
                            logger.info(f"[{parent._correlation_id}] 📧 Sending email digest...")
                            logger.info(f"[{parent._correlation_id}]    - Recipients: {EMAIL_TO}")
                            logger.info(f"[{parent._correlation_id}]    - From: {EMAIL_FROM}")
                            logger.info(f"[{parent._correlation_id}]    - Summaries: {len(summaries_to_send)}")
                            
                            # Sort summaries before sending
                            summaries_to_send = sorted(
                                summaries_to_send,
                                key=lambda x: x['episode'].published,
                                reverse=True
                            )
                            
                            # Send the email
                            email_digest = EmailDigest()
                            result = email_digest.send_digest(summaries_to_send)
                            
                            if result.get('success'):
                                logger.info(f"[{parent._correlation_id}] ✅ Email sent successfully!")
                                parent.state = "complete"
                                parent._email_approved = True
                                parent._final_summaries = summaries_to_send
                            else:
                                logger.error(f"[{parent._correlation_id}] ❌ Failed to send email")
                                error_message = result.get('error', 'Failed to send email - check logs for details')
                                
                        except Exception as e:
                            logger.error(f"[{parent._correlation_id}] ❌ Error sending email: {e}", exc_info=True)
                            error_message = str(e)
                    
                    # Send response
                    if result.get('success'):
                        self._send_json({'status': 'success', 'message': 'Email sent successfully!'})
                    else:
                        self._send_json({'status': 'error', 'message': error_message or 'Failed to send email'})
                    
                    # Signal completion after a short delay
                    if result.get('success'):
                        threading.Thread(
                            target=lambda: (time.sleep(0.5), parent._selection_complete.set()),
                            daemon=True
                        ).start()
                    
                elif self.path == '/api/start-download':
                    # Start downloading episodes
                    episode_ids = data.get('episode_ids', [])
                    transcription_mode = data.get('mode', parent.configuration.get('transcription_mode', 'test'))
                    episode_details = data.get('episode_details', {})
                    
                    # Set the processing mode for downloads
                    parent._processing_mode = transcription_mode
                    
                    # Initialize download status with episode details
                    parent._download_status = {
                        'total': len(episode_ids),
                        'downloaded': 0,
                        'retrying': 0,
                        'failed': 0,
                        'episodeDetails': {},
                        'startTime': time.time()
                    }
                    
                    # Store episode details for later use
                    parent._episode_details = episode_details
                    
                    # Map episode IDs to Episode objects
                    episode_map = {}
                    for ep in parent.episode_cache:
                        ep_id = f"{ep.podcast}|{ep.title}|{ep.published}"
                        episode_map[ep_id] = ep
                    
                    parent._episodes_to_download = []
                    for ep_id in episode_ids:
                        if ep_id in episode_map:
                            parent._episodes_to_download.append(episode_map[ep_id])
                    
                    # Start download thread
                    parent._download_thread = threading.Thread(
                        target=parent._download_episodes_background,
                        daemon=True
                    )
                    parent._download_thread.start()
                    
                    self._send_json({'status': 'success'})
                    
                elif self.path == '/api/manual-download':
                    # Handle manual URL download
                    episode_id = data.get('episode_id')
                    url = data.get('url')
                    
                    # If download is in progress, add to download manager
                    if hasattr(parent, '_download_app') and parent._download_app and hasattr(parent._download_app, '_download_manager'):
                        download_manager = parent._download_app._download_manager
                        if download_manager:
                            download_manager.add_manual_url(episode_id, url)
                            self._send_json({'status': 'processing'})
                            return
                    
                    # Otherwise, if download thread exists, retry there
                    if hasattr(parent, '_download_app') and parent._download_app:
                        # Create a task to retry the download
                        import asyncio
                        loop = parent._download_app._loop
                        if loop and not loop.is_closed():
                            # Get the download manager and trigger retry
                            dm = parent._download_app._download_manager
                            if dm:
                                # Schedule the retry in the event loop
                                future = asyncio.run_coroutine_threadsafe(
                                    dm._retry_with_manual_url(episode_id, url),
                                    loop
                                )
                                logger.info(f"[{parent._correlation_id}] Scheduled manual URL retry for {episode_id}")
                                self._send_json({'status': 'processing'})
                                return
                    
                    # If no active download manager, create a standalone download task
                    logger.info(f"[{parent._correlation_id}] Creating standalone download for manual URL")
                    parent._start_manual_download(episode_id, url)
                    self._send_json({'status': 'processing'})
                    
                elif self.path == '/api/browser-download':
                    # Handle browser-based download
                    episode_id = data.get('episode_id')
                    
                    # If download is in progress, add to download manager
                    if hasattr(parent, '_download_app') and parent._download_app and hasattr(parent._download_app, '_download_manager'):
                        download_manager = parent._download_app._download_manager
                        if download_manager:
                            download_manager.request_browser_download(episode_id)
                            self._send_json({'status': 'processing'})
                            return
                    
                    # Otherwise queue for later
                    parent._browser_download_queue.append({
                        'episode_id': episode_id
                    })
                    
                    self._send_json({'status': 'queued'})
                    
                elif self.path == '/api/debug-download':
                    # Return debug information for episode
                    episode_id = data.get('episode_id')
                    
                    # Get episode details and debug info
                    debug_info = parent._get_download_debug_info(episode_id)
                    
                    self._send_json(debug_info)
                    
                elif self.path == '/api/retry-downloads':
                    # Retry failed downloads
                    failed_episodes = data.get('failed_episodes', [])
                    
                    # Queue retry requests
                    for ep_id in failed_episodes:
                        if ep_id in parent._download_status['episodeDetails']:
                            parent._download_status['episodeDetails'][ep_id]['status'] = 'retrying'
                            parent._download_status['retrying'] += 1
                            parent._download_status['failed'] -= 1
                    
                    self._send_json({'status': 'retrying'})
                    
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
                # Check for cancellation
                if self._fetch_cancelled:
                    logger.info(f"[{self._correlation_id}] ⏹️ Fetch cancelled during progress callback")
                    return False  # Signal to stop fetching
                    
                self.loading_status = {
                    'status': 'loading',
                    'progress': index,
                    'total': total,
                    'current_podcast': podcast_name
                }
                logger.debug(f"[{self._correlation_id}] Progress: {podcast_name} ({index+1}/{total})")
                return True  # Continue fetching
            
            # Create a new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                # Check for cancellation before starting
                if self._fetch_cancelled:
                    logger.info(f"[{self._correlation_id}] ⏹️ Fetch cancelled before starting")
                    return
                
                # Call the fetch callback (it handles its own async execution)
                episodes = self._fetch_callback(
                    self.selected_podcasts,
                    self.configuration['lookback_days'],
                    progress_callback
                )
                
                # Check for cancellation after fetch
                if self._fetch_cancelled:
                    logger.info(f"[{self._correlation_id}] ⏹️ Fetch cancelled after completion")
                    return
                
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
            processingCancelled: false,
            expandedEpisodes: new Set(),  // Track expanded download details
            downloadInterval: null,  // Polling interval for download status
            downloadStatus: null  // Current download status
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
            
            // Calculate time elapsed
            let timeElapsed = '';
            if (APP_STATE.fetchStartTime) {{
                const elapsed = Math.floor((Date.now() - APP_STATE.fetchStartTime) / 1000);
                const minutes = Math.floor(elapsed / 60);
                const seconds = elapsed % 60;
                timeElapsed = minutes > 0 ? `${{minutes}}m ${{seconds}}s` : `${{seconds}}s`;
            }}
            
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
                        
                        <p class="time-elapsed">Time elapsed: ${{timeElapsed || '0s'}}</p>
                        
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
                        
                        <div style="margin-top: 30px;">
                            <button class="button secondary" onclick="cancelEpisodeFetch()">
                                Cancel
                            </button>
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
                    ${{renderModeIndicator()}}
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
                                <div class="episodes-list" style="padding-top: 1px;">
                                    ${{episodesByPodcast[podcast].map(ep => `
                                        <div class="episode-item ${{APP_STATE.selectedEpisodes.has(ep.id) ? 'selected' : ''}}" 
                                             id="episode-${{ep.id.replace(/[|:]/g, '_')}}" 
                                             data-episode-id="${{ep.id.replace(/'/g, "&apos;").replace(/"/g, "&quot;")}}"
                                             style="position: relative; pointer-events: auto;">
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
                        <button class="button secondary" onclick="backToPodcasts()">
                            ← Back
                        </button>
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
                    ${{renderModeIndicator()}}
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
                                <span>Audio Transcription</span>
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
                            <button class="button primary" onclick="startDownloading()">
                                Start Processing →
                            </button>
                        </div>
                    </div>
                </div>
            `;
        }}
        
        function renderDownload() {{
            const downloadStatus = APP_STATE.downloadStatus || {{}};
            const {{ total = 0, downloaded = 0, failed = 0, retrying = 0, episodeDetails = {{}} }} = downloadStatus;
            const remaining = total - downloaded - failed - retrying;
            const processedCount = downloaded + failed; // Both downloaded and failed count as processed
            
            // Sort episodes: Downloaded first, then in queue (retrying/downloading/pending), then failed
            const sortedEpisodes = Object.entries(episodeDetails).sort(([, a], [, b]) => {{
                const statusOrder = {{ 'downloaded': 0, 'success': 0, 'retrying': 1, 'downloading': 1, 'pending': 1, 'queued': 1, 'failed': 2 }};
                return (statusOrder[a.status] || 1) - (statusOrder[b.status] || 1);
            }});
            
            // Group episodes by status
            const failedEpisodes = sortedEpisodes.filter(([_, detail]) => detail.status === 'failed');
            const inQueueEpisodes = sortedEpisodes.filter(([_, detail]) => detail.status === 'pending' || detail.status === 'queued' || detail.status === 'retrying' || detail.status === 'downloading');
            const downloadedEpisodes = sortedEpisodes.filter(([_, detail]) => detail.status === 'downloaded' || detail.status === 'success');
            
            // Check for cookie expiration indicators
            const youtubeAuthErrors = failedEpisodes.filter(([_, detail]) => {{
                const lastError = detail.lastError || '';
                const episode = detail.episode || detail.title || '';
                const isYoutubeError = lastError.toLowerCase().includes('sign in') || 
                                     lastError.toLowerCase().includes('bot') ||
                                     lastError.toLowerCase().includes('authentication') ||
                                     lastError.toLowerCase().includes('youtube') ||
                                     (lastError.includes('403') && (episode.includes('American Optimist') || episode.includes('Dwarkesh')));
                return detail.status === 'failed' && isYoutubeError;
            }});
            
            const showCookieAlert = youtubeAuthErrors.length > 0;
            
            return `
                <div class="header">
                    <div class="logo">RW</div>
                    <div class="header-text">Downloading Audio Files</div>
                    ${{renderModeIndicator()}}
                </div>
                
                <div class="container">
                    ${{renderStageIndicator('download')}}
                    
                    ${{showCookieAlert ? `
                        <div class="cookie-alert">
                            <div class="cookie-alert-header">
                                <span class="cookie-alert-icon">🍪</span>
                                <strong>Cookie Authentication Required</strong>
                            </div>
                            <p>YouTube authentication has expired for American Optimist and/or Dwarkesh podcasts.</p>
                            
                            <div class="cookie-instructions">
                                <h4>To fix this issue:</h4>
                                
                                <ol>
                                    <li><strong>Open YouTube in your browser</strong>
                                        <ul>
                                            <li>Visit <a href="https://youtube.com" target="_blank">youtube.com</a></li>
                                            <li>Make sure you're signed in (check top right corner)</li>
                                            <li>Try playing any video to verify access</li>
                                        </ul>
                                    </li>
                                    
                                    <li><strong>Export your cookies</strong>
                                        <ul>
                                            <li>Install browser extension:
                                                <ul>
                                                    <li>Firefox: <em>"cookies.txt"</em> by Lennon Hill</li>
                                                    <li>Chrome: <em>"Get cookies.txt LOCALLY"</em></li>
                                                </ul>
                                            </li>
                                            <li>Click the extension icon while on youtube.com</li>
                                            <li>Choose "Export" or "Download"</li>
                                        </ul>
                                    </li>
                                    
                                    <li><strong>Save the cookie file</strong>
                                        <ul>
                                            <li>Save as: <code>youtube_cookies.txt</code></li>
                                            <li>Location: <code>~/.config/renaissance-weekly/cookies/</code></li>
                                        </ul>
                                    </li>
                                    
                                    <li><strong>Protect the cookies</strong>
                                        <ul>
                                            <li>Run: <code>python protect_cookies_now.py</code></li>
                                            <li>This prevents the cookies from being overwritten</li>
                                        </ul>
                                    </li>
                                </ol>
                                
                                <div class="cookie-note">
                                    <strong>Note:</strong> YouTube cookies typically expire after 2 years. The protected cookies won't be overwritten by the system.
                                </div>
                                
                                <details class="cookie-details">
                                    <summary>Alternative: Manual URL method</summary>
                                    <div class="cookie-alternative">
                                        <p>If cookie authentication continues to fail, you can:</p>
                                        <ol>
                                            <li>Download episodes manually using any method (yt-dlp, online converters, etc.)</li>
                                            <li>Click "Manual URL" on failed episodes</li>
                                            <li>Enter the local file path (e.g., <code>/home/user/downloads/episode.mp3</code>)</li>
                                        </ol>
                                    </div>
                                </details>
                            </div>
                        </div>
                    ` : ''}}
                    
                    <div class="processing-content">
                        <div class="status-overview">
                            <div class="status-card">
                                <div class="status-count">${{downloaded}}</div>
                                <div class="status-label">Downloaded</div>
                            </div>
                            
                            <div class="status-card">
                                <div class="status-count">${{remaining}}</div>
                                <div class="status-label">Remaining</div>
                            </div>
                            
                            <div class="status-card">
                                <div class="status-count">${{retrying}}</div>
                                <div class="status-label">Retrying</div>
                            </div>
                            
                            <div class="status-card">
                                <div class="status-count">${{failed}}</div>
                                <div class="status-label">Failed</div>
                            </div>
                        </div>
                        
                        <div class="progress-track">
                            <div class="progress-fill" style="width: ${{total > 0 ? (processedCount / total * 100) : 0}}%"></div>
                        </div>
                        
                        ${{processedCount < total ? `
                            <div style="text-align: center; margin: 16px 0; color: #666;">
                                <em>Processing ${{total - processedCount}} remaining episodes...</em>
                            </div>
                        ` : ''}}
                        
                        ${{remaining > 0 ? `
                            <div style="text-align: center; margin: 8px 0; color: #888; font-size: 14px;">
                                <em>The Continue button will be enabled once all episodes are downloaded or failed.</em>
                            </div>
                        ` : ''}}
                        
                        <div class="download-details">
                            ${{downloadedEpisodes.length > 0 ? `
                                <div class="episode-section">
                                    <h3>Downloaded</h3>
                                    <div class="episode-group">
                                        ${{downloadedEpisodes.map(([episodeId, detail]) => {{
                                            return renderDownloadItem(episodeId, detail);
                                        }}).join('')}}
                                    </div>
                                </div>
                            ` : ''}}
                            
                            ${{inQueueEpisodes.length > 0 ? `
                                <div class="episode-section">
                                    <h3>In Queue</h3>
                                    <div class="episode-group">
                                        ${{inQueueEpisodes.map(([episodeId, detail]) => {{
                                            return renderDownloadItem(episodeId, detail);
                                        }}).join('')}}
                                    </div>
                                </div>
                            ` : ''}}
                            
                            ${{failedEpisodes.length > 0 ? `
                                <div class="episode-section">
                                    <h3>Failed Episodes</h3>
                                    <div class="episode-group">
                                        ${{failedEpisodes.map(([episodeId, detail]) => {{
                                            return renderDownloadItem(episodeId, detail);
                                        }}).join('')}}
                                    </div>
                                </div>
                            ` : ''}}
                        </div>
                        
                        <div class="action-bar">
                            ${{failed > 0 ? `
                                <button class="button secondary" onclick="retryAllFailed()">
                                    Retry All Failed
                                </button>
                            ` : ''}}
                            
                            <button class="button danger" onclick="cancelDownloads()">
                                Cancel Downloads
                            </button>
                            
                            <button class="button primary" onclick="continueWithDownloads()" 
                                    ${{remaining > 0 ? 'disabled' : ''}}>
                                Continue
                            </button>
                        </div>
                    </div>
                </div>
                
                <style>
                    .status-overview {{
                        display: flex;
                        gap: 24px;
                        margin-bottom: 32px;
                        justify-content: center;
                    }}
                    
                    .status-card {{
                        background: #f8f8f8;
                        border-radius: 12px;
                        padding: 24px 32px;
                        text-align: center;
                        min-width: 120px;
                        border: 1px solid #e0e0e0;
                        transition: all 0.2s ease;
                    }}
                    
                    .status-card:hover {{
                        background: #f0f0f0;
                        transform: translateY(-2px);
                        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
                    }}
                    
                    .status-count {{
                        font-size: 48px;
                        font-weight: 700;
                        margin-bottom: 8px;
                        color: #333;
                    }}
                    
                    .status-label {{
                        font-size: 14px;
                        color: #666;
                        text-transform: uppercase;
                        letter-spacing: 0.5px;
                    }}
                    
                    .progress-track {{
                        width: 100%;
                        height: 8px;
                        background: #e0e0e0;
                        border-radius: 4px;
                        overflow: hidden;
                        margin-bottom: 32px;
                    }}
                    
                    .progress-fill {{
                        height: 100%;
                        background: #333;
                        border-radius: 4px;
                        transition: width 0.5s ease;
                    }}
                    
                    .download-details {{
                        margin-top: 32px;
                    }}
                    
                    .episode-section {{
                        margin-bottom: 32px;
                    }}
                    
                    .episode-section h3 {{
                        font-size: 16px;
                        font-weight: 600;
                        margin-bottom: 16px;
                        color: #333;
                    }}
                    
                    .episode-group {{
                        max-height: 300px;
                        overflow-y: auto;
                        padding-right: 8px;
                    }}
                    
                    .download-item {{
                        background: white;
                        border: 1px solid #e0e0e0;
                        border-radius: 8px;
                        padding: 16px;
                        margin-bottom: 12px;
                        cursor: pointer;
                        display: flex;
                        justify-content: space-between;
                        align-items: center;
                        position: relative;
                        z-index: 1; /* Ensure items are above background */
                    }}
                    
                    .download-item.success {{
                        border-color: #ddd;
                        background: #fafafa;
                        cursor: default;
                    }}
                    
                    .download-item.queued {{
                        border-color: #e0e0e0;
                        background: white;
                        cursor: default;
                    }}
                    
                    .download-item.retrying {{
                        border-color: #999;
                        background: #f9f9f9;
                        border-left: 4px solid #666;
                        cursor: default;
                    }}
                    
                    .download-item.failed {{
                        border-color: #666;
                        background: #f5f5f5;
                        border-left: 4px solid #333;
                        cursor: pointer !important; /* Ensure failed items are clickable */
                    }}
                    
                    .status-badge {{
                        display: flex;
                        align-items: center;
                        gap: 8px;
                        flex-shrink: 0;
                        padding: 6px 12px;
                        background: #f0f0f0;
                        border-radius: 20px;
                        font-size: 13px;
                        font-weight: 500;
                    }}
                    
                    .download-item.success .status-badge {{
                        background: #e8e8e8;
                        color: #333;
                    }}
                    
                    .download-item.queued .status-badge {{
                        background: #f5f5f5;
                        color: #666;
                    }}
                    
                    .download-item.retrying .status-badge {{
                        background: #efefef;
                        color: #444;
                    }}
                    
                    .download-item.failed .status-badge {{
                        background: #e0e0e0;
                        color: #222;
                    }}
                    
                    .status-icon {{
                        font-size: 16px;
                    }}
                    
                    .episodes-list {{
                        max-height: 500px;
                        overflow-y: auto;
                        scroll-behavior: auto; /* Disable smooth scrolling during updates */
                    }}
                    
                    .download-details-panel {{
                        background: #f5f5f5;
                        border: 1px solid #e0e0e0;
                        border-radius: 8px;
                        padding: 16px;
                        margin: -8px 0 12px 0;
                        position: relative;
                        z-index: 10;
                    }}
                    
                    /* Prevent clicks inside details panel from bubbling up */
                    .download-details-panel * {{
                        pointer-events: auto;
                    }}
                    
                    /* Prevent flashing during updates */
                    .download-item {{
                        transition: none; /* Disable transitions during polling */
                    }}
                    
                    .download-details-panel {{
                        transition: none; /* Disable transitions for details panel */
                    }}
                    
                    .download-item.expandable {{
                        cursor: pointer !important;
                        user-select: none;
                    }}
                    
                    .download-item.expandable:hover {{
                        background: #f9f9f9;
                        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                    }}
                    
                    .download-item.expandable .troubleshoot-actions {{
                        pointer-events: auto;
                    }}
                    
                    /* Ensure failed items aren't blocked by other elements */
                    .download-item.failed * {{
                        pointer-events: none;
                    }}
                    
                    .download-item.failed {{
                        pointer-events: auto !important;
                    }}
                    
                    .download-item.failed .troubleshoot-actions,
                    .download-item.failed .troubleshoot-actions * {{
                        pointer-events: auto !important;
                    }}
                    
                    .expand-icon {{
                        display: inline-block;
                        width: 16px;
                        margin-right: 8px;
                        color: #666;
                        font-size: 12px;
                        vertical-align: middle;
                    }}
                    
                    .attempt-history {{
                        margin-bottom: 16px;
                    }}
                    
                    .history-item {{
                        display: flex;
                        gap: 16px;
                        padding: 4px 0;
                        font-size: 13px;
                        color: #666;
                    }}
                    
                    .troubleshoot-actions {{
                        display: flex;
                        gap: 8px;
                        flex-wrap: wrap;
                    }}
                    
                    .troubleshoot-actions .button {{
                        font-size: 12px;
                        padding: 6px 12px;
                    }}
                    
                    /* File details styling */
                    .file-details {{
                        margin-top: 8px;
                        padding: 8px 0;
                        border-top: 1px solid #e0e0e0;
                    }}
                    
                    .duration-info {{
                        margin-bottom: 4px;
                        font-size: 13px;
                        color: #555;
                    }}
                    
                    .duration-info.duration-mismatch {{
                        font-weight: 600;
                        color: #d97706;
                    }}
                    
                    .detail-label {{
                        font-weight: 500;
                        color: #374151;
                        margin-right: 4px;
                    }}
                    
                    .detail-value {{
                        color: #6b7280;
                    }}
                    
                    .mismatch-indicator {{
                        margin-left: 4px;
                        color: #d97706;
                    }}
                    
                    .file-info {{
                        display: flex;
                        gap: 12px;
                        font-size: 12px;
                        color: #6b7280;
                    }}
                    
                    .detail-item {{
                        padding: 2px 6px;
                        background: #f3f4f6;
                        border-radius: 4px;
                        font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
                    }}
                </style>
            `;
        }}
        
        function renderProcessing() {{
            const {{ total, completed, failed, currently_processing = [], errors }} = APP_STATE.processingStatus || {{}};
            const progress = total > 0 ? ((completed + failed) / total * 100) : 0;
            const remaining = total - completed - failed;
            const estimatedMinutesRemaining = remaining * (APP_STATE.configuration.transcription_mode === 'test' ? 0.5 : 5);
            
            // Calculate time elapsed
            let timeElapsed = '';
            if (APP_STATE.processingStartTime) {{
                const elapsed = Math.floor((Date.now() - APP_STATE.processingStartTime) / 1000);
                const minutes = Math.floor(elapsed / 60);
                const seconds = elapsed % 60;
                timeElapsed = minutes > 0 ? `${{minutes}}m ${{seconds}}s` : `${{seconds}}s`;
            }}
            
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
                    <div class="header-text">Transcribing & Summarizing Episodes</div>
                    ${{renderModeIndicator()}}
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
                            ${{timeElapsed ? `
                                <div class="stat-row">
                                    <span class="stat-label">Time elapsed:</span>
                                    <span class="stat-value">${{timeElapsed}}</span>
                                </div>
                            ` : ''}}
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
            const {{ total, completed, failed, errors }} = APP_STATE.processingStatus || {{}};
            const successRate = total > 0 ? (completed / total * 100).toFixed(1) : 0;
            
            return `
                <div class="header">
                    <div class="logo">RW</div>
                    <div class="header-text">Processing Results</div>
                    ${{renderModeIndicator()}}
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
                            
                            <button class="button primary" onclick="proceedToEmail()" ${{completed < 1 ? 'disabled' : ''}}>
                                ${{completed < 1 ? 'No Episodes Processed' : 'Proceed to Email'}}
                            </button>
                        </div>
                    </div>
                </div>
            `;
        }}
        
        function renderReview() {{
            const {{ completed, failed, errors }} = APP_STATE.processingStatus;
            
            // Group errors by type for better retry strategies
            const errorGroups = {{
                cloudflare: [],
                timeout: [],
                transcription: [],
                other: []
            }};
            
            errors.forEach(err => {{
                if (err.message.includes('403') || err.message.includes('Cloudflare')) {{
                    errorGroups.cloudflare.push(err);
                }} else if (err.message.includes('timeout') || err.message.includes('Timeout')) {{
                    errorGroups.timeout.push(err);
                }} else if (err.message.includes('transcript') || err.message.includes('Transcription')) {{
                    errorGroups.transcription.push(err);
                }} else {{
                    errorGroups.other.push(err);
                }}
            }});
            
            return `
                <div class="header">
                    <div class="logo">RW</div>
                    <div class="header-text">Review & Retry</div>
                </div>
                
                <div class="container">
                    ${{renderStageIndicator('review')}}
                    
                    <div style="max-width: 800px; margin: 48px auto;">
                        <div style="text-align: center; margin-bottom: 48px;">
                            <h2 style="font-size: 28px; font-weight: 600; margin-bottom: 16px;">Review Results</h2>
                            <div style="font-size: 18px; color: #666;">
                                ✅ Successfully Processed: ${{completed}} episodes<br>
                                ❌ Failed: ${{failed}} episodes
                            </div>
                        </div>
                        
                        ${{failed > 0 ? `
                            <div style="background: #FFF5F5; border: 1px solid #FFDDDD; border-radius: 12px; padding: 24px; margin-bottom: 48px;">
                                <h3 style="font-size: 18px; font-weight: 600; margin-bottom: 16px; color: #FF3B30;">Failed Episodes</h3>
                                
                                ${{errorGroups.cloudflare.length > 0 ? `
                                    <div style="margin-bottom: 24px;">
                                        <h4 style="font-size: 16px; font-weight: 600; margin-bottom: 12px;">Cloudflare Protection (${{errorGroups.cloudflare.length}} episodes)</h4>
                                        ${{errorGroups.cloudflare.map(err => `
                                            <div style="padding: 8px 0; border-bottom: 1px solid #FFDDDD;">
                                                <div style="font-weight: 500;">${{err.episode}}</div>
                                                <div style="font-size: 14px; color: #666;">→ Will retry with: YouTube search, Browser automation</div>
                                            </div>
                                        `).join('')}}
                                    </div>
                                ` : ''}}
                                
                                ${{errorGroups.timeout.length > 0 ? `
                                    <div style="margin-bottom: 24px;">
                                        <h4 style="font-size: 16px; font-weight: 600; margin-bottom: 12px;">Download Timeout (${{errorGroups.timeout.length}} episodes)</h4>
                                        ${{errorGroups.timeout.map(err => `
                                            <div style="padding: 8px 0; border-bottom: 1px solid #FFDDDD;">
                                                <div style="font-weight: 500;">${{err.episode}}</div>
                                                <div style="font-size: 14px; color: #666;">→ Will retry with: Direct CDN, Extended timeout (120s)</div>
                                            </div>
                                        `).join('')}}
                                    </div>
                                ` : ''}}
                                
                                ${{errorGroups.transcription.length > 0 ? `
                                    <div style="margin-bottom: 24px;">
                                        <h4 style="font-size: 16px; font-weight: 600; margin-bottom: 12px;">Transcription Failed (${{errorGroups.transcription.length}} episodes)</h4>
                                        ${{errorGroups.transcription.map(err => `
                                            <div style="padding: 8px 0; border-bottom: 1px solid #FFDDDD;">
                                                <div style="font-weight: 500;">${{err.episode}}</div>
                                                <div style="font-size: 14px; color: #666;">→ Will retry with: Full audio transcription</div>
                                            </div>
                                        `).join('')}}
                                    </div>
                                ` : ''}}
                                
                                ${{errorGroups.other.length > 0 ? `
                                    <div style="margin-bottom: 24px;">
                                        <h4 style="font-size: 16px; font-weight: 600; margin-bottom: 12px;">Other Errors (${{errorGroups.other.length}} episodes)</h4>
                                        ${{errorGroups.other.map(err => `
                                            <div style="padding: 8px 0; border-bottom: 1px solid #FFDDDD;">
                                                <div style="font-weight: 500;">${{err.episode}}</div>
                                                <div style="font-size: 14px; color: #666;">${{err.message}}</div>
                                            </div>
                                        `).join('')}}
                                    </div>
                                ` : ''}}
                                
                                <div style="background: #F0F8FF; border: 1px solid #B3D9FF; border-radius: 8px; padding: 16px; margin-top: 16px;">
                                    <p style="margin: 0; font-size: 14px; color: #0066CC;">
                                        <strong>Note:</strong> Retry will use different download sources and strategies. 
                                        Most failures can be resolved with alternative methods.
                                    </p>
                                </div>
                            </div>
                        ` : ''}}
                        
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <button class="button secondary" onclick="cancelAndExit()">
                                Cancel & Exit
                            </button>
                            
                            <div style="display: flex; gap: 12px;">
                                ${{failed > 0 ? `
                                    <button class="button secondary" onclick="retryFailedEpisodes()">
                                        Retry Failed Episodes
                                    </button>
                                ` : ''}}
                                
                                <button class="button primary" onclick="proceedToEmail()" ${{completed < 1 ? 'disabled' : ''}}>
                                    ${{completed < 1 ? 'No Episodes Processed' : 'Proceed to Email'}}
                                </button>
                            </div>
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
                    ${{renderModeIndicator()}}
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
            const message = APP_STATE.emailMessage || 'Email sent successfully!';
            
            return `
                <div class="header">
                    <div class="logo">RW</div>
                    <div class="header-text">Email Sent</div>
                    ${{renderModeIndicator()}}
                </div>
                
                <div class="container">
                    <div class="loading-content" style="margin: 100px auto;">
                        <div style="font-size: 60px; color: #34C759; margin-bottom: 20px;">✓</div>
                        <h2>${{message}}</h2>
                        <p style="margin-top: 10px; color: #666;">Sent to: ${{emailTo}}</p>
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
            const epMatch = title.match(/^(#?\\\\d+\\\\s*[-–—|:]?\\\\s*|episode\\\\s+\\\\d+\\\\s*[-–—|:]?\\\\s*|ep\\\\.?\\\\s*\\\\d+\\\\s*[-–—|:]?\\\\s*)/i);
            if (epMatch) {{
                // Episode number found at start
                return title;
            }}
            
            // Check if there's an episode number elsewhere in the title
            const numberMatch = title.match(/(#\\\\d+|episode\\\\s+\\\\d+|ep\\\\.?\\\\s*\\\\d+)/i);
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
                cleanTitle = cleanTitle.replace(/^(#?\\\\d+\\\\s*[-–—|:]?\\\\s*|episode\\\\s+\\\\d+\\\\s*[-–—|:]?\\\\s*|ep\\\\.?\\\\s*\\\\d+\\\\s*[-–—|:]?\\\\s*)/i, '');
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
            topic = topic.replace(/^(#?\\\\d+\\\\s*[-–—|:]?\\\\s*|episode\\\\s+\\\\d+\\\\s*[-–—|:]?\\\\s*|ep\\\\.?\\\\s*\\\\d+\\\\s*[-–—|:]?\\\\s*)/i, '');
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
        
        function toggleEpisode(id, event) {{
            console.log('toggleEpisode called with id:', id);
            
            // Prevent event bubbling and default behavior
            if (event) {{
                event.stopPropagation();
                event.preventDefault();
            }}
            
            const safeId = id.replace(/[|:]/g, '_');
            const episode = document.getElementById('episode-' + safeId);
            
            if (!episode) {{
                console.error('Episode element not found:', safeId);
                return;
            }}
            
            if (APP_STATE.selectedEpisodes.has(id)) {{
                APP_STATE.selectedEpisodes.delete(id);
                episode.classList.remove('selected');
                console.log('Episode deselected:', id);
            }} else {{
                APP_STATE.selectedEpisodes.add(id);
                episode.classList.add('selected');
                console.log('Episode selected:', id);
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
                APP_STATE.fetchStartTime = Date.now();  // Track when fetching started
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
            }}, 3000);  // Reduced polling frequency from 1s to 3s
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
                    
                    // Update time elapsed
                    if (APP_STATE.fetchStartTime) {{
                        const elapsed = Math.floor((Date.now() - APP_STATE.fetchStartTime) / 1000);
                        const minutes = Math.floor(elapsed / 60);
                        const seconds = elapsed % 60;
                        const timeElapsed = minutes > 0 ? `${{minutes}}m ${{seconds}}s` : `${{seconds}}s`;
                        const timeElapsedElement = document.querySelector('.time-elapsed');
                        if (timeElapsedElement) {{
                            timeElapsedElement.textContent = `Time elapsed: ${{timeElapsed}}`;
                        }}
                    }}
                    
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
                    }}, 1000);  // Keep at 1s for initial fetch completion
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
            }}, 3000);  // Reduced polling frequency from 1s to 3s
        }}
        
        // Helper function for rendering download items
        function renderDownloadItem(episodeId, detail) {{
            const statusClass = (detail.status === 'downloaded' || detail.status === 'success') ? 'success' : (detail.status === 'failed' ? 'failed' : (detail.status === 'retrying' ? 'retrying' : 'queued'));
            const statusText = (detail.status === 'downloaded' || detail.status === 'success') ? 'Downloaded' : (detail.status === 'failed' ? 'Failed' : (detail.status === 'retrying' ? 'Downloading...' : 'In Queue'));
            const statusIcon = (detail.status === 'downloaded' || detail.status === 'success') ? '✓' : (detail.status === 'failed' ? '✗' : (detail.status === 'retrying' ? '↻' : '•'));
            
            // Format duration info
            function formatDuration(durationValue) {{
                // Handle string duration from episodes page (e.g., "1h 23m")
                if (typeof durationValue === 'string' && durationValue && durationValue !== 'Unknown') {{
                    return durationValue;
                }}
                // Handle numeric minutes
                if (typeof durationValue === 'number' && !isNaN(durationValue)) {{
                    const hours = Math.floor(durationValue / 60);
                    const mins = Math.round(durationValue % 60);
                    if (hours > 0) {{
                        return `${{hours}}h ${{mins}}m`;
                    }} else {{
                        return `${{mins}}m`;
                    }}
                }}
                return 'N/A';
            }}
            
            // Check for duration mismatch (downloaded significantly shorter than expected)
            function isDurationMismatch(expected, downloaded) {{
                if (!expected || !downloaded || expected === 'Unknown' || downloaded === 'Unknown') return false;
                const expectedMins = typeof expected === 'string' ? parseDuration(expected) : expected;
                const downloadedMins = typeof downloaded === 'string' ? parseDuration(downloaded) : downloaded;
                if (!expectedMins || !downloadedMins) return false;
                // Consider it a mismatch if downloaded is less than 50% of expected (indicates test mode or partial download)
                return downloadedMins < (expectedMins * 0.5);
            }}
            
            function parseDuration(durationStr) {{
                if (!durationStr) return null;
                const match = durationStr.match(/(\\d+)h\\s*(\\d+)m|(\\d+)m/);
                if (match) {{
                    if (match[1] && match[2]) {{
                        return parseInt(match[1]) * 60 + parseInt(match[2]);
                    }} else if (match[3]) {{
                        return parseInt(match[3]);
                    }}
                }}
                return null;
            }}
            
            // Format file size
            function formatFileSize(bytes) {{
                if (!bytes) return 'Unknown';
                if (bytes < 1024 * 1024) {{
                    return `${{(bytes / 1024).toFixed(1)}}KB`;
                }} else {{
                    return `${{(bytes / (1024 * 1024)).toFixed(1)}}MB`;
                }}
            }}
            
            const expectedDuration = detail.metadata?.duration || detail.expectedDuration;
            const downloadedDuration = detail.downloadedDuration;
            const fileSize = detail.fileSize;
            const downloadSource = detail.downloadSource || detail.source;
            const audioFormat = detail.audioFormat || detail.format;
            
            const hasMismatch = isDurationMismatch(expectedDuration, downloadedDuration);
            
            return `
                <div class="download-item ${{statusClass}} ${{detail.status === 'failed' ? 'expandable' : ''}}" 
                     ${{detail.status === 'failed' ? `data-episode-id="${{episodeId.replace(/"/g, '&quot;')}}" data-clickable="true" onclick="toggleDownloadDetails('${{episodeId.replace(/'/g, "\\\\'")}}', event)"` : ''}}>
                    <div class="episode-info">
                        <div class="episode-title">
                            ${{detail.status === 'failed' ? `<span id="toggle-${{episodeId}}" class="expand-icon">${{APP_STATE.expandedEpisodes && APP_STATE.expandedEpisodes.has(episodeId) ? '▼' : '▶'}}</span>` : ''}}
                            ${{detail.episode || detail.title || episodeId}}
                        </div>
                        
                        ${{(detail.status === 'downloaded' || detail.status === 'success') ? `
                            <div class="file-details">
                                <div class="duration-info ${{hasMismatch ? 'duration-mismatch' : ''}}">
                                    <span class="detail-label">Duration:</span>
                                    <span class="detail-value">Full Podcast: ${{formatDuration(expectedDuration)}} | Downloaded: ${{formatDuration(downloadedDuration)}}</span>
                                    ${{hasMismatch ? ' <span class="mismatch-indicator">⚠️</span>' : ' ✅'}}
                                </div>
                                <div class="file-info">
                                    <span class="detail-item">${{formatFileSize(fileSize)}}</span>
                                    ${{downloadSource ? `<span class="detail-item">${{downloadSource}}</span>` : ''}}
                                    ${{audioFormat ? `<span class="detail-item">${{audioFormat.toUpperCase()}}</span>` : ''}}
                                </div>
                            </div>
                        ` : ''}}
                        
                        ${{detail.status === 'failed' ? `<div class="error-message">${{detail.lastError}}</div>` : ''}}
                        ${{detail.status === 'retrying' ? `<div class="attempt-info">Attempt ${{detail.attemptCount}} - ${{detail.currentStrategy}}</div>` : ''}}
                    </div>
                    <div class="status-badge">
                        <span class="status-icon">${{statusIcon}}</span>
                        <span class="status-text">${{statusText}}</span>
                    </div>
                </div>
                ${{detail.status === 'failed' ? `
                    <div id="details-${{episodeId}}" class="download-details-panel" style="display: ${{APP_STATE.expandedEpisodes && APP_STATE.expandedEpisodes.has(episodeId) ? 'block' : 'none'}};" onclick="event.stopPropagation()" onmousedown="event.stopPropagation()">
                        <div class="attempt-history">
                            <h4>Attempt History:</h4>
                            ${{(detail.history || []).map(h => `
                                <div class="history-item">
                                    <span class="timestamp">${{new Date(h.timestamp).toLocaleTimeString()}}</span>
                                    <span class="strategy">${{h.strategy}}</span>
                                    <span class="error">${{h.error}}</span>
                                </div>
                            `).join('')}}
                        </div>
                        <div class="troubleshoot-actions">
                            <button class="button secondary" onclick="viewDetailedLogs('${{episodeId}}')">View Logs</button>
                            <button class="button secondary" onclick="tryManualUrl('${{episodeId}}')">Manual URL</button>
                            <button class="button secondary" onclick="tryBrowserDownload('${{episodeId}}')">Try Browser</button>
                            <button class="button secondary" onclick="enableDebugMode('${{episodeId}}')">Debug Mode</button>
                        </div>
                    </div>
                ` : ''}}
            `;
        }}
        
        // Main render function
        function render() {{
            const app = document.getElementById('app');
            
            // Save scroll positions before render (for download state)
            let savedScrollPositions = {{}};
            if (APP_STATE.state === 'download') {{
                // Find all scrollable sections
                const scrollableSections = app.querySelectorAll('.episode-group');
                scrollableSections.forEach((section, index) => {{
                    savedScrollPositions[index] = section.scrollTop;
                }});
            }}
            
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
                case 'download':
                    app.innerHTML = renderDownload();
                    // Restore scroll positions after render
                    setTimeout(() => {{
                        const scrollableSections = app.querySelectorAll('.episode-group');
                        scrollableSections.forEach((section, index) => {{
                            if (savedScrollPositions[index] !== undefined) {{
                                section.scrollTop = savedScrollPositions[index];
                            }}
                        }});
                    }}, 0);
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
        function renderModeIndicator() {{
            const mode = APP_STATE.configuration.transcription_mode;
            const modeText = mode === 'test' ? 'Test Mode' : 'Full Mode';
            const modeDesc = mode === 'test' ? '15 minutes' : 'Complete episodes';
            
            return `
                <div class="mode-indicator">
                    <span class="mode-badge ${{mode}}">
                        ${{modeText}}
                    </span>
                    <span class="mode-description">${{modeDesc}}</span>
                </div>
            `;
        }}
        
        function renderStageIndicator(currentStage) {{
            const stages = [
                {{ id: 'podcasts', label: 'Podcasts' }},
                {{ id: 'episodes', label: 'Episodes' }},
                {{ id: 'estimate', label: 'Estimate' }},
                {{ id: 'download', label: 'Download' }},
                {{ id: 'processing', label: 'Transcribe & Summarize' }},
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
            if (!minutes || isNaN(minutes)) return 'N/A';
            if (minutes < 60) {{
                return `${{Math.round(minutes)}} min`;
            }}
            const hours = Math.floor(minutes / 60);
            const mins = Math.round(minutes % 60);
            return `${{hours}}h ${{mins}}m`;
        }}
        
        // New navigation functions
        async function backToPodcasts() {{
            // Clear selected episodes
            APP_STATE.selectedEpisodes.clear();
            
            // Clear selected podcasts to truly reset
            APP_STATE.selectedPodcasts.clear();
            
            // Stop any polling intervals
            if (APP_STATE.globalPollInterval) {{
                clearInterval(APP_STATE.globalPollInterval);
                APP_STATE.globalPollInterval = null;
            }}
            
            // Reset server state by signaling a reset
            try {{
                await fetch('/api/reset-selection', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{}})
                }});
            }} catch (e) {{
                console.error('Failed to reset server state:', e);
            }}
            
            // Go back to podcast selection state
            APP_STATE.state = 'podcast_selection';
            APP_STATE.episodes = [];
            APP_STATE.selectedPodcastNames = [];
            render();
        }}
        
        async function cancelEpisodeFetch() {{
            // Stop any polling intervals
            if (APP_STATE.statusInterval) {{
                clearInterval(APP_STATE.statusInterval);
                APP_STATE.statusInterval = null;
            }}
            
            if (APP_STATE.globalPollInterval) {{
                clearInterval(APP_STATE.globalPollInterval);
                APP_STATE.globalPollInterval = null;
            }}
            
            // Signal server to cancel the fetch
            try {{
                await fetch('/api/cancel-fetch', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{}})
                }});
            }} catch (e) {{
                console.error('Failed to cancel fetch:', e);
            }}
            
            // Reset state and go back to podcast selection
            APP_STATE.state = 'podcast_selection';
            APP_STATE.episodes = [];
            APP_STATE.selectedEpisodes.clear();
            APP_STATE.selectedPodcastNames = [];
            APP_STATE.loading_status = {{
                completed: 0,
                total: 0,
                error: null,
                podcasts: []
            }};
            
            render();
        }}
        
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
                }}, 3000);  // Reduced polling frequency from 1s to 3s
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
                if (!response.ok) {{
                    throw new Error(`Status update failed: ${{response.status}}`);
                }}
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
                    
                    // Make sure we have the final status
                    APP_STATE.processingStatus = {{
                        ...APP_STATE.processingStatus,
                        ...status
                    }};
                    
                    // Log the final status for debugging
                    console.log('Final processing status:', APP_STATE.processingStatus);
                    
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
        
        async function proceedToReview() {{
            // Update server state
            try {{
                await fetch('/api/update-state', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{state: 'review'}})
                }});
            }} catch (e) {{
                console.error('Failed to update server state:', e);
            }}
            
            APP_STATE.state = 'review';
            render();
        }}
        
        // Download stage functions
        async function startDownloading() {{
            APP_STATE.state = 'download';
            APP_STATE.downloadStatus = {{
                total: APP_STATE.selectedEpisodes.size,
                downloaded: 0,
                retrying: 0,
                failed: 0,
                episodeDetails: {{}},
                startTime: Date.now()
            }};
            render();
            
            try {{
                // Build episode details with duration info
                const selectedEpisodeDetails = {{}};
                APP_STATE.episodes.forEach(ep => {{
                    if (APP_STATE.selectedEpisodes.has(ep.id)) {{
                        selectedEpisodeDetails[ep.id] = {{
                            duration: ep.duration,
                            title: ep.title,
                            podcast: ep.podcast
                        }};
                    }}
                }});
                
                const response = await fetch('/api/start-download', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{
                        episode_ids: Array.from(APP_STATE.selectedEpisodes),
                        mode: APP_STATE.configuration.transcription_mode,
                        episode_details: selectedEpisodeDetails
                    }})
                }});
                
                if (!response.ok) {{
                    throw new Error('Failed to start download');
                }}
                
                // Start polling for download progress
                startDownloadPolling();
                
            }} catch (error) {{
                console.error('Failed to start downloads:', error);
                alert('Failed to start downloads. Please try again.');
                APP_STATE.state = 'cost_estimate';
                render();
            }}
        }}
        
        async function startDownloadPolling() {{
            APP_STATE.downloadInterval = setInterval(async () => {{
                try {{
                    const response = await fetch('/api/download-status');
                    const status = await response.json();
                    
                    // Preserve expanded episodes state during updates
                    const previousExpanded = APP_STATE.expandedEpisodes || new Set();
                    
                    APP_STATE.downloadStatus = {{
                        ...APP_STATE.downloadStatus,
                        ...status
                    }};
                    
                    // Restore expanded state
                    APP_STATE.expandedEpisodes = previousExpanded;
                    
                    // Update the display
                    if (APP_STATE.state === 'download') {{
                        // Save scroll position before render
                        const container = document.querySelector('.episodes-list');
                        const scrollTop = container ? container.scrollTop : 0;
                        
                        render();
                        
                        // Restore scroll position after render
                        requestAnimationFrame(() => {{
                            const newContainer = document.querySelector('.episodes-list');
                            if (newContainer && scrollTop > 0) {{
                                newContainer.scrollTop = scrollTop;
                            }}
                        }});
                    }}
                    
                    // Check if downloads are complete
                    if (status.downloaded + status.failed >= status.total && status.total > 0) {{
                        // Only stop polling if no failed episodes or if user has left the download page
                        if (status.failed === 0 || APP_STATE.state !== 'download') {{
                            clearInterval(APP_STATE.downloadInterval);
                        }}
                        
                        // Don't automatically proceed - require manual Continue button
                        // User must click Continue to proceed to processing
                    }}
                    
                }} catch (error) {{
                    console.error('Failed to update download status:', error);
                }}
            }}, 2000);  // Reduced polling frequency from 1s to 2s for downloads
        }}
        
        function toggleDownloadDetails(episodeId, event) {{
            console.log('toggleDownloadDetails called for:', episodeId);
            
            // Prevent event from bubbling up and default action
            if (event) {{
                event.preventDefault();
                event.stopPropagation();
            }}
            
            const detailsDiv = document.getElementById(`details-${{episodeId}}`);
            const toggleIcon = document.getElementById(`toggle-${{episodeId}}`);
            
            if (!detailsDiv || !toggleIcon) {{
                console.error('Could not find details or toggle elements for:', episodeId);
                return;
            }}
            
            if (detailsDiv.style.display === 'none' || !detailsDiv.style.display) {{
                detailsDiv.style.display = 'block';
                toggleIcon.textContent = '▼';
                // Track expanded state
                if (!APP_STATE.expandedEpisodes) APP_STATE.expandedEpisodes = new Set();
                APP_STATE.expandedEpisodes.add(episodeId);
            }} else {{
                detailsDiv.style.display = 'none';
                toggleIcon.textContent = '▶';
                // Track collapsed state
                if (APP_STATE.expandedEpisodes) {{
                    APP_STATE.expandedEpisodes.delete(episodeId);
                }}
            }}
        }}
        
        async function viewDetailedLogs(episodeId) {{
            // Prevent any propagation
            if (event) event.stopPropagation();
            
            const episode = APP_STATE.downloadStatus.episodeDetails[episodeId];
            if (!episode) return;
            
            const logs = episode.attempts.map((attempt, idx) => 
                `Attempt ${{idx + 1}}:\\n` +
                `URL: ${{attempt.url}}\\n` +
                `Error: ${{attempt.error}}\\n` +
                `Duration: ${{attempt.duration}}ms\\n`
            ).join('\\n---\\n');
            
            alert(`Download logs for ${{episode.title}}:\\n\\n${{logs}}`);
        }}
        
        async function tryManualUrl(episodeId) {{
            const url = prompt('Enter direct URL to audio file (MP3, WAV, etc.):\\n\\nFor YouTube URLs, the system will automatically download and convert to MP3.');
            if (!url) return;
            
            try {{
                // Update UI to show it's retrying
                if (APP_STATE.downloadStatus && APP_STATE.downloadStatus.episodeDetails[episodeId]) {{
                    APP_STATE.downloadStatus.episodeDetails[episodeId].status = 'retrying';
                    APP_STATE.downloadStatus.episodeDetails[episodeId].lastError = 'Retrying with manual URL...';
                    render();
                }}
                
                const response = await fetch('/api/manual-download', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{
                        episode_id: episodeId,
                        url: url
                    }})
                }});
                
                const result = await response.json();
                
                if (response.ok) {{
                    // Ensure polling is active to see the update
                    if (!APP_STATE.downloadInterval) {{
                        startDownloadPolling();
                    }}
                    
                    // Show success feedback
                    const episodeTitle = APP_STATE.downloadStatus.episodeDetails[episodeId]?.episode || episodeId;
                    alert(`Manual download started for: ${{episodeTitle.substring(0, 50)}}...\\n\\nThis may take a few moments. The page will update automatically when complete.`);
                    
                    // Keep polling active to see status updates
                    if (!APP_STATE.downloadInterval) {{
                        startDownloadPolling();
                    }}
                }} else {{
                    alert('Failed to start manual download: ' + (result.message || 'Unknown error'));
                }}
            }} catch (error) {{
                console.error('Manual download error:', error);
                alert('Error: ' + error.message);
                
                // Revert status on error
                if (APP_STATE.downloadStatus && APP_STATE.downloadStatus.episodeDetails[episodeId]) {{
                    APP_STATE.downloadStatus.episodeDetails[episodeId].status = 'failed';
                    render();
                }}
            }}
        }}
        
        async function tryBrowserDownload(episodeId) {{
            try {{
                const response = await fetch('/api/browser-download', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{
                        episode_id: episodeId
                    }})
                }});
                
                if (response.ok) {{
                    alert('Browser download started (this may take longer)...');
                }} else {{
                    alert('Failed to start browser download');
                }}
            }} catch (error) {{
                console.error('Browser download error:', error);
                alert('Error: ' + error.message);
            }}
        }}
        
        async function enableDebugMode(episodeId) {{
            try {{
                const response = await fetch('/api/debug-download', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{
                        episode_id: episodeId,
                        debug: true
                    }})
                }});
                
                const result = await response.json();
                alert(`Debug info:\\n\\n${{JSON.stringify(result, null, 2)}}`);
            }} catch (error) {{
                console.error('Debug mode error:', error);
                alert('Error: ' + error.message);
            }}
        }}
        
        async function retryAllFailed() {{
            const failedCount = APP_STATE.downloadStatus.failed;
            if (failedCount === 0) {{
                alert('No failed downloads to retry');
                return;
            }}
            
            if (!confirm(`Retry all ${{failedCount}} failed downloads?`)) {{
                return;
            }}
            
            try {{
                const response = await fetch('/api/retry-downloads', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{
                        failed_episodes: Object.keys(APP_STATE.downloadStatus.episodeDetails)
                            .filter(id => APP_STATE.downloadStatus.episodeDetails[id].status === 'failed')
                    }})
                }});
                
                if (response.ok) {{
                    // Reset retry count and continue polling
                    APP_STATE.downloadStatus.retrying = failedCount;
                    APP_STATE.downloadStatus.failed = 0;
                    render();
                }} else {{
                    alert('Failed to start retry');
                }}
            }} catch (error) {{
                console.error('Retry error:', error);
                alert('Error: ' + error.message);
            }}
        }}
        
        async function continueWithDownloads() {{
            const {{ downloaded, failed, total }} = APP_STATE.downloadStatus;
            
            if (downloaded < 1) {{
                alert('You need at least 1 successfully downloaded episode to continue.');
                return;
            }}
            
            if (failed > 0) {{
                if (!confirm(`${{downloaded}} episodes downloaded successfully, ${{failed}} failed. Continue anyway?`)) {{
                    return;
                }}
            }}
            
            clearInterval(APP_STATE.downloadInterval);
            
            // Filter out failed downloads - only process successfully downloaded episodes
            const successfulEpisodes = new Set();
            Object.entries(APP_STATE.downloadStatus.episodeDetails).forEach(([episodeId, details]) => {{
                if (details.status === 'success' || details.status === 'downloaded') {{
                    successfulEpisodes.add(episodeId);
                }}
            }});
            
            // Update selected episodes to only include successful downloads
            APP_STATE.selectedEpisodes = successfulEpisodes;
            
            // Track when processing started
            APP_STATE.processingStartTime = Date.now();
            
            // Move to processing stage
            APP_STATE.state = 'processing';
            render();
            
            // Start processing
            await startProcessing();
        }}
        
        async function cancelDownloads() {{
            if (confirm('Are you sure you want to cancel downloads? This will stop all remaining downloads.')) {{
                clearInterval(APP_STATE.downloadInterval);
                APP_STATE.state = 'cost_estimate';
                render();
            }}
        }}
        
        async function retryFailedEpisodes() {{
            // Get failed episodes from processing status
            const failedEpisodes = APP_STATE.processingStatus.errors;
            
            if (failedEpisodes.length === 0) {{
                alert('No failed episodes to retry');
                return;
            }}
            
            // Update UI to show we're retrying
            APP_STATE.state = 'processing';
            APP_STATE.processingStatus.startTime = Date.now();
            APP_STATE.processingStatus.currently_processing = failedEpisodes.map(e => e.episode);
            render();
            
            try {{
                // Call retry endpoint with failed episodes
                const response = await fetch('/api/retry-episodes', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{
                        episodes: failedEpisodes,
                        use_alternative_sources: true
                    }})
                }});
                
                if (!response.ok) {{
                    throw new Error('Failed to start retry');
                }}
                
                // Start polling for progress
                startProgressPolling();
                
            }} catch (error) {{
                console.error('Failed to retry episodes:', error);
                alert('Failed to start retry. Please try again.');
                APP_STATE.state = 'review';
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
                        method: 'POST',
                        headers: {{'Content-Type': 'application/json'}},
                        body: JSON.stringify({{
                            send_email: true
                        }})
                    }});
                    
                    const result = await response.json();
                    
                    if (response.ok && result.status === 'success') {{
                        APP_STATE.state = 'complete';
                        APP_STATE.emailMessage = result.message || 'Email sent successfully!';
                        render();
                        setTimeout(() => window.close(), 5000);
                    }} else {{
                        alert('Failed to send email: ' + (result.message || 'Unknown error'));
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
        
        // Add event delegation for episode clicks as primary handler
        document.addEventListener('click', function(e) {{
            // Check if click is on episode item or its children
            const episodeItem = e.target.closest('.episode-item');
            if (episodeItem) {{
                // Prevent default and stop propagation
                e.preventDefault();
                e.stopPropagation();
                
                // Get the episode ID from the data attribute
                const episodeId = episodeItem.getAttribute('data-episode-id');
                if (episodeId) {{
                    console.log('Event delegation handling click for episode:', episodeId);
                    toggleEpisode(episodeId, e);
                }}
            }}
            
            // Handle download item clicks
            const downloadItem = e.target.closest('.download-item.expandable');
            if (downloadItem && !e.target.closest('.troubleshoot-actions') && !e.target.closest('.download-details-panel')) {{
                // Prevent default and stop propagation
                e.preventDefault();
                e.stopPropagation();
                
                // Get episode ID from data attribute first, then try onclick
                const episodeId = downloadItem.getAttribute('data-episode-id');
                if (episodeId) {{
                    console.log('Event delegation handling click for download item (data-attribute):', episodeId);
                    toggleDownloadDetails(episodeId, e);
                }} else {{
                    // Fallback to onclick parsing
                    const onclickAttr = downloadItem.getAttribute('onclick');
                    if (onclickAttr) {{
                        const match = onclickAttr.match(/toggleDownloadDetails\\('([^']+)'/);
                        if (match && match[1]) {{
                            console.log('Event delegation handling click for download item (onclick):', match[1]);
                            toggleDownloadDetails(match[1], e);
                        }}
                    }}
                }}
            }}
        }}, true); // Use capture phase to catch events early
        
        // Start checking for state updates after a brief delay
        setTimeout(() => {{
            APP_STATE.globalPollInterval = setInterval(async () => {{
                // Only poll server state when in server-controlled states
                const serverControlledStates = ['podcast_selection', 'loading'];
                const clientControlledStates = ['cost_estimate', 'download', 'processing', 'results', 'email_approval'];
                
                // Only include episode_selection if we haven't loaded episodes yet
                if (APP_STATE.state === 'episode_selection' && APP_STATE.episodes.length === 0) {{
                    serverControlledStates.push('episode_selection');
                }}
                
                // Skip polling if in client-controlled state or terminal states
                if (clientControlledStates.includes(APP_STATE.state) || 
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
            }}, 5000);  // Reduced polling frequency from 1s to 5s for email stage
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
            position: relative;
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
            position: relative;
            z-index: 1;
        }
        
        .episodes-list {
            position: relative;
        }
        
        .episode-item:first-child {
            border-top: none;
            margin-top: 0;
            padding-top: 24px;
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
        
        .time-elapsed {
            font-size: 14px;
            color: var(--gray-500);
            margin-top: -32px;
            margin-bottom: 32px;
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
            background: var(--gray-100);
            color: var(--gray-600);
            border: 1px solid var(--gray-200);
        }
        
        .mode-badge.test {
            /* Monochromatic style */
        }
        
        .mode-badge.full {
            /* Monochromatic style */
        }
        
        .mode-indicator {
            display: flex;
            align-items: center;
            gap: 8px;
            position: absolute;
            top: 24px;
            right: 24px;
            z-index: 10;
        }
        
        .mode-description {
            font-size: 12px;
            color: var(--gray-500);
            font-weight: 500;
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
        
        /* Cookie Alert Styles */
        .cookie-alert {
            background: #FFF8DC;
            border: 1px solid #FFD700;
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 24px;
            box-shadow: var(--shadow-soft);
        }
        
        .cookie-alert-header {
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 12px;
            font-size: 18px;
            color: var(--gray-700);
        }
        
        .cookie-alert-icon {
            font-size: 24px;
        }
        
        .cookie-alert p {
            color: var(--gray-600);
            margin-bottom: 16px;
        }
        
        .cookie-instructions {
            background: var(--white);
            border-radius: 8px;
            padding: 20px;
            margin-top: 16px;
        }
        
        .cookie-instructions h4 {
            color: var(--gray-700);
            margin-bottom: 16px;
            font-size: 16px;
        }
        
        .cookie-instructions ol {
            counter-reset: steps;
            list-style: none;
            padding-left: 0;
        }
        
        .cookie-instructions ol > li {
            counter-increment: steps;
            margin-bottom: 20px;
            position: relative;
            padding-left: 40px;
        }
        
        .cookie-instructions ol > li::before {
            content: counter(steps);
            position: absolute;
            left: 0;
            top: 0;
            width: 28px;
            height: 28px;
            background: var(--black);
            color: var(--white);
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 600;
            font-size: 14px;
        }
        
        .cookie-instructions strong {
            display: block;
            margin-bottom: 8px;
            color: var(--gray-700);
        }
        
        .cookie-instructions ul {
            list-style: none;
            padding-left: 0;
            margin-top: 8px;
        }
        
        .cookie-instructions ul li {
            padding-left: 20px;
            position: relative;
            margin-bottom: 6px;
            color: var(--gray-600);
            font-size: 14px;
        }
        
        .cookie-instructions ul li::before {
            content: "•";
            position: absolute;
            left: 8px;
            color: var(--gray-400);
        }
        
        .cookie-instructions code {
            background: var(--gray-100);
            padding: 2px 6px;
            border-radius: 4px;
            font-family: 'Consolas', 'Monaco', monospace;
            font-size: 13px;
            color: var(--gray-700);
        }
        
        .cookie-instructions em {
            font-style: normal;
            font-weight: 600;
            color: var(--gray-700);
        }
        
        .cookie-note {
            background: var(--gray-100);
            padding: 12px 16px;
            border-radius: 8px;
            margin-top: 20px;
            font-size: 14px;
            color: var(--gray-600);
        }
        
        .cookie-note strong {
            color: var(--gray-700);
        }
        
        .cookie-details {
            margin-top: 16px;
        }
        
        .cookie-details summary {
            cursor: pointer;
            color: var(--gray-600);
            font-size: 14px;
            font-weight: 500;
            padding: 8px 0;
        }
        
        .cookie-details summary:hover {
            color: var(--gray-700);
        }
        
        .cookie-alternative {
            padding: 16px;
            background: var(--gray-100);
            border-radius: 8px;
            margin-top: 12px;
        }
        
        .cookie-alternative p {
            margin-bottom: 12px;
            font-size: 14px;
            color: var(--gray-600);
        }
        
        .cookie-alternative ol {
            list-style: decimal;
            padding-left: 20px;
        }
        
        .cookie-alternative ol li {
            margin-bottom: 8px;
            font-size: 14px;
            color: var(--gray-600);
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
    
    def _run_retry_processing(self, failed_episodes):
        """Run retry processing for failed episodes with alternative sources"""
        logger.info(f"Starting retry processing for {len(failed_episodes)} failed episodes")
        
        try:
            # Import necessary modules
            import asyncio
            from ..app import RenaissanceWeeklyApp
            
            # Create a new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Run the retry processing
            app = RenaissanceWeeklyApp()
            
            # Extract episode info from failed episodes
            retry_episodes = []
            for error_info in failed_episodes:
                # Parse episode info from error
                episode_name = error_info.get('episode', '')
                # You'll need to reconstruct Episode objects or pass IDs
                # For now, this is a placeholder
                retry_episodes.append(episode_name)
            
            # Run retry with alternative sources
            results = loop.run_until_complete(
                app.retry_failed_episodes(retry_episodes, use_alternative_sources=True)
            )
            
            # Update processing status
            with self._status_lock:
                self._processing_status['completed'] = results.get('successful', 0)
                self._processing_status['failed'] = results.get('failed', 0)
                self._processing_status['errors'] = results.get('errors', [])
                
            logger.info(f"Retry processing complete: {results}")
            
        except Exception as e:
            logger.error(f"Error in retry processing: {e}")
            with self._status_lock:
                self._processing_status['errors'].append({
                    'episode': 'Retry Process',
                    'message': str(e)
                })
        finally:
            # Clean up event loop
            try:
                loop.close()
            except:
                pass
    
    def _download_episodes_background(self):
        """Download episodes in background with concurrent downloads"""
        try:
            logger.info(f"Starting download of {len(self._episodes_to_download)} episodes")
            
            # Import the app to use its download functionality
            from ..app import RenaissanceWeekly
            import asyncio
            
            # Create event loop for async downloads
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                # Create app instance
                app = RenaissanceWeekly()
                
                # Set transcription mode BEFORE starting downloads
                app.current_transcription_mode = self._processing_mode
                logger.info(f"[{self._correlation_id}] Setting download transcription mode to: {self._processing_mode}")
                
                # Store the download manager reference and event loop
                self._download_app = app
                self._download_app._loop = loop  # Store the event loop reference
                
                # Define progress callback to update UI status
                def download_progress_callback(status):
                    with self._status_lock:
                        self._download_status = status
                
                # Create a custom download function that handles manual URLs
                async def run_downloads():
                    # Start the download process
                    download_task = asyncio.create_task(
                        app.download_episodes(self._episodes_to_download, download_progress_callback)
                    )
                    
                    # Wait a moment for download manager to be created
                    await asyncio.sleep(0.1)
                    
                    # Handle manual URLs and browser requests if download manager exists
                    if hasattr(app, '_download_manager') and app._download_manager:
                        download_manager = app._download_manager
                        
                        # Add manual URLs
                        for req in self._manual_download_queue:
                            download_manager.add_manual_url(req['episode_id'], req['url'])
                        self._manual_download_queue.clear()
                        
                        # Add browser requests
                        for req in self._browser_download_queue:
                            download_manager.request_browser_download(req['episode_id'])
                        self._browser_download_queue.clear()
                    
                    # Wait for downloads to complete
                    return await download_task
                
                # Run the download
                result = loop.run_until_complete(run_downloads())
                
                # Update final status
                with self._status_lock:
                    self._download_status = result
                
            finally:
                loop.close()
                asyncio.set_event_loop(None)
                
        except Exception as e:
            logger.error(f"Download thread error: {e}", exc_info=True)
    
    def _get_download_debug_info(self, episode_id):
        """Get debug information for episode download"""
        # Check if we have a download manager
        if hasattr(self, '_download_app') and self._download_app and hasattr(self._download_app, '_download_manager'):
            download_manager = self._download_app._download_manager
            if download_manager:
                return download_manager.get_debug_info(episode_id)
        
        # Fallback to basic info
        episode = None
        for ep in self.episode_cache:
            if f"{ep.podcast}|{ep.title}|{ep.published}" == episode_id:
                episode = ep
                break
        
        if not episode:
            return {'error': 'Episode not found'}
        
        debug_info = {
            'episode': {
                'title': episode.title,
                'podcast': episode.podcast,
                'published': str(episode.published),
                'audio_url': episode.audio_url,
                'transcript_url': episode.transcript_url,
                'description': episode.description[:200] if episode.description else None
            },
            'download_attempts': self._download_status.get('episodeDetails', {}).get(episode_id, {}).get('attempts', []),
            'available_strategies': [
                'RSS feed URL',
                'YouTube search',
                'Apple Podcasts API',
                'Spotify API', 
                'CDN direct access',
                'Browser automation'
            ]
        }
        
        return debug_info
    
    def _start_manual_download(self, episode_id: str, url: str):
        """Start a standalone manual download after the download phase is complete"""
        logger.info(f"[{self._correlation_id}] Starting standalone manual download for {episode_id}")
        
        # Find the episode
        episode = None
        for ep in self.episode_cache:
            if f"{ep.podcast}|{ep.title}|{ep.published}" == episode_id:
                episode = ep
                break
        
        if not episode:
            logger.error(f"[{self._correlation_id}] Episode not found for manual download: {episode_id}")
            return
        
        # Create a thread to handle the manual download
        def run_manual_download():
            try:
                logger.info(f"[{self._correlation_id}] Running manual download for {episode.title}")
                
                # Import necessary modules
                from ..app import RenaissanceWeekly
                from ..transcripts.transcriber import AudioTranscriber
                import asyncio
                
                # Create a new event loop for this thread
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                # Create transcriber to handle the download
                transcriber = AudioTranscriber()
                
                # Download the audio file
                async def download_with_url():
                    try:
                        # Check if this is a local file path
                        from pathlib import Path
                        
                        if url.startswith('/') or url.startswith('~') or url.startswith('file://'):
                            # Handle local file path
                            local_path = Path(url.replace('file://', '').replace('~', str(Path.home())))
                            
                            if local_path.exists() and local_path.is_file():
                                # Copy to our audio directory
                                from ..config import AUDIO_DIR
                                from ..utils.filename_utils import generate_audio_filename
                                import shutil
                                
                                AUDIO_DIR.mkdir(exist_ok=True)
                                # Generate standardized filename (assume test mode for UI uploads)
                                filename = generate_audio_filename(episode, 'test')
                                audio_path = AUDIO_DIR / filename
                                
                                # Copy the file
                                shutil.copy2(local_path, audio_path)
                                logger.info(f"[{self._correlation_id}] ✅ Copied local file to: {audio_path}")
                            else:
                                logger.error(f"[{self._correlation_id}] ❌ Local file not found: {local_path}")
                                audio_path = None
                        else:
                            # Use the transcriber's download method for URLs
                            audio_path = await transcriber.download_audio_simple(
                                episode,
                                url,
                                f"manual-{episode.title[:20]}"
                            )
                        
                        if audio_path and audio_path.exists():
                            logger.info(f"[{self._correlation_id}] ✅ Manual download successful: {audio_path}")
                            
                            # Update download status
                            with self._status_lock:
                                if self._download_status and 'episodeDetails' in self._download_status:
                                    if episode_id in self._download_status['episodeDetails']:
                                        self._download_status['episodeDetails'][episode_id]['status'] = 'success'
                                        self._download_status['episodeDetails'][episode_id]['lastError'] = None
                                        self._download_status['downloaded'] = self._download_status.get('downloaded', 0) + 1
                                        self._download_status['failed'] = max(0, self._download_status.get('failed', 1) - 1)
                            
                            # Update episode cache with successful download
                            episode.audio_url = str(audio_path)
                            
                            return True
                        else:
                            logger.error(f"[{self._correlation_id}] ❌ Manual download failed - no file created")
                            return False
                            
                    except Exception as e:
                        logger.error(f"[{self._correlation_id}] ❌ Manual download error: {e}")
                        return False
                
                # Run the download
                success = loop.run_until_complete(download_with_url())
                
                if not success:
                    # Update status to show failure
                    with self._status_lock:
                        if self._download_status and 'episodeDetails' in self._download_status:
                            if episode_id in self._download_status['episodeDetails']:
                                self._download_status['episodeDetails'][episode_id]['status'] = 'failed'
                                self._download_status['episodeDetails'][episode_id]['lastError'] = 'Manual download failed'
                
                loop.close()
                
            except Exception as e:
                logger.error(f"[{self._correlation_id}] Manual download thread error: {e}", exc_info=True)
        
        # Start the download thread
        download_thread = threading.Thread(target=run_manual_download, daemon=True)
        download_thread.start()
    
    def _generate_email_preview(self):
        """Generate a preview of the email that will be sent"""
        completed = self._processing_status.get('completed', 0) if self._processing_status else 0
        failed = self._processing_status.get('failed', 0) if self._processing_status else 0
        
        # Get summaries the same way the send endpoint does
        summaries_to_preview = []
        
        if hasattr(self, '_processed_summaries') and self._processed_summaries:
            summaries_to_preview = self._processed_summaries
        else:
            # Get from database - same logic as send endpoint
            from ..database import PodcastDatabase
            db = PodcastDatabase()
            
            episodes_with_summaries = db.get_episodes_with_summaries(
                days_back=self.configuration.get('lookback_days', 7),
                transcription_mode=self.configuration.get('transcription_mode', 'test')
            )
            
            # Convert to summary format
            summaries = []
            for ep in episodes_with_summaries:
                from ..models import Episode
                from datetime import datetime
                
                published = ep['published']
                if isinstance(published, str):
                    published = datetime.fromisoformat(published.replace('Z', '+00:00'))
                
                episode_obj = Episode(
                    podcast=ep['podcast'],
                    title=ep['title'],
                    published=published,
                    audio_url=ep.get('audio_url'),
                    transcript_url=ep.get('transcript_url'),
                    description=ep.get('description', ''),
                    link=ep.get('link', ''),
                    duration=ep.get('duration', ''),
                    guid=ep.get('guid', '')
                )
                
                summaries.append({
                    'episode': episode_obj,
                    'summary': ep['summary']
                })
            
            summaries_to_preview = summaries
        
        if summaries_to_preview:
            # Generate HTML preview using EmailDigest
            from ..email.digest import EmailDigest
            email_digest = EmailDigest()
            html_preview = email_digest.generate_html_preview(summaries_to_preview)
            
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