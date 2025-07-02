// Example implementation of new UI states for Renaissance Weekly
// This maintains the existing design aesthetic while adding new functionality

// New render functions to add to selection.py

function renderCostEstimate() {
    const episodeCount = APP_STATE.selectedEpisodes.size;
    const mode = APP_STATE.configuration.transcription_mode;
    
    // Calculate estimates
    const costPerEpisode = mode === 'test' ? 0.10 : 1.50;
    const timePerEpisode = mode === 'test' ? 0.5 : 5; // minutes
    const totalCost = episodeCount * costPerEpisode;
    const totalTime = episodeCount * timePerEpisode;
    
    return `
        <div class="header">
            <div class="logo">RW</div>
            <div class="header-text">Cost & Time Estimate</div>
        </div>
        
        <div class="container">
            ${renderStageIndicator('estimate')}
            
            <div class="estimate-card">
                <div class="estimate-header">
                    <h2>Processing Estimate</h2>
                    <div class="mode-badge ${mode}">${mode.toUpperCase()} MODE</div>
                </div>
                
                <div class="estimate-grid">
                    <div class="estimate-item">
                        <div class="estimate-label">Episodes Selected</div>
                        <div class="estimate-value">${episodeCount}</div>
                    </div>
                    
                    <div class="estimate-item">
                        <div class="estimate-label">Estimated Cost</div>
                        <div class="estimate-value">$${totalCost.toFixed(2)}</div>
                    </div>
                    
                    <div class="estimate-item">
                        <div class="estimate-label">Estimated Time</div>
                        <div class="estimate-value">${formatDuration(totalTime)}</div>
                    </div>
                    
                    <div class="estimate-item">
                        <div class="estimate-label">Cost per Episode</div>
                        <div class="estimate-value">~$${costPerEpisode.toFixed(2)}</div>
                    </div>
                </div>
                
                <div class="estimate-breakdown">
                    <h3>Cost Breakdown</h3>
                    <div class="breakdown-item">
                        <span>Audio Transcription (Whisper API)</span>
                        <span>$${(episodeCount * 0.006 * (mode === 'test' ? 15 : 60)).toFixed(2)}</span>
                    </div>
                    <div class="breakdown-item">
                        <span>Summarization (GPT-4)</span>
                        <span>$${(episodeCount * 0.03).toFixed(2)}</span>
                    </div>
                    <div class="breakdown-item">
                        <span>Other API Calls</span>
                        <span>$${(episodeCount * 0.01).toFixed(2)}</span>
                    </div>
                </div>
                
                <div class="action-section">
                    <button class="button secondary" onclick="goBack()">
                        ← Back to Episodes
                    </button>
                    <button class="button primary" onclick="startProcessing()">
                        Start Processing →
                    </button>
                </div>
            </div>
        </div>
    `;
}

function renderProgress() {
    const { total, completed, failed, current, startTime, errors } = APP_STATE.processingStatus;
    const progress = total > 0 ? (completed + failed) / total * 100 : 0;
    const elapsed = startTime ? (Date.now() - startTime) / 1000 : 0;
    const rate = completed > 0 ? elapsed / completed : 0;
    const remaining = (total - completed - failed) * rate;
    
    return `
        <div class="header">
            <div class="logo">RW</div>
            <div class="header-text">Processing Episodes</div>
        </div>
        
        <div class="container">
            ${renderStageIndicator('processing')}
            
            <div class="progress-card">
                <div class="progress-header">
                    <h2>Processing Progress</h2>
                    <button class="button danger small" onclick="cancelProcessing()">
                        Cancel Processing
                    </button>
                </div>
                
                <div class="progress-bar-container">
                    <div class="progress-bar" style="width: ${progress}%"></div>
                    <div class="progress-text">${completed + failed}/${total} episodes</div>
                </div>
                
                <div class="stats-grid">
                    <div class="stat-item success">
                        <div class="stat-value">${completed}</div>
                        <div class="stat-label">Successful</div>
                    </div>
                    
                    <div class="stat-item danger">
                        <div class="stat-value">${failed}</div>
                        <div class="stat-label">Failed</div>
                    </div>
                    
                    <div class="stat-item">
                        <div class="stat-value">${formatDuration(elapsed / 60)}</div>
                        <div class="stat-label">Elapsed</div>
                    </div>
                    
                    <div class="stat-item">
                        <div class="stat-value">${formatDuration(remaining / 60)}</div>
                        <div class="stat-label">Remaining</div>
                    </div>
                </div>
                
                ${current ? `
                    <div class="current-episode">
                        <div class="current-label">Currently Processing:</div>
                        <div class="current-title">${current.podcast}: ${current.title}</div>
                        <div class="current-status">${current.status}</div>
                    </div>
                ` : ''}
                
                ${errors.length > 0 ? `
                    <div class="error-section">
                        <h3>Failed Episodes</h3>
                        <div class="error-list">
                            ${errors.map(err => `
                                <div class="error-item">
                                    <div class="error-title">${err.episode}</div>
                                    <div class="error-message">${err.message}</div>
                                </div>
                            `).join('')}
                        </div>
                    </div>
                ` : ''}
            </div>
        </div>
    `;
}

