"""
Browser-based downloader using Playwright for Cloudflare-protected content.
"""
import os
import time
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any
import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

try:
    from playwright.async_api import async_playwright, Browser, Page
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logger.warning("Playwright not installed. Browser-based downloads will not be available.")


class BrowserDownloader:
    """Downloads audio files using a real browser to bypass Cloudflare and other protections."""
    
    def __init__(self):
        self.browser: Optional[Browser] = None
        self.context = None
        
    async def __aenter__(self):
        if not PLAYWRIGHT_AVAILABLE:
            return self
            
        playwright = await async_playwright().start()
        # Use Chromium for best compatibility
        self.browser = await playwright.chromium.launch(
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-features=IsolateOrigins,site-per-process',
                '--no-sandbox',
            ]
        )
        
        # Create context with realistic settings
        self.context = await self.browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            locale='en-US',
            timezone_id='America/New_York',
            permissions=['geolocation', 'notifications'],
            extra_http_headers={
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'DNT': '1',
            }
        )
        
        # Add stealth scripts to avoid detection
        await self.context.add_init_script("""
            // Overwrite the navigator.webdriver property
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            
            // Mock chrome runtime
            window.chrome = {
                runtime: {}
            };
            
            // Mock permissions
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );
        """)
        
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
            
    async def download_with_browser(self, url: str, output_path: str, timeout: int = 120) -> bool:
        """
        Download a file using browser automation.
        
        Args:
            url: The URL to download
            output_path: Where to save the file
            timeout: Maximum time to wait for download (seconds)
            
        Returns:
            True if successful, False otherwise
        """
        if not PLAYWRIGHT_AVAILABLE or not self.context:
            logger.error("Playwright not available or not initialized")
            return False
            
        page = None
        try:
            page = await self.context.new_page()
            
            # Set up download handling
            download_path = Path(output_path).parent
            download_path.mkdir(parents=True, exist_ok=True)
            
            # Handle downloads
            download_started = False
            download_info = {}
            
            async def handle_download(download):
                nonlocal download_started, download_info
                download_started = True
                download_info['suggested_filename'] = download.suggested_filename
                download_info['download'] = download
                
            page.on('download', handle_download)
            
            # Navigate to the URL
            logger.info(f"Navigating to {url} with browser")
            response = await page.goto(url, wait_until='networkidle', timeout=30000)
            
            if response and response.status >= 400:
                logger.error(f"HTTP {response.status} error accessing {url}")
                return False
                
            # Wait for any Cloudflare challenges
            await page.wait_for_timeout(5000)
            
            # Check if we got an audio player or download started
            if not download_started:
                # Try to find and click download buttons/links
                download_selectors = [
                    'a[download]',
                    'a[href$=".mp3"]',
                    'a[href$=".m4a"]',
                    'button:has-text("download")',
                    'a:has-text("download")',
                    '.download-button',
                    '[aria-label*="download"]',
                ]
                
                for selector in download_selectors:
                    try:
                        element = await page.wait_for_selector(selector, timeout=2000)
                        if element:
                            await element.click()
                            # Wait for download to start
                            await page.wait_for_timeout(3000)
                            if download_started:
                                break
                    except:
                        continue
                        
            # If still no download, try to extract audio URL from player
            if not download_started:
                audio_url = await self._extract_audio_url_from_page(page)
                if audio_url:
                    # Navigate directly to audio URL
                    await page.goto(audio_url)
                    await page.wait_for_timeout(3000)
                    
            # Wait for download to complete
            if download_started and 'download' in download_info:
                download = download_info['download']
                # Save to specified path
                await download.save_as(output_path)
                logger.info(f"Successfully downloaded to {output_path}")
                return True
            else:
                # Try to save page content if it's audio
                content_type = await page.evaluate('() => document.contentType')
                if content_type and 'audio' in content_type:
                    # Get the audio data
                    audio_data = await page.evaluate('''() => {
                        const audio = document.querySelector('audio, video');
                        if (audio && audio.src) {
                            return fetch(audio.src).then(r => r.blob()).then(blob => {
                                return new Promise((resolve) => {
                                    const reader = new FileReader();
                                    reader.onloadend = () => resolve(reader.result);
                                    reader.readAsDataURL(blob);
                                });
                            });
                        }
                        return null;
                    }''')
                    
                    if audio_data:
                        # Save base64 data to file
                        import base64
                        data = audio_data.split(',')[1]
                        with open(output_path, 'wb') as f:
                            f.write(base64.b64decode(data))
                        logger.info(f"Successfully saved audio content to {output_path}")
                        return True
                        
            logger.error("No download started or audio content found")
            return False
            
        except Exception as e:
            logger.error(f"Browser download failed: {str(e)}")
            return False
        finally:
            if page:
                await page.close()
                
    async def _extract_audio_url_from_page(self, page: Page) -> Optional[str]:
        """Extract audio URL from page content."""
        try:
            # Try multiple strategies to find audio URL
            audio_url = await page.evaluate('''() => {
                // Check for audio/video elements
                const media = document.querySelector('audio, video');
                if (media && media.src) return media.src;
                
                // Check for source elements
                const source = document.querySelector('audio source, video source');
                if (source && source.src) return source.src;
                
                // Check for iframe embeds
                const iframe = document.querySelector('iframe[src*="spotify"], iframe[src*="soundcloud"]');
                if (iframe) return iframe.src;
                
                // Check data attributes
                const dataAudio = document.querySelector('[data-audio-url], [data-mp3-url], [data-episode-url]');
                if (dataAudio) {
                    return dataAudio.getAttribute('data-audio-url') || 
                           dataAudio.getAttribute('data-mp3-url') || 
                           dataAudio.getAttribute('data-episode-url');
                }
                
                // Check for JSON-LD data
                const jsonLd = document.querySelector('script[type="application/ld+json"]');
                if (jsonLd) {
                    try {
                        const data = JSON.parse(jsonLd.textContent);
                        if (data.audio) return data.audio.contentUrl || data.audio.url;
                        if (data.contentUrl) return data.contentUrl;
                    } catch {}
                }
                
                return null;
            }''')
            
            return audio_url
        except:
            return None
            
    async def handle_substack(self, url: str, output_path: str) -> bool:
        """Special handling for Substack podcasts."""
        if not self.context:
            return False
            
        page = None
        try:
            page = await self.context.new_page()
            
            # Navigate to the page
            await page.goto(url, wait_until='networkidle')
            
            # Wait for Cloudflare
            await page.wait_for_timeout(5000)
            
            # Look for the audio player
            audio_url = await page.evaluate('''() => {
                // Substack specific selectors
                const audioPlayer = document.querySelector('.audio-player audio');
                if (audioPlayer) return audioPlayer.src;
                
                // Check portable-text-audio
                const portableAudio = document.querySelector('.portable-text-audio audio');
                if (portableAudio) return portableAudio.src;
                
                // Check data attributes
                const audioElement = document.querySelector('[data-audio-upload]');
                if (audioElement) {
                    const data = audioElement.getAttribute('data-audio-upload');
                    try {
                        const parsed = JSON.parse(data);
                        return parsed.url || parsed.audio_url;
                    } catch {}
                }
                
                return null;
            }''')
            
            if audio_url:
                # Download the audio file
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    headers = {
                        'User-Agent': await page.evaluate('() => navigator.userAgent'),
                        'Referer': url,
                        'Origin': f"{urlparse(url).scheme}://{urlparse(url).netloc}",
                    }
                    
                    async with session.get(audio_url, headers=headers) as response:
                        if response.status == 200:
                            with open(output_path, 'wb') as f:
                                async for chunk in response.content.iter_chunked(8192):
                                    f.write(chunk)
                            logger.info(f"Successfully downloaded Substack audio to {output_path}")
                            return True
                            
            return False
            
        except Exception as e:
            logger.error(f"Substack download failed: {str(e)}")
            return False
        finally:
            if page:
                await page.close()


def download_with_browser_sync(url: str, output_path: str, timeout: int = 120) -> bool:
    """Synchronous wrapper for browser download."""
    async def _download():
        async with BrowserDownloader() as downloader:
            # Special handling for known platforms
            if 'substack.com' in url:
                return await downloader.handle_substack(url, output_path)
            else:
                return await downloader.download_with_browser(url, output_path, timeout)
                
    return asyncio.run(_download())