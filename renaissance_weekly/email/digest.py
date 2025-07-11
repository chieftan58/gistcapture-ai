"""Email digest generation and sending"""

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
    """Handle email digest creation and sending"""
    
    def send_digest(self, summaries: List[Dict]) -> Dict[str, Any]:
        """Send Renaissance Weekly digest
        
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
            
            # Summaries should already be sorted by app.py
            # But ensure they maintain the order: alphabetical by podcast, then date descending
            sorted_summaries = sorted(summaries, key=lambda s: (
                s['episode'].podcast.lower(),
                -s['episode'].published.timestamp()
            ))
            
            # Extract episodes from summaries
            episodes = [s["episode"] for s in sorted_summaries]
            summary_texts = [s["summary"] for s in sorted_summaries]
            
            # Create email content
            html_content = self.create_substack_style_email(summary_texts, episodes)
            plain_content = self._create_plain_text_version(summary_texts)
            
            # Create subject with correct count
            subject = f"Renaissance Weekly: {len(sorted_summaries)} Essential Conversation{'s' if len(sorted_summaries) != 1 else ''}"
            
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
                return True
            
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
        # Extract episodes and summary texts
        episodes = [s["episode"] for s in summaries]
        summary_texts = [s["summary"] for s in summaries]
        
        # Generate the full HTML content
        full_html = self.create_substack_style_email(summary_texts, episodes)
        
        # Extract just the body content for preview
        # Remove DOCTYPE and html/head tags for iframe display
        import re
        body_match = re.search(r'<body[^>]*>(.*?)</body>', full_html, re.DOTALL)
        if body_match:
            body_content = body_match.group(1)
            # Wrap in a container div for proper styling in iframe
            return f'<div style="padding: 20px; background: white;">{body_content}</div>'
        
        return full_html  # Fallback to full HTML if extraction fails
    
    def create_substack_style_email(self, summaries: List[str], episodes: List[Episode]) -> str:
        """Create clean HTML email with Gmail-compatible table of contents and better structure"""
        
        # Group episodes by podcast for better organization
        episodes_by_podcast = {}
        for i, (summary, episode) in enumerate(zip(summaries, episodes[:len(summaries)])):
            if episode.podcast not in episodes_by_podcast:
                episodes_by_podcast[episode.podcast] = []
            episodes_by_podcast[episode.podcast].append((i, episode, summary))
        
        # Sort podcasts alphabetically
        sorted_podcasts = sorted(episodes_by_podcast.keys(), key=lambda x: x.lower())
        
        # Create table of contents with Gmail-compatible links
        toc_html = ""
        for podcast_name in sorted_podcasts:
            podcast_episodes = episodes_by_podcast[podcast_name]
            for i, episode, _ in podcast_episodes:
                # Create a safe anchor name
                anchor_name = f"episode{i}"
                
                toc_html += f'''
                    <tr>
                        <td style="padding: 8px 0;">
                            <a href="#{anchor_name}" style="color: #0066CC; text-decoration: none; font-size: 16px;">
                                <strong>{escape(episode.podcast)}</strong>: {escape(episode.title)}
                            </a>
                            <div style="font-size: 14px; color: #666; margin-top: 4px;">
                                Release Date: {episode.published.strftime('%B %d, %Y')} • {format_duration(episode.duration)}
                            </div>
                        </td>
                    </tr>'''
        
        # Create episodes HTML with Gmail-compatible anchors
        episodes_html = ""
        episode_counter = 0
        
        for podcast_idx, podcast_name in enumerate(sorted_podcasts):
            podcast_episodes = episodes_by_podcast[podcast_name]
            
            for ep_idx, (i, episode, summary) in enumerate(podcast_episodes):
                if episode_counter > 0:
                    # Visual separator between episodes
                    episodes_html += '''
                        <tr>
                            <td style="padding: 60px 0;">
                                <hr style="border: none; border-top: 2px solid #E0E0E0; margin: 0;">
                            </td>
                        </tr>'''
                
                # Create anchor using both id and name for maximum compatibility
                anchor_name = f"episode{i}"
                
                # Add anchor and episode content
                episodes_html += f'''
                    <tr>
                        <td style="padding: 0;">
                            <!-- Gmail-compatible anchor -->
                            <a name="{anchor_name}" id="{anchor_name}" style="display: block; position: relative; top: -60px; visibility: hidden;"></a>
                            
                            <!-- Episode header -->
                            <div style="background: #f0f8ff; padding: 20px; border-radius: 8px; margin-bottom: 30px;">
                                <h2 style="margin: 0 0 10px 0; font-size: 28px; color: #2c3e50; font-family: Georgia, serif; font-weight: normal;">
                                    {escape(episode.podcast)}
                                </h2>
                                <h3 style="margin: 0 0 15px 0; font-size: 20px; color: #34495e; font-family: Georgia, serif; font-weight: normal;">
                                    {escape(episode.title)}
                                </h3>
                                <p style="margin: 0; font-size: 14px; color: #666;">
                                    Release Date: {episode.published.strftime('%B %d, %Y')} • Duration: {format_duration(episode.duration)}
                                </p>
                            </div>'''
                
                # Convert markdown to HTML
                html_content = self._convert_markdown_to_html(summary)
                
                # Wrap content
                episodes_html += f'''
                            <!-- Episode content -->
                            <div style="background: #ffffff; padding: 0 0 40px 0;">
                                {html_content}
                                <div style="margin-top: 40px; text-align: right;">
                                    <a href="#toc" style="color: #666666; text-decoration: none; font-size: 14px;">↑ Back to top</a>
                                </div>
                            </div>
                        </td>
                    </tr>'''
                
                episode_counter += 1
        
        # Create full HTML with DOCTYPE for better Gmail rendering
        return f"""<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" lang="en">
