"""Utility helper functions"""

import os
import re
import time
import random
import hashlib
import asyncio
from typing import List, Optional, Callable, Any, Dict
from pathlib import Path
from datetime import datetime
import uuid
from collections import deque
import threading
from .logging import get_logger

logger = get_logger(__name__)


def validate_env_vars():
    """Validate required environment variables"""
    required = ["OPENAI_API_KEY", "SENDGRID_API_KEY"]
    missing = [var for var in required if not os.getenv(var)]
    
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
    
    email_to = os.getenv("EMAIL_TO", "caddington05@gmail.com")
    if not email_to or email_to == "caddington05@gmail.com":
        logger = get_logger(__name__)
        logger.info("📧 Using default email: caddington05@gmail.com")
        logger.info("💡 To change, set EMAIL_TO in your .env file")


def slugify(text: str) -> str:
    """Convert text to filename-safe string"""
    # Remove or replace invalid filename characters
    invalid_chars = '<>:"/\\|?*'
    safe_text = text
    for char in invalid_chars:
        safe_text = safe_text.replace(char, '_')
    
    # Replace multiple underscores with single
    safe_text = re.sub(r'_+', '_', safe_text)
    
    # Limit length and clean up
    safe_text = safe_text[:100].strip('_')
    
    return safe_text


def format_duration(duration_str: str) -> str:
    """Format duration string into human-readable format"""
    if not duration_str or duration_str == "Unknown":
        return "Unknown"
    
    # Handle HH:MM:SS format
    if ':' in str(duration_str):
        parts = str(duration_str).split(':')
        try:
            if len(parts) == 3:  # HH:MM:SS
                hours = int(parts[0])
                minutes = int(parts[1])
            elif len(parts) == 2:  # MM:SS
                hours = 0
                minutes = int(parts[0])
            else:
                return str(duration_str)
            
            if hours > 0:
                return f"{hours} hour{'s' if hours > 1 else ''} {minutes} minute{'s' if minutes != 1 else ''}"
            else:
                return f"{minutes} minute{'s' if minutes != 1 else ''}"
        except:
            return str(duration_str)
    
    # If already has text like "hour" or "minute", return as is
    if any(word in str(duration_str).lower() for word in ['hour', 'minute', 'second']):
        return str(duration_str)
    
    try:
        # Assume it's seconds if it's just a number
        if str(duration_str).isdigit():
            seconds = int(duration_str)
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            
            if hours > 0:
                return f"{hours} hour{'s' if hours > 1 else ''} {minutes} minute{'s' if minutes != 1 else ''}"
            else:
                return f"{minutes} minute{'s' if minutes != 1 else ''}"
                
    except:
        pass
    
    return str(duration_str)


def seconds_to_duration(seconds: int) -> str:
    """Convert seconds to duration string"""
    if seconds <= 0:
        return "Unknown"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours > 0:
        return f"{hours}h {minutes}m"
    else:
        return f"{minutes}m"


# New utility functions for robustness improvements

def exponential_backoff_with_jitter(attempt: int, base_delay: float = 1.0, max_delay: float = 60.0) -> float:
    """
    Calculate exponential backoff delay with jitter.
    
    Args:
        attempt: The attempt number (0-based)
        base_delay: Base delay in seconds
        max_delay: Maximum delay in seconds
        
    Returns:
        Delay in seconds with jitter applied
    """
    # Calculate exponential delay: base * 2^attempt
    delay = min(base_delay * (2 ** attempt), max_delay)
    
    # Add jitter: ±25% randomization
    jitter = delay * 0.25
    delay_with_jitter = delay + random.uniform(-jitter, jitter)
    
    return max(0, delay_with_jitter)


