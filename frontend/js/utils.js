/**
 * Asiatech Sentiment Analysis - Utility Functions
 * Paper theme design utilities
 */

// Toast notification system — updated for new design
function showToast(message, type = 'info', duration = 4000) {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    
    const icons = {
        success: '✓',
        error: '✕',
        warning: '⚠',
        info: 'ℹ'
    };
    
    toast.innerHTML = `<span>${icons[type] || icons.info}</span><span>${message}</span>`;
    container.appendChild(toast);
    
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(100%)';
        toast.style.transition = 'all 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, duration);
}

// Loading overlay — updated for new design (.show class)
function showLoading(text = 'Loading...') {
    const overlay = document.getElementById('loading-overlay');
    document.getElementById('loading-text').textContent = text;
    overlay.classList.add('show');
}

function hideLoading() {
    document.getElementById('loading-overlay').classList.remove('show');
}

// Format date
function formatDate(dateStr) {
    if (!dateStr) return 'N/A';
    const d = new Date(dateStr);
    return d.toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

// Format number
function formatNumber(num) {
    if (num === null || num === undefined) return 'N/A';
    if (typeof num === 'number') {
        if (num >= 0 && num <= 1) return (num * 100).toFixed(1) + '%';
        return num.toFixed(2);
    }
    return num;
}

// Get sentiment badge HTML
function sentimentBadge(label) {
    if (!label) return '<span class="badge badge-neutral">N/A</span>';
    const cls = label.toLowerCase();
    return `<span class="badge badge-${cls}">${label}</span>`;
}

// Get role badge HTML
function roleBadge(role) {
    const cls = role ? role.toLowerCase() : 'student';
    return `<span class="badge badge-${cls}">${role || 'Student'}</span>`;
}

// Get category badge HTML
function categoryBadge(category) {
    if (!category) return '<span class="badge badge-neutral">N/A</span>';
    const cls = category.toLowerCase();
    return `<span class="badge badge-${cls}">${category}</span>`;
}

// Escape HTML
function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// Debounce
function debounce(fn, delay = 300) {
    let timer;
    return function (...args) {
        clearTimeout(timer);
        timer = setTimeout(() => fn.apply(this, args), delay);
    };
}

// Get API base URL
// Detects environment and returns appropriate backend URL
function getApiBase() {
    const hostname = window.location.hostname;
    if (hostname.includes('vercel.app')) {
        return 'https://student-sentiment-analysis-system.onrender.com/api/v1';
    }
    return 'http://localhost:8000/api/v1';
}

// Likert scale labels
const LIKERT_LABELS = ['', 'Strongly Disagree', 'Disagree', 'Neutral', 'Agree', 'Strongly Agree'];

// Generate likert scale HTML — updated for paper theme
function likertScale(name, label) {
    let html = `<div class="rating-group">
        <span class="rating-label">${escapeHtml(label)}</span>
        <div class="likert-scale">`;
    for (let i = 1; i <= 5; i++) {
        html += `<label class="likert-option">
            <input type="radio" name="${name}" value="${i}" required />
            <span class="likert-btn">${i}</span>
            <span class="likert-label">${LIKERT_LABELS[i]}</span>
        </label>`;
    }
    html += `</div></div>`;
    return html;
}

// Generate textarea field
function textareaField(name, label, placeholder = '') {
    return `<div class="form-group">
        <label for="${name}"><i class="fas fa-pen"></i> ${escapeHtml(label)}</label>
        <textarea id="${name}" name="${name}" class="form-control" placeholder="${escapeHtml(placeholder)}" rows="3" required></textarea>
    </div>`;
}

// Generate select field
function selectField(name, label, options, placeholder = '') {
    let html = `<div class="form-group">
        <label for="${name}"><i class="fas fa-list"></i> ${escapeHtml(label)}</label>
        <select id="${name}" name="${name}" class="form-control" required>
            <option value="">${escapeHtml(placeholder)}</option>`;
    options.forEach(opt => {
        const val = typeof opt === 'object' ? opt.value : opt;
        const txt = typeof opt === 'object' ? opt.label : opt;
        html += `<option value="${escapeHtml(val)}">${escapeHtml(txt)}</option>`;
    });
    html += `</select></div>`;
    return html;
}

// ============================================================
// Model Performance Comparison helpers (frontend-only filter)
// ============================================================
// The backend /api/v1/ml/performance may still return other models/ensembles.
// The comparison UI displays ONLY these four approved models. "DeBERTa +
// RoBERTa" is the stored backend label for the same two-member ensemble that
// is displayed to the user as "RoBERTa + DeBERTa".
const MODEL_PERFORMANCE_ALLOWED = ['XGBoost', 'DeBERTa', 'RoBERTa', 'DeBERTa + RoBERTa'];

function filterModelPerfRows(rows) {
    if (!Array.isArray(rows)) return [];
    return rows.filter(function (r) {
        return r && r.algorithm && MODEL_PERFORMANCE_ALLOWED.indexOf(r.algorithm) !== -1;
    });
}

function modelPerfDisplayName(algorithm) {
    if (algorithm === 'DeBERTa + RoBERTa' || algorithm === 'RoBERTa + DeBERTa') {
        return 'RoBERTa + DeBERTa';
    }
    return algorithm;
}
