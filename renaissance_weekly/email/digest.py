"""New email digest with expandable sections"""

import os
import re
import time
from datetime import datetime
from typing import List, Dict, Any
from html import escape
from sendgrid.helpers.mail import Mail

from ..config import EMAIL_FROM, EMAIL_TO
from ..models import Episode
from ..utils.logging import get_logger
from ..utils.helpers import format_duration
from ..utils.clients import sendgrid_client

logger = get_logger(__name__)


class EmailDigest:
    """Handle email digest creation and sending with expandable sections"""
    
    def send_digest(self, summaries: List[Dict], email_to: str = None) -> Dict[str, Any]:
        """Send Investment Pods Weekly digest with paragraph summaries
        
        Args:
            summaries: List of dicts with 'episode', 'summary', and 'paragraph_summary'
            email_to: Optional email address to override default recipient
        
        Returns:
            Dict with 'success' bool and optional 'error' message
        """
        try:
            # Use provided email_to or fall back to default
            recipient_email = email_to if email_to else EMAIL_TO
            
            logger.info("📧 Preparing Investment Pods Weekly digest...")
            logger.info(f"   Email From: {EMAIL_FROM}")
            logger.info(f"   Email To: {recipient_email}")
            logger.info(f"   Number of summaries: {len(summaries)}")
            
            # Validate inputs
            if not summaries:
                error_msg = "No summaries provided to send_digest"
                logger.error(error_msg)
                return {"success": False, "error": error_msg}
                
            if not recipient_email:
                error_msg = "No recipient email configured"
                logger.error(error_msg)
                return {"success": False, "error": error_msg}
                
            if not sendgrid_client:
                error_msg = "SendGrid client is not initialized"
                logger.error(error_msg)
                return {"success": False, "error": error_msg}
            
            # Sort alphabetically by podcast name
            sorted_summaries = sorted(summaries, key=lambda s: s['episode'].podcast.lower())
            
            # Extract episodes, paragraphs, and full summaries
            episodes = [s["episode"] for s in sorted_summaries]
            paragraph_summaries = [s.get("paragraph_summary", "") for s in sorted_summaries]
            full_summaries = [s["summary"] for s in sorted_summaries]
            
            # Create email content
            html_content = self.create_expandable_email(full_summaries, episodes, paragraph_summaries)
            plain_content = self._create_plain_text_version(full_summaries)
            
            # Create subject with featured guest
            subject = self._generate_subject_line(episodes)
            
            # Create message
            message = Mail(
                from_email=(EMAIL_FROM, "Investment Pods Weekly"),
                to_emails=recipient_email,
                subject=subject,
                plain_text_content=plain_content,
                html_content=html_content
            )
            
            # Check for dry-run mode
            if os.getenv('DRY_RUN') == 'true':
                logger.info("🧪 DRY RUN: Skipping SendGrid email send")
                logger.info(f"  Subject: {subject}")
                logger.info(f"  To: {recipient_email}")
                logger.info(f"  Episodes: {len(sorted_summaries)}")
                logger.info("  Email would be sent in normal operation")
                return {"success": True}
            
            # Send email with retry logic
            max_retries = 3
            retry_delay = 1  # Start with 1 second
            
            for attempt in range(max_retries):
                try:
                    response = sendgrid_client.send(message)
                    
                    if response.status_code == 202:
                        logger.info("✅ Email sent successfully!")
                        return {"success": True}
                    else:
                        error_msg = f"Email failed with status {response.status_code}"
                        logger.error(error_msg)
                        if hasattr(response, 'body'):
                            logger.error(f"Response body: {response.body}")
                            error_msg += f" - {response.body}"
                        
                        # Don't retry on client errors (4xx)
                        if 400 <= response.status_code < 500:
                            logger.error("Client error - not retrying")
                            return {"success": False, "error": error_msg}
                            
                except Exception as e:
                    logger.error(f"Email attempt {attempt + 1} failed: {e}")
                    
                # If not the last attempt, wait before retrying
                if attempt < max_retries - 1:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
            
            error_msg = f"Email failed after {max_retries} attempts"
            logger.error(error_msg)
            return {"success": False, "error": error_msg}
                
        except Exception as e:
            error_msg = f"Email setup error: {e}"
            logger.error(error_msg)
            return {"success": False, "error": error_msg}
    
    def generate_html_preview(self, summaries: List[Dict]) -> str:
        """Generate HTML preview content (without full HTML document structure)"""
        # Extract episodes, paragraphs, and full summaries
        episodes = [s["episode"] for s in summaries]
        paragraph_summaries = [s.get("paragraph_summary", "") for s in summaries]
        full_summaries = [s["summary"] for s in summaries]
        
        # Generate the full HTML content
        full_html = self.create_expandable_email(full_summaries, episodes, paragraph_summaries)
        
        # Extract just the body content for preview
        # Remove DOCTYPE and html/head tags for iframe display
        import re
        body_match = re.search(r'<body[^>]*>(.*?)</body>', full_html, re.DOTALL)
        if body_match:
            body_content = body_match.group(1)
            # Wrap in a container div for proper styling in iframe
            return f'<div style="padding: 20px; background: white;">{body_content}</div>'
        
        return full_html  # Fallback to full HTML if extraction fails
    
    def create_expandable_email(self, full_summaries: List[str], episodes: List[Episode], paragraph_summaries: List[str]) -> str:
        """Create HTML email with expandable sections using HTML5 details/summary"""
        
        # Create separate mobile and desktop versions
        mobile_episodes_html = ""
        mobile_toc_html = ""
        desktop_toc_html = ""
        desktop_summaries_html = ""
        
        # Build mobile TOC - same as desktop but mobile-optimized
        mobile_toc_html = f'''
            <div style="padding: 0;">
                <table border="0" cellpadding="0" cellspacing="0" width="100%" style="border-top: 1px solid #e0e0e0; margin-top: 8px;">
                    <tr>
                        <td style="padding: 12px 0 10px 0;">
                            <p style="margin: 0; font-size: 11px; color: #888; font-family: Georgia, serif; text-transform: uppercase; letter-spacing: 1.5px;">
                                <a name="mobile-toc"></a>
                                Episodes
                            </p>
                        </td>
                    </tr>
                </table>
                <table border="0" cellpadding="0" cellspacing="0" width="100%" style="margin-bottom: 25px;">
        '''
        
        for i, episode in enumerate(episodes):
            mobile_toc_html += f'''
                <tr>
                    <td style="padding: 12px 0; border-bottom: 1px solid #f0f0f0;">
                        <a href="#mobile-episode-{i}" style="color: #2c3e50; text-decoration: none; font-size: 15px; display: block; line-height: 1.4;" class="episode-directory-title">
                            <strong>{self._format_episode_title(episode)}</strong>
                        </a>
                        <div style="margin-top: 4px; font-size: 12px; color: #888;" class="episode-directory-meta">
                            {episode.published.strftime('%B %d, %Y')} • {format_duration(episode.duration)}
                        </div>
                    </td>
                </tr>
            '''
        
        mobile_toc_html += '''
                </table>
            </div>
        '''
        
        for i, (episode, paragraph, full_summary) in enumerate(zip(episodes, paragraph_summaries, full_summaries)):
            # Extract guest name for better formatting
            guest_name = self._extract_guest_name(episode.title, episode.description)
            
            # Build mobile version (current layout preserved exactly)
            mobile_episodes_html += f'''
                <!-- Episode {i + 1} -->
                <div id="mobile-episode-{i}" style="margin-bottom: 40px; border-bottom: 1px solid #E0E0E0; padding-bottom: 40px;">
                    <a name="mobile-episode-{i}"></a>
                    <!-- Episode Title (Full Name) -->
                    <h2 style="margin: 0 0 10px 0; font-size: 24px; color: #2c3e50; font-family: Georgia, serif;">
                        {self._format_episode_title(episode)}
                    </h2>
                    <p style="margin: 0 0 20px 0; font-size: 14px; color: #666;">
                        {episode.published.strftime('%B %d, %Y')} • {format_duration(episode.duration)} • <a href="{self._get_apple_podcast_link(episode)}" style="color: #0066cc; text-decoration: none;">Link to Full Episode</a>
                    </p>
                    
                    <!-- Paragraph Summary -->
                    <div style="font-size: 16px; line-height: 1.6; color: #333; margin-bottom: 20px;">
                        {escape(paragraph)}
                    </div>
                    
                    <!-- Expandable Section for mobile/modern clients -->
                    <details style="margin-top: 20px;">
                        <summary style="cursor: pointer; padding: 10px 20px; background: #f0f0f0; border-radius: 4px; font-size: 14px; color: #666; display: inline-block; list-style: none;">
                            <span style="font-family: Georgia, serif;">Read Full Summary ▼</span>
                        </summary>
                        
                        <!-- Full Summary Content - starts immediately below button -->
                        <div style="padding: 0 20px 20px 20px; background-color: #f8f8f8; border-radius: 0 0 8px 8px; margin-top: -4px;">
                            <!-- Small visual indicator inline with first paragraph -->
                            <div style="padding-top: 15px;">
                                <span style="font-size: 11px; color: #999; text-transform: uppercase; letter-spacing: 0.5px; font-family: Georgia, serif; display: block; margin-bottom: 10px;">FULL SUMMARY</span>
                                {self._convert_markdown_to_html_enhanced(self._strip_duplicate_title(full_summary, episode))}
                            </div>
                        </div>
                    </details>
                    
                    <p style="margin: 20px 0 0 0; text-align: center;">
                        <a href="#mobile-toc" style="display: inline-block; padding: 8px 16px; background: #2c3e50; color: white; text-decoration: none; border-radius: 4px; font-size: 13px;">↑ Back to Episode List</a>
                    </p>
                    
                </div>
            '''
            
            # Build desktop TOC entry
            desktop_toc_html += f'''
                <tr>
                    <td style="padding: 12px 0; border-bottom: 1px solid #f0f0f0;">
                        <a href="#desktop-episode-{i}" style="color: #2c3e50; text-decoration: none; font-size: 16px; line-height: 1.4;">
                            <strong>{self._format_episode_title(episode)}</strong>
                        </a>
                        <div style="margin-top: 4px; font-size: 13px; color: #888;">
                            {episode.published.strftime('%B %d, %Y')} • {format_duration(episode.duration)}
                        </div>
                    </td>
                </tr>
            '''
            
            # Build desktop full summaries
            desktop_summaries_html += f'''
                <div id="desktop-episode-{i}" style="margin-bottom: 50px; padding-bottom: 30px; border-bottom: 1px solid #E0E0E0;">
                    <a name="desktop-episode-{i}"></a>
                    <h2 style="margin: 0 0 10px 0; font-size: 28px; color: #2c3e50; font-family: Georgia, serif;">
                        {self._format_episode_title(episode)}
                    </h2>
                    <p style="margin: 0 0 20px 0; font-size: 14px; color: #666;">
                        {episode.published.strftime('%B %d, %Y')} • {format_duration(episode.duration)} • <a href="{self._get_apple_podcast_link(episode)}" style="color: #0066cc; text-decoration: none;">Link to Full Episode</a>
                    </p>
                    
                    <div style="padding: 30px; background-color: #f8f8f8; border-radius: 8px; margin-top: 20px;">
                        {self._convert_markdown_to_html_enhanced(self._strip_duplicate_title(full_summary, episode))}
                    </div>
                    
                    <p style="margin: 30px 0 0 0; text-align: center;">
                        <a href="#top" style="display: inline-block; padding: 10px 20px; background: #2c3e50; color: white; text-decoration: none; border-radius: 4px; font-size: 14px;">↑ Back to Episode List</a>
                    </p>
                </div>
            '''
        
        # Generate subject line
        subject = self._generate_subject_line(episodes)
        
        # Create full HTML
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Renaissance Weekly</title>
    <style>
        /* Basic reset and mobile-friendly styles */
        body {{
            margin: 0;
            padding: 0;
            font-family: Georgia, serif;
            font-size: 16px;
            line-height: 1.6;
            color: #333;
            -webkit-text-size-adjust: 100%;
            -ms-text-size-adjust: 100%;
            background-color: #ffffff;
        }}
        
        h1, h2, h3 {{
            font-weight: normal;
        }}
        
        a {{
            color: #0066CC;
            text-decoration: none;
        }}
        
        a:hover {{
            text-decoration: underline;
        }}
        
        /* Mobile/Desktop visibility controls */
        .mobile-only {{
            display: block;
        }}
        
        .desktop-only {{
            display: none;
        }}
        
        /* Desktop styles (min-width: 601px) */
        @media only screen and (min-width: 601px) {{
            .mobile-only {{
                display: none !important;
            }}
            
            .desktop-only {{
                display: block !important;
            }}
        }}
        
        /* Mobile-specific fixes */
        table {{
            border-collapse: collapse;
            mso-table-lspace: 0pt;
            mso-table-rspace: 0pt;
        }}
        
        @media only screen and (max-width: 600px) {{
            .container {{
                width: 100% !important;
            }}
            .content-table {{
                width: 100% !important;
            }}
            h1 {{
                font-size: 28px !important;
            }}
            h2 {{
                font-size: 24px !important;
            }}
            h3 {{
                font-size: 16px !important;
            }}
            .episode-content {{
                padding: 15px !important;
            }}
            /* Mobile-specific styles for Episode Directory */
            .episode-directory-title {{
                font-size: 14px !important;
                line-height: 1.4 !important;
            }}
            .episode-directory-meta {{
                font-size: 12px !important;
            }}
        }}
        
        /* Gmail doesn't support advanced CSS selectors, so we'll use a simpler approach */
    </style>