class RateLimiter:
    """Rate limiter with sliding window for API calls"""
    
    def __init__(self, max_requests_per_minute: int = 50, buffer_percentage: float = 0.1):
        """
        Initialize rate limiter.
        
        Args:
            max_requests_per_minute: Maximum requests allowed per minute
            buffer_percentage: Reserve buffer (0.1 = 10% buffer)
        """
        self.max_rpm = int(max_requests_per_minute * (1 - buffer_percentage))
        self.window_size = 60  # seconds
        self.requests = deque()
        self._lock = threading.Lock()
        
        logger.info(f"Rate limiter initialized: {self.max_rpm} requests/minute (with {buffer_percentage*100}% buffer)")
    
    def _cleanup_old_requests(self):
        """Remove requests older than the window size"""
        current_time = time.time()
        cutoff_time = current_time - self.window_size
        
        while self.requests and self.requests[0] < cutoff_time:
            self.requests.popleft()
    
    async def acquire(self, correlation_id: Optional[str] = None) -> float:
        """
        Acquire permission to make a request.
        
        Returns:
            Wait time in seconds (0 if request can proceed immediately)
        """
        cid = correlation_id or str(uuid.uuid4())[:8]
        
        with self._lock:
            self._cleanup_old_requests()
            current_time = time.time()
            
            if len(self.requests) >= self.max_rpm:
                # Calculate wait time until oldest request expires
                oldest_request = self.requests[0]
                wait_time = (oldest_request + self.window_size) - current_time + 0.1
                logger.info(f"[{cid}] Rate limit reached. Waiting {wait_time:.1f}s")
                return wait_time
            else:
                # Add current request
                self.requests.append(current_time)
                remaining = self.max_rpm - len(self.requests)
                logger.debug(f"[{cid}] Rate limit: {len(self.requests)}/{self.max_rpm} used, {remaining} remaining")
                return 0
    
    def get_current_usage(self) -> Dict[str, Any]:
        """Get current rate limiter usage statistics"""
        with self._lock:
            self._cleanup_old_requests()
            return {
                'current_requests': len(self.requests),
                'max_requests': self.max_rpm,
                'utilization': len(self.requests) / self.max_rpm * 100,
                'remaining': max(0, self.max_rpm - len(self.requests))
            }


async def retry_with_backoff(
    func: Callable,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exceptions: tuple = (Exception,),
    correlation_id: Optional[str] = None,
    handle_rate_limit: bool = False
) -> Any:
    """
    Retry a function with exponential backoff and jitter.
    Enhanced with special handling for HTTP 429 rate limit errors.
    
    Args:
        func: Async function to retry
        max_attempts: Maximum number of attempts (5 for rate limits, 3 for others)
        base_delay: Base delay between retries
        max_delay: Maximum delay between retries
        exceptions: Tuple of exceptions to catch and retry
        correlation_id: Optional correlation ID for logging
        handle_rate_limit: Enable special handling for HTTP 429 errors
        
    Returns:
        Result from successful function call
        
    Raises:
        Last exception if all attempts fail
    """
    cid = correlation_id or str(uuid.uuid4())[:8]
    last_exception = None
    
    # Adjust max attempts for rate limit errors
    if handle_rate_limit:
        max_attempts = max(max_attempts, 5)
    
    for attempt in range(max_attempts):
        try:
            logger.debug(f"[{cid}] Attempt {attempt + 1}/{max_attempts} for {func.__name__}")
            result = await func()
            if attempt > 0:
                logger.info(f"[{cid}] Succeeded after {attempt + 1} attempts")
            return result
            
        except exceptions as e:
            last_exception = e
            error_msg = str(e)
            
            # Special handling for rate limit errors
            if handle_rate_limit and "429" in error_msg:
                # Extract retry-after header if available
                retry_after = None
                if hasattr(e, 'response') and hasattr(e.response, 'headers'):
                    retry_after = e.response.headers.get('Retry-After')
                
                if retry_after:
                    try:
                        delay = float(retry_after)
                        logger.warning(f"[{cid}] Rate limited. Server says retry after {delay}s")
                    except:
                        delay = exponential_backoff_with_jitter(attempt, base_delay=60.0, max_delay=300.0)
                else:
                    # Use longer backoff for rate limits
                    delay = exponential_backoff_with_jitter(attempt, base_delay=60.0, max_delay=300.0)
                
                logger.warning(f"[{cid}] HTTP 429 rate limit on attempt {attempt + 1}. Waiting {delay:.1f}s...")
            else:
                # Standard exponential backoff for other errors
                delay = exponential_backoff_with_jitter(attempt, base_delay, max_delay)
                logger.warning(f"[{cid}] Attempt {attempt + 1} failed: {str(e)[:100]}. Retrying in {delay:.1f}s...")
            
            if attempt < max_attempts - 1:
                await asyncio.sleep(delay)
            else:
                logger.error(f"[{cid}] All {max_attempts} attempts failed for {func.__name__}")
    
    raise last_exception


