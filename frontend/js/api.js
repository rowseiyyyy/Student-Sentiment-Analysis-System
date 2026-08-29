/**
 * Asiatech Sentiment Analysis - API Client
 * Handles all HTTP requests to the FastAPI backend.
 */

const API = {
    baseUrl: getApiBase(),

    // Get stored token
    getToken() {
        return localStorage.getItem('asiatech_token');
    },

    // Get stored user
    getUser() {
        try {
            return JSON.parse(localStorage.getItem('asiatech_user'));
        } catch {
            return null;
        }
    },

    // Set auth data
    setAuth(token, user) {
        localStorage.setItem('asiatech_token', token);
        localStorage.setItem('asiatech_user', JSON.stringify(user));
    },

    // Clear auth
    clearAuth() {
        localStorage.removeItem('asiatech_token');
        localStorage.removeItem('asiatech_user');
    },

// Get auth headers
    getHeaders(extra = {}) {
        const headers = {
            'Content-Type': 'application/json',
            ...extra
        };
        const token = this.getToken();
        if (token) {
            headers['Authorization'] = `Bearer ${token}`;
        }
        return headers;
    },

    // Get authorization header only (for FormData uploads where Content-Type must be unset)
    getAuthHeaders() {
        const headers = {};
        const token = this.getToken();
        if (token) {
            headers['Authorization'] = `Bearer ${token}`;
        }
        return headers;
    },

// Generic request method
    async request(method, path, body = null, isFormData = false) {
        const url = `${this.baseUrl}${path}`;
        const options = {
            method,
            headers: isFormData ? this.getAuthHeaders() : this.getHeaders(),
        };
        
        // Don't set Content-Type for FormData, let browser set it with boundary
        if (body) {
            options.body = isFormData ? body : JSON.stringify(body);
        }

        try {
            const response = await fetch(url, options);
            
            // Handle 204 No Content
            if (response.status === 204) {
                return { success: true };
            }
            
            const data = await response.json();
            
            if (!response.ok) {
                const detail = data.detail || 
                    (Array.isArray(data.detail) ? data.detail.map(e => e.msg).join(', ') : 'Request failed');
                throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
            }
            
            return data;
        } catch (error) {
            if (error.name === 'TypeError' && error.message.includes('fetch')) {
                throw new Error('Unable to connect to the server. Please ensure the backend is running.');
            }
            throw error;
        }
    },

    // Convenience methods
    get(path) {
        return this.request('GET', path);
    },

    post(path, body) {
        return this.request('POST', path, body);
    },

    put(path, body) {
        return this.request('PUT', path, body);
    },

    del(path) {
        return this.request('DELETE', path);
    },

    // Upload file (multipart/form-data)
    upload(path, file, fieldName = 'file') {
        const formData = new FormData();
        formData.append(fieldName, file);
        return this.request('POST', path, formData, true);
    },

    // ============================================================
    // AUTH ENDPOINTS
    // ============================================================

    async register(data) {
        return this.post('/auth/register', data);
    },

    async login(email, password) {
        return this.post('/auth/login', { email, password });
    },

    async getMe() {
        return this.get('/auth/me');
    },

async refreshToken(refreshToken) {
        return this.post('/auth/refresh', { refresh_token: refreshToken });
    },

    async forgotPassword(email) {
        return this.post('/auth/forgot-password', { email });
    },

    async resetPassword(token, newPassword) {
        return this.post('/auth/reset-password', { token, new_password: newPassword });
    },

    async getProfile() {
        return this.get('/auth/me/profile');
    },

    async updateProfile(data) {
        return this.put('/auth/me/profile', data);
    },

    // ============================================================
    // EVALUATION ENDPOINTS
    // ============================================================

    async submitEvaluation(data) {
        return this.post('/evaluation', data);
    },

async getEvaluations(params = {}) {
    const query = new URLSearchParams();
    if (params.category) query.set('category', params.category);
    if (params.page) query.set('page', params.page);
    if (params.page_size) query.set('page_size', params.page_size);
    if (params.has_submission !== undefined && params.has_submission !== null) query.set('has_submission', params.has_submission);
    if (params.needs_review) query.set('needs_review', params.needs_review);
    if (params.search) query.set('search', params.search);
    if (params.sort_by) query.set('sort_by', params.sort_by);
    if (params.sort_order) query.set('sort_order', params.sort_order);
    const qs = query.toString();
    return this.get(`/evaluation${qs ? '?' + qs : ''}`);
},

    async getEvaluation(id) {
        return this.get(`/evaluation/${id}`);
    },

    async deleteEvaluation(id) {
        return this.del(`/evaluation/${id}`);
    },

    // Bulk-delete multiple evaluations at once. `ids` is an array of
    // evaluation id strings. Returns { deleted_count, not_found }.
    async bulkDeleteEvaluations(ids) {
        return this.post('/evaluation/bulk-delete', { ids });
    },

    // ============================================================
    // PREDICTION ENDPOINTS
    // ============================================================

    async predict(text) {
        return this.post('/predict', { text });
    },

    // ============================================================
    // ANALYTICS ENDPOINTS
    // ============================================================

    // Turn an optional query-string (e.g. "days=30&category=Faculty")
    // into a "?..." segment (or "sep..." with a custom separator), or ''
    // when empty/absent.
    _buildQuery(params, sep = '?') {
        if (!params) return '';
        var qs = String(params).replace(/^\?/, '');
        return qs ? (sep + qs) : '';
    },

    async getOverallAnalytics(params) {
        return this.get('/analytics/overall' + this._buildQuery(params));
    },

    async getCategoryAnalytics(category, params) {
        return this.get(`/analytics/category?category=${encodeURIComponent(category)}${this._buildQuery(params, '&')}`);
    },

    async getMonthlyTrend(params) {
        return this.get('/analytics/monthly' + this._buildQuery(params));
    },

    async getDailyTrend(params) {
        return this.get('/analytics/daily' + this._buildQuery(params));
    },

    async getWordFrequency(sentiment, topN = 30) {
        return this.get(`/analytics/word-frequency?sentiment=${encodeURIComponent(sentiment)}&top_n=${topN}`);
    },

    async getTopComplaints(limit = 10) {
        return this.get(`/analytics/top-complaints?limit=${limit}`);
    },

    async getTopAppreciations(limit = 10) {
        return this.get(`/analytics/top-appreciations?limit=${limit}`);
    },

    async exportCsv() {
        const url = `${this.baseUrl}/analytics/export/csv`;
        const token = this.getToken();
        const response = await fetch(url, {
            headers: token ? { 'Authorization': `Bearer ${token}` } : {}
        });
        if (!response.ok) throw new Error('Failed to export CSV');
        const blob = await response.blob();
        const downloadUrl = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = downloadUrl;
        a.download = 'evaluations_report.csv';
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(downloadUrl);
    },

    // ============================================================
    // ML / ADMIN ENDPOINTS
    // ============================================================

    async importModelResults({ metrics, xgbModel, xgbVectorizer, debertaZip, robertaZip, setProduction }) {
        const formData = new FormData();
       formData.append('metrics_json', metrics);
        if (xgbModel) formData.append('xgb_model', xgbModel);
        if (xgbVectorizer) formData.append('xgb_vectorizer', xgbVectorizer);
        if (debertaZip) formData.append('deberta_archive', debertaZip);
       if (robertaZip) formData.append('roberta_archive', robertaZip);
       if (setProduction) formData.append('set_production', setProduction);
      return this.request('POST', '/ml/import-results', formData, true);
    },

    async getModels(algorithm = null) {
        const qs = algorithm ? `?algorithm=${encodeURIComponent(algorithm)}` : '';
        return this.get(`/ml/models${qs}`);
    },

    async getModelPerformance() {
        return this.get('/ml/performance');
    },

    async getConfusionMatrix(algorithm) {
        return this.get(`/ml/confusion-matrix?algorithm=${encodeURIComponent(algorithm)}`);
    },

    async getClassificationReport(algorithm) {
        return this.get(`/ml/classification-report?algorithm=${encodeURIComponent(algorithm)}`);
    },

    async rollbackModel(trainingHistoryId) {
        return this.post(`/ml/rollback?training_history_id=${trainingHistoryId}`);
    },

    async downloadModel(algorithm) {
        const url = `${this.baseUrl}/ml/models/${encodeURIComponent(algorithm)}/download`;
        const token = this.getToken();
        const response = await fetch(url, {
            headers: token ? { 'Authorization': `Bearer ${token}` } : {}
        });
        if (!response.ok) throw new Error('Failed to download model');
        const blob = await response.blob();
        const downloadUrl = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = downloadUrl;
        a.download = `${algorithm.toLowerCase().replace(/\s+/g, '_')}_model.pkl`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(downloadUrl);
    },

    // ============================================================
    // BULK IMPORT ENDPOINTS
    // ============================================================

        // ============================================================
    // BULK IMPORT ENDPOINTS
    // ============================================================

    async importEvaluations(file, category) {
        const formData = new FormData();
        formData.append('file', file);
        // category is optional: auto-detect from the headers when omitted.
        // Pass '' / null for a combined (Staff_/Professor_/Facilities_/Payments_)
        // multi-category file, OR to have the server figure it out.
        if (category) {
            formData.append('category', category);
        }
        return this.request('POST', '/imports/evaluations', formData, true);
    }
};