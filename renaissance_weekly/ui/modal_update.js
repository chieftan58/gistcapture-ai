// Modal system for Renaissance Weekly UI
// This replaces native alert(), confirm(), and prompt() with styled modals

const ModalSystem = {
    // Create modal HTML structure
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
        
        // Focus input if present
        const input = modal.querySelector('.modal-input');
        if (input) {
            setTimeout(() => input.focus(), 50);
        }
        
        return { modal, modalId };
    },
    
    // Show alert modal
    alert: function(message, title = '') {
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
            
            // Close on Escape key
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
    
    // Show confirm modal
    confirm: function(message, title = '') {
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
            
            // Close on Escape key
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
    
    // Show prompt modal
    prompt: function(message, defaultValue = '', title = '') {
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
            
            // Submit on Enter
            input.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    submit();
                }
            });
            
            // Close on Escape key
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

// CSS for the modal system
const modalStyles = `
    /* Modal overlay */
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
    
    /* Modal container */
    .modal-container {
        background: white;
        border-radius: 12px;
        padding: 32px;
        max-width: 480px;
        width: 90%;
        max-height: 80vh;
        box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04);
        animation: modalSlideIn 0.3s ease-out;
        position: relative;
    }
    
    /* Modal title */
    .modal-title {
        font-size: 20px;
        font-weight: 600;
        margin-bottom: 16px;
        color: #000;
        letter-spacing: -0.02em;
    }
    
    /* Modal content */
    .modal-content {
        font-size: 16px;
        line-height: 1.6;
        color: #333;
        margin-bottom: 24px;
        white-space: pre-wrap;
    }
    
    /* Modal input */
    .modal-input {
        width: 100%;
        padding: 12px 16px;
        border: 1px solid #e0e0e0;
        border-radius: 8px;
        font-size: 16px;
        font-family: inherit;
        margin-top: 12px;
        transition: border-color 0.2s;
    }
    
    .modal-input:focus {
        outline: none;
        border-color: #666;
    }
    
    /* Modal buttons */
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
        background: #000;
        color: white;
    }
    
    .modal-buttons .button-primary:hover {
        background: #333;
    }
    
    .modal-buttons .button-secondary {
        background: #f5f5f5;
        color: #333;
    }
    
    .modal-buttons .button-secondary:hover {
        background: #e8e8e8;
    }
    
    /* Animations */
    @keyframes modalFadeIn {
        from {
            opacity: 0;
        }
        to {
            opacity: 1;
        }
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
    
    /* Mobile responsive */
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
`;

// Example replacements for the code:
/*
// Replace alert() calls:
// OLD: alert('Failed to submit episodes');
// NEW: ModalSystem.alert('Failed to submit episodes');

// Replace confirm() calls:
// OLD: if (confirm('Are you sure?')) { ... }
// NEW: if (await ModalSystem.confirm('Are you sure?')) { ... }

// Replace prompt() calls:
// OLD: const value = prompt('Enter value:');
// NEW: const value = await ModalSystem.prompt('Enter value:');
*/