function renderResults() {
    const { total, completed, failed, errors } = APP_STATE.processingStatus;
    const successRate = total > 0 ? (completed / total * 100).toFixed(1) : 0;
    
    return `
        <div class="header">
            <div class="logo">RW</div>
            <div class="header-text">Processing Results</div>
        </div>
        
        <div class="container">
            ${renderStageIndicator('results')}
            
            <div class="results-card">
                <div class="results-header">
                    <h2>Processing Complete</h2>
                    <div class="success-rate ${successRate >= 90 ? 'good' : successRate >= 70 ? 'warning' : 'poor'}">
                        ${successRate}% Success Rate
                    </div>
                </div>
                
                <div class="results-summary">
                    <div class="result-stat success">
                        <div class="result-icon">✓</div>
                        <div class="result-count">${completed}</div>
                        <div class="result-label">Successful Episodes</div>
                    </div>
                    
                    <div class="result-stat danger">
                        <div class="result-icon">✗</div>
                        <div class="result-count">${failed}</div>
                        <div class="result-label">Failed Episodes</div>
                    </div>
                </div>
                
                ${failed > 0 ? `
                    <div class="failed-episodes">
                        <h3>Failed Episodes</h3>
                        ${errors.map(err => `
                            <div class="failed-item">
                                <div class="failed-title">${err.episode}</div>
                                <div class="failed-reason">${err.message}</div>
                                <button class="button small" onclick="retryEpisode('${err.id}')">
                                    Retry
                                </button>
                            </div>
                        `).join('')}
                    </div>
                ` : ''}
                
                <div class="action-section">
                    ${failed > 0 ? `
                        <button class="button secondary" onclick="retryAllFailed()">
                            Retry All Failed
                        </button>
                    ` : ''}
                    
                    <button class="button primary" onclick="proceedToEmail()">
                        Continue to Email →
                    </button>
                    
                    <button class="button text" onclick="cancelAndExit()">
                        Cancel & Exit
                    </button>
                </div>
            </div>
        </div>
    `;
}

function renderEmailApproval() {
    const { emailPreview } = APP_STATE;
    const { completed, failed } = APP_STATE.processingStatus;
    
    return `
        <div class="header">
            <div class="logo">RW</div>
            <div class="header-text">Email Approval</div>
        </div>
        
        <div class="container">
            ${renderStageIndicator('email')}
            
            <div class="email-card">
                <div class="email-header">
                    <h2>Review & Send Email</h2>
                </div>
                
                <div class="email-stats">
                    <div class="email-stat">
                        <span class="stat-label">Episodes in digest:</span>
                        <span class="stat-value">${completed}</span>
                    </div>
                    ${failed > 0 ? `
                        <div class="email-stat warning">
                            <span class="stat-label">Episodes excluded:</span>
                            <span class="stat-value">${failed}</span>
                        </div>
                    ` : ''}
                </div>
                
                <div class="email-preview">
                    <h3>Email Preview</h3>
                    <div class="preview-content">
                        ${emailPreview ? emailPreview : 'Loading preview...'}
                    </div>
                </div>
                
                <div class="email-recipients">
                    <h3>Recipients</h3>
                    <div class="recipient-list">
                        ${APP_STATE.recipients ? APP_STATE.recipients.map(r => `
                            <div class="recipient">${r}</div>
                        `).join('') : 'Configured recipients will receive this email'}
                    </div>
                </div>
                
                <div class="action-section">
                    <button class="button secondary" onclick="goBackToResults()">
                        ← Back to Results
                    </button>
                    
                    <button class="button primary large" onclick="sendEmail()">
                        Send Email
                    </button>
                </div>
            </div>
        </div>
    `;
}

// Helper function for stage indicator
function renderStageIndicator(currentStage) {
    const stages = [
        { id: 'podcasts', label: 'Podcasts' },
        { id: 'episodes', label: 'Episodes' },
        { id: 'estimate', label: 'Estimate' },
        { id: 'processing', label: 'Process' },
        { id: 'results', label: 'Results' },
        { id: 'email', label: 'Email' }
    ];
    
    const currentIndex = stages.findIndex(s => s.id === currentStage);
    
    return `
        <div class="stage-indicator">
            ${stages.map((stage, index) => `
                <div class="stage-wrapper">
                    <div class="stage-dot ${index <= currentIndex ? 'active' : ''} ${index === currentIndex ? 'current' : ''}"></div>
                    <div class="stage-label ${index <= currentIndex ? 'active' : ''}">${stage.label}</div>
                </div>
                ${index < stages.length - 1 ? '<div class="stage-connector"></div>' : ''}
            `).join('')}
        </div>
    `;
}

// Utility functions
function formatDuration(minutes) {
    if (minutes < 60) {
        return `${Math.round(minutes)} min`;
    }
    const hours = Math.floor(minutes / 60);
    const mins = Math.round(minutes % 60);
    return `${hours}h ${mins}m`;
}

// API interaction functions
async function startProcessing() {
    APP_STATE.state = 'processing';
    APP_STATE.processingStatus.startTime = Date.now();
    render();
    
    // Start polling for status updates
    APP_STATE.statusInterval = setInterval(updateProcessingStatus, 2000);
    
    // Send start request
    await fetch('/api/start-processing', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            episodes: Array.from(APP_STATE.selectedEpisodes)
        })
    });
}

async function updateProcessingStatus() {
    try {
        const response = await fetch('/api/processing-status');
        const status = await response.json();
        
        APP_STATE.processingStatus = {
            ...APP_STATE.processingStatus,
            ...status
        };
        
        // Check if processing is complete
        if (status.completed + status.failed >= status.total) {
            clearInterval(APP_STATE.statusInterval);
            APP_STATE.state = 'results';
        }
        
        render();
    } catch (error) {
        console.error('Failed to update status:', error);
    }
}

async function cancelProcessing() {
    if (confirm('Are you sure you want to cancel processing? This will stop all remaining episodes.')) {
        clearInterval(APP_STATE.statusInterval);
        
        await fetch('/api/cancel-processing', {
            method: 'POST'
        });
        
        APP_STATE.state = 'results';
        render();
    }
}