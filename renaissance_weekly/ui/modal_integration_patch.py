"""
Modal Integration Patch for Renaissance Weekly UI

This file contains the patches needed to integrate custom modals into the UI.
Apply these changes to selection.py to replace native browser dialogs.
"""

# 1. Add modal CSS to the _get_css() method (add before the closing """ of the CSS):
MODAL_CSS = """
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
        }
"""

# 2. Add the ModalSystem JavaScript object (add after <script> tag, before any other functions):
MODAL_SYSTEM_JS = """
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

# 3. Example replacements for alert() calls:
"""
# Find and replace all alert() calls:
alert('Failed to submit episodes');
# Replace with:
await ModalSystem.alert('Failed to submit episodes', 'Error');

# Find and replace all confirm() calls:
if (confirm('Are you sure you want to cancel?')) {
# Replace with:
if (await ModalSystem.confirm('Are you sure you want to cancel?', 'Cancel Processing')) {

# Find and replace all prompt() calls:
const url = prompt('Enter direct URL to audio file');
# Replace with:
const url = await ModalSystem.prompt('Enter direct URL to audio file', '', 'Manual Download');
"""

# 4. Key replacements to make functions async:
"""
# Change these function declarations from:
function submitEpisodes() {
# To:
async function submitEpisodes() {

# Change these function declarations from:
function cancelProcessing() {
# To:
async function cancelProcessing() {

# And so on for any function that uses the modal system
"""