</head>
<body class="body" style="margin: 0; padding: 0; background-color: #ffffff;">
    <u></u><!-- Gmail detection hack -->
    <a name="top"></a>
    <div id="top"></div>
    <table border="0" cellpadding="0" cellspacing="0" width="100%">
        <tr>
            <td align="center" style="padding: 0;">
                <table class="container" border="0" cellpadding="0" cellspacing="0" width="600" style="max-width: 600px;">
                    <!-- Header -->
                    <tr>
                        <td align="center" style="padding: 25px 20px 20px 20px;">
                            <h1 style="margin: 0 0 8px 0; font-size: 38px; color: #000; font-family: Georgia, serif; font-weight: normal; letter-spacing: -0.5px;">Investment Pods Weekly</h1>
                            <p style="margin: 0 0 10px 0; font-size: 15px; color: #666; font-family: Georgia, serif;">by Pods Distilled</p>
                            <p style="margin: 0; font-size: 13px; color: #999; font-family: Georgia, serif;">{datetime.now().strftime('%B %d, %Y')}</p>
                        </td>
                    </tr>
                    
                    <!-- Mobile Version: TOC and Episodes -->
                    <tr class="mobile-only">
                        <td class="episode-content" style="padding: 0 20px;">
                            {mobile_toc_html}
                            {mobile_episodes_html}
                        </td>
                    </tr>
                    
                    <!-- Desktop Version: Table of Contents -->
                    <tr class="desktop-only">
                        <td style="padding: 0 20px;">
                            <table border="0" cellpadding="0" cellspacing="0" width="100%" style="border-top: 1px solid #e0e0e0; margin-top: 10px;">
                                <tr>
                                    <td style="padding: 15px 0 10px 0;">
                                        <p id="toc" style="margin: 0; font-size: 12px; color: #888; font-family: Georgia, serif; text-transform: uppercase; letter-spacing: 1.5px;">
                                            <a name="toc"></a>
                                            Episodes
                                        </p>
                                    </td>
                                </tr>
                            </table>
                            
                            <!-- Episode list -->
                            <table border="0" cellpadding="0" cellspacing="0" width="100%" style="margin-bottom: 35px;">
                                {desktop_toc_html}
                            </table>
                        </td>
                    </tr>
                    
                    <!-- Desktop Version: Full Summaries -->
                    <tr class="desktop-only">
                        <td style="padding: 0 20px;">
                            {desktop_summaries_html}
                        </td>
                    </tr>
                    
                    <!-- Footer -->
                    <tr>
                        <td align="center" style="padding: 25px 20px; border-top: 1px solid #E0E0E0;">
                            <p style="margin: 0; font-size: 13px; color: #888; font-family: Georgia, serif;">© 2025 Pods Distilled™ · All rights reserved · Not investment advice</p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>"""
    
    def _generate_subject_line(self, episodes: List[Episode]) -> str:
        """Generate dynamic subject line with featured guests or podcasts"""
        # Find the most prominent guest name
        guest_names = []
        for episode in episodes:
            guest = self._extract_guest_name(episode.title, episode.description or "")
            if guest and guest != "the guest":
                guest_names.append(guest)
        
        if guest_names:
            # Take the first guest and add "and more"
            featured_guest = guest_names[0]
            if len(guest_names) > 1:
                return f"Investment Pods: {featured_guest}, {guest_names[1]} & more"
            else:
                return f"Investment Pods: {featured_guest} and more this week"
        else:
            # Better fallback - use podcast names
            unique_podcasts = list(set(ep.podcast for ep in episodes))
            if len(unique_podcasts) <= 3:
                podcast_list = ", ".join(unique_podcasts[:-1]) + f" & {unique_podcasts[-1]}" if len(unique_podcasts) > 1 else unique_podcasts[0]
                return f"Investment Pods Weekly: {podcast_list}"
            else:
                return f"Investment Pods Weekly: {unique_podcasts[0]}, {unique_podcasts[1]} & {len(unique_podcasts)-2} more podcasts"
    
    def _extract_guest_name(self, title: str, description: str = "") -> str:
        """Extract guest name from episode title or description"""
        import re
        
        # More comprehensive patterns for podcast titles
        patterns = [
            # Episode number followed by name before "on"
            r'(?:Ep|Episode)\s*\d+:\s*([A-Z][a-zA-Z\s&]+?)\s+on\s+',
            # Name followed by "on" topic
            r':\s*([A-Z][a-zA-Z\s&]+?)\s+on\s+[A-Z]',
            # Episode # followed by name and "and" (like "#763: Howard Marks and...")
            r'^#\d+:\s*([A-Z][a-zA-Z\s]+?)\s+and\s+',
            # Name at start before colon (moved up for priority)
            r'^([A-Z][a-zA-Z\s&]+?):\s',
            # Name BEFORE "with" (to catch "Stanley Druckenmiller with...")
            r'^([A-Z][a-zA-Z\s&]+?)\s+with\s+',
            # With/featuring patterns (after checking name before with)
            r'with\s+([A-Z][a-zA-Z\s&]+?)(?:\s*[\|\-\:]|$)',
            r'featuring\s+([A-Z][a-zA-Z\s&]+?)(?:\s*[\|\-\:]|$)',
            r'ft\.\s+([A-Z][a-zA-Z\s&]+?)(?:\s*[\|\-\:]|$)',
            # Guest patterns
            r'guest[:\s]+([A-Z][a-zA-Z\s&]+?)(?:\s*[\|\-\:]|$)',
            # Names at end after pipe/dash
            r'[\|\-]\s*([A-Z][a-zA-Z\s&]+?)(?:\s*$)',
            # Names between delimiters
            r'[\|\-]\s*([A-Z][a-zA-Z\s&]+?)\s*[\|\-]',
        ]
        
        # Try title first
        for pattern in patterns:
            match = re.search(pattern, title, re.IGNORECASE)
            if match:
                guest = match.group(1).strip()
                # More flexible validation - allow "&" and up to 6 words
                word_count = len(guest.split())
                if 1 <= word_count <= 6 and len(guest) < 80:
                    # Clean up common artifacts
                    guest = re.sub(r'\s+&\s+', ' & ', guest)  # Normalize ampersands
                    guest = guest.strip(' &')  # Remove trailing ampersands
                    # Don't return single common words
                    if word_count == 1 and guest.lower() in ['the', 'with', 'and', 'on']:
                        continue
                    return guest
        
        # Special handling for "Name & Name" pattern at end of title
        name_pair_pattern = r'[\|\-:]\s*([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*)\s*&\s*([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*)\s*$'
        match = re.search(name_pair_pattern, title)
        if match:
            name1 = match.group(1).strip()
            name2 = match.group(2).strip()
            return f"{name1} & {name2}"
        
        # Try description as fallback with same patterns
        if description:
            for pattern in patterns[:6]:  # Use first 6 patterns for description
                match = re.search(pattern, description, re.IGNORECASE)
                if match:
                    guest = match.group(1).strip()
                    word_count = len(guest.split())
                    if 1 <= word_count <= 6 and len(guest) < 80:
                        guest = re.sub(r'\s+&\s+', ' & ', guest)
                        guest = guest.strip(' &')
                        return guest
        
        return "the guest"
    
    def _extract_host_name(self, podcast_name: str) -> str:
        """Extract or infer host name from podcast name"""
        # Known mappings
        host_mapping = {
            "Tim Ferriss": "Tim Ferriss",
            "All-In": "the All-In hosts",
            "The Drive": "Peter Attia",
            "Lex Fridman": "Lex Fridman",
            "Dwarkesh Podcast": "Dwarkesh Patel",
            "EconTalk": "Russ Roberts",
            "Invest Like the Best": "Patrick O'Shaughnessy",
        }
        
        return host_mapping.get(podcast_name, "the host")
    
    def _extract_topics(self, title: str, guest_name: str) -> str:
        """Extract main topics from title for natural language flow"""
        # Remove common prefixes and guest names
        import re
        
        # Remove patterns like "Ep 123:", "#123:", etc.
        title = re.sub(r'^(Ep\s*\d+|#\d+|Episode\s*\d+)[:\s\-]*', '', title, flags=re.IGNORECASE)
        
        # Remove the specific guest name if found
        if guest_name and guest_name != "the guest":
            title = title.replace(guest_name, '').strip()
        
        # Remove guest name patterns
        title = re.sub(r'with\s+[A-Z][a-zA-Z\s]+?[\|\-\:]', '', title, flags=re.IGNORECASE)
        title = re.sub(r'featuring\s+[A-Z][a-zA-Z\s]+?[\|\-\:]', '', title, flags=re.IGNORECASE)
        title = re.sub(r'ft\.\s+[A-Z][a-zA-Z\s]+?[\|\-\:]', '', title, flags=re.IGNORECASE)
        
        # Clean up and lowercase first letter
        title = title.strip(' |-:')
        if title and title[0].isupper():
            title = title[0].lower() + title[1:]
        
        return title or "various topics"
    
    def _convert_markdown_to_html(self, markdown: str) -> str:
        """Convert markdown to HTML"""
        # Basic markdown to HTML conversion
        html = escape(markdown)
        
        # Convert headers
        html = re.sub(r'^### (.+)$', r'<h4>\1</h4>', html, flags=re.MULTILINE)
        html = re.sub(r'^## (.+)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
        html = re.sub(r'^# (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
        
        # Convert bold
        html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
        
        # Convert italic
        html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)
        
        # Convert bullet points
        html = re.sub(r'^[•\-\*]\s+(.+)$', r'<li>\1</li>', html, flags=re.MULTILINE)
        
        # Wrap consecutive <li> in <ul>
        html = re.sub(r'(<li>.*?</li>\s*)+', lambda m: f'<ul>{m.group(0)}</ul>', html, flags=re.DOTALL)
        
        # Convert paragraphs
        paragraphs = html.split('\n\n')
        html_paragraphs = []
        for p in paragraphs:
            p = p.strip()
            if p and not p.startswith('<'):
                p = f'<p>{p}</p>'
            html_paragraphs.append(p)
        
        return '\n'.join(html_paragraphs)
    
    def _convert_markdown_to_html_enhanced(self, markdown: str) -> str:
        """Convert markdown to HTML with enhanced formatting for email clients"""
        # First escape HTML
        html = escape(markdown)
        
        # Convert headers with inline styles
        html = re.sub(r'^### (.+)$', r'<h4 style="margin: 20px 0 10px 0; font-size: 16px; color: #34495e; font-family: Georgia, serif;">\1</h4>', html, flags=re.MULTILINE)
        html = re.sub(r'^## (.+)$', r'<h3 style="margin: 20px 0 10px 0; font-size: 18px; color: #2c3e50; font-family: Georgia, serif;">\1</h3>', html, flags=re.MULTILINE)
        html = re.sub(r'^# (.+)$', r'<h2 style="margin: 20px 0 10px 0; font-size: 20px; color: #2c3e50; font-family: Georgia, serif;">\1</h2>', html, flags=re.MULTILINE)
        
        # Convert bold and italic
        html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
        html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)
        
        # Convert bullet points with proper spacing
        html = re.sub(r'^[•\-\*]\s+(.+)$', r'<li style="margin-bottom: 8px; line-height: 1.6;">\1</li>', html, flags=re.MULTILINE)
        
        # Wrap consecutive <li> in <ul> with margin
        lines = html.split('\n')
        result_lines = []
        in_list = False
        list_items = []
        
        for line in lines:
            if '<li' in line:
                if not in_list:
                    in_list = True
                list_items.append(line)
            else:
                if in_list and list_items:
                    # Close the list
                    result_lines.append('<ul style="margin: 15px 0; padding-left: 20px;">')
                    result_lines.extend(list_items)
                    result_lines.append('</ul>')
                    list_items = []
                    in_list = False
                result_lines.append(line)
        
        # Handle any remaining list items
        if list_items:
            result_lines.append('<ul style="margin: 15px 0; padding-left: 20px;">')
            result_lines.extend(list_items)
            result_lines.append('</ul>')
        
        html = '\n'.join(result_lines)
        
        # Split into paragraphs and add proper spacing
        paragraphs = html.split('\n\n')
        html_paragraphs = []
        
        for p in paragraphs:
            p = p.strip()
            if p:
                # Check if it's already an HTML tag
                if p.startswith('<h') or p.startswith('<ul'):
                    html_paragraphs.append(p)
                else:
                    # Regular paragraph with spacing
                    html_paragraphs.append(f'<p style="margin: 0 0 15px 0; line-height: 1.6; font-size: 16px; color: #333;">{p}</p>')
        
        # Join with explicit spacing
        return '\n'.join(html_paragraphs)
    
    def _create_plain_text_version(self, summaries: List[str]) -> str:
        """Create plain text version of email"""
        plain_text = "RENAISSANCE WEEKLY\n"
        plain_text += "=" * 50 + "\n\n"
        plain_text += f"Date: {datetime.now().strftime('%B %d, %Y')}\n\n"
        
        for i, summary in enumerate(summaries, 1):
            plain_text += f"EPISODE {i}\n"
            plain_text += "-" * 30 + "\n"
            plain_text += summary + "\n\n"
        
        plain_text += "=" * 50 + "\n"
        plain_text += "Renaissance Weekly - For the intellectually ambitious\n"
        
        return plain_text
    
    def _format_episode_title(self, episode: Episode) -> str:
        """Format episode title, avoiding duplicate podcast names"""
        import re
        
        title = escape(episode.title)
        podcast_name = escape(episode.podcast)
        
        # Check if the title already contains the podcast name (case insensitive)
        # Handle variations like "MacroVoices" vs "Macro Voices"
        podcast_name_normalized = podcast_name.lower().replace(' ', '')
        title_normalized = title.lower().replace(' ', '')
        
        # Check if podcast name is already in the title
        if podcast_name_normalized in title_normalized:
            # Just return the title as-is
            return title
        
        # Also check for common patterns like "#488" which indicate the podcast name is implicit
        if re.match(r'^#\d+[:\s]', title):
            # Episode number format, prepend podcast name
            return f"{podcast_name}: {title}"
        
        # Otherwise prepend the podcast name
        return f"{podcast_name}: {title}"
    
    def _strip_duplicate_title(self, summary: str, episode: Episode) -> str:
        """Strip duplicate title from the beginning of the summary"""
        import re
        
        # Check if summary starts with the episode title (as a header or plain text)
        lines = summary.strip().split('\n')
        if not lines:
            return summary
        
        first_line = lines[0].strip()
        
        # Remove markdown headers
        first_line_clean = re.sub(r'^#+\s*', '', first_line)
        
        # Check if first line matches the episode title
        title_normalized = episode.title.lower().strip()
        first_line_normalized = first_line_clean.lower().strip()
        
        # Also check with podcast name prepended
        full_title = f"{episode.podcast}: {episode.title}".lower().strip()
        
        if (first_line_normalized == title_normalized or 
            first_line_normalized == full_title or
            title_normalized in first_line_normalized):
            # Remove the first line
            return '\n'.join(lines[1:]).strip()
        
        return summary
    
    def _get_apple_podcast_link(self, episode: Episode) -> str:
        """Get Apple Podcasts link for episode"""
        # If we have a direct episode link, use that
        if episode.link and 'apple.com' in episode.link:
            return episode.link
        
        # Otherwise construct from apple_podcast_id if available
        if episode.apple_podcast_id:
            return f"https://podcasts.apple.com/us/podcast/id{episode.apple_podcast_id}"
        
        # Fallback to generic link or episode link
        return episode.link or "#"
    
    def _extract_and_format_resources(self, summary: str) -> str:
        """Extract and format books/resources mentioned in the summary"""
        import re
        
        # Look for book titles (in quotes or italics)
        book_patterns = [
            r'"([^"]+)"\s*by\s*([A-Z][a-zA-Z\s\.]+?)(?:[,\.]|$)',  # "Title" by Author
            r'book\s+"([^"]+)"',  # book "Title"
            r'\*([^\*]+)\*\s*by\s*([A-Z][a-zA-Z\s\.]+?)(?:[,\.]|$)',  # *Title* by Author
        ]
        
        books = []
        book_titles_seen = set()
        for pattern in book_patterns:
            matches = re.findall(pattern, summary, re.IGNORECASE)
            for match in matches:
                if isinstance(match, tuple):
                    title = match[0].strip()
                    author = match[1].strip() if len(match) > 1 else ""
                    # Clean up the extraction
                    if title and not any(skip in title.lower() for skip in ['the book', 'his book', 'her book']):
                        # Check for duplicates by title
                        title_key = title.lower()
                        if title_key not in book_titles_seen:
                            book_titles_seen.add(title_key)
                            books.append(f"{title} by {author}" if author else title)
                else:
                    if match and not any(skip in match.lower() for skip in ['the book', 'his book', 'her book']):
                        title_key = match.strip().lower()
                        if title_key not in book_titles_seen:
                            book_titles_seen.add(title_key)
                            books.append(match.strip())
        
        # Look for other resources (websites, papers, etc.)
        resource_patterns = [
            r'(?:paper|article)\s*"([^"]+)"',  # paper "Title"
            r'(?:website|site)\s+([a-zA-Z0-9\-]+\.(?:com|org|net|io|ai)(?:/[^\s]*)?)',  # website domain.com/path
            r'(?:available at|found at|see)\s+([a-zA-Z0-9\-]+\.(?:com|org|net|io|ai)(?:/[^\s]*)?)',
        ]
        
        resources = []
        for pattern in resource_patterns:
            matches = re.findall(pattern, summary, re.IGNORECASE)
            for match in matches:
                resource = match.strip().rstrip('.')
                if len(resource) > 10:
                    resources.append(resource)
        
        # Books are already de-duplicated above
        unique_books = books
        
        # Remove duplicate resources
        seen = set()
        unique_resources = []
        for resource in resources:
            if resource.lower() not in seen:
                seen.add(resource.lower())
                unique_resources.append(resource)
        
        # Format the output
        if not unique_books and not unique_resources:
            return ""
        
        html = '<div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #e0e0e0;">'
        html += '<h4 style="margin: 0 0 15px 0; font-size: 16px; color: #2c3e50; font-family: Georgia, serif;">Resources Mentioned</h4>'
        
        if unique_books:
            html += '<p style="margin: 0 0 10px 0; font-size: 14px; color: #666; font-weight: bold;">Books:</p>'
            html += '<ul style="margin: 0 0 20px 0; padding-left: 20px;">'
            for book in unique_books[:5]:  # Limit to 5 books
                html += f'<li style="margin-bottom: 5px; font-size: 14px; color: #333;">{escape(book)}</li>'
            html += '</ul>'
        
        if unique_resources:
            html += '<p style="margin: 0 0 10px 0; font-size: 14px; color: #666; font-weight: bold;">Other Resources:</p>'
            html += '<ul style="margin: 0 0 20px 0; padding-left: 20px;">'
            for resource in unique_resources[:5]:  # Limit to 5 resources
                html += f'<li style="margin-bottom: 5px; font-size: 14px; color: #333;">{escape(resource)}</li>'
            html += '</ul>'
        
        html += '</div>'
        return html
    
    def _format_sponsors(self, episode: Episode, full_summary: str = "") -> str:
        """Format sponsor information for the episode"""
        import re
        
        # Common sponsor patterns
        sponsor_patterns = [
            # Standard sponsorship mentions
            r'(?:sponsored by|brought to you by|thanks to|sponsor[s]? (?:are|is|include[s]?))\s+([A-Z][^\.,\n]{2,40})',
            r'(?:today\'s sponsor|our sponsor|this episode\'s sponsor)[s]?\s*[:\-]?\s*([A-Z][^\.,\n]{2,40})',
            # Company names with URLs
            r'(?:visit|go to|check out)\s+([A-Z][a-zA-Z0-9]+)(?:\s+at)?\s+[a-zA-Z0-9]+\.(?:com|org|net|io|ai)',
            # Direct company mentions with promo codes
            r'([A-Z][a-zA-Z0-9]+)\s+(?:promo code|discount code|code)',
            # Common sponsor formats
            r'thanks to\s+([A-Z][a-zA-Z0-9\s&]+?)(?:\s+for\s+sponsoring)',
        ]
        
        sponsors = []
        sponsor_links = {}
        
        # Search in both description and summary
        search_texts = []
        if episode.description:
            search_texts.append(episode.description)
        if full_summary:
            search_texts.append(full_summary)
        
        for text in search_texts:
            # Extract sponsors
            for pattern in sponsor_patterns:
                matches = re.findall(pattern, text, re.IGNORECASE | re.MULTILINE)
                for match in matches:
                    sponsor = match.strip()
                    # Clean up sponsor name
                    sponsor = re.sub(r'\s*[-\.]\s*(?:visit|go to|check out).*$', '', sponsor, flags=re.IGNORECASE)
                    sponsor = re.sub(r'\s+at\s+[a-zA-Z0-9]+\..*$', '', sponsor, flags=re.IGNORECASE)
                    sponsor = re.sub(r'\s*\(.*?\)\s*$', '', sponsor)  # Remove parenthetical info
                    sponsor = sponsor.strip(' .,;:')
                    
                    # Validate sponsor name
                    if (len(sponsor) > 2 and len(sponsor) < 40 and 
                        not sponsor.lower() in ['the', 'and', 'our', 'their', 'this', 'that']):
                        sponsors.append(sponsor)
            
            # Extract sponsor URLs
            url_patterns = [
                r'([a-zA-Z0-9]+\.(?:com|org|net|io|ai)/[a-zA-Z0-9\-_/]+)',
                r'(?:www\.)([a-zA-Z0-9]+\.(?:com|org|net|io|ai))',
                r'([a-zA-Z0-9]+)\.(?:com|org|net|io|ai)/([a-zA-Z0-9]+)',  # domain.com/promo
            ]
            
            for pattern in url_patterns:
                urls = re.findall(pattern, text, re.IGNORECASE)
                for url in urls:
                    if isinstance(url, tuple):
                        url = '/'.join(url)
                    if not url.startswith('http'):
                        sponsor_links[url] = f"https://{url}"
        
        # Remove duplicates and clean up
        unique_sponsors = []
        seen = set()
        for sponsor in sponsors:
            sponsor_clean = sponsor.strip()
            sponsor_lower = sponsor_clean.lower()
            if sponsor_lower not in seen and sponsor_clean:
                seen.add(sponsor_lower)
                unique_sponsors.append(sponsor_clean)
        
        # Try to match sponsors with their URLs
        for sponsor in unique_sponsors:
            sponsor_key = sponsor.lower().replace(' ', '').replace('-', '')
            for url, full_url in sponsor_links.items():
                if sponsor_key in url.lower() or url.lower() in sponsor_key:
                    sponsor_links[sponsor] = full_url
                    break
        
        if not unique_sponsors:
            return ""
        
        # Format sponsor section
        html = '<div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #e0e0e0;">'
        html += '<h4 style="margin: 0 0 15px 0; font-size: 16px; color: #2c3e50; font-family: Georgia, serif;">Sponsors</h4>'
        html += '<div style="font-size: 14px; line-height: 1.8; color: #333;">'
        
        for i, sponsor in enumerate(unique_sponsors[:5]):  # Limit to 5 sponsors
            if i > 0:
                html += '<span style="color: #ccc; margin: 0 8px;">•</span>'
            if sponsor in sponsor_links:
                html += f'<a href="{sponsor_links[sponsor]}" style="color: #0066cc; text-decoration: none;">{escape(sponsor)}</a>'
            else:
                html += f'<span>{escape(sponsor)}</span>'
        
        html += '</div>'
        html += '</div>'
        return html