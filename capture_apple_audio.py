#!/usr/bin/env python3
"""Use Playwright to capture audio URL from Apple Podcasts web player"""

import asyncio
from playwright.async_api import async_playwright
import re

async def capture_audio_url():
    print("CAPTURING AUDIO URL FROM APPLE PODCASTS WEB PLAYER")
    print("=" * 80)
    
    episode_url = "https://podcasts.apple.com/us/podcast/ep-118-marc-andreessen-on-ai-robotics-americas-industrial/id1573141757?i=1000715621905"
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--disable-blink-features=AutomationControlled']
        )
        
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        )
        
        page = await context.new_page()
        
        # Capture all network requests
        audio_urls = []
        
        async def handle_request(request):
            url = request.url
            # Look for audio file requests
            if any(ext in url for ext in ['.mp3', '.m4a', '.aac', 'audio']):
                print(f"Found audio request: {url[:100]}...")
                audio_urls.append(url)
            # Also capture any interesting API calls
            if 'api' in url and 'apple' in url:
                print(f"API request: {url[:100]}...")
        
        # Set up request interception
        page.on('request', handle_request)
        
        print(f"\nNavigating to: {episode_url}")
        
        try:
            # Navigate to the page
            await page.goto(episode_url, wait_until='networkidle', timeout=30000)
            
            print("Page loaded, waiting for player...")
            await page.wait_for_timeout(3000)
            
            # Try to find and click play button
            play_selectors = [
                'button[aria-label*="play" i]',
                'button[aria-label*="Play" i]',
                'button.play-button',
                '[class*="play-button"]',
                'button[data-testid*="play"]',
                'svg[aria-label*="play" i]'
            ]
            
            for selector in play_selectors:
                try:
                    play_button = await page.query_selector(selector)
                    if play_button:
                        print(f"Found play button with selector: {selector}")
                        await play_button.click()
                        print("Clicked play button!")
                        break
                except:
                    continue
            
            # Wait for audio to start loading
            await page.wait_for_timeout(5000)
            
            # Also check for audio elements in the DOM
            audio_elements = await page.query_selector_all('audio')
            print(f"\nFound {len(audio_elements)} audio elements")
            
            for audio in audio_elements:
                src = await audio.get_attribute('src')
                if src:
                    print(f"Audio element src: {src[:100]}...")
                    audio_urls.append(src)
            
            # Check for video elements (sometimes used for audio)
            video_elements = await page.query_selector_all('video')
            print(f"Found {len(video_elements)} video elements")
            
            for video in video_elements:
                src = await video.get_attribute('src')
                if src:
                    print(f"Video element src: {src[:100]}...")
                    audio_urls.append(src)
            
            # Try to extract from JavaScript
            try:
                # Look for any JavaScript variables containing URLs
                js_urls = await page.evaluate("""
                    () => {
                        const urls = [];
                        // Check window object for audio URLs
                        for (const key in window) {
                            if (typeof window[key] === 'string' && window[key].includes('.mp3')) {
                                urls.push(window[key]);
                            }
                        }
                        // Check localStorage
                        for (let i = 0; i < localStorage.length; i++) {
                            const value = localStorage.getItem(localStorage.key(i));
                            if (value && value.includes('.mp3')) {
                                urls.push(value);
                            }
                        }
                        return urls;
                    }
                """)
                
                if js_urls:
                    print(f"\nFound URLs in JavaScript: {len(js_urls)}")
                    for url in js_urls:
                        print(f"   - {url[:100]}...")
                        audio_urls.append(url)
            except:
                pass
            
        except Exception as e:
            print(f"\nError: {e}")
        
        finally:
            await browser.close()
        
        print(f"\n\nSUMMARY:")
        print(f"Total audio URLs captured: {len(set(audio_urls))}")
        
        # Remove duplicates and print unique URLs
        unique_urls = list(set(audio_urls))
        for i, url in enumerate(unique_urls, 1):
            print(f"\n{i}. {url}")
            
            # Check if it's accessible
            if not url.startswith('blob:'):
                print("   Testing accessibility...")
                import aiohttp
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.head(url, timeout=5) as resp:
                            print(f"   Status: {resp.status}")
                            if resp.status == 200:
                                print(f"   ✅ This URL is accessible!")
                except Exception as e:
                    print(f"   ❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(capture_audio_url())