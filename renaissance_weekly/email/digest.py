"""Email digest generation and sending"""

import re
from datetime import datetime
from typing import List, Dict
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
    
    def send_digest(self, summaries: List[Dict]) -> bool:
        """Send Renaissance Weekly digest"""
        try:
            logger.info("📧 Preparing Renaissance Weekly digest...")
            
            # Extract episodes from summaries
            episodes = [s["episode"] for s in summaries]
            summary_texts = [s["summary"] for s in summaries]
            
            # Create email content
            html_content = self.create_substack_style_email(summary_texts, episodes)
            plain_content = self._create_plain_text_version(summary_texts)
            
            # Create subject with correct count
            subject = f"Renaissance Weekly: {len(summaries)} Essential Conversation{'s' if len(summaries) != 1 else ''}"
            
            # Create message
            message = Mail(
                from_email=(EMAIL_FROM, "Renaissance Weekly"),
                to_emails=EMAIL_TO,
                subject=subject,
                plain_text_content=plain_content,
                html_content=html_content
            )
            
            # Send email
            response = sendgrid_client.send(message)
            
            if response.status_code == 202:
                logger.info("✅ Email sent successfully!")
                return True
            else:
                logger.error(f"Email failed: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Email error: {e}")
            return False
    
    def create_substack_style_email(self, summaries: List[str], episodes: List[Episode]) -> str:
        """Create clean HTML email with table of contents and better structure"""
        
        # Create table of contents
        toc_html = ""
        for i, episode in enumerate(episodes[:len(summaries)]):
            toc_html += f'''
                <tr>
                    <td style="padding: 8px 0;">
                        <a href="#episode-{i}" style="color: #0066CC; text-decoration: none; font-size: 16px;">
                            <strong>{episode.podcast}</strong>: {episode.title}
                        </a>
                        <div style="font-size: 14px; color: #666; margin-top: 4px;">
                            Release Date: {episode.published.strftime('%B %d, %Y')} • {format_duration(episode.duration)}
                        </div>
                    </td>
                </tr>'''
        
        # Create episodes HTML with better separation
        episodes_html = ""
        for i, (summary, episode) in enumerate(zip(summaries, episodes[:len(summaries)])):
            # Add anchor for navigation
            episodes_html += f'<tr id="episode-{i}"><td style="padding: 0;">'
            
            if i > 0:
                # Visual separator between episodes
                episodes_html += '''
                    <div style="padding: 60px 0;">
                        <hr style="border: none; border-top: 2px solid #E0E0E0; margin: 0;">
                    </div>'''
            
            # Add title header for this podcast episode
            episodes_html += f'''
                <div style="background: #f0f8ff; padding: 20px; border-radius: 8px; margin-bottom: 30px;">
                    <h2 style="margin: 0 0 10px 0; font-size: 28px; color: #2c3e50; font-family: Georgia, serif; font-weight: normal;">
                        {episode.podcast}
                    </h2>
                    <h3 style="margin: 0 0 15px 0; font-size: 20px; color: #34495e; font-family: Georgia, serif; font-weight: normal;">
                        {episode.title}
                    </h3>
                    <p style="margin: 0; font-size: 14px; color: #666;">
                        Release Date: {episode.published.strftime('%B %d, %Y')} • Duration: {format_duration(episode.duration)}
                    </p>
                </div>'''
            
            # Convert markdown to HTML
            html_content = self._convert_markdown_to_html(summary)
            
            # Wrap content in a container
            episodes_html += f'''
                <div style="background: #ffffff; padding: 0 0 40px 0;">
                    {html_content}
                    <div style="margin-top: 40px; text-align: right;">
                        <a href="#toc" style="color: #666; text-decoration: none; font-size: 14px;">↑ Back to top</a>
                    </div>
                </div>
            </td></tr>'''
        
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="X-UA-Compatible" content="IE=edge">
    <title>Renaissance Weekly</title>
    <!--[if mso]>
    <style type="text/css">
        table {{border-collapse: collapse;}}
        .outlook-font {{font-family: Arial, sans-serif !important;}}
    </style>
    <![endif]-->