def validate_audio_file_comprehensive(file_path: Path, correlation_id: Optional[str] = None) -> bool:
    """
    Comprehensive audio file validation checking header, samples, and tail.
    
    Args:
        file_path: Path to the audio file
        correlation_id: Optional correlation ID for logging
        
    Returns:
        True if file is valid audio, False otherwise
    """
    cid = correlation_id or str(uuid.uuid4())[:8]
    
    if not file_path.exists():
        logger.error(f"[{cid}] File does not exist: {file_path}")
        return False
    
    file_size = file_path.stat().st_size
    
    # Check minimum size (100KB)
    if file_size < 100 * 1024:
        logger.warning(f"[{cid}] File too small: {file_size} bytes")
        return False
    
    # Check maximum size (500MB)
    if file_size > 500 * 1024 * 1024:
        logger.warning(f"[{cid}] File too large: {file_size / 1024 / 1024:.1f} MB")
        return False
    
    try:
        with open(file_path, 'rb') as f:
            # Check header (first 16 bytes)
            header = f.read(16)
            
            # Audio file signatures
            audio_signatures = [
                (b'ID3', 0),           # MP3 with ID3 tag
                (b'\xFF\xFB', 0),      # MP3
                (b'\xFF\xF3', 0),      # MP3
                (b'\xFF\xF2', 0),      # MP3
                (b'ftyp', 4),          # MP4/M4A (at offset 4)
                (b'OggS', 0),          # Ogg Vorbis
                (b'RIFF', 0),          # WAV
                (b'fLaC', 0),          # FLAC
            ]
            
            # Check for audio signatures
            valid_header = False
            for sig, offset in audio_signatures:
                if offset == 0:
                    if header.startswith(sig):
                        valid_header = True
                        logger.debug(f"[{cid}] Valid audio signature found: {sig}")
                        break
                else:
                    if len(header) > offset + len(sig) and header[offset:offset+len(sig)] == sig:
                        valid_header = True
                        logger.debug(f"[{cid}] Valid audio signature found at offset {offset}: {sig}")
                        break
            
            # Check if it's HTML (common error response)
            if header.lower().startswith(b'<!doctype') or header.lower().startswith(b'<html'):
                logger.error(f"[{cid}] File appears to be HTML, not audio")
                return False
            
            if not valid_header:
                logger.warning(f"[{cid}] No valid audio signature found in header")
                return False
            
            # Sample validation: check 5 random positions in the file
            sample_positions = [
                int(file_size * 0.2),
                int(file_size * 0.4),
                int(file_size * 0.6),
                int(file_size * 0.8),
                file_size - 1024  # Near the end
            ]
            
            for pos in sample_positions:
                if pos < file_size - 16:
                    f.seek(pos)
                    sample = f.read(16)
                    
                    # Check for HTML content in the middle of file
                    if b'<html' in sample.lower() or b'<!doctype' in sample.lower():
                        logger.error(f"[{cid}] Found HTML content at position {pos}")
                        return False
                    
                    # Check for null bytes (corruption indicator)
                    if sample == b'\x00' * 16:
                        logger.warning(f"[{cid}] Found null bytes at position {pos}")
                        # Don't fail immediately, some formats have null padding
            
            # Check tail (last 1KB)
            if file_size > 1024:
                f.seek(file_size - 1024)
                tail = f.read()
                
                # Some formats have ID3v1 tags at the end
                if b'TAG' in tail[-128:]:
                    logger.debug(f"[{cid}] Found ID3v1 tag at end of file")
            
            logger.info(f"[{cid}] File validation passed: {file_size / 1024 / 1024:.1f} MB")
            return True
            
    except Exception as e:
        logger.error(f"[{cid}] Error validating file: {e}")
        return False


def calculate_file_hash(file_path: Path, chunk_size: int = 8192) -> str:
    """Calculate SHA256 hash of a file"""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()


class ProgressTracker:
    """Track progress across multiple operations"""
    
    def __init__(self, total_items: int, correlation_id: Optional[str] = None):
        self.total_items = total_items
        self.completed_items = 0
        self.failed_items = 0
        self.current_item = None
        self.start_time = time.time()
        self.item_start_time = None
        self.correlation_id = correlation_id or str(uuid.uuid4())[:8]
        self._lock = asyncio.Lock()
    
    async def start_item(self, item_name: str):
        """Mark the start of processing an item"""
        async with self._lock:
            self.current_item = item_name
            self.item_start_time = time.time()
            logger.info(f"[{self.correlation_id}] Starting: {item_name} ({self.completed_items + 1}/{self.total_items})")
    
    async def complete_item(self, success: bool = True):
        """Mark the completion of an item"""
        async with self._lock:
            if success:
                self.completed_items += 1
            else:
                self.failed_items += 1
            
            if self.item_start_time:
                item_duration = time.time() - self.item_start_time
                total_duration = time.time() - self.start_time
                
                # Calculate ETA
                items_processed = self.completed_items + self.failed_items
                if items_processed > 0:
                    avg_time_per_item = total_duration / items_processed
                    remaining_items = self.total_items - items_processed
                    eta_seconds = remaining_items * avg_time_per_item
                    
                    logger.info(
                        f"[{self.correlation_id}] {'✓' if success else '✗'} {self.current_item} "
                        f"({item_duration:.1f}s) | Progress: {items_processed}/{self.total_items} "
                        f"| Success rate: {self.completed_items/items_processed*100:.1f}% "
                        f"| ETA: {eta_seconds/60:.1f}m"
                    )
            
            self.current_item = None
            self.item_start_time = None
    
    def get_summary(self) -> dict:
        """Get progress summary"""
        total_duration = time.time() - self.start_time
        items_processed = self.completed_items + self.failed_items
        
        return {
            'total_items': self.total_items,
            'completed': self.completed_items,
            'failed': self.failed_items,
            'success_rate': self.completed_items / items_processed * 100 if items_processed > 0 else 0,
            'duration_seconds': total_duration,
            'avg_time_per_item': total_duration / items_processed if items_processed > 0 else 0
        }