<head>
    <meta http-equiv="Content-Type" content="text/html; charset=utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="X-UA-Compatible" content="IE=edge">
    <title>Renaissance Weekly</title>
    <!--[if mso]>
    <style type="text/css">
        table {{border-collapse: collapse;}}
        .outlook-font {{font-family: Arial, sans-serif !important;}}
    </style>
    <![endif]-->
    <style type="text/css">
        /* Reset styles */
        body, table, td, a {{ -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }}
        table, td {{ mso-table-lspace: 0pt; mso-table-rspace: 0pt; }}
        img {{ -ms-interpolation-mode: bicubic; border: 0; outline: none; text-decoration: none; }}
        
        /* Remove default link styles in Gmail */
        a[x-apple-data-detectors] {{
            color: inherit !important;
            text-decoration: none !important;
            font-size: inherit !important;
            font-family: inherit !important;
            font-weight: inherit !important;
            line-height: inherit !important;
        }}
        
        /* Gmail-specific anchor fix */
        a[name] {{
            display: block;
            position: relative;
            top: -60px;
            visibility: hidden;
        }}
    </style>
</head>
<body style="margin: 0; padding: 0; font-family: Georgia, serif; font-size: 18px; line-height: 1.6; color: #333; background-color: #FFFFFF; -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%;">
    <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="background-color: #FFFFFF;">
        <tr>
            <td align="center" style="padding: 40px 20px;">
                <!--[if mso]>
                <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="600">
                <tr>
                <td>
                <![endif]-->
                <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="max-width: 600px;">
                    <!-- Header -->
                    <tr>
                        <td style="padding: 0 0 40px 0; text-align: center;">
                            <h1 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 48px; font-weight: normal; letter-spacing: -1px; color: #000000; mso-line-height-rule: exactly; line-height: 1.1;">Renaissance Weekly</h1>
                            <p style="margin: 0 0 20px 0; font-size: 18px; color: #666666; font-style: italic; font-family: Georgia, serif;">The smartest podcasts, distilled.</p>
                            <p style="margin: 0; font-size: 14px; color: #999999; text-transform: uppercase; letter-spacing: 1px; font-family: Arial, sans-serif;">{datetime.now().strftime('%B %d, %Y')}</p>
                        </td>
                    </tr>
                    
                    <!-- Introduction -->
                    <tr>
                        <td style="padding: 0 0 50px 0;">
                            <p style="margin: 0; font-size: 20px; line-height: 1.7; color: #333333; font-weight: 300; font-family: Georgia, serif;">In a world of infinite content, attention is the scarcest resource. This week's edition brings you the essential insights from conversations that matter.</p>
                        </td>
                    </tr>
                    
                    <!-- Table of Contents Anchor -->
                    <tr>
                        <td>
                            <a name="toc" id="toc" style
                            <a name="toc" id="toc" style="display: block; position: relative; top: -60px; visibility: hidden;"></a>
                        </td>
                    </tr>
                    
                    <!-- Table of Contents -->
                    <tr>
                        <td style="padding: 0 0 50px 0;">
                            <div style="background: #f8f8f8; padding: 30px; border-radius: 8px;">
                                <h2 style="margin: 0 0 20px 0; font-size: 24px; color: #000000; font-family: Georgia, serif; font-weight: normal;">This Week's Essential Conversations</h2>
                                <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%">
                                    {toc_html}
                                </table>
                            </div>
                        </td>
                    </tr>
                    
                    <!-- Episodes -->
                    {episodes_html}
                    
                    <!-- Footer -->
                    <tr>
                        <td style="padding: 60px 0 40px 0; text-align: center; border-top: 1px solid #E0E0E0;">
                            <p style="margin: 0 0 15px 0; font-size: 24px; font-family: Georgia, serif; color: #000000;">Renaissance Weekly</p>
                            <p style="margin: 0 0 20px 0; font-size: 16px; color: #666666; font-style: italic; font-family: Georgia, serif;">"For those who remain curious."</p>
                            <p style="margin: 0; font-size: 14px; color: #999999;">
                                <a href="https://gistcapture.ai" style="color: #666666; text-decoration: none;">gistcapture.ai</a>
                            </p>
                        </td>
                    </tr>
                </table>
                <!--[if mso]>
                </td>
                </tr>
                </table>
                <![endif]-->
            </td>
        </tr>
    </table>
