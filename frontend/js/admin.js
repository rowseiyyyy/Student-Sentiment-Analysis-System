/**
 * Asiatech Sentiment Analysis - Admin Module
 * Updated for "Asiatech Feedback Casefile" paper theme design.
 * Admin dashboard: responses table, analytics, ML training, data import, charts.
 * All data fetching, export, CRUD logic preserved.
 */

var ADMIN = {
    currentUser: null,
    charts: {},

    init: function() {
        var user = API.getUser();
        if (user && user.role === 'administrator') {
            this.currentUser = user;
            this.showDashboard();
        }
    },

    handleLogin: async function(email, password) {
        showLoading('Logging in...');
        try {
            var result = await API.login(email, password);
            API.setAuth(result.access_token, result.user);
            this.currentUser = result.user;
            showToast('Welcome, ' + result.user.full_name + '!', 'success');
            this.showDashboard();
        } catch (error) {
            showToast('Login failed: ' + error.message, 'error');
        } finally {
            hideLoading();
        }
    },

    logout: function() {
        API.clearAuth();
        this.currentUser = null;
        this.destroyCharts();
        APP.goToPage('page-login');
        document.getElementById('nav-admin').style.display = 'none';
    },

    destroyCharts: function() {
        var _this = this;
        Object.values(this.charts).forEach(function(c) { if (c) c.destroy(); });
        this.charts = {};
    },

    showDashboard: function() {
        APP.goToPage('page-admin-dashboard');
        document.getElementById('nav-admin').style.display = 'flex';
        document.getElementById('badge-admin').textContent = '\u{1F6E1} ' + (this.currentUser ? this.currentUser.full_name : 'Administrator');
        this.renderTab('overview');
    },

    renderTab: function(tab) {
        var content = document.getElementById('admin-content');
        content.innerHTML = '';
        var tabContent = document.createElement('div');
        tabContent.id = 'admin-tab-content';
        content.appendChild(tabContent);

        switch(tab) {
            case 'overview': this.renderOverview(tabContent); break;
            case 'responses': this.renderResponses(tabContent); break;
            case 'analytics': this.renderAnalytics(tabContent); break;
            case 'ml': this.renderMLPanel(tabContent); break;
            case 'import': this.renderImportPanel(tabContent); break;
        }
    },

    // ============================================================
    // OVERVIEW TAB — Paper theme design
    // ============================================================
renderOverview: async function(container) {
        container.innerHTML = '<div class="text-center mt-4"><div class="spinner"></div><p>Loading overview...</p></div>';
        try {
            var overall = await API.getOverallAnalytics();
            var perf = await API.getModelPerformance();

            // Real "By Department" data from the category analytics endpoint
            var categories = ['Faculty', 'Staff', 'Facilities', 'Payment'];
            var catData = await Promise.all(categories.map(function(c) {
                return API.getCategoryAnalytics(c).catch(function() { return null; });
            }));
            var maxCatTotal = 1;
            var ledgerRowsHtml = categories.map(function(c, i) {
                var d = catData[i];
                var total = d && d.breakdown ? (d.breakdown.total || 0) : 0;
                if (total > maxCatTotal) maxCatTotal = total;
                return { label: c, total: total };
            }).map(function(r) {
                var pct = maxCatTotal > 0 ? Math.round((r.total / maxCatTotal) * 100) : 0;
                var fillClass = r.total === 0 ? '' : (r.label === 'Faculty' ? 'pos' : (r.label === 'Staff' ? 'neu' : 'neg'));
                return '<div class="ledger-row"><span class="label">' + r.label + '</span><div class="ledger-track"><div class="ledger-fill ' + fillClass + '" style="width:' + pct + '%"></div></div><span class="pct">' + r.total + '</span></div>';
            }).join('');

            container.innerHTML = '' +
                '<div class="page-header">' +
                    '<div>' +
                        '<span style="font-family:var(--font-mono);font-size:.7rem;letter-spacing:.12em;text-transform:uppercase;color:var(--ink-faint);display:block;margin-bottom:.35rem;">Casefile Overview — All Departments</span>' +
                        '<h1>Dashboard Overview</h1>' +
                    '</div>' +
                    '<div class="date-note">Compiled ' + new Date().toLocaleDateString('en-US',{month:'long',day:'numeric',year:'numeric'}) + '</div>' +
                '</div>' +
                '<div class="stats-grid">' +
                    '<div class="stat-card"><div class="stat-icon green"><i class="fas fa-smile"></i></div><div class="stat-info"><h3>' + (overall.breakdown.positive || 0) + '</h3><p>Positive Feedbacks</p><small>' + (overall.breakdown.positive_pct ? overall.breakdown.positive_pct.toFixed(1) + '%' : '') + '</small></div></div>' +
                    '<div class="stat-card"><div class="stat-icon yellow"><i class="fas fa-meh"></i></div><div class="stat-info"><h3>' + (overall.breakdown.neutral || 0) + '</h3><p>Neutral Feedbacks</p><small>' + (overall.breakdown.neutral_pct ? overall.breakdown.neutral_pct.toFixed(1) + '%' : '') + '</small></div></div>' +
                    '<div class="stat-card"><div class="stat-icon red"><i class="fas fa-frown"></i></div><div class="stat-info"><h3>' + (overall.breakdown.negative || 0) + '</h3><p>Negative Feedbacks</p><small>' + (overall.breakdown.negative_pct ? overall.breakdown.negative_pct.toFixed(1) + '%' : '') + '</small></div></div>' +
                    '<div class="stat-card"><div class="stat-icon blue"><i class="fas fa-file-alt"></i></div><div class="stat-info"><h3>' + (overall.evaluation_volume || 0) + '</h3><p>Total Evaluations</p></div></div>' +
                    '<div class="stat-card"><div class="stat-icon purple"><i class="fas fa-chart-bar"></i></div><div class="stat-info"><h3>' + (overall.average_confidence ? overall.average_confidence.toFixed(1) + '%' : 'N/A') + '</h3><p>Avg Confidence</p></div></div>' +
                    '<div class="stat-card"><div class="stat-icon blue"><i class="fas fa-trophy"></i></div><div class="stat-info"><h3 style="font-size:1.1rem;">' + (perf.best_model || 'N/A') + '</h3><p>Best Model</p></div></div>' +
                '</div>' +
                '<div class="two-col">' +
                    '<div>' +
                        '<div class="chart-card" style="margin-bottom:1.1rem;"><h3><i class="fas fa-chart-pie"></i> Sentiment Distribution</h3><div class="chart-container"><canvas id="chart-sentiment-overview"></canvas></div></div>' +
                        '<div class="chart-card"><h3><i class="fas fa-chart-bar"></i> Model Performance Comparison</h3><div class="chart-container"><canvas id="chart-model-perf"></canvas></div></div>' +
                    '</div>' +
                    '<div>' +
                        '<div class="card" style="margin-bottom:1.1rem;">' +
                            '<div class="card-header"><h3><i class="fas fa-chart-bar"></i> By Department</h3></div>' +
                            '<div class="ledger-bars">' + ledgerRowsHtml + '</div>' +
                        '</div>' +
                        '<div class="card">' +
                            '<div class="card-header"><h3><i class="fas fa-table"></i> Model Performance</h3></div>' +
                            '<div class="table-container"><table class="perf-table"><thead><tr><th>Algorithm</th><th>Accuracy</th><th>Precision</th><th>Recall</th><th>F1</th><th>Status</th></tr></thead><tbody>' +
                                perf.rows.map(function(r) {
                                    return '<tr><td><strong>' + r.algorithm + '</strong> ' + (r.is_production_model ? '<span class="crown">\u2605</span>' : '') + '</td><td>' + formatNumber(r.accuracy) + '</td><td>' + formatNumber(r.precision) + '</td><td>' + formatNumber(r.recall) + '</td><td>' + formatNumber(r.f1_score) + '</td><td>' + (r.is_production_model ? '<span class="badge badge-positive">Production</span>' : '<span class="badge badge-neutral">Standby</span>') + '</td></tr>';
                                }).join('') +
                                (perf.rows.length === 0 ? '<tr><td colspan="6" class="text-center text-muted">No training data available.</td></tr>' : '') +
                            '</tbody></table></div>' +
                        '</div>' +
                    '</div>' +
                '</div>';

            this.renderSentimentChart(overall.breakdown);
            this.renderModelPerfChart(perf.rows);
        } catch (error) {
            container.innerHTML = '<div class="page-header"><h1>Dashboard Overview</h1></div><div class="card"><div class="empty-state"><div class="empty-icon"><i class="fas fa-database"></i></div><h3>No Data Available</h3><p>' + error.message + '</p></div></div>';
        }
    },

    renderSentimentChart: function(breakdown) {
        setTimeout(function() {
            var ctx = document.getElementById('chart-sentiment-overview');
            if (!ctx) return;
            ADMIN.destroyCharts();
            ADMIN.charts.sentiment = new Chart(ctx, {
                type: 'pie',
                data: { labels: ['Positive', 'Neutral', 'Negative'], datasets: [{ data: [breakdown.positive || 0, breakdown.neutral || 0, breakdown.negative || 0], backgroundColor: ['#2f6f4e', '#b7791f', '#b33a3a'], borderWidth: 2, borderColor: '#f8f9f5' }] },
                options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } } }
            });
        }, 100);
    },

    renderModelPerfChart: function(rows) {
        setTimeout(function() {
            var ctx = document.getElementById('chart-model-perf');
            if (!ctx) return;
            ADMIN.charts.modelPerf = new Chart(ctx, {
                type: 'bar',
                data: { labels: rows.map(function(r) { return r.algorithm; }), datasets: [{ label: 'Accuracy', data: rows.map(function(r) { return r.accuracy || 0; }), backgroundColor: '#2b3a67' }, { label: 'F1 Score', data: rows.map(function(r) { return r.f1_score || 0; }), backgroundColor: '#b7791f' }] },
                options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true, max: 1 } }, plugins: { legend: { position: 'bottom' } } }
            });
        }, 100);
    },

    // ============================================================
    // RESPONSES TAB — Paper theme design
    // ============================================================
    async renderResponses(container) {
        container.innerHTML = '' +
            '<div class="page-header">' +
                '<div>' +
                    '<span style="font-family:var(--font-mono);font-size:.7rem;letter-spacing:.12em;text-transform:uppercase;color:var(--ink-faint);display:block;margin-bottom:.35rem;">Full Transcript</span>' +
                    '<h1>Every entry, logged</h1>' +
                '</div>' +
                '<div style="display:flex;gap:0.5rem;flex-wrap:wrap;">' +
                    '<button class="btn btn-success" onclick="ADMIN.exportCSV()"><i class="fas fa-download"></i> CSV</button>' +
                    '<button class="btn btn-primary" onclick="ADMIN.exportXLSX()"><i class="fas fa-file-excel"></i> XLSX</button>' +
                '</div>' +
            '</div>' +
            '<div class="filter-bar">' +
                '<select class="form-control" id="filter-category">' +
                    '<option value="">All Categories</option>' +
                    '<option value="Faculty">Faculty</option>' +
                    '<option value="Staff">Staff</option>' +
                    '<option value="Facilities">Facilities</option>' +
                    '<option value="Payment">Payments</option>' +
                '</select>' +
                '<input type="text" class="form-control" id="filter-search" placeholder="Search by student ID, course, evaluatee, strengths..." style="flex:1;min-width:200px;" />' +
                '<button class="btn btn-primary" onclick="ADMIN.loadResponses()"><i class="fas fa-search"></i> Search</button>' +
                '<button class="btn btn-secondary" onclick="ADMIN.resetFilters()"><i class="fas fa-undo"></i> Reset</button>' +
            '</div>' +
            '<div id="responses-loading" class="text-center mt-3 hidden"><div class="spinner"></div><p>Loading responses...</p></div>' +
            '<div id="responses-table-container"></div>' +
            '<div id="responses-pagination" class="pagination"></div>';

        document.getElementById('filter-category').addEventListener('change', function() { ADMIN.currentPage = 1; ADMIN.loadResponses(); });
        document.getElementById('filter-search').addEventListener('input', debounce(function() { ADMIN.currentPage = 1; ADMIN.loadResponses(); }, 500));
        this.loadResponses();
    },

    currentPage: 1,

    getCategoryDisplayName: function(category) {
        if (!category) return 'N/A';
        var cat = String(category).toLowerCase();
        if (cat === 'faculty') return 'Faculty';
        if (cat === 'staff') return 'Staff';
        if (cat === 'facilities') return 'Facilities';
        if (cat === 'payment' || cat === 'payments') return 'Payment';
        return category;
    },

    getCategoryApiValue: function(category) {
        if (!category) return '';
        var displayName = this.getCategoryDisplayName(category);
        if (displayName === 'Payment') return 'Payment';
        return displayName;
    },

    getCategoryBadgeClass: function(category) {
        var displayName = this.getCategoryDisplayName(category);
        if (displayName === 'Faculty') return 'faculty';
        if (displayName === 'Staff') return 'staff';
        if (displayName === 'Facilities') return 'facilities';
        if (displayName === 'Payment') return 'payment';
        return 'neutral';
    },

    getStudentInfo: function(item) {
        return item.student || item.student_info || item.submitted_by || {};
    },

    getEvaluateeLabel: function(item) {
        var category = this.getCategoryDisplayName(item && item.category);
        if (category === 'Faculty') {
            return item && item.evaluatee ? item.evaluatee : 'N/A';
        }
        if (category === 'Staff') return 'Staff';
        if (category === 'Facilities') return 'Facilities';
        if (category === 'Payment') return 'Payment';
        return item && item.evaluatee ? item.evaluatee : 'N/A';
    },

    async loadResponses() {
        var category = document.getElementById('filter-category') ? document.getElementById('filter-category').value : '';
        var search = document.getElementById('filter-search') ? document.getElementById('filter-search').value : '';
        var loading = document.getElementById('responses-loading');
        var tableContainer = document.getElementById('responses-table-container');
        var pagination = document.getElementById('responses-pagination');

        if (loading) loading.classList.remove('hidden');
        if (tableContainer) tableContainer.innerHTML = '';

try {
            var data = await API.getEvaluations({ category: this.getCategoryApiValue(category), page: this.currentPage, page_size: 20, has_submission: true });
            var items = Array.isArray(data.items) ? data.items : [];

            if (search) {
                var q = search.toLowerCase();
                items = items.filter(function(item) {
                    var si = ADMIN.getStudentInfo(item);
                    var searchFields = [
                        (si.student_id || ''),
                        (si.course || ''),
                        (si.year_level || ''),
                        (ADMIN.getEvaluateeLabel(item) || ''),
                        (item.strengths || ''),
                        (item.areas_for_improvement || ''),
                        (item.comment || ''),
                        (item.category || '')
                    ];
                    return searchFields.some(function(f) { return String(f).toLowerCase().indexOf(q) !== -1; });
                });
            }

            if (items.length === 0) {
                if (tableContainer) tableContainer.innerHTML = '<div class="empty-state"><div class="empty-icon"><i class="fas fa-inbox"></i></div><h3>No Responses Found</h3><p>' + (search ? 'Try a different search term.' : 'No evaluations have been submitted yet.') + '</p></div>';
            } else {
                var rows = items.map(function(item, idx) {
                    var si = ADMIN.getStudentInfo(item);
                    var rowNum = (ADMIN.currentPage - 1) * 20 + idx + 1;
                    var strengths = item.strengths || '';
                    var improvements = item.areas_for_improvement || '';
                    var evaluatee = ADMIN.getEvaluateeLabel(item);
                    var categoryDisplay = ADMIN.getCategoryDisplayName(item.category);
                    var badgeClass = ADMIN.getCategoryBadgeClass(item.category);
                    var commentsRaw = '';
                    if (strengths) commentsRaw += 'Strengths: ' + strengths;
                    if (improvements) commentsRaw += (commentsRaw ? '\n\n' : '') + 'Areas for Improvement: ' + improvements;
var commentsDisplay = commentsRaw
                        ? escapeHtml(commentsRaw.length > 180 ? commentsRaw.substring(0, 180) + '...' : commentsRaw)
                        : '<span class="text-muted">N/A</span>';
                    return '<tr>' +
                        '<td style="font-family:var(--font-mono);font-size:.72rem;color:var(--ink-faint);">' + rowNum + '</td>' +
                        '<td>' + escapeHtml(si.student_id || 'N/A') + '</td>' +
                        '<td>' + escapeHtml(si.course || 'N/A') + '</td>' +
                        '<td>' + escapeHtml(si.year_level || 'N/A') + '</td>' +
                        '<td><span class="badge badge-' + badgeClass + '">' + escapeHtml(categoryDisplay) + '</span></td>' +
                        '<td>' + escapeHtml(evaluatee) + '</td>' +
                        '<td style="white-space:nowrap;">' + sentimentBadge(item.sentiment) + '</td>' +
                        '<td style="max-width:320px;overflow:hidden;text-overflow:ellipsis;white-space:pre-line;" title="' + escapeHtml(commentsRaw) + '">' + commentsDisplay + '</td>' +
                        '<td style="font-family:var(--font-mono);font-size:.8rem;white-space:nowrap;">' + formatDate(item.created_at) + '</td>' +
                        '<td style="white-space:nowrap;">' +
                            '<button class="btn btn-sm btn-primary" onclick="ADMIN.viewEval(\'' + item.id + '\')" title="View Complete Evaluation"><i class="fas fa-eye"></i></button> ' +
                            '<button class="btn btn-sm btn-danger" onclick="ADMIN.deleteEval(\'' + item.id + '\')" title="Delete"><i class="fas fa-trash"></i></button>' +
                        '</td></tr>';
                }).join('');

                if (tableContainer) tableContainer.innerHTML = '<div class="table-container"><table>' +
                    '<thead><tr><th>#</th><th>Student ID</th><th>Course</th><th>Year Level</th><th>Category</th><th>Evaluatee</th><th>Sentiment</th><th style="max-width:320px;">Comments</th><th style="white-space:nowrap;">Date</th><th style="white-space:nowrap;">Actions</th></tr></thead>' +
                    '<tbody>' + rows + '</tbody></table></div>';
            }

            var totalPages = Math.ceil((data.total || 0) / 20);
            if (pagination) pagination.innerHTML = '';
            if (totalPages > 1) {
                for (var i = 1; i <= totalPages; i++) {
                    (function(pageNum) {
                        var btn = document.createElement('button');
                        btn.textContent = pageNum;
                        btn.className = pageNum === ADMIN.currentPage ? 'active' : '';
                        btn.addEventListener('click', function() { ADMIN.currentPage = pageNum; ADMIN.loadResponses(); });
                        if (pagination) pagination.appendChild(btn);
                    })(i);
                }
            }
        } catch (error) {
            if (tableContainer) tableContainer.innerHTML = '<div class="empty-state"><div class="empty-icon"><i class="fas fa-exclamation-triangle" style="color:var(--neu);"></i></div><h3>Error Loading Responses</h3><p>' + error.message + '</p></div>';
        } finally {
            if (loading) loading.classList.add('hidden');
        }
    },

    resetFilters: function() {
        var cat = document.getElementById('filter-category');
        var search = document.getElementById('filter-search');
        if (cat) cat.value = '';
        if (search) search.value = '';
        this.currentPage = 1;
        this.loadResponses();
    },

    // ============================================================
    // VIEW EVALUATION (Modal) — Paper theme design
    // ============================================================
    async viewEval(id) {
        showLoading('Loading evaluation details...');
        try {
            var item = await API.getEvaluation(id);
            hideLoading();

            var studentInfo = this.getStudentInfo(item);
            var ratings = item.ratings || {};
            var strengths = item.strengths || '';
            var improvements = item.areas_for_improvement || '';
            var evaluatee = this.getEvaluateeLabel(item);
            var categoryDisplay = this.getCategoryDisplayName(item.category);
            var badgeClass = this.getCategoryBadgeClass(item.category);

            var ratingsHtml = '';
            var ratingKeys = Object.keys(ratings);
            if (ratingKeys.length > 0) {
                var ratingRows = ratingKeys.map(function(k) {
                    var label = k.replace(/_/g, ' ').replace(/\b\w/g, function(l) { return l.toUpperCase(); });
                    return '<tr><td>' + escapeHtml(label) + '</td><td><strong>' + ratings[k] + '/5</strong></td></tr>';
                }).join('');
                ratingsHtml = '<div class="form-section" style="margin-top:1rem;"><h4 style="margin-bottom:0.5rem;">Quantitative Ratings</h4><div class="table-container"><table><thead><tr><th>Aspect</th><th>Rating</th></tr></thead><tbody>' + ratingRows + '</tbody></table></div>';
            }

            var html = '' +
                '<div class="modal-row">' +
                    '<div class="modal-field"><label>Student ID</label><p>' + escapeHtml(studentInfo.student_id || 'N/A') + '</p></div>' +
                    '<div class="modal-field"><label>Date Submitted</label><p>' + formatDate(item.created_at) + '</p></div>' +
                '</div>' +
                '<div class="modal-row">' +
                    '<div class="modal-field"><label>Course</label><p>' + escapeHtml(studentInfo.course || 'N/A') + '</p></div>' +
                    '<div class="modal-field"><label>Year Level</label><p>' + escapeHtml(studentInfo.year_level || 'N/A') + '</p></div>' +
                '</div>' +
                '<div class="modal-row">' +
                    '<div class="modal-field"><label>Category</label><p><span class="badge badge-' + badgeClass + '">' + escapeHtml(categoryDisplay) + '</span></p></div>' +
                    '<div class="modal-field"><label>Evaluatee</label><p>' + escapeHtml(evaluatee) + '</p></div>' +
                '</div>' +
                ratingsHtml +
                '<div style="margin-top:1rem;display:grid;grid-template-columns:1fr 1fr;gap:0.75rem;">' +
                    '<div style="background:var(--pos-bg);padding:0.75rem;border:1px solid var(--paper-line);">' +
                        '<h4 style="font-family:var(--font-mono);font-size:.7rem;letter-spacing:.06em;text-transform:uppercase;color:var(--pos);margin-bottom:.3rem;"><i class="fas fa-thumbs-up"></i> Strengths</h4>' +
                        '<p style="font-size:.85rem;white-space:pre-wrap;">' + (strengths ? escapeHtml(strengths) : '<span class="text-muted">No strengths provided.</span>') + '</p>' +
                    '</div>' +
                    '<div style="background:var(--neg-bg);padding:0.75rem;border:1px solid var(--paper-line);">' +
                        '<h4 style="font-family:var(--font-mono);font-size:.7rem;letter-spacing:.06em;text-transform:uppercase;color:var(--neg);margin-bottom:.3rem;"><i class="fas fa-lightbulb"></i> Improvements</h4>' +
                        '<p style="font-size:.85rem;white-space:pre-wrap;">' + (improvements ? escapeHtml(improvements) : '<span class="text-muted">No improvements suggested.</span>') + '</p>' +
                    '</div>' +
                '</div>';

            APP.openModal(html);
        } catch (error) {
            hideLoading();
            showToast('Failed to load evaluation details: ' + error.message, 'error');
        }
    },

    async deleteEval(id) {
        if (!confirm('Are you sure you want to permanently delete this evaluation? This action cannot be undone.')) return;
        showLoading('Deleting evaluation...');
        try {
            await API.deleteEvaluation(id);
            showToast('Evaluation deleted successfully.', 'success');
            this.loadResponses();
        } catch (error) {
            showToast('Delete failed: ' + error.message, 'error');
        } finally {
            hideLoading();
        }
    },

