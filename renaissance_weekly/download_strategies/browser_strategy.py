"""Browser automation strategy - last resort for heavily protected content"""

import asyncio
from pathlib import Path
from typing import Optional, Tuple, Dict
import aiohttp
from . import DownloadStrategy
from ..utils.logging import get_logger

logger = get_logger(__name__)


class BrowserStrategy(DownloadStrategy):
    """Use browser automation to bypass all protections"""
    
    @property
    def name(self) -> str:
        return "browser"
    
    def can_handle(self, url: str, podcast_name: str) -> bool:
        """Can handle anything as last resort"""
        return True
    
    async def download(self, url: str, output_path: Path, episode_info: Dict) -> Tuple[bool, Optional[str]]:
        """Download using browser automation"""
        try:
            # Check if Playwright is installed
            try:
                from playwright.async_api import async_playwright
            except ImportError:
                return False, "Playwright not installed. Run: pip install playwright && playwright install chromium"
            
            logger.info("🌐 Using browser automation...")
            
            async with async_playwright() as p:
                # Launch browser with stealth settings
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        '--disable-blink-features=AutomationControlled',
                        '--disable-features=IsolateOrigins,site-per-process',
                        '--disable-web-security',
                        '--disable-features=site-per-process',
                        '--no-sandbox'
                    ]
                )
                
                # Create context with realistic settings
                context = await browser.new_context(
                    user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    viewport={'width': 1920, 'height': 1080},
                    locale='en-US',
                    timezone_id='America/Chicago',
                )
                
                # Add stealth scripts
                await context.add_init_script("""
                    // Override navigator properties
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                    Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
                    
                    // Chrome specific
                    window.chrome = {runtime: {}};
                    
                    // Permissions
                    const originalQuery = window.navigator.permissions.query;
                    window.navigator.permissions.query = (parameters) => (
                        parameters.name === 'notifications' ?
                            Promise.resolve({state: Notification.permission}) :
                            originalQuery(parameters)
                    );
                """)
                
                page = await context.new_page()
                
                # Set up network monitoring
                audio_urls = []
                
                async def handle_response(response):
                    try:
                        if response.status == 200:
                            content_type = response.headers.get('content-type', '')
                            url_lower = response.url.lower()
                            
                            # Check for audio content
                            if ('audio' in content_type or 
                                any(ext in url_lower for ext in ['.mp3', '.m4a', '.aac', '.ogg', '.wav']) or
                                'audio' in url_lower):
                                
                                # Filter out small files (likely not full episodes)
                                content_length = response.headers.get('content-length', '0')
                                if int(content_length) > 1000000:  # > 1MB
                                    audio_urls.append(response.url)
                                    logger.info(f"🎵 Found audio URL: {response.url[:80]}...")
                    except:
                        pass
                
                page.on('response', handle_response)
                
                # Navigate to episode page
                logger.info(f"Navigating to: {url[:80]}...")
                try:
                    await page.goto(url, wait_until='domcontentloaded', timeout=30000)
                except:
                    # Continue even if page load timeout
                    pass
                
                # Wait for initial page load
                await page.wait_for_timeout(3000)
                
                # Try to find and click play button
                play_selectors = [
                    # Generic play buttons
                    'button[aria-label*="play" i]',
                    'button[aria-label*="Play" i]',
                    'button[title*="play" i]',
                    '.play-button',
                    '[class*="play"][class*="button"]',
                    '[data-testid*="play"]',
                    'button:has-text("Play")',
                    'div[role="button"]:has-text("Play")',
                    
                    # Platform specific
                    '.audio-player-play-button',  # Substack
                    '.pencraft .play-button',      # Substack alt
                    '.ytp-play-button',            # YouTube
                    '[data-a-target="player-play-pause-button"]',  # Twitch
                    '.PlayButton',                 # Various
                    '.playerButton',               # Various
                    
                    # Icon-based buttons
                    'button svg[class*="play"]',
                    'button [class*="play-icon"]',
                    '[class*="play"] svg',
                ]
                
                clicked = False
                for selector in play_selectors:
                    try:
                        # Check if element exists and is visible
                        element = await page.query_selector(selector)
                        if element and await element.is_visible():
                            await element.click()
                            clicked = True
                            logger.info(f"Clicked play button: {selector}")
                            break
                    except:
                        continue
                
                if not clicked:
                    logger.warning("Could not find play button, monitoring network anyway...")
                
                # Wait for audio to start loading
                await page.wait_for_timeout(5000)
                
                # Sometimes audio loads in iframes
                frames = page.frames
                for frame in frames[1:]:  # Skip main frame
                    try:
                        # Check for play buttons in iframes
                        for selector in play_selectors[:5]:  # Try first few selectors
                            try:
                                element = await frame.query_selector(selector)
                                if element and await element.is_visible():
                                    await element.click()
                                    logger.info(f"Clicked play in iframe: {selector}")
                                    await page.wait_for_timeout(3000)
                                    break
                            except:
                                pass
                    except:
                        pass
                
                # Final wait to capture any lazy-loaded audio
                await page.wait_for_timeout(3000)
                
                # Try to download the best audio URL found
                if audio_urls:
                    # Prefer longer URLs (often more specific/direct)
                    audio_urls.sort(key=len, reverse=True)
                    
                    for audio_url in audio_urls[:3]:  # Try top 3 URLs
                        logger.info(f"Attempting download from: {audio_url[:80]}...")
                        
                        try:
                            # Get cookies from browser context
                            cookies = await context.cookies()
                            cookie_header = '; '.join([f"{c['name']}={c['value']}" for c in cookies])
                            
                            # Download with cookies and headers from browser
                            async with aiohttp.ClientSession() as session:
                                headers = {
                                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                                    'Cookie': cookie_header,
                                    'Referer': url,
                                    'Accept': '*/*',
                                    'Accept-Language': 'en-US,en;q=0.9',
                                }
                                
                                async with session.get(audio_url, headers=headers) as response:
                                    if response.status == 200:
                                        # Download in chunks
                                        downloaded = 0
                                        with open(output_path, 'wb') as f:
                                            async for chunk in response.content.iter_chunked(8192):
                                                f.write(chunk)
                                                downloaded += len(chunk)
                                                
                                                # Log progress every 10MB
                                                if downloaded % (10 * 1024 * 1024) == 0:
                                                    logger.debug(f"Downloaded {downloaded / 1024 / 1024:.1f} MB...")
                                        
                                        if downloaded > 1000000:  # At least 1MB
                                            await browser.close()
                                            logger.info(f"✅ Browser download successful ({downloaded / 1024 / 1024:.1f} MB)")
                                            return True, None
                                        else:
                                            output_path.unlink()  # Remove small file
                                            
                        except Exception as e:
                            logger.debug(f"Failed to download {audio_url[:50]}...: {e}")
                            continue
                
                await browser.close()
                return False, "No downloadable audio found on page"
                
        except Exception as e:
            error_msg = f"Browser automation error: {str(e)}"
            logger.error(error_msg)
            return False, error_msg