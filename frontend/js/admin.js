/**
 * Asiatech Sentiment Analysis - Admin Module
 * Updated for "Asiatech Feedback Casefile" paper theme design.
 * Admin dashboard: responses table, analytics, ML training, data import, charts.
 * All data fetching, export, CRUD logic preserved.
 *
 * FIXES APPLIED (this version):
 * 1. Chart race condition — destroyCharts() was being called inside
 *    renderSentimentChart's setTimeout, which could wipe out the
 *    Model Performance chart if its timeout fired first. Charts are
 *    now destroyed exactly once, before either chart is (re)drawn.
 * 2. "By Department" bar colors were hardcoded by category name
 *    (Faculty=green, Staff=yellow, Facilities/Payment=red) regardless
 *    of actual sentiment. That bar only ever showed volume, not
 *    sentiment, so the colors were misleading. It's now a single
 *    neutral color, and each row is labeled "n evaluations" so it's
 *    clear this is a count, not a sentiment score.
 * 3. Added small "source" captions under Overview cards so it's clear
 *    where each number/chart comes from (which API endpoint / what
 *    it's counting), since that was the root of the "confusing" complaint.
 * 4. DATA-LINEAGE LABELING — the dashboard silently mixed two unrelated
 *    data sources on one screen: (a) live evaluation-form submissions,
 *    all-time, from the evaluations/predictions tables, and (b) ML
 *    training-run metrics, per-algorithm latest run, from the model
 *    training history table. Neither updates the other. A student
 *    submitting more evaluations does not change Model Performance;
 *    retraining a model does not retroactively change past students'
 *    recorded predictions. Both the Overview and Analytics tabs now
 *    have explicit section banners ("Live Submission Data" vs "Latest
 *    Model Training Results") plus precise per-widget captions stating
 *    exactly what's counted and over what time range.
 * 5. BULK DELETE — the Responses tab only supported deleting one
 *    evaluation at a time. Each row now has a selection checkbox, plus
 *    a "select all on this page" header checkbox, and a bulk-action
 *    toolbar that appears once at least one row is selected, letting
 *    admins delete many responses in a single confirmed action via
 *    POST /evaluation/bulk-delete. Selection persists across page/filter
 *    changes within the Responses tab so a multi-page cleanup doesn't
 *    lose progress, and is cleared after a successful delete or when the
 *    admin navigates away from the tab.
 */