async exportCSV() {
        showLoading('Exporting CSV...');
        try {
            var data = await API.getEvaluations({ page_size: 10000, has_submission: true });
            var items = data.items || [];
            var headers = ['Student ID', 'Course', 'Year Level', 'Category', 'Evaluatee', 'Strengths', 'Areas for Improvement', 'Date Submitted'];
            var rows = items.map(function(item) {
                var si = ADMIN.getStudentInfo(item);
                return [
                    '"' + (si.student_id || '') + '"',
                    '"' + (si.course || '') + '"',
                    '"' + (si.year_level || '') + '"',
                    '"' + ADMIN.getCategoryDisplayName(item.category) + '"',
                    '"' + (ADMIN.getEvaluateeLabel(item) || '') + '"',
                    '"' + ((item.strengths || '').replace(/"/g, '""')) + '"',
                    '"' + ((item.areas_for_improvement || '').replace(/"/g, '""')) + '"',
                    '"' + (item.created_at || '') + '"'
                ];
            });
            var csvContent = headers.join(',') + '\n' + rows.map(function(r) { return r.join(','); }).join('\n');
            var blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
            var url = URL.createObjectURL(blob);
            var a = document.createElement('a');
            a.href = url;
            a.download = 'student_responses_' + new Date().toISOString().split('T')[0] + '.csv';
            document.body.appendChild(a);
            a.click();
            a.remove();
            URL.revokeObjectURL(url);
            showToast('CSV exported successfully!', 'success');
        } catch (error) {
            showToast('Export failed: ' + error.message, 'error');
        } finally {
            hideLoading();
        }
    },

    async exportXLSX() {
        showLoading('Exporting XLSX...');
        try {
            var data = await API.getEvaluations({ page_size: 10000, has_submission: true });
            var items = data.items || [];
            var headers = ['Student ID', 'Course', 'Year Level', 'Category', 'Evaluatee', 'Strengths', 'Areas for Improvement', 'Date Submitted'];
            var rows = items.map(function(item) {
                var si = ADMIN.getStudentInfo(item);
                return [
                    '"' + (si.student_id || '') + '"',
                    '"' + (si.course || '') + '"',
                    '"' + (si.year_level || '') + '"',
                    '"' + ADMIN.getCategoryDisplayName(item.category) + '"',
                    '"' + (ADMIN.getEvaluateeLabel(item) || '') + '"',
                    '"' + ((item.strengths || '').replace(/"/g, '""')) + '"',
                    '"' + ((item.areas_for_improvement || '').replace(/"/g, '""')) + '"',
                    '"' + (item.created_at || '') + '"'
                ];
            });
            var csvContent = headers.join(',') + '\n' + rows.map(function(r) { return r.join(','); }).join('\n');
var aoa = [headers];
            items.forEach(function(item) {
                var si = ADMIN.getStudentInfo(item);
                aoa.push([
                    si.student_id || '',
                    si.course || '',
                    si.year_level || '',
                    ADMIN.getCategoryDisplayName(item.category),
                    ADMIN.getEvaluateeLabel(item) || '',
                    item.strengths || '',
                    item.areas_for_improvement || '',
                    item.created_at || ''
                ]);
            });
            var ws = XLSX.utils.aoa_to_sheet(aoa);
            var wb = XLSX.utils.book_new();
            XLSX.utils.book_append_sheet(wb, ws, 'Responses');
            XLSX.writeFile(wb, 'student_responses_' + new Date().toISOString().split('T')[0] + '.xlsx');
            showToast('XLSX exported successfully!', 'success');
        } catch (error) {
            showToast('Export failed: ' + error.message, 'error');
        } finally {
            hideLoading();
        }
    },

    // ============================================================
    // ANALYTICS TAB — Paper theme design
    // ============================================================
    async renderAnalytics(container) {
        container.innerHTML = '' +
            '<div class="page-header"><div><span style="font-family:var(--font-mono);font-size:.7rem;letter-spacing:.12em;text-transform:uppercase;color:var(--ink-faint);display:block;margin-bottom:.35rem;">Detailed Analytics</span><h1>Trends &amp; top signals</h1></div></div>' +
            '<div class="stats-grid" style="grid-template-columns:repeat(auto-fit,minmax(220px,1fr));">' +
                '<div class="stat-card"><div class="stat-icon green"><i class="fas fa-chart-line"></i></div><div class="stat-info"><h3 id="ana-pos-pct">-</h3><p>Positive Rate</p></div></div>' +
                '<div class="stat-card"><div class="stat-icon blue"><i class="fas fa-file-alt"></i></div><div class="stat-info"><h3 id="ana-total">-</h3><p>Total Entries</p></div></div>' +
                '<div class="stat-card"><div class="stat-icon yellow"><i class="fas fa-bullseye"></i></div><div class="stat-info"><h3 id="ana-confidence">-</h3><p>Model Confidence</p></div></div>' +
            '</div>' +
            '<div class="chart-grid">' +
                '<div class="chart-card"><h3><i class="fas fa-chart-line"></i> Monthly Trend</h3><div class="chart-container"><canvas id="chart-monthly-trend"></canvas></div></div>' +
                '<div class="chart-card"><h3><i class="fas fa-chart-bar"></i> Sentiment by Category</h3><div class="chart-container"><canvas id="chart-category-sentiment"></canvas></div></div>' +
            '</div>' +
            '<div class="two-col">' +
                '<div class="card"><div class="card-header"><h3><i class="fas fa-exclamation-circle"></i> Top Complaints</h3></div><div id="top-complaints-list"></div></div>' +
                '<div class="card"><div class="card-header"><h3><i class="fas fa-star"></i> Top Appreciations</h3></div><div id="top-appreciations-list"></div></div>' +
            '</div>';

        showLoading('Loading analytics...');
        try {
            var results = await Promise.all([
                API.getOverallAnalytics(),
                API.getMonthlyTrend(),
                API.getTopComplaints(5),
                API.getTopAppreciations(5)
            ]);
            var overall = results[0];
            var monthly = results[1];
            var complaints = results[2];
            var appreciations = results[3];

            document.getElementById('ana-pos-pct').textContent = (overall.breakdown.positive_pct || 0).toFixed(1) + '%';
            document.getElementById('ana-total').textContent = overall.evaluation_volume || 0;
            document.getElementById('ana-confidence').textContent = overall.average_confidence ? overall.average_confidence.toFixed(1) + '%' : 'N/A';

            var categories = ['Faculty', 'Staff', 'Facilities', 'Payment'];
            var catData = await Promise.all(categories.map(function(c) { return API.getCategoryAnalytics(c).catch(function() { return null; }); }));

            setTimeout(function() {
                var ctx = document.getElementById('chart-category-sentiment');
                if (!ctx) return;
                ADMIN.charts.categorySentiment = new Chart(ctx, {
                    type: 'bar',
                    data: {
                        labels: categories,
                        datasets: [
                            { label: 'Positive', data: catData.map(function(d) { return d && d.breakdown ? d.breakdown.positive || 0 : 0; }), backgroundColor: '#2f6f4e' },
                            { label: 'Neutral', data: catData.map(function(d) { return d && d.breakdown ? d.breakdown.neutral || 0 : 0; }), backgroundColor: '#b7791f' },
                            { label: 'Negative', data: catData.map(function(d) { return d && d.breakdown ? d.breakdown.negative || 0 : 0; }), backgroundColor: '#b33a3a' }
                        ]
                    },
                    options: { responsive: true, maintainAspectRatio: false, scales: { x: { stacked: true }, y: { stacked: true } }, plugins: { legend: { position: 'bottom' } } }
                });
            }, 100);

            setTimeout(function() {
                var ctx2 = document.getElementById('chart-monthly-trend');
                if (!ctx2) return;
                var points = monthly.points || [];
                ADMIN.charts.monthlyTrend = new Chart(ctx2, {
                    type: 'line',
                    data: {
                        labels: points.map(function(p) { return p.period; }),
                        datasets: [
                            { label: 'Positive', data: points.map(function(p) { return p.positive; }), borderColor: '#2f6f4e', backgroundColor: 'rgba(47,111,78,0.1)', fill: true, tension: 0.4 },
                            { label: 'Neutral', data: points.map(function(p) { return p.neutral; }), borderColor: '#b7791f', backgroundColor: 'rgba(183,121,31,0.1)', fill: true, tension: 0.4 },
                            { label: 'Negative', data: points.map(function(p) { return p.negative; }), borderColor: '#b33a3a', backgroundColor: 'rgba(179,58,58,0.1)', fill: true, tension: 0.4 }
                        ]
                    },
                    options: { responsive: true, maintainAspectRatio: false, interaction: { intersect: false, mode: 'index' }, plugins: { legend: { position: 'bottom' } } }
                });
            }, 100);

            var complaintsList = document.getElementById('top-complaints-list');
            if (complaints.items && complaints.items.length > 0) {
                complaintsList.innerHTML = complaints.items.map(function(c) {
                    return '<div style="padding:.5rem 0;border-bottom:1px dashed var(--paper-line);"><p style="font-size:.88rem;">"' + escapeHtml(c.comment.substring(0, 150)) + '"</p><small class="text-muted" style="font-family:var(--font-mono);font-size:.72rem;">' + c.category + ' | Confidence: ' + formatNumber(c.confidence) + '</small></div>';
                }).join('');
            } else {
                complaintsList.innerHTML = '<p class="text-muted text-center">No complaints data available.</p>';
            }

            var appreciationsList = document.getElementById('top-appreciations-list');
            if (appreciations.items && appreciations.items.length > 0) {
                appreciationsList.innerHTML = appreciations.items.map(function(a) {
                    return '<div style="padding:.5rem 0;border-bottom:1px dashed var(--paper-line);"><p style="font-size:.88rem;">"' + escapeHtml(a.comment.substring(0, 150)) + '"</p><small class="text-muted" style="font-family:var(--font-mono);font-size:.72rem;">' + a.category + ' | Confidence: ' + formatNumber(a.confidence) + '</small></div>';
                }).join('');
            } else {
                appreciationsList.innerHTML = '<p class="text-muted text-center">No appreciations data available.</p>';
            }
        } catch (error) {
            container.innerHTML += '<div class="card"><div class="empty-state"><div class="empty-icon"><i class="fas fa-exclamation-triangle" style="color:var(--neu);"></i></div><h3>Analytics Error</h3><p>' + error.message + '</p></div>';
        } finally {
            hideLoading();
        }
    },

    // ============================================================
    // ML TRAINING TAB — Paper theme design
    // ============================================================
    renderMLPanel: function(container) {
        container.innerHTML = '' +
            '<div class="page-header"><div><span style="font-family:var(--font-mono);font-size:.7rem;letter-spacing:.12em;text-transform:uppercase;color:var(--ink-faint);display:block;margin-bottom:.35rem;">ML Training Panel</span><h1>Model on duty</h1></div></div>' +
            '<div class="tabs" id="ml-tabs">' +
                '<button class="tab-btn active" data-mltab="upload"><i class="fas fa-upload"></i> Upload Dataset</button>' +
                '<button class="tab-btn" data-mltab="train"><i class="fas fa-play"></i> Train Models</button>' +
                '<button class="tab-btn" data-mltab="performance"><i class="fas fa-chart-bar"></i> Performance</button>' +
                '<button class="tab-btn" data-mltab="confusion"><i class="fas fa-th"></i> Confusion Matrix</button>' +
                '<button class="tab-btn" data-mltab="history"><i class="fas fa-history"></i> History</button>' +
            '</div>' +
            '<div id="ml-tab-content"></div>';

        document.querySelectorAll('#ml-tabs .tab-btn').forEach(function(btn) {
            btn.addEventListener('click', function() {
                document.querySelectorAll('#ml-tabs .tab-btn').forEach(function(b) { b.classList.remove('active'); });
                btn.classList.add('active');
                ADMIN.renderMLTab(btn.dataset.mltab);
            });
        });
        this.renderMLTab('upload');
    },

    renderMLTab: function(tab) {
        var content = document.getElementById('ml-tab-content');
        if (!content) return;
        switch(tab) {
            case 'upload': this.renderMLUpload(content); break;
            case 'train': this.renderMLTrain(content); break;
            case 'performance': this.renderMLPerformance(content); break;
            case 'confusion': this.renderMLConfusion(content); break;
            case 'history': this.renderMLHistory(content); break;
        }
    },

    renderMLUpload: function(container) {
        container.innerHTML = '' +
            '<div class="upload-area" onclick="document.getElementById(\'ml-file-inp\').click()">' +
                '<input type="file" id="ml-file-inp" accept=".csv,.xlsx,.xls" class="hidden" onchange="ADMIN.handleDatasetUpload(this.files[0])" />' +
                '<div class="upload-icon"><i class="fas fa-cloud-upload-alt"></i></div>' +
                '<h4>Drop your dataset file here</h4>' +
                '<p>CSV or Excel with columns: category, comment, sentiment</p>' +
            '</div>' +
            '<div id="upload-result" class="mt-2"></div>';
    },

    async handleDatasetUpload(file) {
        if (!file) return;
        showLoading('Uploading dataset...');
        var resultDiv = document.getElementById('upload-result');
        try {
            var result = await API.uploadDataset(file);
            resultDiv.innerHTML = '' +
                '<div class="card" style="border-left:4px solid var(--pos);">' +
                    '<h4 style="color:var(--pos);"><i class="fas fa-check-circle"></i> Upload Successful</h4>' +
                    '<p><strong>File:</strong> ' + result.filename + '</p>' +
                    '<p><strong>Rows:</strong> ' + result.rows + '</p>' +
                    '<p><strong>Categories:</strong> ' + (result.categories ? result.categories.join(', ') : 'N/A') + '</p>' +
                    '<button class="btn btn-primary mt-2" onclick="ADMIN.startTraining(\'' + result.filename + '\')"><i class="fas fa-play"></i> Train Models Now</button>' +
                '</div>';
            showToast('Dataset uploaded successfully!', 'success');
        } catch (error) {
            resultDiv.innerHTML = '<div class="card" style="border-left:4px solid var(--neg);"><h4 style="color:var(--neg);"><i class="fas fa-times-circle"></i> Upload Failed</h4><p>' + error.message + '</p></div>';
            showToast('Upload failed: ' + error.message, 'error');
        } finally {
            hideLoading();
        }
    },

    startTraining: function(filename) {
        document.querySelectorAll('#ml-tabs .tab-btn').forEach(function(b) { b.classList.remove('active'); });
        document.querySelector('[data-mltab="train"]').classList.add('active');
        this.renderMLTab('train');
        var input = document.getElementById('train-dataset');
        if (input) input.value = filename;
    },

    renderMLTrain: function(container) {
        container.innerHTML = '' +
            '<div class="eval-form-card">' +
                '<h2><i class="fas fa-play"></i> Train / Retrain Models</h2>' +
                '<p class="form-desc">Train SVM, Random Forest, and evaluate BERT on your dataset.</p>' +
                '<form id="train-form">' +
                    '<div class="form-group"><label>Dataset filename</label><input type="text" id="train-dataset" class="form-control" placeholder="Filename from upload (e.g. dataset.csv)" required /></div>' +
                    '<div class="form-group"><label>n_estimators (Random Forest)</label><input type="number" class="form-control" id="train-estimators" value="300" min="50" max="1000" /></div>' +
                    '<div class="form-group"><label>Max depth (optional)</label><input type="number" class="form-control" id="train-max-depth" placeholder="Leave empty for default" /></div>' +
                    '<button type="submit" class="btn btn-primary btn-lg"><i class="fas fa-play"></i> Start Training</button>' +
                '</form>' +
                '<div id="train-result" class="mt-2"></div>' +
            '</div>';

        document.getElementById('train-form').addEventListener('submit', async function(e) {
            e.preventDefault();
            var datasetFilename = document.getElementById('train-dataset').value.trim();
            var nEstimators = parseInt(document.getElementById('train-estimators').value) || 300;
            var maxDepth = parseInt(document.getElementById('train-max-depth').value) || null;
            var resultDiv = document.getElementById('train-result');

            if (!datasetFilename) { showToast('Please enter the dataset filename.', 'warning'); return; }

            resultDiv.innerHTML = '<div class="text-center mt-3"><div class="spinner"></div><p>Training models... This may take a few minutes.</p></div>';

            try {
                var result = await API.trainModels({ dataset_filename: datasetFilename, n_estimators: nEstimators, max_depth: maxDepth });
                resultDiv.innerHTML = '<div class="card" style="border-left:4px solid var(--pos);margin-top:1rem;"><h4 style="color:var(--pos);"><i class="fas fa-check-circle"></i> Training Complete!</h4><p><strong>Best Model:</strong> ' + result.best_model + '</p><pre style="background:var(--paper);padding:1rem;border:1px solid var(--paper-line);overflow-x:auto;font-family:var(--font-mono);font-size:.8rem;">' + JSON.stringify(result.metrics, null, 2) + '</pre><button class="btn btn-primary mt-2" onclick="ADMIN.renderMLTab(\'performance\')"><i class="fas fa-chart-bar"></i> View Performance</button></div>';
                showToast('Training completed! Best model: ' + result.best_model, 'success');
            } catch (error) {
                resultDiv.innerHTML = '<div class="card" style="border-left:4px solid var(--neg);margin-top:1rem;"><h4 style="color:var(--neg);"><i class="fas fa-times-circle"></i> Training Failed</h4><p>' + error.message + '</p></div>';
                showToast('Training failed: ' + error.message, 'error');
            }
        });
    },

    async renderMLPerformance(container) {
        container.innerHTML = '<div class="text-center mt-3"><div class="spinner"></div><p>Loading performance...</p></div>';
        try {
            var perf = await API.getModelPerformance();
            var rowsHtml = perf.rows.map(function(r) {
                return '<tr><td><strong>' + r.algorithm + '</strong> ' + (r.is_production_model ? '<span class="crown"><i class="fas fa-crown"></i></span>' : '') + '</td><td>' + formatNumber(r.accuracy) + '</td><td>' + formatNumber(r.precision) + '</td><td>' + formatNumber(r.recall) + '</td><td>' + formatNumber(r.f1_score) + '</td><td>' + (r.training_time_seconds ? r.training_time_seconds.toFixed(1) + 's' : 'N/A') + '</td><td>' + (r.inference_time_ms ? r.inference_time_ms.toFixed(2) : 'N/A') + '</td><td>' + (r.is_production_model ? '<span class="badge badge-positive">Production</span>' : '<span class="badge badge-neutral">Standby</span>') + '</td><td><button class="btn btn-sm btn-primary" onclick="ADMIN.viewConfusionMatrix(\'' + r.algorithm + '\')" title="Confusion Matrix"><i class="fas fa-th"></i></button> <button class="btn btn-sm btn-outline" onclick="ADMIN.downloadModel(\'' + r.algorithm + '\')" title="Download"><i class="fas fa-download"></i></button></td></tr>';
            }).join('');

            container.innerHTML = '' +
                '<div class="card">' +
                    '<div class="card-header"><h3><i class="fas fa-chart-bar"></i> Model Performance Comparison</h3>' + (perf.best_model ? '<span class="badge badge-positive"><i class="fas fa-crown"></i> Best: ' + perf.best_model + '</span>' : '') + '</div>' +
                    '<div class="table-container"><table class="perf-table"><thead><tr><th>Algorithm</th><th>Accuracy</th><th>Precision</th><th>Recall</th><th>F1</th><th>Train Time</th><th>Inference</th><th>Status</th><th>Actions</th></tr></thead><tbody>' + (rowsHtml || '<tr><td colspan="9" class="text-center text-muted">No training data available.</td></tr>') + '</tbody></table></div>' +
                '</div>';
        } catch (error) {
            container.innerHTML = '<div class="card"><div class="empty-state"><div class="empty-icon"><i class="fas fa-exclamation-triangle" style="color:var(--neu);"></i></div><h3>Error</h3><p>' + error.message + '</p></div>';
        }
    },

    async viewConfusionMatrix(algorithm) {
        try {
            var data = await API.getConfusionMatrix(algorithm);
            var content = document.getElementById('ml-tab-content');
            if (!content) return;
            content.innerHTML = '' +
                '<div class="card">' +
                    '<div class="card-header"><h3><i class="fas fa-th"></i> Confusion Matrix: ' + data.algorithm + '</h3><button class="btn btn-sm btn-outline" onclick="ADMIN.renderMLTab(\'performance\')"><i class="fas fa-arrow-left"></i> Back</button></div>' +
                    '<div class="table-container"><table><thead><tr><th>Actual \\\\ Predicted</th>' + data.labels.map(function(l) { return '<th>' + l + '</th>'; }).join('') + '</tr></thead><tbody>' + data.matrix.map(function(row, i) { return '<tr><td><strong>' + data.labels[i] + '</strong></td>' + row.map(function(val) { return '<td style="text-align:center;font-weight:600;font-family:var(--font-mono);">' + val + '</td>'; }).join('') + '</tr>'; }).join('') + '</tbody></table></div>' +
                '</div>';
        } catch (error) {
            showToast('Failed to load confusion matrix: ' + error.message, 'error');
        }
    },

    async downloadModel(algorithm) {
        try {
            await API.downloadModel(algorithm);
            showToast('Model downloaded!', 'success');
        } catch (error) {
            showToast('Download failed: ' + error.message, 'error');
        }
    },

    renderMLConfusion: function(container) {
        container.innerHTML = '' +
            '<div class="card">' +
                '<h3><i class="fas fa-th"></i> Confusion Matrix</h3>' +
                '<p class="form-desc">Select an algorithm to view its confusion matrix.</p>' +
                '<div class="form-inline mb-2">' +
                    '<select class="form-control" id="cm-algorithm" style="width:auto;"><option value="SVM">SVM</option><option value="Random Forest">Random Forest</option><option value="Naive Bayes">Naive Bayes</option><option value="BERT">BERT</option></select>' +
                    '<button class="btn btn-primary" onclick="ADMIN.viewConfusionMatrix(document.getElementById(\'cm-algorithm\').value)"><i class="fas fa-eye"></i> View</button>' +
                '</div>' +
                '<div id="cm-result"></div>' +
            '</div>';
    },

    async renderMLHistory(container) {
        container.innerHTML = '<div class="text-center mt-3"><div class="spinner"></div><p>Loading history...</p></div>';
        try {
            var models = await API.getModels();
            var rowsHtml = models.map(function(m) {
                return '<tr><td style="font-family:var(--font-mono);font-size:.72rem;">' + (m.id ? m.id.substring(0, 8) : 'N/A') + '...</td><td><strong>' + m.algorithm + '</strong></td><td><span class="badge badge-' + (m.status === 'completed' ? 'positive' : m.status === 'failed' ? 'negative' : 'neutral') + '">' + m.status + '</span></td><td>' + formatNumber(m.accuracy) + '</td><td>' + formatNumber(m.f1_score) + '</td><td style="font-family:var(--font-mono);font-size:.8rem;">' + (m.dataset_filename || 'N/A') + '</td><td>' + (m.is_production_model ? '<span class="badge badge-positive">Active</span>' : '<span class="badge badge-neutral">-</span>') + '</td><td style="font-family:var(--font-mono);font-size:.8rem;">' + formatDate(m.created_at) + '</td><td><button class="btn btn-sm btn-warning" onclick="ADMIN.rollbackModel(\'' + m.id + '\')" title="Set as production"><i class="fas fa-arrow-up"></i></button></td></tr>';
            }).join('');

            container.innerHTML = '' +
                '<div class="card">' +
                    '<div class="card-header"><h3><i class="fas fa-history"></i> Training History</h3></div>' +
                    '<div class="table-container"><table><thead><tr><th>ID</th><th>Algorithm</th><th>Status</th><th>Accuracy</th><th>F1</th><th>Dataset</th><th>Production</th><th>Date</th><th>Actions</th></tr></thead><tbody>' + (rowsHtml || '<tr><td colspan="9" class="text-center text-muted">No training history available.</td></tr>') + '</tbody></table></div>' +
                '</div>';
        } catch (error) {
            container.innerHTML = '<div class="card"><div class="empty-state"><div class="empty-icon"><i class="fas fa-exclamation-triangle" style="color:var(--neu);"></i></div><h3>Error</h3><p>' + error.message + '</p></div>';
        }
    },

    async rollbackModel(id) {
        if (!confirm('Set this model as the production model?')) return;
        showLoading('Rolling back...');
        try {
            await API.rollbackModel(id);
            showToast('Production model updated!', 'success');
            this.renderMLTab('history');
        } catch (error) {
            showToast('Rollback failed: ' + error.message, 'error');
        } finally {
            hideLoading();
        }
    },

    // ============================================================
    // IMPORT DATA TAB — Paper theme design
    // ============================================================
    renderImportPanel: function(container) {
        container.innerHTML = '' +
            '<div class="page-header"><div><span style="font-family:var(--font-mono);font-size:.7rem;letter-spacing:.12em;text-transform:uppercase;color:var(--ink-faint);display:block;margin-bottom:.35rem;">Bulk Import</span><h1>Import evaluations</h1></div></div>' +
            '<div class="upload-area" onclick="document.getElementById(\'import-file-inp\').click()">' +
                '<input type="file" id="import-file-inp" accept=".csv,.xlsx,.xls" class="hidden" onchange="ADMIN.handleImport(this.files[0])" />' +
                '<div class="upload-icon"><i class="fas fa-file-upload"></i></div>' +
                '<h4>Drop file here to import</h4>' +
                '<p>CSV or Excel. Required columns: category, comment, sentiment</p>' +
            '</div>' +
            '<div id="import-result" class="mt-2"></div>';
    },

    async handleImport(file) {
        if (!file) return;
        showLoading('Importing evaluations...');
        var resultDiv = document.getElementById('import-result');
        try {
            var result = await API.importEvaluations(file);
            var errorsHtml = '';
            if (result.errors && result.errors.length > 0) {
                errorsHtml = '<div class="mt-2"><h4 style="font-family:var(--font-mono);font-size:.72rem;letter-spacing:.06em;text-transform:uppercase;color:var(--neg);">Errors:</h4><div class="table-container" style="max-height:200px;overflow-y:auto;"><table><thead><tr><th>Row</th><th>Error</th></tr></thead><tbody>' + result.errors.map(function(e) { return '<tr><td>' + e.row + '</td><td>' + escapeHtml(e.errors ? e.errors.join(', ') : e.error) + '</td></tr>'; }).join('') + '</tbody></table></div>';
            }

            resultDiv.innerHTML = '' +
                '<div class="card" style="border-left:4px solid var(--pos);">' +
                    '<h4 style="color:var(--pos);"><i class="fas fa-check-circle"></i> Import Complete</h4>' +
                    '<div class="stats-grid mt-2" style="grid-template-columns:repeat(3,1fr);">' +
                        '<div class="stat-card"><div class="stat-icon blue"><i class="fas fa-file-alt"></i></div><div class="stat-info"><h3>' + result.total_rows + '</h3><p>Total Rows</p></div></div>' +
                        '<div class="stat-card"><div class="stat-icon green"><i class="fas fa-check-circle"></i></div><div class="stat-info"><h3>' + result.imported + '</h3><p>Imported</p></div></div>' +
                        '<div class="stat-card"><div class="stat-icon red"><i class="fas fa-times-circle"></i></div><div class="stat-info"><h3>' + result.failed + '</h3><p>Failed</p></div></div>' +
                    '</div>' +
                    errorsHtml +
                '</div>';
            showToast('Import completed successfully!', 'success');
        } catch (error) {
            resultDiv.innerHTML = '<div class="card" style="border-left:4px solid var(--neg);"><h4 style="color:var(--neg);"><i class="fas fa-times-circle"></i> Import Failed</h4><p>' + error.message + '</p></div>';
            showToast('Import failed: ' + error.message, 'error');
        } finally {
            hideLoading();
        }
    }
};
