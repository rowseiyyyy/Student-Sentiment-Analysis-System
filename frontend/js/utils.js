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
    
    const icon = document.createElement('span');
    icon.textContent = icons[type] || icons.info;
    const content = document.createElement('span');
    content.textContent = message;
    toast.append(icon, content);
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
// Detection order:
//   1. An explicit override — set window.ASIATECH_API_BASE (in index.html or a
//      deployment-injected config snippet) to point at any backend. Escape hatch
//      for forks, custom domains and preview deployments.
//   2. Local pages (localhost / 127.0.0.1 / file://) -> the local dev backend.
//   3. Every other (deployed) host -> the production backend.
// Previously anything that was not *.vercel.app fell through to localhost:8000,
// so a frontend served from a custom domain, a Render static site, Netlify or a
// Vercel *preview* URL silently called the visitor's own machine and every
// request failed with "Unable to connect to the server".
function getApiBase() {
    if (window.ASIATECH_API_BASE) {
        return window.ASIATECH_API_BASE;
    }
    const hostname = window.location.hostname;
    const isLocalPage =
        hostname === '' ||            // file:// (opened straight from disk)
        hostname === 'localhost' ||
        hostname === '127.0.0.1' ||
        hostname === '[::1]' ||
        hostname.endsWith('.localhost');
    if (isLocalPage) {
        return 'http://localhost:8000/api/v1';
    }
    return 'https://student-sentiment-analysis-system.onrender.com/api/v1';
}

// Likert scale labels
const LIKERT_LABELS = ['', 'Strongly Disagree', 'Disagree', 'Neutral', 'Agree', 'Strongly Agree'];

// Generate likert scale HTML — updated for paper theme
function likertScale(name, label) {
    let html = `<div class="rating-group" data-name="${name}">
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
// The comparison UI displays ONLY these approved models. The two real-time
// pair ensembles are "XGBoost (TF-IDF) + mDeBERTa" and "XGBoost (TF-IDF) +
// XLM-RoBERTa"; "Average (All Models)" is the plain equal-weight average of
// all three models. XLM-RoBERTa entries remain as historical/reporting data.
const MODEL_PERFORMANCE_ALLOWED = ['XGBoost (TF-IDF)', 'mDeBERTa', 'XLM-RoBERTa', 'Multilingual MiniLM', 'mDeBERTa + XLM-RoBERTa'];

function filterModelPerfRows(rows) {
    if (!Array.isArray(rows)) return [];
    return rows.filter(function (r) {
        return r && r.algorithm && MODEL_PERFORMANCE_ALLOWED.indexOf(r.algorithm) !== -1;
    });
}

function modelPerfDisplayName(algorithm) {
    // Active ensemble: mDeBERTa + XLM-RoBERTa.
    if (algorithm === 'mDeBERTa + XLM-RoBERTa' || algorithm === 'XLM-RoBERTa + mDeBERTa') {
        return 'XLM-RoBERTa + mDeBERTa';
    }
    // Legacy composites (superseded ensembles) keep their historical display
    // names so older comparison rows remain readable.
    if (algorithm === 'XGBoost (TF-IDF) + mDeBERTa' || algorithm === 'mDeBERTa + XGBoost (TF-IDF)') {
        return 'mDeBERTa + XGBoost (TF-IDF)';
    }
    if (algorithm === 'XGBoost (TF-IDF) + XLM-RoBERTa') {
        return 'XLM-RoBERTa + XGBoost (TF-IDF)';
    }
    if (algorithm === 'Average (All Models)') {
        return 'Average (All Models)';
    }
    return algorithm;
}
