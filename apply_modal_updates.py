#!/usr/bin/env python3
"""
Apply modal updates to Renaissance Weekly UI
This script updates the selection.py file to use custom styled modals
instead of native browser alerts/confirms/prompts.
"""

import re
import sys
from pathlib import Path

def apply_modal_updates():
    """Apply modal system updates to selection.py"""
    
    selection_file = Path("renaissance_weekly/ui/selection.py")
    if not selection_file.exists():
        print("Error: selection.py not found!")
        return False
    
    # Read the file
    with open(selection_file, 'r') as f:
        content = f.read()
    
    # Backup original
    backup_file = selection_file.with_suffix('.py.backup')
    with open(backup_file, 'w') as f:
        f.write(content)
    print(f"✓ Created backup: {backup_file}")
    
    # 1. Add modal CSS (insert before the closing """ of _get_css)
    modal_css = """
        /* Modal System */
        .modal-overlay {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0, 0, 0, 0.3);
            backdrop-filter: blur(4px);
            -webkit-backdrop-filter: blur(4px);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 9999;
            animation: modalFadeIn 0.2s ease-out;
        }
        
        .modal-container {
            background: var(--white);
            border-radius: 16px;
            padding: 32px;
            max-width: 480px;
            width: 90%;
            max-height: 80vh;
            box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04);
            animation: modalSlideIn 0.3s ease-out;
            position: relative;
        }
        
        .modal-title {
            font-size: 20px;
            font-weight: 600;
            margin-bottom: 16px;
            color: var(--black);
            letter-spacing: -0.02em;
            line-height: 1.2;
        }
        
        .modal-content {
            font-size: 16px;
            line-height: 1.6;
            color: var(--gray-700);
            margin-bottom: 24px;
            white-space: pre-wrap;
        }
        
        .modal-input {
            width: 100%;
            padding: 12px 16px;
            border: 1px solid var(--gray-200);
            border-radius: 8px;
            font-size: 16px;
            font-family: inherit;
            margin-top: 12px;
            transition: border-color 0.2s;
            background: var(--white);
        }
        
        .modal-input:focus {
            outline: none;
            border-color: var(--black);
        }
        
        .modal-buttons {
            display: flex;
            gap: 12px;
            justify-content: flex-end;
        }
        
        .modal-buttons .button {
            padding: 10px 20px;
            border-radius: 8px;
            font-size: 15px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s;
            border: none;
            font-family: inherit;
        }
        
        .modal-buttons .button-primary {
            background: var(--black);
            color: var(--white);
        }
        
        .modal-buttons .button-primary:hover {
            background: var(--gray-700);
        }
        
        .modal-buttons .button-secondary {
            background: var(--gray-100);
            color: var(--gray-700);
        }
        
        .modal-buttons .button-secondary:hover {
            background: var(--gray-200);
        }
        
        @keyframes modalFadeIn {
            from { opacity: 0; }
            to { opacity: 1; }
        }
        
        @keyframes modalSlideIn {
            from {
                transform: translateY(-20px) scale(0.95);
                opacity: 0;
            }
            to {
                transform: translateY(0) scale(1);
                opacity: 1;
            }
        }
        
        @media (max-width: 640px) {
            .modal-container {
                padding: 24px;
                width: 95%;
            }
            
            .modal-title {
                font-size: 18px;
            }
            
            .modal-content {
                font-size: 15px;
            }
            
            .modal-buttons {
                flex-direction: column-reverse;
            }
            
            .modal-buttons .button {
                width: 100%;
            }
        }"""
    
    # Find the end of _get_css method and insert modal CSS
    css_pattern = r'(def _get_css\(self\).*?)(        """)'
    css_replacement = lambda m: m.group(1) + modal_css + '\n' + m.group(2)
    content = re.sub(css_pattern, css_replacement, content, flags=re.DOTALL)
    print("✓ Added modal CSS styles")
    
    # 2. Add ModalSystem JavaScript
    modal_js = """
        // Modal System
        const ModalSystem = {
            createModal: function(options = {}) {
                const modalId = 'modal-' + Date.now();
                const modal = document.createElement('div');
                modal.id = modalId;
                modal.className = 'modal-overlay';
                
                const content = `
                    <div class="modal-container">
                        ${options.title ? `<h3 class="modal-title">${options.title}</h3>` : ''}
                        <div class="modal-content">
                            ${options.message || ''}
                            ${options.input ? `<input type="text" class="modal-input" placeholder="${options.placeholder || ''}" value="${options.defaultValue || ''}">` : ''}
                        </div>
                        <div class="modal-buttons">
                            ${options.cancelButton ? `<button class="button button-secondary modal-cancel">${options.cancelText || 'Cancel'}</button>` : ''}
                            <button class="button button-primary modal-confirm">${options.confirmText || 'OK'}</button>
                        </div>
                    </div>
                `;
                
                modal.innerHTML = content;
                document.body.appendChild(modal);
                
                const input = modal.querySelector('.modal-input');
                if (input) {
                    setTimeout(() => input.focus(), 50);
                }
                
                return { modal, modalId };
            },
            
            alert: async function(message, title = '') {
                return new Promise((resolve) => {
                    const { modal, modalId } = this.createModal({
                        title: title,
                        message: message,
                        confirmText: 'OK',
                        cancelButton: false
                    });
                    
                    const confirmBtn = modal.querySelector('.modal-confirm');
                    confirmBtn.addEventListener('click', () => {
                        document.getElementById(modalId).remove();
                        resolve();
                    });
                    
                    const escHandler = (e) => {
                        if (e.key === 'Escape') {
                            document.getElementById(modalId).remove();
                            document.removeEventListener('keydown', escHandler);
                            resolve();
                        }
                    };
                    document.addEventListener('keydown', escHandler);
                });
            },
            
            confirm: async function(message, title = '') {
                return new Promise((resolve) => {
                    const { modal, modalId } = this.createModal({
                        title: title,
                        message: message,
                        confirmText: 'Confirm',
                        cancelText: 'Cancel',
                        cancelButton: true
                    });
                    
                    const confirmBtn = modal.querySelector('.modal-confirm');
                    const cancelBtn = modal.querySelector('.modal-cancel');
                    
                    confirmBtn.addEventListener('click', () => {
                        document.getElementById(modalId).remove();
                        resolve(true);
                    });
                    
                    cancelBtn.addEventListener('click', () => {
                        document.getElementById(modalId).remove();
                        resolve(false);
                    });
                    
                    const escHandler = (e) => {
                        if (e.key === 'Escape') {
                            document.getElementById(modalId).remove();
                            document.removeEventListener('keydown', escHandler);
                            resolve(false);
                        }
                    };
                    document.addEventListener('keydown', escHandler);
                });
            },
            
            prompt: async function(message, defaultValue = '', title = '') {
                return new Promise((resolve) => {
                    const { modal, modalId } = this.createModal({
                        title: title,
                        message: message,
                        input: true,
                        defaultValue: defaultValue,
                        confirmText: 'OK',
                        cancelText: 'Cancel',
                        cancelButton: true
                    });
                    
                    const confirmBtn = modal.querySelector('.modal-confirm');
                    const cancelBtn = modal.querySelector('.modal-cancel');
                    const input = modal.querySelector('.modal-input');
                    
                    const submit = () => {
                        const value = input.value;
                        document.getElementById(modalId).remove();
                        resolve(value);
                    };
                    
                    confirmBtn.addEventListener('click', submit);
                    
                    cancelBtn.addEventListener('click', () => {
                        document.getElementById(modalId).remove();
                        resolve(null);
                    });
                    
                    input.addEventListener('keypress', (e) => {
                        if (e.key === 'Enter') {
                            submit();
                        }
                    });
                    
                    const escHandler = (e) => {
                        if (e.key === 'Escape') {
                            document.getElementById(modalId).remove();
                            document.removeEventListener('keydown', escHandler);
                            resolve(null);
                        }
                    };
                    document.addEventListener('keydown', escHandler);
                });
            }
        };
        
"""
    
    # Insert ModalSystem after <script> tag
    script_pattern = r'(<script>)'
    script_replacement = r'\1' + modal_js
    content = re.sub(script_pattern, script_replacement, content)
    print("✓ Added ModalSystem JavaScript")
    
    # 3. Replace alert() calls with ModalSystem.alert()
    # Map of alert messages to appropriate titles
    alert_replacements = [
        (r"alert\('Failed to submit episodes'\);", 
         "await ModalSystem.alert('Failed to submit episodes', 'Error');"),
        (r"alert\('Failed to start downloads\. Please try again\.'\);", 
         "await ModalSystem.alert('Failed to start downloads. Please try again.', 'Download Error');"),
        (r"alert\('No failed downloads to retry'\);", 
         "await ModalSystem.alert('No failed downloads to retry', 'Info');"),
        (r"alert\('Failed to start retry'\);", 
         "await ModalSystem.alert('Failed to start retry', 'Error');"),
        (r"alert\('No failed episodes to retry'\);", 
         "await ModalSystem.alert('No failed episodes to retry', 'Info');"),
        (r"alert\('Failed to start retry\. Please try again\.'\);", 
         "await ModalSystem.alert('Failed to start retry. Please try again.', 'Error');"),
        (r"alert\('You need at least 1 successfully downloaded episode to continue\.'\);", 
         "await ModalSystem.alert('You need at least 1 successfully downloaded episode to continue.', 'Minimum Episodes Required');"),
        (r"alert\('Browser download started \(this may take longer\)\.\.\.'\);", 
         "await ModalSystem.alert('Browser download started (this may take longer)...', 'Download Started');"),
        (r"alert\('Failed to start browser download'\);", 
         "await ModalSystem.alert('Failed to start browser download', 'Error');"),
        (r"alert\(`Download logs for \$\{episode\.title\}:\\n\\n\$\{logs\}`\);", 
         "await ModalSystem.alert(`Download logs for ${episode.title}:\\n\\n${logs}`, 'Download Logs');"),
        (r"alert\(`Manual download started for: \$\{episodeTitle\.substring\(0, 50\)\}\.\.\.\\n\\nThis may take a few moments\. The page will update automatically when complete\.\`\);", 
         "await ModalSystem.alert(`Manual download started for: ${episodeTitle.substring(0, 50)}...\\n\\nThis may take a few moments. The page will update automatically when complete.`, 'Manual Download');"),
        (r"alert\(`Debug info:\\n\\n\$\{JSON\.stringify\(result, null, 2\)\}\`\);", 
         "await ModalSystem.alert(`Debug info:\\n\\n${JSON.stringify(result, null, 2)}`, 'Debug Information');"),
        (r"alert\('Failed to start manual download: ' \+ \(result\.message \|\| 'Unknown error'\)\);", 
         "await ModalSystem.alert('Failed to start manual download: ' + (result.message || 'Unknown error'), 'Error');"),
        (r"alert\('Failed to send email: ' \+ \(result\.message \|\| 'Unknown error'\)\);", 
         "await ModalSystem.alert('Failed to send email: ' + (result.message || 'Unknown error'), 'Email Error');"),
        (r"alert\('Error sending email: ' \+ error\.message\);", 
         "await ModalSystem.alert('Error sending email: ' + error.message, 'Email Error');"),
        (r"alert\('Error: ' \+ error\.message\);", 
         "await ModalSystem.alert('Error: ' + error.message, 'Error');"),
        (r"alert\('Error submitting episodes: ' \+ error\.message\);", 
         "await ModalSystem.alert('Error submitting episodes: ' + error.message, 'Submission Error');"),
    ]
    
    for pattern, replacement in alert_replacements:
        content = re.sub(pattern, replacement, content)
    print("✓ Replaced alert() calls")
    
    # 4. Replace confirm() calls
    confirm_replacements = [
        (r"if \(confirm\('Are you sure you want to cancel processing\? This will stop all remaining episodes\.'\)\)", 
         "if (await ModalSystem.confirm('Are you sure you want to cancel processing? This will stop all remaining episodes.', 'Cancel Processing'))"),
        (r"if \(!confirm\(`Retry all \$\{failedCount\} failed downloads\?`\)\)", 
         "if (!await ModalSystem.confirm(`Retry all ${failedCount} failed downloads?`, 'Retry Downloads'))"),
        (r"if \(!confirm\(`\$\{downloaded\} episodes downloaded successfully, \$\{failed\} failed\. Continue anyway\?`\)\)", 
         "if (!await ModalSystem.confirm(`${downloaded} episodes downloaded successfully, ${failed} failed. Continue anyway?`, 'Continue with Failed Downloads'))"),
        (r"if \(confirm\('Are you sure you want to cancel downloads\? This will stop all remaining downloads\.'\)\)", 
         "if (await ModalSystem.confirm('Are you sure you want to cancel downloads? This will stop all remaining downloads.', 'Cancel Downloads'))"),
        (r"if \(confirm\('Send the email digest\?'\)\)", 
         "if (await ModalSystem.confirm('Send the email digest?', 'Send Email'))"),
        (r"if \(confirm\('Cancel and exit\? No email will be sent\.'\)\)", 
         "if (await ModalSystem.confirm('Cancel and exit? No email will be sent.', 'Cancel and Exit'))"),
    ]
    
    for pattern, replacement in confirm_replacements:
        content = re.sub(pattern, replacement, content)
    print("✓ Replaced confirm() calls")
    
    # 5. Replace prompt() calls
    prompt_pattern = r"const url = prompt\('Enter direct URL to audio file \(MP3, WAV, etc\.\):\\n\\nFor YouTube URLs, the system will automatically download and convert to MP3\.'\);"
    prompt_replacement = "const url = await ModalSystem.prompt('Enter direct URL to audio file (MP3, WAV, etc.)\\n\\nFor YouTube URLs, the system will automatically download and convert to MP3.\\n\\nYou can also enter a local file path (e.g., /path/to/file.mp3)', '', 'Manual Download URL');"
    content = re.sub(prompt_pattern, prompt_replacement, content)
    print("✓ Replaced prompt() calls")
    
    # 6. Make functions that use modals async
    functions_to_async = [
        'submitEpisodes',
        'cancelProcessing',
        'retryAllFailed',
        'continueWithDownloads',
        'cancelDownloads',
        'sendEmail',
        'manualDownload',
        'browserDownload',
        'showDebugInfo',
        'retryFailedEpisodes'
    ]
    
    for func in functions_to_async:
        # Pattern to match function declaration
        pattern = rf'(function {func}\([^)]*\) {{)'
        replacement = rf'async \1'
        content = re.sub(pattern, replacement, content)
    print("✓ Made modal-using functions async")
    
    # Write the updated content
    with open(selection_file, 'w') as f:
        f.write(content)
    
    print("\n✅ Modal system integration complete!")
    print(f"   Original backed up to: {backup_file}")
    print("   The UI now uses custom styled modals instead of browser dialogs.")
    
    return True

if __name__ == "__main__":
    success = apply_modal_updates()
    sys.exit(0 if success else 1)