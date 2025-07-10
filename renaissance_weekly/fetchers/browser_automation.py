"""Browser automation for Cloudflare-protected sites using Playwright"""

import asyncio
import re
from typing import Optional, Tuple
from urllib.parse import urlparse
import os

from ..utils.logging import get_logger
from ..models import Episode

logger = get_logger(__name__)

try:
    from playwright.async_api import async_playwright, Browser, Page
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logger.warning("Playwright not installed. Browser automation will not be available.")


class BrowserAutomation:
    """Handle Cloudflare-protected sites using browser automation"""
    
    def __init__(self):
        self.browser: Optional[Browser] = None
        self.playwright = None
        
    async def __aenter__(self):
        if PLAYWRIGHT_AVAILABLE:
            self.playwright = await async_playwright().start()
            # Use chromium with specific args to avoid detection
            self.browser = await self.playwright.chromium.launch(
                headless=True,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--disable-features=IsolateOrigins,site-per-process',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-accelerated-2d-canvas',
                    '--no-gpu',
                    '--window-size=1920,1080',
                ]
            )
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
    
    async def get_audio_url_from_substack(self, episode_url: str) -> Optional[str]:
        """Extract audio URL from Substack post using browser automation"""
        if not PLAYWRIGHT_AVAILABLE:
            logger.error("Playwright not available for browser automation")
            return None
            
        if not self.browser:
            logger.error("Browser not initialized")
            return None
            
        try:
            logger.info(f"🌐 Using browser automation for: {episode_url}")
            
            # Create a new context with realistic settings
            context = await self.browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                locale='en-US',
                timezone_id='America/New_York',
            )
            
            # Create page
            page = await context.new_page()
            
            # Add stealth scripts
            await self._add_stealth_scripts(page)
            
            # Navigate with retries for Cloudflare challenges
            audio_url = await self._navigate_and_extract_audio(page, episode_url)
            
            await context.close()
            
            return audio_url
            
        except Exception as e:
            logger.error(f"Browser automation failed: {e}")
            return None
    
    async def _add_stealth_scripts(self, page: Page):
        """Add scripts to make browser less detectable"""
        # Override navigator properties
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => false
            });
            
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']
            });
            
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
            
            // Pass Chrome runtime test
            window.chrome = {
                runtime: {}
            };
            
            // Pass permissions test
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );
        """)
    
    async def _navigate_and_extract_audio(self, page: Page, url: str, max_retries: int = 3) -> Optional[str]:
        """Navigate to page and extract audio URL, handling Cloudflare challenges"""
        for attempt in range(max_retries):
            try:
                logger.info(f"Navigation attempt {attempt + 1}/{max_retries}")
                
                # Navigate to the page
                response = await page.goto(url, wait_until='networkidle', timeout=30000)
                
                # Check if we hit Cloudflare challenge
                if await self._is_cloudflare_challenge(page):
                    logger.info("Cloudflare challenge detected, waiting...")
                    # Wait for challenge to complete
                    await asyncio.sleep(5)
                    
                    # Check if we're through
                    if not await self._is_cloudflare_challenge(page):
                        logger.info("✅ Passed Cloudflare challenge")
                    else:
                        logger.warning("Still on Cloudflare challenge page")
                        continue
                
                # Wait for content to load
                await page.wait_for_load_state('networkidle')
                
                # Look for audio player
                audio_url = await self._extract_audio_url(page)
                if audio_url:
                    logger.info(f"✅ Found audio URL: {audio_url[:80]}...")
                    return audio_url
                
                # Try scrolling to trigger lazy loading
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
                await asyncio.sleep(2)
                
                # Try again after scroll
                audio_url = await self._extract_audio_url(page)
                if audio_url:
                    logger.info(f"✅ Found audio URL after scroll: {audio_url[:80]}...")
                    return audio_url
                    
            except Exception as e:
                logger.warning(f"Navigation attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
                    
        return None
    
    async def _is_cloudflare_challenge(self, page: Page) -> bool:
        """Check if we're on a Cloudflare challenge page"""
        try:
            # Check for common Cloudflare challenge indicators
            title = await page.title()
            if 'just a moment' in title.lower() or 'checking your browser' in title.lower():
                return True
                
            # Check for Cloudflare challenge text
            challenge_selectors = [
                'text=Checking your browser',
                'text=This process is automatic',
                'text=DDoS protection by Cloudflare',
                '#cf-challenge-running',
                '.cf-browser-verification'
            ]
            
            for selector in challenge_selectors:
                if await page.locator(selector).count() > 0:
                    return True
                    
        except:
            pass
            
        return False
    
    async def _extract_audio_url(self, page: Page) -> Optional[str]:
        """Extract audio URL from the page"""
        try:
            # Common audio player selectors
            audio_selectors = [
                'audio[src]',
                'audio source[src]',
                'iframe[src*="substack-audio-player"]',
                'div[class*="audio-player"] a[href*=".mp3"]',
                'a[href*="api.substack.com/feed/podcast"][href*=".mp3"]',
                'meta[property="og:audio"]',
            ]
            
            for selector in audio_selectors:
                elements = await page.locator(selector).all()
                for element in elements:
                    if selector.startswith('meta'):
                        url = await element.get_attribute('content')
                    else:
                        url = await element.get_attribute('src') or await element.get_attribute('href')
                    
                    if url and ('.mp3' in url or '.m4a' in url or 'audio' in url):
                        # Resolve relative URLs
                        if url.startswith('/'):
                            parsed = urlparse(page.url)
                            url = f"{parsed.scheme}://{parsed.netloc}{url}"
                        return url
            
            # Try to find audio URL in page scripts
            scripts = await page.locator('script').all()
            for script in scripts:
                content = await script.inner_text()
                # Look for audio URLs in JavaScript
                matches = re.findall(r'["\'](https?://[^"\']+\.(?:mp3|m4a))["\']', content)
                for match in matches:
                    if 'api.substack.com' in match or 'audio' in match:
                        return match
                        
        except Exception as e:
            logger.debug(f"Audio extraction error: {e}")
            
        return None


async def get_audio_with_browser(episode: Episode) -> Optional[str]:
    """Convenience function to get audio URL using browser automation"""
    if not episode.link:
        return None
        
    # Only use for Substack URLs
    if 'substack.com' not in episode.link:
        return None
        
    try:
        async with BrowserAutomation() as browser:
            audio_url = await browser.get_audio_url_from_substack(episode.link)
            return audio_url
    except Exception as e:
        logger.error(f"Browser automation failed for {episode.title}: {e}")
        return None