var ADMIN = {
    currentUser: null,
    charts: {},
    currentPage: 1,
    // Ids of evaluations currently checked in the Responses table.
    // Persists across page/filter changes so an admin can select rows
    // on page 1, flip to page 2, and still bulk-delete both batches
    // together. Cleared on tab entry and after a successful delete.
    selectedIds: new Set(),

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
            if (result.user.role !== 'administrator') {
                showToast('This login is for administrators only.', 'warning');
                API.clearAuth();
                hideLoading();
                return;
            }
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
            var perfRows = filterModelPerfRows(perf.rows);

            // "By Department" = total evaluation COUNT per category, from
            // GET /analytics/category?category=X (the .breakdown.total field).
            // This is a volume chart, not a sentiment chart — see fix #2 note above.
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
                // FIX: color no longer depends on category name (was always
                // green for Faculty, yellow for Staff, red for Facilities/
                // Payment regardless of real sentiment). Single neutral fill
                // since this bar represents COUNT, not sentiment.
                var fillClass = r.total === 0 ? '' : 'vol';
                var displayLabel = r.label === 'Payment' ? 'Payments' : r.label;
                return '<div class="ledger-row"><span class="label">' + displayLabel + '</span><div class="ledger-track"><div class="ledger-fill ' + fillClass + '" style="width:' + pct + '%"></div></div><span class="pct">' + r.total + '</span></div>';
            }).join('');

            container.innerHTML = '' +
                '<div class="page-header">' +
                    '<div>' +
                        '<span style="font-family:var(--font-mono);font-size:.7rem;letter-spacing:.12em;text-transform:uppercase;color:var(--ink-faint);display:block;margin-bottom:.35rem;">Casefile Overview — All Departments</span>' +
                        '<h1>Dashboard Overview</h1>' +
                    '</div>' +
                    '<div class="date-note">Compiled ' + new Date().toLocaleDateString('en-US',{month:'long',day:'numeric',year:'numeric'}) + '</div>' +
                '</div>' +
                '<div class="data-lineage-banner" style="font-family:var(--font-mono);font-size:.68rem;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-faint);background:var(--paper-alt,#f1f1ec);border:1px dashed var(--paper-line);padding:.4rem .6rem;margin-bottom:.75rem;">' +
                    '<i class="fas fa-database"></i>&nbsp; Live Submission Data <span style="opacity:.6;">— every card and chart below, up to and including the "Model Performance" table row for status, reflects ALL evaluation-form submissions ever received (not filtered by dataset or date), except where noted.</span>' +
                '</div>' +
                '<div class="stats-grid">' +
                    '<div class="stat-card"><div class="stat-icon green"><i class="fas fa-smile"></i></div><div class="stat-info"><h3>' + (overall.breakdown.positive || 0) + '</h3><p>Positive Feedbacks</p><small>' + (overall.breakdown.positive_pct ? overall.breakdown.positive_pct.toFixed(1) + '%' : '') + '</small><small class="source-note" style="display:block;font-family:var(--font-mono);font-size:.62rem;color:var(--ink-faint);margin-top:.15rem;">All-time, all submissions</small></div></div>' +
                    '<div class="stat-card"><div class="stat-icon yellow"><i class="fas fa-meh"></i></div><div class="stat-info"><h3>' + (overall.breakdown.neutral || 0) + '</h3><p>Neutral Feedbacks</p><small>' + (overall.breakdown.neutral_pct ? overall.breakdown.neutral_pct.toFixed(1) + '%' : '') + '</small><small class="source-note" style="display:block;font-family:var(--font-mono);font-size:.62rem;color:var(--ink-faint);margin-top:.15rem;">All-time, all submissions</small></div></div>' +
                    '<div class="stat-card"><div class="stat-icon red"><i class="fas fa-frown"></i></div><div class="stat-info"><h3>' + (overall.breakdown.negative || 0) + '</h3><p>Negative Feedbacks</p><small>' + (overall.breakdown.negative_pct ? overall.breakdown.negative_pct.toFixed(1) + '%' : '') + '</small><small class="source-note" style="display:block;font-family:var(--font-mono);font-size:.62rem;color:var(--ink-faint);margin-top:.15rem;">All-time, all submissions</small></div></div>' +
                    '<div class="stat-card"><div class="stat-icon blue"><i class="fas fa-file-alt"></i></div><div class="stat-info"><h3>' + (overall.evaluation_volume || 0) + '</h3><p>Total Evaluations</p><small class="source-note" style="display:block;font-family:var(--font-mono);font-size:.62rem;color:var(--ink-faint);margin-top:.15rem;">All-time count of submitted evaluation forms</small></div></div>' +
                    '<div class="stat-card"><div class="stat-icon purple"><i class="fas fa-chart-bar"></i></div><div class="stat-info"><h3>' + (overall.average_confidence ? (overall.average_confidence * 100).toFixed(1) + '%' : 'N/A') + '</h3><p>Avg Confidence</p><small class="source-note" style="display:block;font-family:var(--font-mono);font-size:.62rem;color:var(--ink-faint);margin-top:.15rem;">Avg. of each submission\'s prediction confidence at time of submission</small></div></div>' +
                '</div>' +
                '<div class="two-col">' +
                    '<div>' +
                        '<div class="chart-card" style="margin-bottom:1.1rem;">' +
                            '<h3><i class="fas fa-chart-pie"></i> Sentiment Distribution</h3>' +
                            '<p class="source-note" style="font-family:var(--font-mono);font-size:.7rem;color:var(--ink-faint);margin:.15rem 0 .6rem;">All evaluation-form submissions ever received, classified positive / neutral / negative at the time each was submitted.' +
                            '<div class="chart-container"><canvas id="chart-sentiment-overview"></canvas></div>' +
                        '</div>' +
                        '<div class="chart-card">' +
                            '<h3><i class="fas fa-chart-bar"></i> Model Performance Comparison</h3>' +
                            '<p class="source-note" style="font-family:var(--font-mono);font-size:.7rem;color:var(--ink-faint);margin:.15rem 0 .6rem;"><strong>Not submission data.</strong> Accuracy &amp; F1 score measured on the held-out test split from each algorithm\'s most recent training run — one bar pair per algorithm\'s latest run, independent of how many students have submitted evaluations since.' +
                            '<div class="chart-container"><canvas id="chart-model-perf"></canvas></div>' +
                        '</div>' +
                    '</div>' +
                    '<div>' +
                        '<div class="card" style="margin-bottom:1.1rem;">' +
                            '<div class="card-header"><h3><i class="fas fa-chart-bar"></i> By Department</h3></div>' +
                            '<p class="source-note" style="font-family:var(--font-mono);font-size:.7rem;color:var(--ink-faint);margin:.15rem 0 .6rem;">Number of evaluation forms received per department, all-time (volume only — not a sentiment score)' +
                            '<div class="ledger-bars">' + ledgerRowsHtml + '</div>' +
                        '</div>' +
                        '<div class="card">' +
                            '<div class="card-header"><h3><i class="fas fa-table"></i> Model Performance</h3></div>' +
                            '<p class="source-note" style="font-family:var(--font-mono);font-size:.7rem;color:var(--ink-faint);margin:.15rem 0 .6rem;"><strong>Not submission data.</strong> One row per model showing metrics from that model\'s most recent training run only (not combined across datasets or runs).</p>' +
                            '<div class="table-container"><table class="perf-table"><thead><tr><th>Model</th><th>Accuracy</th><th>Precision</th><th>Recall</th><th>F1-Score</th></tr></thead><tbody>' +
                                perfRows.map(function(r) {
                                    return '<tr><td><strong>' + modelPerfDisplayName(r.algorithm) + '</strong></td><td>' + formatNumber(r.accuracy) + '</td><td>' + formatNumber(r.precision) + '</td><td>' + formatNumber(r.recall) + '</td><td>' + formatNumber(r.f1_score) + '</td></tr>';
                                }).join('') +
                                (perfRows.length === 0 ? '<tr><td colspan="5" class="text-center text-muted">No training data available.</td></tr>' : '') +
                            '</tbody></table></div>' +
                        '</div>' +
                    '</div>' +
                '</div>';

            // FIX #1: destroy all existing charts exactly once, before
            // (re)drawing either chart. Previously destroyCharts() lived
            // inside renderSentimentChart's own setTimeout, so whichever
            // chart's 100ms timer fired second could wipe out the chart
            // that had just been drawn by the other timer — a race
            // condition that made the bar chart randomly vanish.
            this.destroyCharts();
            this.renderSentimentChart(overall.breakdown);
            this.renderModelPerfChart(perfRows);
        } catch (error) {
            container.innerHTML = '<div class="page-header"><h1>Dashboard Overview</h1></div><div class="card"><div class="empty-state"><div class="empty-icon"><i class="fas fa-database"></i></div><h3>No Data Available</h3><p>' + error.message + '</p></div></div>';
        }
    },

    renderSentimentChart: function(breakdown) {
        setTimeout(function() {
            var ctx = document.getElementById('chart-sentiment-overview');
            if (!ctx) return;
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
                data: { labels: rows.map(function(r) { return modelPerfDisplayName(r.algorithm); }), datasets: [{ label: 'Accuracy', data: rows.map(function(r) { return r.accuracy || 0; }), backgroundColor: '#2b3a67' }, { label: 'F1 Score', data: rows.map(function(r) { return r.f1_score || 0; }), backgroundColor: '#b7791f' }] },
                options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true, max: 1 } }, plugins: { legend: { position: 'bottom' } } }
            });
        }, 100);
    },

    // ============================================================
    // RESPONSES TAB — Paper theme design
    // ============================================================
        async renderResponses(container) {
        // Fresh entry into the tab starts with a clean selection.
        this.selectedIds = new Set();

        container.innerHTML = '' +
            '<div class="page-header">' +
                '<div>' +
                    '<span style="font-family:var(--font-mono);font-size:.7rem;letter-spacing:.12em;text-transform:uppercase;color:var(--ink-faint);display:block;margin-bottom:.35rem;">Full Transcript</span>' +
                    '<h1>Every entry, logged</h1>' +
                '</div>' +
                '<div style="display:flex;gap:0.5rem;flex-wrap:wrap;">' +
                    '<button class="btn btn-secondary" onclick="ADMIN.openImportPanel()"><i class="fas fa-file-import"></i> Import Dataset</button>' +
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
                '<label style="display:flex;align-items:center;gap:.4rem;font-size:.82rem;white-space:nowrap;flex-shrink:0;">' +
                    '<input type="checkbox" id="filter-needs-review" /> Needs Review only' +
                '</label>' +
                '<input type="text" class="form-control" id="filter-search" placeholder="Search by student ID, course, strengths..." style="flex:1;min-width:200px;" />' +
                '<button class="btn btn-primary" onclick="ADMIN.loadResponses()"><i class="fas fa-search"></i> Search</button>' +
                '<button class="btn btn-secondary" onclick="ADMIN.resetFilters()"><i class="fas fa-undo"></i> Reset</button>' +
            '</div>' +
            '<div id="bulk-actions-bar" class="hidden" style="display:none;align-items:center;gap:0.75rem;background:var(--paper-alt,#f1f1ec);border:1px solid var(--paper-line);padding:.5rem .75rem;margin-bottom:.75rem;">' +
                '<span id="bulk-selected-count" style="font-family:var(--font-mono);font-size:.78rem;color:var(--ink-faint);"></span>' +
                '<button class="btn btn-sm btn-danger" onclick="ADMIN.bulkDeleteSelected()"><i class="fas fa-trash"></i> Delete Selected</button>' +
                '<button class="btn btn-sm btn-secondary" onclick="ADMIN.clearSelection()"><i class="fas fa-times"></i> Clear Selection</button>' +
            '</div>' +
            '<div id="responses-loading" class="text-center mt-3 hidden"><div class="spinner"></div><p>Loading responses...</p></div>' +
            '<div id="responses-table-container"></div>' +
            '<div id="responses-pagination" class="pagination"></div>';

        document.getElementById('filter-category').addEventListener('change', function() { ADMIN.currentPage = 1; ADMIN.loadResponses(); });
        document.getElementById('filter-search').addEventListener('input', debounce(function() { ADMIN.currentPage = 1; ADMIN.loadResponses(); }, 500));
        document.getElementById('filter-needs-review').addEventListener('change', function() { ADMIN.currentPage = 1; ADMIN.loadResponses(); });
        this.loadResponses();
    },
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

    // ------------------------------------------------------------
    // Multi-select helpers for bulk delete
    // ------------------------------------------------------------

    updateBulkBar: function() {
        var bar = document.getElementById('bulk-actions-bar');
        var countEl = document.getElementById('bulk-selected-count');
        if (!bar || !countEl) return;
        var n = this.selectedIds.size;
        if (n > 0) {
            bar.classList.remove('hidden');
            bar.style.display = 'flex';
            countEl.textContent = n + ' selected';
        } else {
            bar.classList.add('hidden');
            bar.style.display = 'none';
        }
        var selectAllBox = document.getElementById('select-all-checkbox');
        if (selectAllBox) {
            var rowBoxes = document.querySelectorAll('.row-select-checkbox');
            var allChecked = rowBoxes.length > 0 && Array.prototype.every.call(rowBoxes, function(cb) { return cb.checked; });
            selectAllBox.checked = allChecked;
        }
    },

    toggleRowSelect: function(id, checked) {
        if (checked) {
            this.selectedIds.add(id);
        } else {
            this.selectedIds.delete(id);
        }
        this.updateBulkBar();
    },

    toggleSelectAll: function(checked) {
        var rowBoxes = document.querySelectorAll('.row-select-checkbox');
        rowBoxes.forEach(function(cb) {
            cb.checked = checked;
            if (checked) {
                ADMIN.selectedIds.add(cb.dataset.id);
            } else {
                ADMIN.selectedIds.delete(cb.dataset.id);
            }
        });
        this.updateBulkBar();
    },

    clearSelection: function() {
        this.selectedIds = new Set();
        document.querySelectorAll('.row-select-checkbox').forEach(function(cb) { cb.checked = false; });
        this.updateBulkBar();
    },

    async bulkDeleteSelected() {
        var ids = Array.from(this.selectedIds);
        if (ids.length === 0) return;
        var confirmMsg = ids.length === 1
            ? 'Are you sure you want to permanently delete this evaluation? This action cannot be undone.'
            : 'Are you sure you want to permanently delete these ' + ids.length + ' evaluations? This action cannot be undone.';
        if (!confirm(confirmMsg)) return;

        showLoading('Deleting ' + ids.length + ' evaluation(s)...');
        try {
            var result = await API.bulkDeleteEvaluations(ids);
            var msg = result.deleted_count + ' evaluation(s) deleted.';
            if (result.not_found && result.not_found.length > 0) {
                msg += ' ' + result.not_found.length + ' were already gone (skipped).';
            }
            showToast(msg, 'success');
            this.selectedIds = new Set();
            this.loadResponses();
        } catch (error) {
            showToast('Bulk delete failed: ' + error.message, 'error');
        } finally {
            hideLoading();
        }
    },

         async loadResponses() {
        var needsReview = document.getElementById('filter-needs-review') ? document.getElementById('filter-needs-review').checked : false;
        var category = document.getElementById('filter-category') ? document.getElementById('filter-category').value : '';
        var search = document.getElementById('filter-search') ? document.getElementById('filter-search').value : '';
        var loading = document.getElementById('responses-loading');
        var tableContainer = document.getElementById('responses-table-container');
        var pagination = document.getElementById('responses-pagination');

        if (loading) loading.classList.remove('hidden');
        if (tableContainer) tableContainer.innerHTML = '';

        try {
            var data = await API.getEvaluations({ category: this.getCategoryApiValue(category), page: this.currentPage, page_size: 20, has_submission: true, needs_review: needsReview });
            var items = Array.isArray(data.items) ? data.items : [];
        
            if (search) {
                var q = search.toLowerCase();
                items = items.filter(function(item) {
                    var si = ADMIN.getStudentInfo(item);
                                        var searchFields = [
                        (si.student_id || ''),
                        (si.course || ''),
                        (si.year_level || ''),
                        (item.share_your_thoughts || ''),
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
                    var thoughts = item.share_your_thoughts || '';
                    var categoryDisplay = ADMIN.getCategoryDisplayName(item.category);
                    var badgeClass = ADMIN.getCategoryBadgeClass(item.category);
                    var commentsRaw = thoughts;
                    var commentsDisplay = commentsRaw
                        ? escapeHtml(commentsRaw.length > 180 ? commentsRaw.substring(0, 180) + '...' : commentsRaw)
                        : '<span class="text-muted">N/A</span>';
                    var isChecked = ADMIN.selectedIds.has(item.id);
                    return '<tr>' +
                        '<td><input type="checkbox" class="row-select-checkbox" data-id="' + item.id + '" ' + (isChecked ? 'checked' : '') + ' onchange="ADMIN.toggleRowSelect(\'' + item.id + '\', this.checked)" /></td>' +
                        '<td style="font-family:var(--font-mono);font-size:.72rem;color:var(--ink-faint);">' + rowNum + '</td>' +
                        '<td>' + escapeHtml(si.student_id || 'N/A') + '</td>' +
                        '<td>' + escapeHtml(si.course || 'N/A') + '</td>' +
                        '<td>' + escapeHtml(si.year_level || 'N/A') + '</td>' +
                        '<td><span class="badge badge-' + badgeClass + '">' + escapeHtml(categoryDisplay) + '</span></td>' +
                        '<td style="white-space:nowrap;">' + sentimentBadge(item.sentiment) + '</td>' +
                        '<td style="max-width:320px;overflow:hidden;text-overflow:ellipsis;white-space:pre-line;" title="' + escapeHtml(commentsRaw) + '">' + commentsDisplay + '</td>' +
                        '<td style="font-family:var(--font-mono);font-size:.8rem;white-space:nowrap;">' + formatDate(item.created_at) + '</td>' +
                        '<td style="white-space:nowrap;">' +
                            '<button class="btn btn-sm btn-primary" onclick="ADMIN.viewEval(\'' + item.id + '\')" title="View Complete Evaluation"><i class="fas fa-eye"></i></button> ' +
                            '<button class="btn btn-sm btn-danger" onclick="ADMIN.deleteEval(\'' + item.id + '\')" title="Delete"><i class="fas fa-trash"></i></button>' +
                        '</td></tr>';
                }).join('');

                if (tableContainer) tableContainer.innerHTML = '<div class="table-container"><table>' +
                    '<thead><tr><th><input type="checkbox" id="select-all-checkbox" onchange="ADMIN.toggleSelectAll(this.checked)" title="Select all on this page" /></th><th>#</th><th>Student ID</th><th>Course</th><th>Year Level</th><th>Category</th><th>Sentiment</th><th style="max-width:320px;">Comments</th><th style="white-space:nowrap;">Date</th><th style="white-space:nowrap;">Actions</th></tr></thead>' +
                    '<tbody>' + rows + '</tbody></table></div>';
            }

            // Reflect current selection state (e.g. after navigating back
            // to a page whose rows were previously checked).
            this.updateBulkBar();

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

        // ------------------------------------------------------------
    // RESPONSES TAB — Import Dataset (Google Form export)
    // ------------------------------------------------------------

    openImportPanel: function() {
        var html = '' +
            '<div style="margin-bottom:1rem;">' +
                '<p style="font-size:.88rem;color:var(--ink-soft);">Import a compiled spreadsheet of student responses — e.g. the Excel/CSV export of your Google Form — instead of typing them in one by one. This bulk-loads them exactly as if each student had submitted the live form.</p>' +
            '</div>' +
            '<div class="form-group">' +
                '<label for="import-category-select"><i class="fas fa-list"></i> Which form is this file from?</label>' +
                '<select class="form-control" id="import-category-select">' +
                    '<option value="">Auto-detect (combined files accepted too)</option>' +
                    '<option value="Faculty">Professor / Faculty Evaluation</option>' +
                    '<option value="Staff">Staff Evaluation</option>' +
                    '<option value="Facilities">Facilities Evaluation</option>' +
                    '<option value="Payment">Payments Evaluation</option>' +
                '</select>' +
            '</div>' +
            '<div style="background:var(--paper-alt,#f1f1ec);border:1px dashed var(--paper-line);padding:.75rem .9rem;margin-bottom:1rem;font-size:.82rem;line-height:1.65;">' +
                '<strong style="font-family:var(--font-mono);font-size:.68rem;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-faint);display:block;margin-bottom:.4rem;"><i class="fas fa-circle-info"></i> Column checklist for this file</strong>' +
                '<ul style="margin-left:1.1rem;">' +
                    '<li><strong>Required:</strong> a column with the student\'s open-ended answer — header should contain a word like "thoughts", "comment", or "feedback".</li>' +
                    '<li><strong>Recommended:</strong> Student ID, Course, Year Level — if included, these show up on the response the same as a normal submission. Leave a row\'s Student ID blank to import it anonymously.</li>' +
                    '<li><strong>Faculty only:</strong> a column naming the professor evaluated.</li>' +
                    '<li><strong>Rating questions</strong> (the 1–5 scale questions) — keep Google Forms\' original question text as the column header; they\'re matched automatically.</li>' +
                    '<li style="color:var(--neg);"><strong>Leave Sentiment out entirely.</strong> The system always calculates Positive / Neutral / Negative itself — a Sentiment column in your file is ignored, never read.</li>' +
                    '<li>Accepted files: <strong>.csv, .xlsx, .xls</strong>. Use <strong>Auto-detect</strong>: a single-category export (one Google Form) is detected and imported into that category, while a combined multi-category file (columns prefixed Staff_ / Professor_ / Facilities_ / Payments_*) expands each spreadsheet row into up to four evaluations. Picking a specific category is only needed for single-category files.</li>' +
                '</ul>' +
            '</div>' +
            '<div class="upload-area" onclick="document.getElementById(\'import-resp-file-inp\').click()">' +
                '<input type="file" id="import-resp-file-inp" accept=".csv,.xlsx,.xls" class="hidden" onchange="ADMIN.handleResponsesImport(this.files[0])" />' +
                '<div class="upload-icon"><i class="fas fa-cloud-upload-alt"></i></div>' +
                '<h4>Click to choose your file</h4>' +
                '<p>Or drag it here</p>' +
            '</div>' +
            '<div id="import-resp-result" class="mt-2"></div>';
        APP.openModal(html);
    },

    async handleResponsesImport(file) {
        if (!file) return;
        var catSelect = document.getElementById('import-category-select');
        var category = catSelect ? catSelect.value : '';
        var resultDiv = document.getElementById('import-resp-result');
        var categoryLabel = category ? category + ' ' : '';
        showLoading('Importing ' + categoryLabel + 'responses — this can take a moment while each one is scored...');
        try {
            var result = await API.importEvaluations(file, category);
            var errorsHtml = '';
            if (result.errors && result.errors.length > 0) {
                errorsHtml = '<div class="mt-2">' +
                    '<h4 style="font-family:var(--font-mono);font-size:.72rem;letter-spacing:.06em;text-transform:uppercase;color:var(--neg);">Rows skipped:</h4>' +
                    '<div class="table-container" style="max-height:220px;overflow-y:auto;"><table><thead><tr><th>Row</th><th>Preview</th><th>Reason</th></tr></thead><tbody>' +
                    result.errors.map(function(e) {
                        return '<tr><td>' + e.row + '</td><td>' + escapeHtml(e.comment || '') + '</td><td>' + escapeHtml((e.errors || []).join('; ')) + '</td></tr>';
                    }).join('') +
                    '</tbody></table></div></div>';
            }
            resultDiv.innerHTML = '' +
                '<div class="card" style="border-left:4px solid var(--pos);">' +
                    '<h4 style="color:var(--pos);"><i class="fas fa-check-circle"></i> Import Complete</h4>' +
                    '<div class="stats-grid mt-2" style="grid-template-columns:repeat(3,1fr);">' +
                        '<div class="stat-card"><div class="stat-icon blue"><i class="fas fa-file-alt"></i></div><div class="stat-info"><h3>' + result.total_rows + '</h3><p>Total Rows</p></div></div>' +
                        '<div class="stat-card"><div class="stat-icon green"><i class="fas fa-check-circle"></i></div><div class="stat-info"><h3>' + result.imported + '</h3><p>Imported</p></div></div>' +
                        '<div class="stat-card"><div class="stat-icon red"><i class="fas fa-times-circle"></i></div><div class="stat-info"><h3>' + result.failed + '</h3><p>Skipped</p></div></div>' +
                    '</div>' +
                    errorsHtml +
                    '<button class="btn btn-primary mt-2" onclick="APP.closeModal();ADMIN.loadResponses();"><i class="fas fa-table"></i> View in Responses</button>' +
                '</div>';
            showToast(result.imported + ' response(s) imported and scored.', 'success');
        } catch (error) {
            resultDiv.innerHTML = '<div class="card" style="border-left:4px solid var(--neg);"><h4 style="color:var(--neg);"><i class="fas fa-times-circle"></i> Import Failed</h4><p>' + escapeHtml(error.message) + '</p></div>';
            showToast('Import failed: ' + error.message, 'error');
        } finally {
            hideLoading();
        }
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
            var thoughts = item.share_your_thoughts || '';
            var categoryDisplay = this.getCategoryDisplayName(item.category);
            var badgeClass = this.getCategoryBadgeClass(item.category);
            var mismatchHtml = '';
            if (item.is_mismatch) {
            mismatchHtml = '<div class="form-section" style="margin-top:1rem;border-left:3px solid var(--neu, #b7791f);padding-left:.75rem;">' +
            '<h4 style="color:var(--neu, #b7791f);"><i class="fas fa-triangle-exclamation"></i> Likert / Sentiment Mismatch</h4>' +
            '<p style="font-size:.85rem;">Type: <strong>' + escapeHtml((item.mismatch_type || '').replace(/_/g, ' ')) + '</strong></p>' +
        '<p style="font-size:.8rem;color:var(--ink-faint);">The numeric ratings and the written comment\'s sentiment point in different directions for this submission — worth a closer read.</p>' +
    '</div>';
}
            var ratingsHtml = '';
            var ratingKeys = Object.keys(ratings);
            if (ratingKeys.length > 0) {
                var ratingRows = ratingKeys.map(function(k) {
                    var label = k.replace(/_/g, ' ').replace(/\b\w/g, function(l) { return l.toUpperCase(); });
                    return '<tr><td>' + escapeHtml(label) + '</td><td><strong>' + ratings[k] + '/5</strong></td></tr>';
                }).join('');
                ratingsHtml = '<div class="form-section" style="margin-top:1rem;"><h4 style="margin-bottom:0.5rem;">Quantitative Ratings</h4><div class="table-container"><table><thead><tr><th>Aspect</th><th>Rating</th></tr></thead><tbody>' + ratingRows + '</tbody></table></div>';

                if (item.likert_sentiment || item.likert_average != null) {
                    ratingsHtml += '<div class="modal-row" style="margin-top:0.75rem;">' +
                        '<div class="modal-field"><label>Likert Sentiment</label><p>' + (item.likert_sentiment ? sentimentBadge(item.likert_sentiment) : '<span class="text-muted">N/A</span>') + '</p></div>' +
                        '<div class="modal-field"><label>Likert Average</label><p>' + (item.likert_average != null ? '<strong>' + item.likert_average + '/5</strong>' : '<span class="text-muted">N/A</span>') + '</p></div>' +
                    '</div></div>';
                } else {
                    ratingsHtml += '</div>';
                }
            }

            var predictionHtml = '';
            var pred = item.prediction || null;
            if (pred) {
                var modelRows = [
                    { label: 'XGBoost', pred: pred.xgb_prediction, conf: pred.xgb_confidence },
                    { label: 'DeBERTa', pred: pred.deberta_prediction, conf: pred.deberta_confidence },
                    { label: 'RoBERTa', pred: pred.roberta_prediction, conf: pred.roberta_confidence }
                ].map(function(m) {
                    var isOfficial = pred.algorithm_used === m.label;
                    return '<tr>' +
                        '<td><strong>' + m.label + '</strong> ' + (isOfficial ? '<span class="badge badge-positive" title="Used for the official sentiment"><i class="fas fa-crown"></i> Official</span>' : '') + '</td>' +
                        '<td>' + (m.pred ? sentimentBadge(m.pred) : '<span class="text-muted">N/A</span>') + '</td>' +
                        '<td style="white-space:nowrap;">' + sentimentBadge(item.sentiment) + 
                        (item.is_mismatch ? ' <span class="badge badge-warning" title="Likert/Text sentiment disagree: ' + escapeHtml(item.mismatch_type || '') + '"><i class="fas fa-triangle-exclamation"></i></span>' : '') +
'</td>' +
                        '<td>' + (m.conf != null ? (m.conf * 100).toFixed(1) + '%' : '<span class="text-muted">N/A</span>') + '</td>' +
                    '</tr>';
                }).join('');

                predictionHtml = '<div class="form-section" style="margin-top:1rem;">' +
                    '<h4 style="margin-bottom:0.5rem;">Text Sentiment — Model Breakdown</h4>' +
                    '<div class="table-container"><table><thead><tr><th>Model</th><th>Prediction</th><th>Confidence</th></tr></thead><tbody>' + modelRows + '</tbody></table></div>' +
                    (pred.algorithm_used === 'XGBoost + DeBERTa + RoBERTa' && pred.ensemble_prediction
                        ? '<p style="font-size:.8rem;color:var(--ink-faint);margin-top:.5rem;"><i class="fas fa-info-circle"></i> Official result is the weighted ensemble of all three models above (' + (pred.ensemble_confidence != null ? (pred.ensemble_confidence * 100).toFixed(1) + '%' : 'N/A') + ' confidence).</p>'
                        : '') +
                '</div>';
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
                '<div class="modal-field" style="margin-bottom:0.75rem;"><label>Category</label><p><span class="badge badge-' + badgeClass + '">' + escapeHtml(categoryDisplay) + '</span></p></div>' +
mismatchHtml +
ratingsHtml +
predictionHtml +
                                '<div style="margin-top:1rem;">' +
                    '<div style="background:var(--paper-alt,#f1f1ec);padding:0.75rem;border:1px solid var(--paper-line);">' +
                        '<h4 style="font-family:var(--font-mono);font-size:.7rem;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-faint);margin-bottom:.3rem;"><i class="fas fa-comment-dots"></i> Share Your Thoughts</h4>' +
                        '<p style="font-size:.85rem;white-space:pre-wrap;">' + (thoughts ? escapeHtml(thoughts) : '<span class="text-muted">No response provided.</span>') + '</p>' +
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
            this.selectedIds.delete(id);
            showToast('Evaluation deleted successfully.', 'success');
            this.loadResponses();
        } catch (error) {
            showToast('Delete failed: ' + error.message, 'error');
        } finally {
            hideLoading();
        }
    },

    // ============================================================
    // EXPORTS
    // ============================================================
    async exportCSV() {
        showLoading('Exporting CSV...');
        try {
            await API.exportCsv();
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
                        var headers = [
                'Student ID', 'Course', 'Year Level', 'Category',
                'Share Your Thoughts', 'Ratings (avg)',
                'Likert Sentiment', 'Likert Average', 'Text Sentiment', 'Official Confidence',
                'XGB Prediction', 'XGB Confidence', 'DeBERTa Prediction', 'DeBERTa Confidence',
                'RoBERTa Prediction', 'RoBERTa Confidence', 'Date Submitted'
            ];
            var aoa = [headers];
            items.forEach(function(item) {
                var si = ADMIN.getStudentInfo(item);
                var ratingVals = item.ratings ? Object.values(item.ratings) : [];
                var ratingAvg = ratingVals.length > 0
                    ? (ratingVals.reduce(function(a, b) { return a + b; }, 0) / ratingVals.length).toFixed(2)
                    : '';
                var pred = item.prediction || {};
                                aoa.push([
                    si.student_id || '',
                    si.course || '',
                    si.year_level || '',
                    ADMIN.getCategoryDisplayName(item.category),
                    item.share_your_thoughts || '',
                    ratingAvg,
                    item.likert_sentiment || '',
                    item.likert_average != null ? item.likert_average : '',
                    item.sentiment || '',
                    pred.confidence_score != null ? pred.confidence_score : '',
                    pred.xgb_prediction || '',
                    pred.xgb_confidence != null ? pred.xgb_confidence : '',
                    pred.deberta_prediction || '',
                    pred.deberta_confidence != null ? pred.deberta_confidence : '',
                    pred.roberta_prediction || '',
                    pred.roberta_confidence != null ? pred.roberta_confidence : '',
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
            '<div class="data-lineage-banner" style="font-family:var(--font-mono);font-size:.68rem;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-faint);background:var(--paper-alt,#f1f1ec);border:1px dashed var(--paper-line);padding:.4rem .6rem;margin-bottom:.75rem;">' +
                '<i class="fas fa-database"></i>&nbsp; Live Submission Data <span style="opacity:.6;">— every section on this tab is drawn from evaluation-form submissions, all-time. Nothing here reflects ML training runs.</span>' +
            '</div>' +
            '<div class="stats-grid" style="grid-template-columns:repeat(auto-fit,minmax(220px,1fr));">' +
                '<div class="stat-card"><div class="stat-icon green"><i class="fas fa-chart-line"></i></div><div class="stat-info"><h3 id="ana-pos-pct">-</h3><p>Positive Rate</p><small class="source-note" style="display:block;font-family:var(--font-mono);font-size:.62rem;color:var(--ink-faint);margin-top:.15rem;">All-time, all submissions</small></div></div>' +
                '<div class="stat-card"><div class="stat-icon blue"><i class="fas fa-file-alt"></i></div><div class="stat-info"><h3 id="ana-total">-</h3><p>Total Entries</p><small class="source-note" style="display:block;font-family:var(--font-mono);font-size:.62rem;color:var(--ink-faint);margin-top:.15rem;">All-time count of submitted evaluation forms</small></div></div>' +
                '<div class="stat-card"><div class="stat-icon yellow"><i class="fas fa-bullseye"></i></div><div class="stat-info"><h3 id="ana-confidence">-</h3><p>Model Confidence</p><small class="source-note" style="display:block;font-family:var(--font-mono);font-size:.62rem;color:var(--ink-faint);margin-top:.15rem;">Avg. of each submission\'s prediction confidence at time of submission</small></div></div>' +
            '</div>' +
            '<div class="chart-grid">' +
                '<div class="chart-card"><h3><i class="fas fa-chart-line"></i> Monthly Trend</h3><p class="source-note" style="font-family:var(--font-mono);font-size:.68rem;color:var(--ink-faint);margin:.15rem 0 .5rem;">Evaluation-form submissions grouped by the month they were submitted, all-time.</p><div class="chart-container"><canvas id="chart-monthly-trend"></canvas></div></div>' +
                '<div class="chart-card"><h3><i class="fas fa-chart-bar"></i> Sentiment by Category</h3><p class="source-note" style="font-family:var(--font-mono);font-size:.68rem;color:var(--ink-faint);margin:.15rem 0 .5rem;">Evaluation-form submissions grouped by department category, all-time.</p><div class="chart-container"><canvas id="chart-category-sentiment"></canvas></div></div>' +
            '</div>' +
            '<div class="two-col">' +
                '<div class="card"><div class="card-header"><h3><i class="fas fa-exclamation-circle"></i> Top Complaints</h3></div><p class="source-note" style="font-family:var(--font-mono);font-size:.68rem;color:var(--ink-faint);margin:.15rem .75rem .5rem;">Highest-confidence Negative comments, all-time, drawn verbatim from submitted evaluations.</p><div id="top-complaints-list"></div></div>' +
                '<div class="card"><div class="card-header"><h3><i class="fas fa-star"></i> Top Appreciations</h3></div><p class="source-note" style="font-family:var(--font-mono);font-size:.68rem;color:var(--ink-faint);margin:.15rem .75rem .5rem;">Highest-confidence Positive comments, all-time, drawn verbatim from submitted evaluations.</p><div id="top-appreciations-list"></div></div>' +
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
            document.getElementById('ana-confidence').textContent = overall.average_confidence ? (overall.average_confidence * 100).toFixed(1) + '%' : 'N/A';

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
    // MODEL RESULTS TAB (Colab-trained models, imported)
    // ============================================================
    renderMLPanel: function(container) {
        container.innerHTML = '' +
            '<div class="page-header"><div><span style="font-family:var(--font-mono);font-size:.7rem;letter-spacing:.12em;text-transform:uppercase;color:var(--ink-faint);display:block;margin-bottom:.35rem;">Model Results</span><h1>Model on duty</h1></div></div>' +
            '<div class="data-lineage-banner" style="font-family:var(--font-mono);font-size:.68rem;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-faint);background:var(--paper-alt,#f1f1ec);border:1px dashed var(--paper-line);padding:.4rem .6rem;margin-bottom:.75rem;">' +
                '<i class="fas fa-flask"></i>&nbsp; Latest Model Training Results <span style="opacity:.6;">— models are trained in Google Colab, then imported here. This panel never trains anything locally.</span>' +
            '</div>' +
            '<div class="tabs" id="ml-tabs">' +
                '<button class="tab-btn active" data-mltab="import"><i class="fas fa-file-import"></i> Import from Colab</button>' +
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
        this.renderMLTab('import');
    },

    renderMLTab: function(tab) {
        var content = document.getElementById('ml-tab-content');
        if (!content) return;
        switch(tab) {
            case 'import': this.renderMLImport(content); break;
            case 'performance': this.renderMLPerformance(content); break;
            case 'confusion': this.renderMLConfusion(content); break;
            case 'history': this.renderMLHistory(content); break;
        }
    },

    renderMLImport: async function(container) {
        container.innerHTML = '' +
            '<div class="eval-form-card">' +
                '<h2><i class="fas fa-file-import"></i> Import Colab Training Results</h2>' +
                '<p class="form-desc">After training XGBoost, DeBERTa, and RoBERTa in Colab, upload the exported metrics JSON here (see the export cell in the Colab notebook). Optionally attach the trained model files so the app can serve them for live predictions.</p>' +
                '<div class="form-group">' +
                    '<label>Metrics JSON <span style="color:var(--neg);">(required)</span></label>' +
                    '<input type="file" class="form-control" id="import-metrics-file" accept=".json" required />' +
                '</div>' +
                '<div class="form-group"><label>XGBoost model (.pkl / .joblib)</label><input type="file" class="form-control" id="import-xgb-model" accept=".pkl,.joblib" /></div>' +
                '<div class="form-group"><label>XGBoost TF-IDF vectorizer (.pkl / .joblib)</label><input type="file" class="form-control" id="import-xgb-vectorizer" accept=".pkl,.joblib" /></div>' +
                '<div class="form-group"><label>DeBERTa model folder (.zip)</label><input type="file" class="form-control" id="import-deberta-zip" accept=".zip" /></div>' +
                '<div class="form-group"><label>RoBERTa model folder (.zip)</label><input type="file" class="form-control" id="import-roberta-zip" accept=".zip" /></div>' +
                '<div class="form-group"><label>Set as production model (optional)</label>' +
                    '<select class="form-control" id="import-set-production">' +
                        '<option value="">Auto (best weighted F1 among imported)</option>' +
                        '<option value="XGBoost">XGBoost</option>' +
                        '<option value="DeBERTa">DeBERTa</option>' +
                        '<option value="RoBERTa">RoBERTa</option>' +
                        '<option value="DeBERTa + RoBERTa">DeBERTa + RoBERTa</option>' +
                    '</select>' +
                '</div>' +
                '<button class="btn btn-primary btn-lg" onclick="ADMIN.submitImportResults()"><i class="fas fa-upload"></i> Import Results</button>' +
                '<div id="import-ml-result" class="mt-2"></div>' +
            '</div>';

        // Pre-select & highlight the currently active production model so the
        // dropdown reflects reality instead of always resetting to "Auto".
        try {
            var perf = await API.getModelPerformance();
            var select = container.querySelector('#import-set-production');
            if (select && perf && perf.best_model) {
                var active = modelPerfDisplayName(perf.best_model);
                var match = null;
                Array.prototype.forEach.call(select.options, function(opt) {
                    // canonicalise: backend may return "RoBERTa + DeBERTa" for
                    // the "DeBERTa + RoBERTa" ensemble.
                    if (modelPerfDisplayName(opt.value) === active) { match = opt; }
                });
                if (match) {
                    match.selected = true;
                    // visually flag the current production model
                    var box = select.closest('.form-group');
                    var existing = container.querySelector('.import-prod-current-note');
                    if (existing) existing.remove();
                    var note = document.createElement('div');
                    note.className = 'import-prod-current-note';
                    note.style.cssText = 'margin-top:.35rem;font-size:.72rem;font-family:var(--font-mono);color:var(--ink-faint);';
                    note.textContent = 'Currently active: ' + active + ' (Auto will keep it unless you pick another).';
                    if (box) box.appendChild(note);
                }
            }
        } catch (e) {
            // Non-blocking: fall back to the default "Auto" selection.
        }
    },

    async submitImportResults() {
        var metricsFile = document.getElementById('import-metrics-file').files[0];
        if (!metricsFile) { showToast('Please choose the metrics JSON file exported from Colab.', 'warning'); return; }
        var resultDiv = document.getElementById('import-ml-result');
        showLoading('Importing model results...');
        try {
            var result = await API.importModelResults({
                metrics: metricsFile,
                xgbModel: document.getElementById('import-xgb-model').files[0],
                xgbVectorizer: document.getElementById('import-xgb-vectorizer').files[0],
                debertaZip: document.getElementById('import-deberta-zip').files[0],
                robertaZip: document.getElementById('import-roberta-zip').files[0],
                setProduction: document.getElementById('import-set-production').value || null
            });
            resultDiv.innerHTML = '<div class="card" style="border-left:4px solid var(--pos);"><h4 style="color:var(--pos);"><i class="fas fa-check-circle"></i> Import Complete</h4><p><strong>Production model:</strong> ' + result.production_model + '</p><p><strong>Algorithms imported:</strong> ' + result.imported_algorithms.join(', ') + '</p><p style="font-size:.8rem;color:var(--ink-faint);">' + (result.artifacts_updated.length ? 'Model files updated: ' + result.artifacts_updated.join(', ') + '. If DeBERTa/RoBERTa weights changed, restart the API server so it loads the new weights.' : 'No model files were uploaded — only metrics were recorded.') + '</p><button class="btn btn-primary mt-2" onclick="ADMIN.renderMLTab(\'performance\')"><i class="fas fa-chart-bar"></i> View Performance</button></div>';
            showToast('Model results imported!', 'success');
        } catch (error) {
            resultDiv.innerHTML = '<div class="card" style="border-left:4px solid var(--neg);"><h4 style="color:var(--neg);"><i class="fas fa-times-circle"></i> Import Failed</h4><p>' + error.message + '</p></div>';
            showToast('Import failed: ' + error.message, 'error');
        } finally {
            hideLoading();
        }
    },

    async renderMLPerformance(container) {
        container.innerHTML = '<div class="text-center mt-3"><div class="spinner"></div><p>Loading performance...</p></div>';
        try {
            var perf = await API.getModelPerformance();
            var rowsHtml = filterModelPerfRows(perf.rows).map(function(r) {
                return '<tr><td><strong>' + modelPerfDisplayName(r.algorithm) + '</strong></td><td>' + formatNumber(r.accuracy) + '</td><td>' + formatNumber(r.precision) + '</td><td>' + formatNumber(r.recall) + '</td><td>' + formatNumber(r.f1_score) + '</td><td><button class="btn btn-sm btn-primary" onclick="ADMIN.viewConfusionMatrix(\'' + r.algorithm + '\')" title="Confusion Matrix"><i class="fas fa-th"></i></button> <button class="btn btn-sm btn-outline" onclick="ADMIN.downloadModel(\'' + r.algorithm + '\')" title="Download"><i class="fas fa-download"></i></button></td></tr>';
            }).join('');

            container.innerHTML = '' +
                '<div class="card">' +
                    '<div class="card-header"><h3><i class="fas fa-chart-bar"></i> Model Performance Comparison</h3></div>' +
                    '<p class="source-note" style="font-family:var(--font-mono);font-size:.68rem;color:var(--ink-faint);margin:0 .75rem .5rem;">One row per model, its most recent training run only — measured on that run\'s own held-out test split, not on live submissions.</p>' +
                    '<div class="table-container"><table class="perf-table"><thead><tr><th>Model</th><th>Accuracy</th><th>Precision</th><th>Recall</th><th>F1-Score</th><th>Actions</th></tr></thead><tbody>' + (rowsHtml || '<tr><td colspan="6" class="text-center text-muted">No training data available.</td></tr>') + '</tbody></table></div>' +
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

    async renderMLConfusion(container) {
        container.innerHTML = '<div class="text-center mt-3"><div class="spinner"></div><p>Loading available models...</p></div>';
        try {
            var perf = await API.getModelPerformance();
            var optionsHtml = filterModelPerfRows(perf.rows).map(function(r) {
                return '<option value="' + r.algorithm + '">' + modelPerfDisplayName(r.algorithm) + '</option>';
            }).join('');

            if (!optionsHtml) {
                container.innerHTML = '<div class="card"><div class="empty-state"><div class="empty-icon"><i class="fas fa-th"></i></div><h3>No Trained Models Yet</h3><p>Train XGBoost, DeBERTa, or RoBERTa first to view a confusion matrix.</p></div></div>';
                return;
            }

            container.innerHTML = '' +
                '<div class="card">' +
                    '<h3><i class="fas fa-th"></i> Confusion Matrix</h3>' +
                    '<p class="form-desc">Select an approach to view its confusion matrix.</p>' +
                    '<div class="form-inline mb-2">' +
                        '<select class="form-control" id="cm-algorithm" style="width:auto;">' + optionsHtml + '</select>' +
                        '<button class="btn btn-primary" onclick="ADMIN.viewConfusionMatrix(document.getElementById(\'cm-algorithm\').value)"><i class="fas fa-eye"></i> View</button>' +
                    '</div>' +
                    '<div id="cm-result"></div>' +
                '</div>';
        } catch (error) {
            container.innerHTML = '<div class="card"><div class="empty-state"><div class="empty-icon"><i class="fas fa-exclamation-triangle" style="color:var(--neu);"></i></div><h3>Error</h3><p>' + error.message + '</p></div></div>';
        }
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
                    '<div class="card-header"><h3><i class="fas fa-history"></i> Import History</h3></div>' +
'<p class="source-note" style="font-family:var(--font-mono);font-size:.68rem;color:var(--ink-faint);margin:0 .75rem .5rem;">Every model import from Colab, one row each, most recent first. "Dataset" is the filename recorded at export time in Colab.</p>' +
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
    }
};
