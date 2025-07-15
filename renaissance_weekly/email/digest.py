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
    
    def send_digest(self, summaries: List[Dict]) -> Dict[str, Any]:
        """Send Renaissance Weekly digest with paragraph summaries
        
        Args:
            summaries: List of dicts with 'episode', 'summary', and 'paragraph_summary'
        
        Returns:
            Dict with 'success' bool and optional 'error' message
        """
        try:
            logger.info("📧 Preparing Renaissance Weekly digest...")
            logger.info(f"   Email From: {EMAIL_FROM}")
            logger.info(f"   Email To: {EMAIL_TO}")
            logger.info(f"   Number of summaries: {len(summaries)}")
            
            # Validate inputs
            if not summaries:
                error_msg = "No summaries provided to send_digest"
                logger.error(error_msg)
                return {"success": False, "error": error_msg}
                
            if not EMAIL_TO:
                error_msg = "EMAIL_TO is not configured"
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
                from_email=(EMAIL_FROM, "Renaissance Weekly"),
                to_emails=EMAIL_TO,
                subject=subject,
                plain_text_content=plain_content,
                html_content=html_content
            )
            
            # Check for dry-run mode
            if os.getenv('DRY_RUN') == 'true':
                logger.info("🧪 DRY RUN: Skipping SendGrid email send")
                logger.info(f"  Subject: {subject}")
                logger.info(f"  To: {EMAIL_TO}")
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
        """Create HTML email with expandable sections"""
        
        # Create episodes HTML with expandable sections
        episodes_html = ""
        
        for i, (episode, paragraph, full_summary) in enumerate(zip(episodes, paragraph_summaries, full_summaries)):
            # Extract guest name for better formatting
            guest_name = self._extract_guest_name(episode.title)
            
            # Create unique IDs for expandable elements
            checkbox_id = f"expand-{i}"
            
            episodes_html += f'''
                <!-- Episode {i + 1} -->
                <div style="margin-bottom: 40px; border-bottom: 1px solid #E0E0E0; padding-bottom: 40px;">
                    <!-- Podcast and Episode Title -->
                    <h2 style="margin: 0 0 10px 0; font-size: 24px; color: #2c3e50; font-family: Georgia, serif;">
                        {escape(episode.podcast)}
                    </h2>
                    <h3 style="margin: 0 0 15px 0; font-size: 18px; color: #34495e; font-family: Georgia, serif; font-weight: normal;">
                        {guest_name} and {self._extract_host_name(episode.podcast)} discuss {self._extract_topics(episode.title)}
                    </h3>
                    <p style="margin: 0 0 20px 0; font-size: 14px; color: #666;">
                        {episode.published.strftime('%B %d, %Y')} • {format_duration(episode.duration)}
                    </p>
                    
                    <!-- Paragraph Summary -->
                    <div style="font-size: 16px; line-height: 1.6; color: #333; margin-bottom: 20px;">
                        {escape(paragraph)}
                    </div>
                    
                    <!-- Expandable Section -->
                    <input type="checkbox" id="{checkbox_id}" style="display: none;">
                    <label for="{checkbox_id}" style="display: inline-block; padding: 10px 20px; background: #f0f0f0; border-radius: 4px; cursor: pointer; font-size: 14px; color: #666; margin-bottom: 20px;">
                        ▼ Read Full Analysis ({len(full_summary.split())} words)
                    </label>
                    
                    <!-- Full Summary (hidden by default) -->
                    <div class="full-summary" id="full-{checkbox_id}" style="display: none; margin-top: 20px;">
                        {self._convert_markdown_to_html(full_summary)}
                    </div>
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
        /* CSS for expandable sections */
        input[type="checkbox"]:checked + label + .full-summary {{
            display: block !important;
        }}
        
        input[type="checkbox"]:checked + label::before {{
            content: "▲ " !important;
        }}
        
        label[for^="expand-"]::before {{
            content: "▼ ";
        }}
        
        /* Basic styles */
        body {{
            margin: 0;
            padding: 0;
            font-family: Georgia, serif;
            font-size: 16px;
            line-height: 1.6;
            color: #333;
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
        
        /* Gmail-specific fixes */
        @media only screen and (max-width: 600px) {{
            .container {{
                width: 100% !important;
                padding: 20px !important;
            }}
        }}
    </style>
</head>
<body>
    <div class="container" style="max-width: 600px; margin: 0 auto; padding: 40px 20px;">
        <!-- Header -->
        <div style="text-align: center; margin-bottom: 40px;">
            <h1 style="margin: 0 0 10px 0; font-size: 36px; color: #000;">Renaissance Weekly</h1>
            <p style="margin: 0 0 20px 0; font-size: 16px; color: #666; font-style: italic;">Investment Intelligence from the Podcast Universe</p>
            <p style="margin: 0; font-size: 14px; color: #999;">{datetime.now().strftime('%B %d, %Y')}</p>
        </div>
        
        <!-- Episodes -->
        {episodes_html}
        
        <!-- Footer -->
        <div style="margin-top: 60px; padding-top: 40px; border-top: 1px solid #E0E0E0; text-align: center; font-size: 14px; color: #666;">
            <p>Renaissance Weekly - For the intellectually ambitious</p>
        </div>
    </div>
</body>
</html>"""
    
    def _generate_subject_line(self, episodes: List[Episode]) -> str:
        """Generate dynamic subject line with featured guests"""
        # Find the most prominent guest name
        guest_names = []
        for episode in episodes:
            guest = self._extract_guest_name(episode.title)
            if guest and guest != "[Guest Name]":
                guest_names.append(guest)
        
        if guest_names:
            # Take the first guest and add "and more"
            featured_guest = guest_names[0]
            return f"The Investment Pods You've Missed: {featured_guest} and more"
        else:
            # Fallback subject
            return f"Renaissance Weekly: {len(episodes)} Essential Conversations"
    
    def _extract_guest_name(self, title: str) -> str:
        """Extract guest name from episode title"""
        import re
        
        # Common patterns in podcast titles
        patterns = [
            r'with\s+([A-Z][a-zA-Z\s]+?)(?:\s*[\|\-\:]|$)',
            r'featuring\s+([A-Z][a-zA-Z\s]+?)(?:\s*[\|\-\:]|$)',
            r'ft\.\s+([A-Z][a-zA-Z\s]+?)(?:\s*[\|\-\:]|$)',
            r'guest[:\s]+([A-Z][a-zA-Z\s]+?)(?:\s*[\|\-\:]|$)',
            r'[\|\-]\s*([A-Z][a-zA-Z\s]+?)\s*[\|\-]',
            r'^([A-Z][a-zA-Z\s]+?):\s',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, title, re.IGNORECASE)
            if match:
                guest = match.group(1).strip()
                # Basic validation
                if 2 <= len(guest.split()) <= 4 and len(guest) < 50:
                    return guest
        
        return "[Guest Name]"
    
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
    
    def _extract_topics(self, title: str) -> str:
        """Extract main topics from title for natural language flow"""
        # Remove common prefixes and guest names
        import re
        
        # Remove patterns like "Ep 123:", "#123:", etc.
        title = re.sub(r'^(Ep\s*\d+|#\d+|Episode\s*\d+)[:\s\-]*', '', title, flags=re.IGNORECASE)
        
        # Remove guest name patterns
        title = re.sub(r'with\s+[A-Z][a-zA-Z\s]+?[\|\-\:]', '', title, flags=re.IGNORECASE)
        title = re.sub(r'featuring\s+[A-Z][a-zA-Z\s]+?[\|\-\:]', '', title, flags=re.IGNORECASE)
        
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