class CircuitBreaker:
    """Circuit breaker pattern for handling failing services"""
    
    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0, 
                 correlation_id: Optional[str] = None, rate_limit_threshold: int = 3,
                 rate_limit_recovery: float = 300.0):
        """
        Initialize circuit breaker with enhanced rate limit handling.
        
        Args:
            failure_threshold: Failures before opening circuit
            recovery_timeout: Time before attempting recovery
            correlation_id: Correlation ID for logging
            rate_limit_threshold: Consecutive 429 errors before opening
            rate_limit_recovery: Recovery time for rate limit errors (5 minutes)
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.rate_limit_threshold = rate_limit_threshold
        self.rate_limit_recovery = rate_limit_recovery
        self.failure_count = 0
        self.rate_limit_count = 0
        self.last_failure_time = None
        self.state = "closed"  # closed, open, half-open
        self.correlation_id = correlation_id or str(uuid.uuid4())[:8]
        self._lock = asyncio.Lock()
    
    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function through circuit breaker"""
        async with self._lock:
            if self.state == "open":
                recovery_time = self.rate_limit_recovery if self.rate_limit_count >= self.rate_limit_threshold else self.recovery_timeout
                if time.time() - self.last_failure_time > recovery_time:
                    logger.info(f"[{self.correlation_id}] Circuit breaker moving to half-open state")
                    self.state = "half-open"
                else:
                    time_remaining = recovery_time - (time.time() - self.last_failure_time)
                    raise Exception(f"Circuit breaker is open (failures: {self.failure_count}, rate limits: {self.rate_limit_count}). Retry in {time_remaining:.0f}s")
        
        try:
            result = await func(*args, **kwargs)
            
            async with self._lock:
                if self.state == "half-open":
                    logger.info(f"[{self.correlation_id}] Circuit breaker recovered, closing")
                    self.state = "closed"
                    self.failure_count = 0
                    self.rate_limit_count = 0
            
            return result
            
        except Exception as e:
            async with self._lock:
                self.failure_count += 1
                self.last_failure_time = time.time()
                
                # Track rate limit errors separately
                if "429" in str(e):
                    self.rate_limit_count += 1
                    logger.warning(f"[{self.correlation_id}] Rate limit error {self.rate_limit_count}/{self.rate_limit_threshold}")
                    
                    if self.rate_limit_count >= self.rate_limit_threshold:
                        logger.warning(
                            f"[{self.correlation_id}] Circuit breaker opening due to rate limits. "
                            f"Recovery in {self.rate_limit_recovery/60:.1f} minutes"
                        )
                        self.state = "open"
                else:
                    # Reset rate limit count on other errors
                    self.rate_limit_count = 0
                
                if self.failure_count >= self.failure_threshold:
                    logger.warning(
                        f"[{self.correlation_id}] Circuit breaker opening after {self.failure_count} failures"
                    )
                    self.state = "open"
                
                logger.debug(f"[{self.correlation_id}] Circuit breaker failure {self.failure_count}/{self.failure_threshold}")
            
            raise


def get_available_memory() -> float:
    """Get available system memory in MB"""
    try:
        import psutil
        return psutil.virtual_memory().available / 1024 / 1024
    except ImportError:
        # If psutil not available, return conservative estimate
        return 1024.0  # 1GB


def get_cpu_count() -> int:
    """Get number of CPU cores"""
    try:
        import multiprocessing
        return multiprocessing.cpu_count()
    except:
        return 2  # Conservative default