</body>
</html>"""
    
    def _convert_markdown_to_html(self, markdown: str) -> str:
        """Convert markdown to HTML with proper handling and escaping"""
        lines = markdown.split('\n')
        html_lines = []
        in_code_block = False
        current_paragraph = []
        
        for line in lines:
            # Handle code blocks
            if line.strip().startswith('```'):
                if current_paragraph:
                    html_lines.append('<p style="margin: 0 0 20px 0;">' + ' '.join(current_paragraph) + '</p>')
                    current_paragraph = []
                
                in_code_block = not in_code_block
                if in_code_block:
                    html_lines.append('<pre style="background: #f5f5f5; padding: 15px; border-radius: 5px; overflow-x: auto; margin: 0 0 20px 0;"><code>')
                else:
                    html_lines.append('</code></pre>')
                continue
            
            if in_code_block:
                html_lines.append(escape(line))
                continue
            
            # Handle headers (must be at start of line)
            if line.strip():
                header_match = re.match(r'^(#{1,6})\s+(.*)$', line)
                if header_match:
                    if current_paragraph:
                        html_lines.append('<p style="margin: 0 0 20px 0;">' + ' '.join(current_paragraph) + '</p>')
                        current_paragraph = []
                    
                    level = len(header_match.group(1))
                    text = header_match.group(2)
                    
                    # Process inline formatting in headers
                    text = self._process_inline_formatting(text)
                    
                    if level == 1:
                        html_lines.append(f'<h1 style="margin: 40px 0 30px 0; font-size: 32px; color: #000000; font-family: Georgia, serif; font-weight: normal;">{text}</h1>')
                    elif level == 2:
                        html_lines.append(f'<h2 style="margin: 35px 0 20px 0; font-size: 26px; color: #000000; font-family: Georgia, serif; font-weight: normal;">{text}</h2>')
                    elif level == 3:
                        html_lines.append(f'<h3 style="margin: 30px 0 15px 0; font-size: 22px; color: #333333; font-weight: 600;">{text}</h3>')
                    else:
                        html_lines.append(f'<h{level} style="margin: 25px 0 15px 0; font-size: 18px; color: #333333; font-weight: 600;">{text}</h{level}>')
                    continue
                
                # Handle lists
                if line.strip().startswith('- ') or line.strip().startswith('* '):
                    if current_paragraph:
                        html_lines.append('<p style="margin: 0 0 20px 0;">' + ' '.join(current_paragraph) + '</p>')
                        current_paragraph = []
                    
                    # Check if we're continuing a list or starting a new one
                    if not html_lines or not html_lines[-1].endswith('</li>'):
                        html_lines.append('<ul style="margin: 0 0 20px 0; padding-left: 30px;">')
                    
                    list_text = line.strip()[2:]
                    list_text = self._process_inline_formatting(list_text)
                    html_lines.append(f'<li style="margin: 0 0 8px 0; line-height: 1.6;">{list_text}</li>')
                    continue
                elif html_lines and html_lines[-1].endswith('</li>'):
                    # Close the list if we're not continuing
                    html_lines.append('</ul>')
                
                # Handle blockquotes
                if line.strip().startswith('>'):
                    if current_paragraph:
                        html_lines.append('<p style="margin: 0 0 20px 0;">' + ' '.join(current_paragraph) + '</p>')
                        current_paragraph = []
                    
                    quote_text = line.strip()[1:].strip()
                    quote_text = self._process_inline_formatting(quote_text)
                    html_lines.append(f'<blockquote style="margin: 0 0 20px 0; padding-left: 20px; border-left: 4px solid #e0e0e0; color: #666666; font-style: italic;">{quote_text}</blockquote>')
                    continue
                
                # Handle horizontal rules
                if re.match(r'^[\-\*_]{3,}$', line.strip()):
                    if current_paragraph:
                        html_lines.append('<p style="margin: 0 0 20px 0;">' + ' '.join(current_paragraph) + '</p>')
                        current_paragraph = []
                    html_lines.append('<hr style="border: none; border-top: 1px solid #e0e0e0; margin: 30px 0;">')
                    continue
                
                # Regular paragraph line - escape HTML first
                processed_line = self._process_inline_formatting(escape(line.strip()))
                current_paragraph.append(processed_line)
            
            else:
                # Empty line - end current paragraph
                if current_paragraph:
                    html_lines.append('<p style="margin: 0 0 20px 0;">' + ' '.join(current_paragraph) + '</p>')
                    current_paragraph = []
                
                # Close any open lists
                if html_lines and html_lines[-1].endswith('</li>'):
                    html_lines.append('</ul>')
        
        # Don't forget last paragraph
        if current_paragraph:
            html_lines.append('<p style="margin: 0 0 20px 0;">' + ' '.join(current_paragraph) + '</p>')
        
        # Close any open lists at the end
        if html_lines and html_lines[-1].endswith('</li>'):
            html_lines.append('</ul>')
        
        return '\n'.join(html_lines)
    
    def _process_inline_formatting(self, text: str) -> str:
        """Process inline markdown formatting (bold, italic, links, code)"""
        # Note: text is already HTML-escaped at this point
        
        # Code spans (must be processed before other formatting)
        text = re.sub(r'`([^`]+)`', r'<code style="background: #f5f5f5; padding: 2px 4px; border-radius: 3px; font-size: 0.9em;">\1</code>', text)
        
        # Bold (must be before italic)
        text = re.sub(r'\*\*([^\*]+)\*\*', r'<strong>\1</strong>', text)
        
        # Italic
        text = re.sub(r'\*([^\*]+)\*', r'<em>\1</em>', text)
        
        # Links - with proper URL validation and escaping
        def replace_link(match):
            link_text = match.group(1)
            url = match.group(2)
            
            # Ensure URL is safe
            if url.startswith(('http://', 'https://', 'mailto:', '/')):
                # Escape quotes in URL
                safe_url = url.replace('"', '&quot;')
                return f'<a href="{safe_url}" style="color: #0066CC; text-decoration: none;">{link_text}</a>'
            else:
                # Assume relative URL, escape it
                safe_url = url.replace('"', '&quot;')
                return f'<a href="{safe_url}" style="color: #0066CC; text-decoration: none;">{link_text}</a>'
        
        text = re.sub(r'\[([^\]]+)\]\(([^\)]+)\)', replace_link, text)
        
        return text
    
    def _create_plain_text_version(self, summaries: List[str]) -> str:
        """Create plain text version"""
        plain = "RENAISSANCE WEEKLY\n"
        plain += "The smartest podcasts, distilled.\n"
        plain += f"{datetime.now().strftime('%B %d, %Y')}\n\n"
        plain += "="*60 + "\n\n"
        
        for summary in summaries:
            # Remove markdown
            text = re.sub(r'\*\*([^*]+)\*\*', r'\1', summary)
            text = re.sub(r'\*([^*]+)\*', r'\1', text)
            text = re.sub(r'\[([^\]]+)\]\(([^\)]+)\)', r'\1 (\2)', text)
            text = re.sub(r'^#+\s+', '', text, flags=re.MULTILINE)
            
            plain += text + "\n\n" + "="*60 + "\n\n"
        
        plain += "Renaissance Weekly\n"
        plain += "For those who remain curious.\n"
        plain += "https://gistcapture.ai"
        
        return plain