</head>
<body style="margin: 0; padding: 0; font-family: Georgia, serif; font-size: 18px; line-height: 1.6; color: #333; background-color: #FFF; -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%;">
    <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="background-color: #FFF;">
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
                            <h1 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 48px; font-weight: normal; letter-spacing: -1px; color: #000; mso-line-height-rule: exactly; line-height: 1.1;">Renaissance Weekly</h1>
                            <p style="margin: 0 0 20px 0; font-size: 18px; color: #666; font-style: italic; font-family: Georgia, serif;">The smartest podcasts, distilled.</p>
                            <p style="margin: 0; font-size: 14px; color: #999; text-transform: uppercase; letter-spacing: 1px; font-family: Arial, sans-serif;">{datetime.now().strftime('%B %d, %Y')}</p>
                        </td>
                    </tr>
                    
                    <!-- Introduction -->
                    <tr>
                        <td style="padding: 0 0 50px 0;">
                            <p style="margin: 0; font-size: 20px; line-height: 1.7; color: #333; font-weight: 300; font-family: Georgia, serif;">In a world of infinite content, attention is the scarcest resource. This week's edition brings you the essential insights from conversations that matter.</p>
                        </td>
                    </tr>
                    
                    <!-- Table of Contents -->
                    <tr id="toc">
                        <td style="padding: 0 0 50px 0;">
                            <div style="background: #f8f8f8; padding: 30px; border-radius: 8px;">
                                <h2 style="margin: 0 0 20px 0; font-size: 24px; color: #000; font-family: Georgia, serif; font-weight: normal;">This Week's Essential Conversations</h2>
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
                            <p style="margin: 0 0 15px 0; font-size: 24px; font-family: Georgia, serif; color: #000;">Renaissance Weekly</p>
                            <p style="margin: 0 0 20px 0; font-size: 16px; color: #666; font-style: italic; font-family: Georgia, serif;">"For those who remain curious."</p>
                            <p style="margin: 0; font-size: 14px; color: #999;">
                                <a href="https://gistcapture.ai" style="color: #666; text-decoration: none;">gistcapture.ai</a>
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
        """Convert markdown to HTML with proper handling"""
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
                        html_lines.append(f'<h1 style="margin: 40px 0 30px 0; font-size: 32px; color: #000; font-family: Georgia, serif; font-weight: normal;">{text}</h1>')
                    elif level == 2:
                        html_lines.append(f'<h2 style="margin: 35px 0 20px 0; font-size: 26px; color: #000; font-family: Georgia, serif; font-weight: normal;">{text}</h2>')
                    elif level == 3:
                        html_lines.append(f'<h3 style="margin: 30px 0 15px 0; font-size: 22px; color: #333; font-weight: 600;">{text}</h3>')
                    else:
                        html_lines.append(f'<h{level} style="margin: 25px 0 15px 0; font-size: 18px; color: #333; font-weight: 600;">{text}</h{level}>')
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
                    html_lines.append(f'<blockquote style="margin: 0 0 20px 0; padding-left: 20px; border-left: 4px solid #e0e0e0; color: #666; font-style: italic;">{quote_text}</blockquote>')
                    continue
                
                # Handle horizontal rules
                if re.match(r'^[\-\*_]{3,}$', line.strip()):
                    if current_paragraph:
                        html_lines.append('<p style="margin: 0 0 20px 0;">' + ' '.join(current_paragraph) + '</p>')
                        current_paragraph = []
                    html_lines.append('<hr style="border: none; border-top: 1px solid #e0e0e0; margin: 30px 0;">')
                    continue
                
                # Regular paragraph line
                processed_line = self._process_inline_formatting(line.strip())
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
        # Escape HTML first
        text = escape(text)
        
        # Code spans (must be processed before other formatting)
        text = re.sub(r'`([^`]+)`', r'<code style="background: #f5f5f5; padding: 2px 4px; border-radius: 3px; font-size: 0.9em;">\1</code>', text)
        
        # Bold (must be before italic)
        text = re.sub(r'\*\*([^\*]+)\*\*', r'<strong>\1</strong>', text)
        
        # Italic
        text = re.sub(r'\*([^\*]+)\*', r'<em>\1</em>', text)
        
        # Links - with proper URL validation
        def replace_link(match):
            link_text = match.group(1)
            url = match.group(2)
            # Basic URL validation
            if url.startswith(('http://', 'https://', 'mailto:', '/')):
                return f'<a href="{url}" style="color: #0066CC; text-decoration: none;">{link_text}</a>'
            else:
                # Assume relative URL
                return f'<a href="{url}" style="color: #0066CC; text-decoration: none;">{link_text}</a>'
        
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