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
    // Global dashboard filters (Overview tab). '' means All-time / All
    // departments. Applied to every submission-data widget on the tab;
    // the Model Performance table is training-run data and is unaffected.
    // Now applied to the Analytics tab too (see _qs / scopeLabel).
    overviewFilters: { days: '', category: '' },
    // "Preview the faculty view": pin every submission chart to the Professors
    // category, which is what the faculty role is served server-side.
    facultyPreview: false,
    // Last rendered tab, so a filter/preview change can re-render whichever tab
    // is actually on screen rather than forcing the Overview.
    currentTab: 'overview',

    // ---- Negative spike alerts (Feature 1) ----
    // Alerts recomputed by ADMIN.checkAlerts(); dismissal keys survive
    // reloads via localStorage so an acknowledged spike stays cleared
    // until the NEXT period's data changes.
    alerts: [],
    alertPollTimer: null,
    ALERT_POLL_MS: 15 * 60 * 1000, // 15 minutes
    // Spike fires when: negative up >=50% vs last month AND +3 or more
    // in absolute count, OR this month's negative rate >40% of the
    // category's submissions (with >=5 total, to avoid tiny-sample noise).
    ALERT_PCT_THRESHOLD: 50,
    ALERT_ABS_THRESHOLD: 3,
    ALERT_RATE_CEILING: 40,
    ALERT_RATE_MIN_TOTAL: 5,

    getDismissedAlerts: function() {
        try { return JSON.parse(localStorage.getItem('asiatech_dismissed_alerts') || '[]'); }
        catch (e) { return []; }
    },

    dismissAlertKey: function(key) {
        var dismissed = this.getDismissedAlerts();
        if (dismissed.indexOf(key) === -1) {
            dismissed.push(key);
            localStorage.setItem('asiatech_dismissed_alerts', JSON.stringify(dismissed));
        }
    },

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
            // Offer (never force) a password change when the account still
            // uses its seed default password.
            if (result.using_default_password) {
                APP.promptDefaultPasswordChange(password);
            }
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
        this.stopAlertPolling();
        this.hideAlertPanel();
        APP.goToPage('page-login');
        document.getElementById('nav-admin').style.display = 'none';
    },

    destroyCharts: function() {
        Object.values(this.charts).forEach(function(c) { if (c) c.destroy(); });
        this.charts = {};
    },

    // Draw a chart into the element `hostId`, or fall back to the same
    // graceful "No data available." caption the Top Complaints /
    // Top Appreciations lists use when there is nothing to plot. Without
    // this, an empty dataset produces a broken axis-only canvas (and
    // Chart.js scale errors) instead of a readable placeholder.
    mountChart: function(hostId, hasData, draw, emptyMessage) {
        var host = document.getElementById(hostId);
        if (!host) return;
        if (!hasData) {
            host.style.display = 'flex';
            host.style.alignItems = 'center';
            host.style.justifyContent = 'center';
            host.innerHTML = '<p class="text-muted text-center">' + escapeHtml(emptyMessage || 'No data available.') + '</p>';
            return;
        }
        host.style.display = '';
        host.style.alignItems = '';
        host.style.justifyContent = '';
        host.innerHTML = '<canvas></canvas>';
        draw(host.querySelector('canvas'));
    },

    showDashboard: function() {
        APP.goToPage('page-admin-dashboard');
        document.getElementById('nav-admin').style.display = 'flex';
        // The name sits inside the account menu button now, so it gets the
        // name only -- the shield glyph and the "Administrator" fallback label
        // belonged to the old standalone badge and would be redundant against
        // the button's own person icon.
        const name = this.currentUser ? this.currentUser.full_name : 'Administrator';
        const badge = document.getElementById('badge-admin');
        if (badge) badge.textContent = name;
        const header = document.getElementById('account-menu-name');
        if (header) header.textContent = 'Signed in as ' + name;
        this.setAccountMenuOpen(false);
        this.updateFacultyPreviewButton();
        this.renderTab('overview');
        // Negative spike alerting: run once on load, then poll.
        this.checkAlerts();
        this.startAlertPolling();
    },

    // ============================================================
    // SCOPE — one query string for every submission chart on every
    // tab, plus the "preview the faculty lens" mode.
    //
    // The Overview tab used to build its filter query inline while the
    // Analytics tab passed nothing at all, so an admin who filtered to
    // "Faculty · last 30 days" and then clicked Analytics was looking at
    // unfiltered numbers with nothing on screen to say so.
    // ============================================================

    // _qs()             -> the current tab scope (preview-aware)
    // _qs('Facilities') -> pin one department, keeping the date filter.
    //                     Used by the per-department comparison panels.
    _qs: function(forceCategory) {
        var f = this.overviewFilters;
        var params = [];
        if (f.days) params.push('days=' + encodeURIComponent(f.days));
        // Preview mode outranks the department dropdown: the whole point is to
        // see what a faculty account is served.
        var category = forceCategory || (this.facultyPreview ? 'Professors' : f.category);
        if (category) params.push('category=' + encodeURIComponent(category));
        return params.join('&');
    },

    // Plain-English description of what the charts currently cover. Never
    // claim "all-time" while a filter is applied.
    scopeLabel: function() {
        var f = this.overviewFilters;
        var dept = this.facultyPreview
            ? 'Professors only (faculty preview)'
            : (f.category ? this.getCategoryDisplayName(f.category) : 'all departments');
        return dept + ' · ' + (f.days ? ('last ' + f.days + ' days') : 'all-time');
    },

    // The per-department comparison panels exist to put all four departments
    // side by side, so they are meaningless the moment one is selected (or the
    // faculty preview pins the scope to one).
    departmentCompareSuppressed: function() {
        return !!(this.facultyPreview || this.overviewFilters.category);
    },

    // One ratings + one aspect-averages call per department, in parallel, each
    // pinned to that department but keeping the active date filter. Only called
    // when the comparison is actually being shown.
    fetchDepartmentRatings: function() {
        var cats = ['Faculty', 'Staff', 'Facilities', 'Payment'];
        var self = this;
        return Promise.all(cats.map(function(c) {
            return Promise.all([
                API.getRatingDistribution(self._qs(c)),
                API.getAspectAverages(self._qs(c))
            ]).then(function(pair) {
                return {
                    category: c,
                    label: self.getCategoryDisplayName(c),
                    ratings: pair[0],
                    aspects: pair[1]
                };
            });
        })).catch(function() { return []; });
    },

    // Banner shown whenever the charts are not showing everything, so the
    // admin can always tell which of two number sets they are looking at.
    scopeBanner: function() {
        var f = this.overviewFilters;
        if (!this.facultyPreview && !f.days && !f.category) return '';
        var text = this.facultyPreview
            ? '<strong>Faculty preview</strong> — every submission chart below is scoped to the ' +
              'Professors category, exactly as a faculty account is served it.'
            : '<strong>Filtered</strong> — charts show ' + escapeHtml(this.scopeLabel()) + '.';
        return '<div class="scope-banner' + (this.facultyPreview ? ' preview' : '') + '">' +
            '<i class="fas ' + (this.facultyPreview ? 'fa-user-secret' : 'fa-filter') + '"></i> ' + text +
            ' <button class="btn btn-sm btn-outline" onclick="ADMIN.clearOverviewFilters()"><i class="fas fa-times"></i> Reset</button>' +
            (this.facultyPreview
                ? ' <button class="btn btn-sm btn-outline" onclick="ADMIN.toggleFacultyPreview()">Exit preview</button>'
                : '') +
            '</div>';
    },

    // Re-render whichever tab is on screen: the filter bar and the preview
    // toggle both live outside the tab body.
    refreshCurrentTab: function() {
        this.renderTab(this.currentTab || 'overview');
    },

    // Preview mode: show every submission chart exactly as a faculty account
    // sees it. For that role the category is pinned server-side; an admin
    // asks for the same slice explicitly, so both see one query.
    toggleFacultyPreview: function() {
        this.facultyPreview = !this.facultyPreview;
        this.updateFacultyPreviewButton();
        this.refreshCurrentTab();
    },

    updateFacultyPreviewButton: function() {
        var btn = document.getElementById('faculty-preview-btn');
        if (!btn) return;
        btn.classList.toggle('active', this.facultyPreview);
        btn.setAttribute('aria-pressed', this.facultyPreview ? 'true' : 'false');
        btn.title = this.facultyPreview
            ? 'Previewing the faculty view (Professors only) — click to exit'
            : 'Preview every chart exactly as a faculty account sees it';
        // The menu item carries an explicit On/Off readout: inside a dropdown
        // the pressed styling is easy to miss, and this toggle changes what
        // every number on the page means.
        var state = document.getElementById('faculty-preview-state');
        if (state) state.textContent = this.facultyPreview ? 'On' : 'Off';
    },

    // ---- account menu ---------------------------------------------------
    // Holds identity plus the faculty lens, the layout editor and Close file.
    // These were inline in the nav row and consumed ~300px, which left the tab
    // strip scrolling sideways with the active tab off screen.
    //
    // Closes on outside click and on Escape, which is the behaviour people
    // expect from a menu and is what makes it usable one-handed.
    toggleAccountMenu(event) {
        if (event) event.stopPropagation();
        this.setAccountMenuOpen(
            document.getElementById('account-menu-panel').classList.contains('hidden')
        );
    },

    setAccountMenuOpen(open) {
        const panel = document.getElementById('account-menu-panel');
        const btn = document.getElementById('account-menu-btn');
        if (!panel) return;
        panel.classList.toggle('hidden', !open);
        if (btn) {
            btn.classList.toggle('open', open);
            btn.setAttribute('aria-expanded', open ? 'true' : 'false');
        }
        // One global listener rather than one per open, so a reopened menu
        // does not stack duplicate handlers.
        if (open && !this._accountMenuBound) {
            this._accountMenuBound = true;
            document.addEventListener('click', (e) => {
                const menu = document.getElementById('account-menu');
                if (menu && !menu.contains(e.target)) this.setAccountMenuOpen(false);
            });
            document.addEventListener('keydown', (e) => {
                if (e.key === 'Escape') this.setAccountMenuOpen(false);
            });
        }
    },

    // Keep the active tab visible in the scrollable tab strip. The scrollbar
    // is hidden, so without this a tab further along the row would activate
    // off-screen with no visible indicator and no scrollbar to explain why.
    showActiveTab() {
        const active = document.querySelector('.nav-links li button.active');
        if (!active || typeof active.scrollIntoView !== 'function') return;
        // "nearest" scrolls the minimum distance, so an already-visible tab
        // does not jump the whole strip to the left.
        active.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    },

    renderTab: function(tab) {
        this.currentTab = tab;
        var content = document.getElementById('admin-content');
        content.innerHTML = '';
        var tabContent = document.createElement('div');
        tabContent.id = 'admin-tab-content';
        content.appendChild(tabContent);

        // Apply the shared, admin-editable layout. LAYOUT.mount() reads the
        // saved geometry and, for an administrator only, attaches the resize
        // handles. Faculty and students get the same geometry with no
        // controls in the DOM at all. mount() is async because the geometry
        // comes from the API, but the tab renders immediately and the layout
        // settles in behind it -- a slow or failed layout fetch must never
        // delay or blank the dashboard.
        if (typeof LAYOUT !== 'undefined') {
            LAYOUT.mountToolbar();
            LAYOUT.load('page-admin-dashboard').then(function () {
                LAYOUT.mountWhenReady(
                    document.getElementById('admin-tab-content'),
                    'page-admin-dashboard'
                );
            });
        }
        switch(tab) {
            case 'overview': this.renderOverview(tabContent); break;
            case 'responses': this.renderResponses(tabContent); break;
            case 'analytics': this.renderAnalytics(tabContent); break;
            case 'ml': this.renderMLPanel(tabContent); break;
            case 'actions': this.renderActionUpdates(tabContent); break;
            
        }
        // The tab strip is scrollable with a hidden scrollbar, so the active
        // tab is scrolled into view explicitly on every switch.
        this.showActiveTab();
    },

    // ============================================================
    // OVERVIEW TAB — Paper theme design
    // ============================================================
    renderOverview: async function(container) {
        container.innerHTML = '<div class="text-center mt-4"><div class="spinner"></div><p>Loading overview...</p></div>';
        try {
            var f = this.overviewFilters;
            // One shared scope for every submission chart on every tab, so the
            // Overview and the Analytics tab can never disagree. Preview mode
            // pins the category to Professors.
            var filterQs = this._qs();
            // Used by the per-card captions so no card claims "all-time" while a
            // filter is actually applied.
            var scopeNote = escapeHtml(this.scopeLabel());

            var overall = await API.getOverallAnalytics(filterQs || null);
            var perf = await API.getModelPerformance();
            var perfRows = filterModelPerfRows(perf.rows);
            // Best-performing row: the model with the highest metrics
            // (max F1-score, accuracy as tie-break) — independent of the
            // backend's production/best_model declaration, which may
            // point at a different row than the metric leader.
            var winnerAlgo = null;
            if (perfRows.length) {
                var bestRow = perfRows.reduce(function(a, b) {
                    var fa = [(a.f1_score || 0), (a.accuracy || 0)];
                    var fb = [(b.f1_score || 0), (b.accuracy || 0)];
                    return (fb[0] > fa[0] || (fb[0] === fa[0] && fb[1] > fa[1])) ? b : a;
                });
                winnerAlgo = bestRow.algorithm;
            }

            // "By Department" = sentiment distribution per category, from
            // GET /analytics/category?category=X (the .breakdown
            // positive/neutral/negative counts). Each row is a stacked
            // horizontal bar: green = Positive, yellow = Neutral,
            // red = Negative; segment widths are proportional to the
            // largest department total so rows remain comparable.
            var categories = ['Faculty', 'Staff', 'Facilities', 'Payment'];
            var catData = await Promise.all(categories.map(function(c) {
                return API.getCategoryAnalytics(c, filterQs || null).catch(function() { return null; });
            }));
            var maxCatTotal = 1;
            var ledgerRows = categories.map(function(c, i) {
                var d = catData[i];
                var b = (d && d.breakdown) || {};
                var counts = {
                    pos: b.positive || 0,
                    neu: b.neutral || 0,
                    neg: b.negative || 0
                };
                var total = b.total || (counts.pos + counts.neu + counts.neg);
                if (total > maxCatTotal) maxCatTotal = total;
                return { label: c, total: total, counts: counts };
            });
            var ledgerRowsHtml = ledgerRows.map(function(r) {
                var seg = function(count, cls, name) {
                    if (count <= 0) return '';
                    var w = (count / maxCatTotal) * 100;
                    return '<div class="ledger-fill ' + cls + '" style="width:' + w + '%" title="' + name + ': ' + count + '"></div>';
                };
                var displayLabel = r.label === 'Payment' ? 'Payments' : r.label;
                var countLabel = r.total > 0
                    ? r.counts.pos + ' pos · ' + r.counts.neu + ' neu · ' + r.counts.neg + ' neg'
                    : 'No submissions';
                return '<div class="ledger-row"><span class="label">' + displayLabel + '</span><div class="ledger-track">' +
                    seg(r.counts.pos, 'pos', 'Positive') + seg(r.counts.neu, 'neu', 'Neutral') + seg(r.counts.neg, 'neg', 'Negative') +
                    '</div><span class="pct" title="' + countLabel + '">' + r.total + '</span></div>';
            }).join('');

            // ---- Trend & change indicators (KPI badges + sparklines) ----
            // Uses GET /analytics/monthly: compares the current calendar
            // month against the previous one and renders a mini sparkline
            // of the last 6 months for each KPI card.
            var monthly = await API.getMonthlyTrend(filterQs || null).catch(function() { return { points: [] }; });
            var mPoints = (monthly && monthly.points) || [];

            function trendBadge(cur, prev, opts) {
                opts = opts || {};
                // invert: for metrics where "up" is bad (e.g. negative
                // feedback), a rising value is shown in red instead of green.
                var invert = !!opts.invert;
                var upCls = invert ? 'bad' : 'good';
                var downCls = invert ? 'good' : 'bad';
                if (prev === 0 && cur === 0) {
                    return '<span class="trend-badge flat"><i class="fas fa-minus"></i> 0% vs last month</span>';
                }
                if (prev === 0) {
                    return '<span class="trend-badge ' + upCls + '"><i class="fas fa-arrow-up"></i> new this month</span>';
                }
                var pct = ((cur - prev) / prev) * 100;
                if (Math.abs(pct) < 0.05) {
                    return '<span class="trend-badge flat"><i class="fas fa-minus"></i> 0% vs last month</span>';
                }
                var cls = pct > 0 ? upCls : downCls;
                var arrow = pct > 0 ? 'fa-arrow-up' : 'fa-arrow-down';
                var tooltip = (pct > 0 ? '+' : '') + pct.toFixed(1) + '% vs last month (' + prev + ' → ' + cur + ')';
                return '<span class="trend-badge ' + cls + '" title="' + tooltip + '"><i class="fas ' + arrow + '"></i> ' +
                    (pct > 0 ? '+' : '') + Math.round(pct) + '%</span>';
            }

            // Percentage line under a KPI number. Empty string when there is
            // no data, so the meta row still holds its height.
            function pct(value) {
                return value ? '<small>' + value.toFixed(1) + '%</small>' : '';
            }

            // One KPI card. The caption is clamped to two lines by CSS (a long
            // sentence used to wrap to four and stretch every card in the row),
            // so the full text rides along in title= for hover/screen readers.
            // The badge + percentage share one .stat-meta row, which keeps the
            // cards short and lines that row up across all five.
            function kpiCard(opts) {
                return '<div class="stat-card">' +
                    '<div class="stat-icon ' + opts.tone + '"><i class="fas ' + opts.icon + '"></i></div>' +
                    '<div class="stat-info">' +
                        '<h3>' + opts.value + '</h3>' +
                        '<p>' + opts.label + '</p>' +
                        (opts.spark || '') +
                        '<div class="stat-meta">' + (opts.badge || '') + (opts.pct || '') + '</div>' +
                        '<small class="source-note" title="' + opts.caption + '">' + opts.caption + '</small>' +
                    '</div>' +
                '</div>';
            }

            function sparkline(series, color) {
                // Inline SVG polyline of the last 6 monthly values.
                var data = series.slice(-6);
                if (data.length < 2 || data.every(function(v) { return v === 0; })) {
                    return '<svg class="sparkline" viewBox="0 0 80 24" preserveAspectRatio="none"><line x1="0" y1="22" x2="80" y2="22" stroke="' + color + '" stroke-dasharray="2,2" stroke-width="1" opacity=".45"/></svg>';
                }
                var max = Math.max.apply(null, data);
                var step = 80 / (data.length - 1);
                var pts = data.map(function(v, i) {
                    var x = i * step;
                    var y = max === 0 ? 22 : 22 - (v / max) * 20;
                    return x.toFixed(1) + ',' + y.toFixed(1);
                }).join(' ');
                return '<svg class="sparkline" viewBox="0 0 80 24" preserveAspectRatio="none"><polyline points="' + pts +
                    '" fill="none" stroke="' + color + '" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/></svg>';
            }

            function barSparkline(series, color) {
                // Bar variant of sparkline(): same 80x24 footprint, but one bar
                // per day, so a single busy day stands out instead of being
                // smoothed into a line. Used for the last-N-days indicator.
                var data = series.slice(-30);
                if (!data.length || data.every(function(v) { return v === 0; })) {
                    return '<svg class="sparkline" viewBox="0 0 80 24" preserveAspectRatio="none"><line x1="0" y1="22" x2="80" y2="22" stroke="' + color + '" stroke-dasharray="2,2" stroke-width="1" opacity=".45"/></svg>';
                }
                var max = Math.max.apply(null, data);
                var step = 80 / data.length;
                var barW = Math.max(1, step - 1.2);
                var bars = data.map(function(v, i) {
                    // Keep a 1-unit sliver for any non-zero day so "one
                    // submission" is still visible next to a busy day.
                    var h = v > 0 ? Math.max(1, (v / max) * 20) : 0;
                    return '<rect x="' + (i * step).toFixed(2) + '" y="' + (22 - h).toFixed(2) + '" width="' + barW.toFixed(2) +
                        '" height="' + h.toFixed(2) + '" fill="' + color + '" rx="0.5"/>';
                }).join('');
                return '<svg class="sparkline" viewBox="0 0 80 24" preserveAspectRatio="none">' + bars + '</svg>';
            }

            // Pairs the existing 6-month line sparkline with the new
            // last-N-days bar sparkline inside a single KPI card. Each half
            // carries its own native tooltip saying which window it covers.
            function kpiSparkPair(monthSeries, monthColor, daySeries) {
                return '<span class="spark-pair">' +
                    '<span title="Monthly totals, last 6 months">' + sparkline(monthSeries, monthColor) + '</span>' +
                    '<span title="Daily submissions, last ' + dailyWindow + ' days">' + barSparkline(daySeries, monthColor) + '</span>' +
                '</span>';
            }

            // The same "No data available." treatment mountChart() uses, for
            // the new widgets that are markup rather than Chart.js canvases.
            function emptyBlock(message) {
                return '<p class="text-muted text-center" style="padding:1.1rem 0 .6rem;font-size:.82rem;">' + escapeHtml(message) + '</p>';
            }

            // Compact mono date for the health widget: takes the date part of
            // the server's ISO string rather than new Date(), so a naive UTC
            // timestamp is not shifted by the browser's timezone.
            function shortDate(iso) {
                return iso ? iso.slice(0, 10) : '\u2014';
            }

            var byPeriod = {};
            mPoints.forEach(function(p) { byPeriod[p.period] = p; });
            var nowKey = new Date().toISOString().slice(0, 7);
            var prevDate = new Date();
            prevDate.setMonth(prevDate.getMonth() - 1);
            var prevKey = prevDate.toISOString().slice(0, 7);
            var curMonth = byPeriod[nowKey] || { positive: 0, neutral: 0, negative: 0, total: 0 };
            var prevMonth = byPeriod[prevKey] || { positive: 0, neutral: 0, negative: 0, total: 0 };
            // Fallback: if the current calendar month has no submissions yet
            // (e.g. early in the month), compare against the latest two
            // recorded months so the badge still reflects recent movement.
            if (!byPeriod[nowKey] && mPoints.length >= 2) {
                curMonth = mPoints[mPoints.length - 1];
                prevMonth = mPoints[mPoints.length - 2];
            }
            var sparkSeries = function(key) {
                return mPoints.slice(-6).map(function(p) { return p[key] || 0; });
            };

            // ---- Recent activity window (last N days, per KPI card) ----
            // The monthly sparkline above answers "how has this moved over the
            // year"; this answers "what happened this week/fortnight". The
            // window follows the global date filter when one is set (so these
            // widgets stay in sync with the rest of the tab) and defaults to
            // the last 14 days otherwise.
            var dailyWindow = parseInt(f.days, 10) || 14;
            var dailyParams = 'days=' + dailyWindow +
                (f.category ? '&category=' + encodeURIComponent(f.category) : '');
            var daily = await API.getDailyTrend(dailyParams).catch(function() { return { points: [] }; });
            var dailyByDay = {};
            ((daily && daily.points) || []).forEach(function(p) { dailyByDay[p.period] = p; });
            // GET /analytics/daily only returns days that have submissions, so
            // the window is zero-filled here: a zero day is real information
            // (a quiet day), not missing data.
            var dailyKeys = (function() {
                var keys = [];
                var nowMs = Date.now();
                for (var i = dailyWindow - 1; i >= 0; i--) {
                    keys.push(new Date(nowMs - i * 86400000).toISOString().slice(0, 10));
                }
                return keys;
            })();
            function dailySeries(key) {
                return dailyKeys.map(function(k) {
                    var p = dailyByDay[k];
                    return p ? (p[key] || 0) : 0;
                });
            }

            var trendPos = trendBadge(curMonth.positive, prevMonth.positive);
            var trendNeu = trendBadge(curMonth.neutral, prevMonth.neutral);
            var trendNeg = trendBadge(curMonth.negative, prevMonth.negative, { invert: true });
            var trendTot = trendBadge(curMonth.total, prevMonth.total);
            var sparkPos = kpiSparkPair(sparkSeries('positive'), '#2f6f4e', dailySeries('positive'));
            var sparkNeu = kpiSparkPair(sparkSeries('neutral'), '#b7791f', dailySeries('neutral'));
            var sparkNeg = kpiSparkPair(sparkSeries('negative'), '#b33a3a', dailySeries('negative'));
            var sparkTot = kpiSparkPair(sparkSeries('total'), '#2b3a67', dailySeries('total'));

            // ============================================================
            // Quick-glance widgets (Term-over-Term / Leaderboard / Health)
            // ============================================================
            // ---- Term-over-term: current grading period vs the previous one ----
            // "Current" is resolved server-side from today's month through the
            // same _academic_term_lookup() the Analytics term chart uses, so the
            // two can never disagree; during a break month it falls back to the
            // most recently completed period. Rendered as a doughnut pair here
            // so Overview reads differently from the Analytics stacked bar.
            var termCmp = await API.getTermComparison(filterQs).catch(function() { return null; });

            function termStripRow(cls, name, pct) {
                return '<div class="term-cmp-strip-row"><span class="term-dot ' + cls + '"></span>' +
                    '<span class="term-cmp-name">' + name + '</span>' +
                    '<span class="term-cmp-pct">' + pct.toFixed(1) + '%</span></div>';
            }

            function termSideHtml(side, tag, tone) {
                if (!side) {
                    // First-term-in-history case: render this side as a plain
                    // note instead of a broken or zeroed comparison.
                    return '<div class="term-cmp-side term-cmp-side-empty">' +
                        '<span class="term-cmp-tag">' + tag + '</span>' +
                        '<p class="text-muted" style="font-size:.75rem;margin:.75rem 0;">No earlier grading period to compare against.</p>' +
                        '</div>';
                }
                return '<div class="term-cmp-side">' +
                    '<span class="term-cmp-tag">' + tag + '</span>' +
                    '<p class="term-cmp-term" title="' + escapeHtml(side.term) + '">' + escapeHtml(side.term) + '</p>' +
                    '<div class="term-cmp-donut"><canvas id="chart-term-cmp-' + tone + '"></canvas></div>' +
                    '<div class="term-cmp-strip">' +
                        termStripRow('pos', 'Positive', side.positive_pct) +
                        termStripRow('neu', 'Neutral', side.neutral_pct) +
                        termStripRow('neg', 'Negative', side.negative_pct) +
                    '</div>' +
                    '<p class="term-cmp-vol">' + side.total + ' submission' + (side.total === 1 ? '' : 's') + '</p>' +
                    '</div>';
            }

            var hasTermCmp = !!(termCmp && ((termCmp.current && termCmp.current.total > 0) ||
                (termCmp.previous && termCmp.previous.total > 0)));
            var termCmpBodyHtml;
            if (!hasTermCmp) {
                termCmpBodyHtml = emptyBlock('No submissions in the current or preceding grading period.');
            } else {
                // A break month swaps what the two sides mean, so label them by
                // what they actually are rather than "current"/"previous".
                var prevTag = termCmp.is_break_month ? 'Earlier period' : 'Previous period';
                var curTag = termCmp.is_break_month ? 'Latest completed' : 'Current period';
                var deltaHtml = '';
                if (termCmp.current && termCmp.previous) {
                    var deltaPp = termCmp.current.positive_pct - termCmp.previous.positive_pct;
                    var deltaCls = Math.abs(deltaPp) < 0.05 ? 'flat' : (deltaPp > 0 ? 'good' : 'bad');
                    var deltaArrow = Math.abs(deltaPp) < 0.05 ? 'fa-minus' : (deltaPp > 0 ? 'fa-arrow-up' : 'fa-arrow-down');
                    deltaHtml = '<div class="term-cmp-delta"><span class="trend-badge ' + deltaCls +
                        '" title="Positive share: ' + escapeHtml(termCmp.previous.term) + ' \u2192 ' + escapeHtml(termCmp.current.term) +
                        '"><i class="fas ' + deltaArrow + '"></i> ' + (deltaPp > 0 ? '+' : '') + deltaPp.toFixed(1) + 'pp</span></div>';
                }
                termCmpBodyHtml = '<div class="term-cmp">' +
                        termSideHtml(termCmp.previous, prevTag, 'previous') +
                        deltaHtml +
                        termSideHtml(termCmp.current, curTag, 'current') +
                    '</div>' +
                    '<p class="term-cmp-note">' + escapeHtml(termCmp.note) + '</p>';
            }

            // ---- Quick department leaderboard ----
            // Ranks the categories already fetched for the By Department card by
            // positive share, so this adds no extra request. Top 3 / bottom 3,
            // with anything already listed on top excluded from the bottom list
            // so a small department count (this school has four) never lists the
            // same department twice. Pointers lead to the fuller views.
            var displayCategory = function(c) { return c === 'Payment' ? 'Payments' : c; };
            var rankedDepts = ledgerRows.filter(function(r) {
                return r.total > 0;
            }).map(function(r) {
                return { label: r.label, total: r.total, counts: r.counts, posPct: (r.counts.pos / r.total) * 100 };
            }).sort(function(a, b) {
                return b.posPct - a.posPct || b.total - a.total;
            });
            var topDepts = rankedDepts.slice(0, 3);
            var topLabels = {};
            topDepts.forEach(function(r) { topLabels[r.label] = true; });
            var bottomDepts = rankedDepts.slice(-3).reverse().filter(function(r) { return !topLabels[r.label]; });

            function leaderboardRow(r, rank, tone) {
                var total = r.total || 1;
                var segment = function(count, cls) {
                    if (count <= 0) return '';
                    return '<div class="ledger-fill ' + cls + '" style="width:' + ((count / total) * 100) + '%"></div>';
                };
                return '<div class="ledger-row">' +
                    '<span class="label"><span class="leader-rank ' + tone + '">' + rank + '</span>' + displayCategory(r.label) +
                        ' <span class="leader-n">n=' + r.total + '</span></span>' +
                    '<div class="ledger-track">' + segment(r.counts.pos, 'pos') + segment(r.counts.neu, 'neu') + segment(r.counts.neg, 'neg') + '</div>' +
                    '<span class="pct" title="' + r.counts.pos + ' pos \u00b7 ' + r.counts.neu + ' neu \u00b7 ' + r.counts.neg + ' neg">' +
                        r.posPct.toFixed(0) + '%</span>' +
                    '</div>';
            }

            var leaderboardHtml;
            if (!rankedDepts.length) {
                leaderboardHtml = emptyBlock('No department submissions match the current filter.');
            } else {
                leaderboardHtml = '<div class="leaderboard-group">' +
                    '<span class="leaderboard-heading">Most positive</span>' +
                    '<div class="ledger-bars">' + topDepts.map(function(r, i) { return leaderboardRow(r, i + 1, 'top'); }).join('') + '</div>' +
                    '</div>';
                if (bottomDepts.length) {
                    leaderboardHtml += '<div class="leaderboard-group">' +
                        '<span class="leaderboard-heading">Needs attention</span>' +
                        '<div class="ledger-bars">' + bottomDepts.map(function(r) {
                            return leaderboardRow(r, rankedDepts.length - rankedDepts.indexOf(r), 'bottom');
                        }).join('') + '</div>' +
                        '</div>';
                }
                if (rankedDepts.length < 6) {
                    leaderboardHtml += '<p class="leaderboard-note">Showing ' +
                        (topDepts.length + bottomDepts.length) + ' of ' + rankedDepts.length +
                        ' departments \u2014 with fewer than six, a department would otherwise appear in both lists. ' +
                        'The full per-department split is in By Department below.</p>';
                }
            }

            // ---- System health snapshot ----
            var lowPct = overall.low_confidence_pct || 0;
            var lowCount = overall.low_confidence_count || 0;
            var daysSince = overall.days_since_last_submission;
            // Colour bands, mirrored in the card's (i) caption: green = healthy,
            // amber = worth a look, red = act. Deliberately conservative - more
            // than a quarter of predictions at coin-flip confidence, or over a
            // week of silence, is a real signal about the data pipeline.
            var lowTone = lowPct < 10 ? 'good' : (lowPct < 25 ? 'warn' : 'bad');
            var idleTone = (daysSince === null || daysSince === undefined) ? 'warn'
                : (daysSince <= 2 ? 'good' : (daysSince <= 7 ? 'warn' : 'bad'));
            function healthRow(icon, label, value, tone, hint) {
                return '<div class="health-row">' +
                    '<span class="health-icon ' + tone + '"><i class="fas ' + icon + '"></i></span>' +
                    '<span class="health-label">' + label + '</span>' +
                    '<span class="health-value ' + tone + '" title="' + escapeHtml(hint) + '">' + value + '</span>' +
                    '</div>';
            }
            var hasHealthData = (overall.evaluation_volume || 0) > 0;
            var healthBodyHtml = !hasHealthData
                ? emptyBlock('No submissions match the current filter.')
                : '<div class="health-rows">' +
                    healthRow('fa-triangle-exclamation', 'Low-confidence submissions', lowPct.toFixed(1) + '%', lowTone,
                        lowCount + ' of ' + (overall.evaluation_volume || 0) +
                        ' predictions scored below 50% model confidence') +
                    healthRow('fa-clock', 'Days since last submission',
                        (daysSince === null || daysSince === undefined) ? '\u2014' : String(daysSince), idleTone,
                        'Time since the most recent submission in this filter scope') +
                    healthRow('fa-calendar-check', 'Last submission',
                        shortDate(overall.last_submission_at), 'neutral',
                        'Date of the most recent submission in this filter scope') +
                    '</div>';
            var trendPeriod = (byPeriod[nowKey] ? nowKey : (mPoints.length ? mPoints[mPoints.length - 1].period : '')) || '—';

            container.innerHTML = '' +
                '<div class="page-header">' +
                    '<div>' +
                        '<span style="font-family:var(--font-mono);font-size:.7rem;letter-spacing:.12em;text-transform:uppercase;color:var(--ink-faint);display:block;margin-bottom:.35rem;">Casefile Overview — All Departments</span>' +
                        '<h1>Dashboard Overview</h1>' +
                    '</div>' +
                    '<div class="date-note">Compiled ' + new Date().toLocaleDateString('en-US',{month:'long',day:'numeric',year:'numeric'}) + '</div>' +
                '</div>' +
                '<div class="data-lineage-banner" style="font-family:var(--font-mono);font-size:.68rem;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-faint);background:var(--paper-alt,#f1f1ec);border:1px solid #E5E7EB;padding:.4rem .6rem;margin-bottom:.75rem;">' +
                    '<i class="fas fa-database"></i>&nbsp; Live Submission Data <span style="opacity:.6;">— every card and chart below, up to and including the "Model Performance" table row for status, reflects ALL evaluation-form submissions ever received (not filtered by dataset or date), except where noted.</span>' +
                '</div>' +
                '<div class="filter-bar">' +
                    '<span class="filter-label"><i class="fas fa-filter"></i> Filter:</span>' +
                    '<select id="ov-filter-days" onchange="ADMIN.setOverviewFilter(\'days\', this.value)" title="Date range">' +
                        '<option value=""' + (f.days === '' ? ' selected' : '') + '>All-time</option>' +
                        '<option value="7"' + (f.days === '7' ? ' selected' : '') + '>Last 7 days</option>' +
                        '<option value="30"' + (f.days === '30' ? ' selected' : '') + '>Last 30 days</option>' +
                        '<option value="90"' + (f.days === '90' ? ' selected' : '') + '>Last 90 days</option>' +
                    '</select>' +
                    '<select id="ov-filter-category" onchange="ADMIN.setOverviewFilter(\'category\', this.value)" title="Department">' +
                        '<option value=""' + (f.category === '' ? ' selected' : '') + '>All Departments</option>' +
                        categories.map(function(c) {
                            var label = c === 'Payment' ? 'Payments' : c;
                            return '<option value="' + c + '"' + (f.category === c ? ' selected' : '') + '>' + label + '</option>';
                        }).join('') +
                    '</select>' +
                    (filterQs ? '<button class="btn btn-sm btn-outline" onclick="ADMIN.clearOverviewFilters()"><i class="fas fa-times"></i> Reset</button>' : '') +
                    '<span class="filter-scope">Applies to every submission chart, on this tab and the Analytics tab. Model Performance reflects training runs and is unaffected.</span>' +
                '</div>' +
                this.scopeBanner() +
                '<div class="stats-grid">' +
                    kpiCard({ tone: 'green', icon: 'fa-smile', value: overall.breakdown.positive || 0, label: 'Positive Feedbacks', spark: sparkPos, badge: trendPos, pct: pct(overall.breakdown.positive_pct), caption: scopeNote }) +
                    kpiCard({ tone: 'yellow', icon: 'fa-meh', value: overall.breakdown.neutral || 0, label: 'Neutral Feedbacks', spark: sparkNeu, badge: trendNeu, pct: pct(overall.breakdown.neutral_pct), caption: scopeNote }) +
                    kpiCard({ tone: 'red', icon: 'fa-frown', value: overall.breakdown.negative || 0, label: 'Negative Feedbacks', spark: sparkNeg, badge: trendNeg, pct: pct(overall.breakdown.negative_pct), caption: scopeNote + ' · badge compares ' + trendPeriod + ' vs prior month' }) +
                    kpiCard({ tone: 'blue', icon: 'fa-file-alt', value: overall.evaluation_volume || 0, label: 'Total Evaluations', spark: sparkTot, badge: trendTot, caption: 'Counted in ' + scopeNote }) +
                    kpiCard({ tone: 'purple', icon: 'fa-chart-bar', value: overall.average_confidence ? (overall.average_confidence * 100).toFixed(1) + '%' : 'N/A', label: 'Avg Confidence', caption: 'Avg. of each submission\'s prediction confidence at time of submission' }) +
                '</div>' +
                '<div class="chart-grid">' +
                    '<div class="chart-card">' +
                        '<h3><i class="fas fa-graduation-cap"></i> Term-over-Term</h3>' +
                        '<p class="source-note">The grading period in progress versus the one immediately before it, resolved from today\'s date through the same academic calendar that drives the Analytics term chart. During a break or enrollment month there is no active period, so the two most recently completed periods are compared instead and the caption below says so.</p>' +
                        termCmpBodyHtml +
                    '</div>' +
                    '<div class="chart-card">' +
                        '<div class="leaderboard-header">' +
                            '<h3><i class="fas fa-list-ol"></i> Department Leaderboard</h3>' +
                            '<span class="leaderboard-actions">' +
                                '<button class="btn btn-sm btn-outline" onclick="ADMIN.scrollToOverviewCard(\'overview-by-department\')" title="Jump to the full By Department breakdown on this tab"><i class="fas fa-arrow-down"></i> By Department</button>' +
                                '<button class="btn btn-sm btn-outline" onclick="ADMIN.renderTab(\'analytics\')" title="Open the Analytics tab for the full breakdown"><i class="fas fa-chart-line"></i> Analytics</button>' +
                            '</span>' +
                        '</div>' +
                        '<p class="source-note">Departments ranked by the positive share of their submissions: the bar shows the full positive / neutral / negative split, the right-hand figure is that department\'s positive rate and n is its submission count. A quick ranking only - the full split lives in By Department and Analytics.</p>' +
                        leaderboardHtml +
                    '</div>' +
                    '<div class="chart-card">' +
                        '<h3><i class="fas fa-heartbeat"></i> System Health</h3>' +
                        '<p class="source-note">At-a-glance data health for the current filter scope. Green = healthy, amber = worth a look, red = act. "Low confidence" means the model scored a prediction below 50% confidence (the configurable LOW_CONFIDENCE_THRESHOLD), so those submissions are worth a human review rather than being trusted as-is.</p>' +
                        healthBodyHtml +
                    '</div>' +
                '</div>' +
                '<div class="two-col">' +
                    '<div>' +
                        '<div class="chart-card" style="margin-bottom:1.1rem;">' +
                            '<h3><i class="fas fa-chart-pie"></i> Sentiment Distribution</h3>' +
                            '<p class="source-note" style="color:var(--ink-faint);margin:.15rem 0 .6rem;">All evaluation-form submissions ever received, classified positive / neutral / negative at the time each was submitted.' +
                            '<div class="chart-container"><canvas id="chart-sentiment-overview"></canvas></div>' +
                        '</div>' +
                        '<div class="chart-card">' +
                            '<h3><i class="fas fa-chart-bar"></i> Model Performance Comparison</h3>' +
                            '<p class="source-note" style="color:var(--ink-faint);margin:.15rem 0 .6rem;"><strong>Not submission data.</strong> Accuracy &amp; F1 score measured on the held-out test split from each algorithm\'s most recent training run — one bar pair per algorithm\'s latest run, independent of how many students have submitted evaluations since.' +
                            '<div class="chart-container"><canvas id="chart-model-perf"></canvas></div>' +
                        '</div>' +
                    '</div>' +
                    '<div>' +
                        '<div class="card" id="overview-by-department" style="margin-bottom:1.1rem;">' +
                            '<div class="card-header"><h3><i class="fas fa-chart-bar"></i> By Department</h3></div>' +
                            '<p class="source-note" style="color:var(--ink-faint);margin:.15rem 0 .6rem;">Evaluation forms per department, in ' + scopeNote + ', stacked by predicted sentiment (<span style="color:var(--pos);font-weight:600;">green</span> = Positive, <span style="color:var(--neu);font-weight:600;">yellow</span> = Neutral, <span style="color:var(--neg);font-weight:600;">red</span> = Negative; hover the count for the exact split)' +
                            '<div class="ledger-bars">' + ledgerRowsHtml + '</div>' +
                        '</div>' +
                        '<div class="card">' +
                            '<div class="card-header"><h3><i class="fas fa-table"></i> Model Performance</h3></div>' +
                            '<p class="source-note" style="color:var(--ink-faint);margin:.15rem 0 .6rem;"><strong>Not submission data.</strong> One row per model showing metrics from that model\'s most recent training run only (not combined across datasets or runs).</p>' +
                            '<div class="table-container"><table class="perf-table"><thead><tr><th>Model</th><th>Accuracy</th><th>Precision</th><th>Recall</th><th>F1-Score</th></tr></thead><tbody>' +
                                perfRows.map(function(r) {
                                    var isWinner = winnerAlgo && r.algorithm === winnerAlgo;
                                    return '<tr' + (isWinner ? ' class="winner-row"' : '') + '><td><strong>' + modelPerfDisplayName(r.algorithm) + '</strong>' +
                                        (isWinner ? ' <span class="winner-badge" title="Highest F1-score of the trained models"><i class="fas fa-trophy"></i> Best</span>' : '') +
                                        '</td><td>' + formatNumber(r.accuracy) + '</td><td>' + formatNumber(r.precision) + '</td><td>' + formatNumber(r.recall) + '</td><td>' + formatNumber(r.f1_score) + '</td></tr>';
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
            this.compressNotes(container);
            this.destroyCharts();
            this.renderSentimentChart(overall.breakdown);
            this.renderModelPerfChart(perfRows);
            this.renderTermComparisonChart(termCmp);
        } catch (error) {
            container.innerHTML = '<div class="page-header"><h1>Dashboard Overview</h1></div><div class="card"><div class="empty-state"><div class="empty-icon"><i class="fas fa-database"></i></div><h3>No Data Available</h3><p>' + escapeHtml(error.message) + '</p></div></div>';
        }
    },

    clearOverviewFilters: function() {
        this.overviewFilters = { days: '', category: '' };
        var content = document.getElementById('admin-tab-content');
        if (content) this.renderOverview(content); else this.renderTab('overview');
    },

    // Replace long grey monospace explanation paragraphs (class
    // .source-note) with a compact "(i)" hover tooltip. Text under
    // 90 chars is kept visible as a subtle caption; longer text
    // collapses into the badge's native title tooltip.
    compressNotes: function(root) {
        (root || document).querySelectorAll('.source-note').forEach(function(note) {
            if (note.dataset.compressed) return;
            note.dataset.compressed = '1';
            var text = note.textContent.trim();
            if (!text) return;
            if (text.length <= 90) return; // short caption: leave visible
            var badge = document.createElement('span');
            badge.className = 'note-badge';
            badge.innerHTML = '<i class="fas fa-info"></i>';
            badge.title = text.replace(/\s+/g, ' ');
            note.innerHTML = '';
            note.appendChild(badge);
            note.style.display = 'inline-block';
        });
    },

    setOverviewFilter: function(key, value) {
        this.overviewFilters[key] = value;
        var content = document.getElementById('admin-tab-content');
        if (content) this.renderOverview(content); else this.renderTab('overview');
    },

    renderSentimentChart: function(breakdown) {
        setTimeout(function() {
            var ctx = document.getElementById('chart-sentiment-overview');
            if (!ctx) return;
            // Sleek donut: hollow centre shows the total feedback count
            // (dominant sentiment % on hover is covered by tooltips).
            var total = (breakdown.positive || 0) + (breakdown.neutral || 0) + (breakdown.negative || 0);
            var centerText = {
                id: 'centerText',
                afterDraw: function(chart) {
                    if (chart.config.type !== 'doughnut') return;
                    var meta = chart.getDatasetMeta(0).data[0];
                    if (!meta) return;
                    var g = chart.ctx;
                    g.save();
                    g.textAlign = 'center';
                    g.textBaseline = 'middle';
                    g.font = '700 1.5rem "Public Sans", sans-serif';
                    g.fillStyle = '#1c231f';
                    g.fillText(String(total), meta.x, meta.y - 8);
                    g.font = '500 .62rem "Public Sans", sans-serif';
                    g.fillStyle = '#8b9389';
                    g.fillText('TOTAL', meta.x, meta.y + 14);
                    g.restore();
                }
            };
            ADMIN.charts.sentiment = new Chart(ctx, {
                type: 'doughnut',
                data: { labels: ['Positive', 'Neutral', 'Negative'], datasets: [{ data: [breakdown.positive || 0, breakdown.neutral || 0, breakdown.negative || 0], backgroundColor: ['#2f6f4e', '#b7791f', '#b33a3a'], borderWidth: 2, borderColor: '#f8f9f5', hoverOffset: 6 }] },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    cutout: '68%',
                    plugins: { legend: { position: 'bottom', labels: { usePointStyle: true, pointStyle: 'circle', boxWidth: 8 } } }
                },
                plugins: [centerText]
            });
        }, 100);
    },

    // Two small doughnut "rings" (deliberately not the Analytics stacked bar)
    // showing the current and previous grading period side by side. Each ring's
    // centre carries that period's raw submission volume, and the strip beneath
    // it lists the positive / neutral / negative split, so Overview stays a
    // glance while Analytics keeps the full detail.
    renderTermComparisonChart: function(termCmp) {
        if (!termCmp) return;
        [
            { id: 'chart-term-cmp-previous', side: termCmp.previous, key: 'termCmpPrevious' },
            { id: 'chart-term-cmp-current', side: termCmp.current, key: 'termCmpCurrent' }
        ].forEach(function(entry) {
            var side = entry.side;
            // A missing or empty side renders as the "no earlier period" note
            // built by termSideHtml(), so there is no canvas to draw into.
            if (!side || !side.total) return;
            setTimeout(function() {
                var canvas = document.getElementById(entry.id);
                if (!canvas) return;
                var centerText = {
                    id: 'termCmpCenter',
                    afterDraw: function(chart) {
                        var meta = chart.getDatasetMeta(0).data[0];
                        if (!meta) return;
                        var g = chart.ctx;
                        g.save();
                        g.textAlign = 'center';
                        g.textBaseline = 'middle';
                        g.font = '700 1.15rem "Public Sans", sans-serif';
                        g.fillStyle = '#1c231f';
                        g.fillText(String(side.total), meta.x, meta.y - 6);
                        g.font = '500 .55rem "Public Sans", sans-serif';
                        g.fillStyle = '#8b9389';
                        g.fillText('SUBMISSIONS', meta.x, meta.y + 12);
                        g.restore();
                    }
                };
                ADMIN.charts[entry.key] = new Chart(canvas, {
                    type: 'doughnut',
                    data: {
                        labels: ['Positive', 'Neutral', 'Negative'],
                        datasets: [{
                            data: [side.positive, side.neutral, side.negative],
                            backgroundColor: ['#2f6f4e', '#b7791f', '#b33a3a'],
                            borderWidth: 2,
                            borderColor: '#f8f9f5',
                            hoverOffset: 4
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        cutout: '66%',
                        // Legend hidden: the strip under each ring already names
                        // each sentiment with its percentage.
                        plugins: {
                            legend: { display: false },
                            tooltip: {
                                callbacks: {
                                    label: function(item) {
                                        var total = side.total || 1;
                                        return item.label + ': ' + item.parsed + ' (' + ((item.parsed / total) * 100).toFixed(1) + '%)';
                                    }
                                }
                            }
                        }
                    },
                    plugins: [centerText]
                });
            }, 100);
        });
    },

    // Jump helper for the Overview leaderboard: scrolls to a card further down
    // the same tab instead of re-fetching or duplicating its full breakdown.
    scrollToOverviewCard: function(id) {
        var el = document.getElementById(id);
        if (el && el.scrollIntoView) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    },

    renderModelPerfChart: function(rows) {
        setTimeout(function() {
            var ctx = document.getElementById('chart-model-perf');
            if (!ctx) return;
            ADMIN.charts.modelPerf = new Chart(ctx, {
                type: 'bar',
                data: { labels: rows.map(function(r) { return modelPerfDisplayName(r.algorithm); }), datasets: [{ label: 'Accuracy', data: rows.map(function(r) { return r.accuracy || 0; }), backgroundColor: '#2b3a67' }, { label: 'F1 Score', data: rows.map(function(r) { return r.f1_score || 0; }), backgroundColor: '#b7791f' }] },
                options: { responsive: true, maintainAspectRatio: false, layout: { padding: { bottom: 6 } }, scales: { x: { ticks: { maxRotation: 0, autoSkip: false, padding: 8 } }, y: { beginAtZero: true, max: 1, ticks: { callback: function(value) { return Math.round(value * 100) + '%'; } } } }, plugins: { legend: { position: 'top', align: 'end', labels: { usePointStyle: true, pointStyle: 'circle', boxWidth: 8, padding: 12 } }, tooltip: { callbacks: { label: function(item) { return item.dataset.label + ': ' + (item.parsed.y * 100).toFixed(1) + '%'; } } } } }
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
            '<div id="responses-summary"></div>' +
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
                '<input type="text" class="form-control" id="filter-search" placeholder="Search by course, year level, sentiment..." style="flex:1;min-width:200px;" />' +
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
            '<div id="responses-pagination" class="pagination"></div>' +
            // Voice in a Box — a separate anonymous feedback stream.
            // Rendered below the evaluation table as a card feed with
            // its own lightweight sentiment filter. Deliberately NOT a
            // table and deliberately NOT part of the evaluation data.
            '<div id="voice-feed-section" class="voice-feed-section"></div>';

        document.getElementById('filter-category').addEventListener('change', function() { ADMIN.currentPage = 1; ADMIN.loadResponses(); });
        document.getElementById('filter-search').addEventListener('input', debounce(function() { ADMIN.currentPage = 1; ADMIN.loadResponses(); }, 500));
        document.getElementById('filter-needs-review').addEventListener('change', function() { ADMIN.currentPage = 1; ADMIN.loadResponses(); });
        this.loadResponses();
        this.loadVoiceFeed();
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

    // ============================================================
    // NEGATIVE SPIKE ALERTING (Feature 1)
    // Per-category month-over-month comparison using the existing
    // monthly trend endpoint. Alert objects are plain data
    // ({key, category, type, message, cur, prev, period}) so an
    // email/push hook can consume them later without refactoring.
    // ============================================================
    checkAlerts: async function() {
        try {
            var categories = ['Faculty', 'Staff', 'Payment', 'Facilities'];
            var periodKey = new Date().toISOString().slice(0, 7); // e.g. 2026-08
            var dismissed = this.getDismissedAlerts();
            var cfg = this;

            var trends = await Promise.all(categories.map(function(c) {
                return API.getMonthlyTrend('category=' + encodeURIComponent(c))
                    .catch(function() { return { points: [] }; });
            }));

            var alerts = [];
            categories.forEach(function(category, i) {
                var points = (trends[i] && trends[i].points) || [];
                if (points.length === 0) return;
                var cur = points[points.length - 1];
                var prev = points.length >= 2 ? points[points.length - 2] : null;
                var negCur = cur.negative || 0;
                var negPrev = prev ? (prev.negative || 0) : 0;
                var totalCur = cur.total || 0;

                // Rule 1: >=50% increase AND +3 absolute (kills "1 -> 2" noise).
                if (prev && negCur > negPrev &&
                    ((negCur - negPrev) / negPrev) * 100 >= cfg.ALERT_PCT_THRESHOLD &&
                    (negCur - negPrev) >= cfg.ALERT_ABS_THRESHOLD) {
                    var pct = Math.round(((negCur - negPrev) / negPrev) * 100);
                    alerts.push({
                        key: category + '|' + periodKey + '|spike',
                        category: category, type: 'spike', period: periodKey,
                        cur: negCur, prev: negPrev,
                        message: category + ': negative feedback up ' + pct + '% this month (' + negPrev + ' \u2192 ' + negCur + ').'
                    });
                }
                // Rule 2: absolute ceiling — negative rate >40% of this
                // period's submissions (>=5 total), even without a
                // prior-period comparison.
                if (totalCur >= cfg.ALERT_RATE_MIN_TOTAL && (negCur / totalCur) * 100 > cfg.ALERT_RATE_CEILING) {
                    var rate = Math.round((negCur / totalCur) * 100);
                    alerts.push({
                        key: category + '|' + periodKey + '|ceiling',
                        category: category, type: 'ceiling', period: periodKey,
                        cur: negCur, prev: negPrev,
                        message: category + ': ' + rate + '% of this month\u2019s submissions are negative (' + negCur + ' of ' + totalCur + ').'
                    });
                }
            });

            this.alerts = alerts.filter(function(a) { return dismissed.indexOf(a.key) === -1; });
            this.updateAlertBell();
        } catch (error) {
            // Alerting must never break the dashboard.
            console.warn('Alert check failed:', error);
        }
    },

    startAlertPolling: function() {
        if (this.alertPollTimer) clearInterval(this.alertPollTimer);
        this.alertPollTimer = setInterval(function() { ADMIN.checkAlerts(); }, this.ALERT_POLL_MS);
    },

    stopAlertPolling: function() {
        if (this.alertPollTimer) {
            clearInterval(this.alertPollTimer);
            this.alertPollTimer = null;
        }
    },

    updateAlertBell: function() {
        var wrap = document.getElementById('alert-bell-wrap');
        var count = document.getElementById('alert-bell-count');
        if (!wrap || !count) return;
        wrap.classList.toggle('visible', !!this.currentUser);
        if (this.alerts.length > 0) {
            count.textContent = this.alerts.length;
            count.classList.remove('hidden');
        } else {
            count.classList.add('hidden');
        }
    },

    toggleAlertPanel: function() {
        var panel = document.getElementById('alert-panel');
        if (!panel) return;
        if (panel.classList.contains('hidden')) {
            this.renderAlertPanel();
            panel.classList.remove('hidden');
        } else {
            panel.classList.add('hidden');
        }
    },

    hideAlertPanel: function() {
        var panel = document.getElementById('alert-panel');
        if (panel) panel.classList.add('hidden');
    },

    renderAlertPanel: function() {
        var panel = document.getElementById('alert-panel');
        if (!panel) return;
        if (this.alerts.length === 0) {
            panel.innerHTML = '<div class="alert-empty"><i class="fas fa-check-circle"></i> No negative feedback spikes detected.' +
                '<span class="source-note" style="margin:0;">Checked monthly, per department \u00b7 last run ' + new Date().toLocaleTimeString() + '</span></div>';
            return;
        }
        panel.innerHTML = '<div class="alert-panel-title"><i class="fas fa-triangle-exclamation"></i> Negative Feedback Alerts</div>' +
            this.alerts.map(function(a) {
                return '<div class="alert-card">' +
                    '<p class="alert-message">' + escapeHtml(a.message) + '</p>' +
                    '<span class="source-note" style="margin:0 0 .45rem;">Period ' + escapeHtml(a.period) + ' \u00b7 source: monthly submissions with a prediction on record</span>' +
                    '<div class="alert-actions">' +
                        '<button class="btn btn-sm btn-outline" onclick="ADMIN.viewAlertResponses(\'' + escapeHtml(a.category) + '\')"><i class="fas fa-table"></i> View responses</button>' +
                        '<button class="btn btn-sm btn-outline" onclick="ADMIN.dismissAlert(\'' + escapeHtml(a.key) + '\')"><i class="fas fa-times"></i> Dismiss</button>' +
                    '</div></div>';
            }).join('');
    },

    dismissAlert: function(key) {
        this.dismissAlertKey(key);
        this.alerts = this.alerts.filter(function(a) { return a.key !== key; });
        this.updateAlertBell();
        this.renderAlertPanel();
        showToast('Alert dismissed \u2014 it stays cleared unless the spike persists into the next review.', 'info');
    },

    viewAlertResponses: function(category) {
        this.hideAlertPanel();
        this.renderTab('responses');
        // Pre-apply the category filter after the tab markup exists, then
        // load through the normal filter pipeline. (Sentiment-based spikes
        // are not the same as Likert mismatches, so needs-review stays off.)
        var catSel = document.getElementById('filter-category');
        if (catSel) {
            var match = Array.prototype.find.call(catSel.options, function(o) { return o.value === category; });
            catSel.value = match ? category : '';
        }
        ADMIN.currentPage = 1;
        this.loadResponses();
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

         // Results summary strip at the top of the Responses tab: aggregated
    // counts for the responses being browsed (optionally narrowed by the
    // Category filter). Uses the existing analytics endpoints, so it
    // always matches the Dashboard/Analytics figures.
    renderResponsesSummary: function(category, summary, total, reviewCount) {
        var el = document.getElementById('responses-summary');
        if (!el) return;
        var b = (summary && summary.breakdown) || {};
        var pos = b.positive || 0, neu = b.neutral || 0, neg = b.negative || 0;
        var scopeLabel = category ? this.getCategoryDisplayName(category) + ' responses' : 'all responses';
        var card = function(icon, iconCls, value, label, sub) {
            return '<div class="stat-card"><div class="stat-icon ' + iconCls + '"><i class="fas ' + icon + '"></i></div>' +
                '<div class="stat-info"><h3>' + value + '</h3><p>' + label + '</p>' +
                (sub ? '<small class="source-note">' + sub + '</small>' : '') +
                '</div></div>';
        };
        var pct = function(n) { return b.total ? ((n / b.total) * 100).toFixed(1) + '%' : '0%'; };
        var avgConf = summary && summary.average_confidence
            ? (summary.average_confidence * 100).toFixed(1) + '%'
            : 'N/A';
        el.innerHTML = '<div class="stats-grid" style="grid-template-columns:repeat(auto-fit,minmax(180px,1fr));margin-bottom:1.1rem;">' +
            card('fa-inbox', 'blue', (b.total || 0), 'Total Responses', scopeLabel) +
            card('fa-smile', 'green', pos, 'Positive', pct(pos) + ' of all responses') +
            card('fa-meh', 'yellow', neu, 'Neutral', pct(neu) + ' of all responses') +
            card('fa-frown', 'red', neg, 'Negative', pct(neg) + ' of all responses') +
            card('fa-bullseye', 'purple', avgConf, 'Avg Confidence', 'ML prediction confidence') +
            card('fa-triangle-exclamation', 'yellow', (reviewCount || 0), 'Needs Review', 'Likert / sentiment mismatches') +
        '</div>';
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
            var fetches = [
                API.getEvaluations({ category: this.getCategoryApiValue(category), page: this.currentPage, page_size: 20, has_submission: true, needs_review: needsReview, search: search || undefined }),
                category
                    ? API.getCategoryAnalytics(category).catch(function() { return null; })
                    : API.getOverallAnalytics().catch(function() { return null; }),
                API.getEvaluations({ needs_review: true, page: 1, page_size: 1, category: this.getCategoryApiValue(category) || undefined }).catch(function() { return null; })
            ];
            var results = await Promise.all(fetches);
            var data = results[0];
            var summary = results[1];
            var reviewData = results[2];
            var items = Array.isArray(data.items) ? data.items : [];

            this.renderResponsesSummary(category, summary, data.total, reviewData && reviewData.total);
        

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
                        '<td>' + escapeHtml(item.course || si.course || 'N/A') + '</td>' +
                        '<td>' + escapeHtml(item.year_level || si.year_level || 'N/A') + '</td>' +
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
                    '<thead><tr><th><input type="checkbox" id="select-all-checkbox" onchange="ADMIN.toggleSelectAll(this.checked)" title="Select all on this page" /></th><th>#</th><th>Course</th><th>Year Level</th><th>Category</th><th>Sentiment</th><th style="max-width:320px;">Comments</th><th style="white-space:nowrap;">Date</th><th style="white-space:nowrap;">Actions</th></tr></thead>' +
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
            if (tableContainer) tableContainer.innerHTML = '<div class="empty-state"><div class="empty-icon"><i class="fas fa-exclamation-triangle" style="color:var(--neu);"></i></div><h3>Error Loading Responses</h3><p>' + escapeHtml(error.message) + '</p></div>';
        } finally {
            if (loading) loading.classList.add('hidden');
        }
    },

    // ============================================================
    // VOICE IN A BOX FEED — separate anonymous stream (Responses tab)
    // Card feed below the evaluation table with its own lightweight
    // sentiment filter. Deliberately a separate dataset: it never
    // mixes into the evaluation table, the summary cards, analytics,
    // or any existing KPI.
    // ============================================================

    async loadVoiceFeed() {
        var section = document.getElementById('voice-feed-section');
        if (!section) return;

        var filter = document.getElementById('voice-feed-filter');
        var sentiment = filter ? filter.value : '';

        section.innerHTML =
            '<div class="voice-feed-head">' +
                '<div>' +
                    '<span class="voice-kicker"><i class="fas fa-inbox"></i> Anonymous drop box · separate stream</span>' +
                    '<h2>Voice in a Box</h2>' +
                '</div>' +
                '<span class="voice-feed-count" id="voice-feed-count">Loading...</span>' +
            '</div>' +
            '<p class="voice-feed-note">Open-ended messages about the overall school experience. Fully anonymous — no student ID is attached, and these entries are counted separately from the evaluation responses above. <span title="Submissions arrive via the \'Voice in a Box\' drop box on the landing page; no student identifier exists for them." class="note-badge">i</span></p>' +
            '<div class="filter-bar" style="justify-content:flex-start;">' +
                '<span class="filter-label">Filter</span>' +
                '<select class="form-control" id="voice-feed-filter">' +
                    '<option value="">All sentiments</option>' +
                    '<option value="Positive"' + (sentiment === 'Positive' ? ' selected' : '') + '>Positive</option>' +
                    '<option value="Neutral"' + (sentiment === 'Neutral' ? ' selected' : '') + '>Neutral</option>' +
                    '<option value="Negative"' + (sentiment === 'Negative' ? ' selected' : '') + '>Negative</option>' +
                '</select>' +
            '</div>' +
            '<div id="voice-feed-container" class="voice-feed-grid"><div class="text-center" style="grid-column:1/-1;"><div class="spinner"></div><p>Loading Voice in a Box submissions...</p></div></div>';

        document.getElementById('voice-feed-filter').addEventListener('change', function() { ADMIN.loadVoiceFeed(); });

        try {
            var data = await API.getVoiceNotes({ sentiment: sentiment || undefined, page: 1, page_size: 100 });
            var items = Array.isArray(data.items) ? data.items : [];
            var countEl = document.getElementById('voice-feed-count');
            if (countEl) countEl.textContent = (data.total || 0) + ' entr' + ((data.total === 1) ? 'y' : 'ies') + (sentiment ? ' · ' + sentiment + ' only' : '');

            var feed = document.getElementById('voice-feed-container');
            if (!feed) return;

            if (items.length === 0) {
                feed.className = '';
                feed.innerHTML = '<div class="empty-state"><div class="empty-icon"><i class="fas fa-inbox"></i></div>' +
                    '<h3>No Voice in a Box submissions yet</h3>' +
                    '<p>' + (sentiment ? 'No ' + sentiment.toLowerCase() + ' submissions yet — try another filter.' : 'Students haven\u2019t dropped any messages in the box yet.') + '</p></div>';
                return;
            }

            feed.className = 'voice-feed-grid';
            feed.innerHTML = items.map(function(item) {
                var sentimentLabel = item.sentiment || 'Neutral';
                var cls = sentimentLabel.toLowerCase();
                var conf = (item.confidence_score !== null && item.confidence_score !== undefined)
                    ? (item.confidence_score * 100).toFixed(1) + '%'
                    : 'N/A';
                return '<article class="voice-feed-card sentiment-' + cls + '">' +
                    '<p class="voice-feed-msg">' + escapeHtml(item.message) + '</p>' +
                    '<div class="voice-feed-meta">' +
                        sentimentBadge(sentimentLabel) +
                        '<span class="voice-feed-conf" title="Sentiment model confidence">conf ' + conf + '</span>' +
                        '<span class="voice-feed-date" title="Submitted anonymously">' + formatDate(item.created_at) + '</span>' +
                        '<button class="voice-feed-delete" onclick="ADMIN.deleteVoiceNote(\'' + item.id + '\')" title="Delete submission"><i class="fas fa-trash"></i></button>' +
                    '</div>' +
                '</article>';
            }).join('');
        } catch (error) {
            var feedEl = document.getElementById('voice-feed-container');
            if (feedEl) {
                feedEl.className = '';
                feedEl.innerHTML = '<div class="empty-state"><div class="empty-icon"><i class="fas fa-exclamation-triangle" style="color:var(--neu);"></i></div><h3>Could not load Voice in a Box</h3><p>' + escapeHtml(error.message) + '</p></div>';
            }
        }
    },

    async deleteVoiceNote(id) {
        if (!confirm('Delete this anonymous Voice in a Box submission? This cannot be undone.')) return;
        try {
            await API.deleteVoiceNote(id);
            showToast('Voice in a Box submission deleted.', 'success');
            this.loadVoiceFeed();
        } catch (error) {
            showToast(error.message || 'Delete failed.', 'error');
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
            '<div style="background:var(--paper-alt,#f1f1ec);border:1px solid #E5E7EB;padding:.75rem .9rem;margin-bottom:1rem;font-size:.82rem;line-height:1.65;">' +
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
            var missingModelCount = pred ? [pred.official_prediction].filter(function(p) { return !p; }).length : 1;
            if (pred) {
                // Multilingual MiniLM is the ONLY live model, so the official
                // result IS its result. The classical TF-IDF research models
                // (SVM / Naive Bayes / Logistic Regression) never run in the
                // request path, so their columns stay empty for live rows.
                var modelRows = [
                    { label: 'Multilingual MiniLM', pred: pred.official_prediction, conf: pred.confidence_score, isOfficial: true },
                    { label: 'SVM', pred: pred.svm_prediction, conf: pred.svm_confidence },
                    { label: 'Naive Bayes', pred: pred.naive_bayes_prediction, conf: pred.naive_bayes_confidence },
                    { label: 'Logistic Regression', pred: pred.logistic_regression_prediction, conf: pred.logistic_regression_confidence }
                ];
                modelRows = modelRows.map(function(m) {
                    var isOfficial = m.isOfficial || pred.algorithm_used === m.label;
                    var predCell = m.pred
                        ? sentimentBadge(m.pred)
                        : '<span class="text-muted" title="No stored prediction - the classical research models never run in the live request path">Not run</span>';
                    var confCell = m.conf != null
                        ? (m.conf * 100).toFixed(1) + '%'
                        : '<span class="text-muted" title="No stored confidence - the classical research models never run in the live request path">Not run</span>';
                    return '<tr>' +
                        '<td><strong>' + m.label + '</strong> ' + (isOfficial ? '<span class="badge badge-positive" title="Used for the official sentiment"><i class="fas fa-crown"></i> Official</span>' : '') + '</td>' +
                        '<td>' + predCell + '</td>' +
                        '<td style="white-space:nowrap;">' + sentimentBadge(item.sentiment) + 
                        (item.is_mismatch ? ' <span class="badge badge-warning" title="Likert/Text sentiment disagree: ' + escapeHtml(item.mismatch_type || '') + '"><i class="fas fa-triangle-exclamation"></i></span>' : '') +
'</td>' +
                        '<td>' + confCell + '</td>' +
                    '</tr>';
                }).join('');

                predictionHtml = '<div class="form-section" style="margin-top:1rem;">' +
                    '<h4 style="margin-bottom:0.5rem;">Text Sentiment — Model Breakdown</h4>' +
                    '<div class="table-container"><table><thead><tr><th>Model</th><th>Prediction</th><th>Confidence</th></tr></thead><tbody>' + modelRows + '</tbody></table></div>' +
                    (missingModelCount > 0 ? '<p style="font-size:.8rem;color:var(--neg,#b33a3a);margin-top:.5rem;"><i class="fas fa-exclamation-triangle"></i> The live model (Multilingual MiniLM) has not produced a result for this submission. Its weights are fetched from the private Hugging Face repo at startup.</p>' : '') +
                    '<p style="font-size:.8rem;color:var(--ink-faint);margin-top:.5rem;"><i class="fas fa-info-circle"></i> The official result comes from the live production model, Multilingual MiniLM. The SVM, Naive Bayes and Logistic Regression research models are trained and evaluated offline for the model comparison and never run during live inference.</p>' +
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
                'SVM Prediction', 'SVM Confidence',
                'Naive Bayes Prediction', 'Naive Bayes Confidence',
                'Logistic Regression Prediction', 'Logistic Regression Confidence',
                'Date Submitted'
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
                    item.course || si.course || '',
                    item.year_level || si.year_level || '',
                    ADMIN.getCategoryDisplayName(item.category),
                    item.share_your_thoughts || '',
                    ratingAvg,
                    item.likert_sentiment || '',
                    item.likert_average != null ? item.likert_average : '',
                    item.sentiment || '',
                    pred.confidence_score != null ? pred.confidence_score : '',
                    pred.svm_prediction || '',
                    pred.svm_confidence != null ? pred.svm_confidence : '',
                    pred.naive_bayes_prediction || '',
                    pred.naive_bayes_confidence != null ? pred.naive_bayes_confidence : '',
                    pred.logistic_regression_prediction || '',
                    pred.logistic_regression_confidence != null ? pred.logistic_regression_confidence : '',
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
        // Every figure on this tab is scoped by the same filter/preview state as
        // the Overview (see _qs). The banner plus the per-card captions below
        // make the active scope explicit, because these numbers used to ignore
        // the filter entirely and silently disagree with the Overview tab.
        var scopeQs = this._qs();
        var scopeNote = escapeHtml(this.scopeLabel());
        var deptCompareHidden = this.departmentCompareSuppressed();
        container.innerHTML = '' +
            '<div class="page-header"><div><span style="font-family:var(--font-mono);font-size:.7rem;letter-spacing:.12em;text-transform:uppercase;color:var(--ink-faint);display:block;margin-bottom:.35rem;">Detailed Analytics</span><h1>Trends &amp; top signals</h1></div></div>' +
            this.scopeBanner() +
            '<div class="data-lineage-banner" style="font-family:var(--font-mono);font-size:.68rem;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-faint);background:var(--paper-alt,#f1f1ec);border:1px solid #E5E7EB;padding:.4rem .6rem;margin-bottom:.75rem;">' +
                '<i class="fas fa-database"></i>&nbsp; Live Submission Data <span style="opacity:.6;">— every section on this tab is drawn from evaluation-form submissions. Nothing here reflects ML training runs.</span>' +
            '</div>' +
            '<div class="stats-grid" style="grid-template-columns:repeat(auto-fit,minmax(220px,1fr));">' +
                '<div class="stat-card"><div class="stat-icon green"><i class="fas fa-chart-line"></i></div><div class="stat-info"><h3 id="ana-pos-pct">-</h3><p>Positive Rate</p><small class="source-note">Scope: ' + scopeNote + '</small></div></div>' +
                '<div class="stat-card"><div class="stat-icon blue"><i class="fas fa-file-alt"></i></div><div class="stat-info"><h3 id="ana-total">-</h3><p>Total Entries</p><small class="source-note">Counted in ' + scopeNote + '</small></div></div>' +
                '<div class="stat-card"><div class="stat-icon yellow"><i class="fas fa-bullseye"></i></div><div class="stat-info"><h3 id="ana-confidence">-</h3><p>Model Confidence</p><small class="source-note">Mean prediction confidence, ' + scopeNote + '</small></div></div>' +
            '</div>' +
            '<div class="chart-grid">' +
                '<div class="chart-card"><h3><i class="fas fa-chart-line"></i> Monthly Trend</h3><p class="source-note" style="color:var(--ink-faint);margin:.15rem 0 .5rem;">Evaluation-form submissions grouped by the month they were submitted, in ' + scopeNote + '.</p><div class="chart-container"><canvas id="chart-monthly-trend"></canvas></div></div>' +
                '<div class="chart-card"><h3><i class="fas fa-chart-bar"></i> Sentiment by Category</h3><p class="source-note" style="color:var(--ink-faint);margin:.15rem 0 .5rem;">Evaluation-form submissions grouped by department category. This panel always compares all four departments, so the department filter does not apply to it.</p><div class="chart-container"><canvas id="chart-category-sentiment"></canvas></div></div>' +
            '</div>' +
            '<div class="chart-grid">' +
                '<div class="chart-card"><h3><i class="fas fa-graduation-cap"></i> Sentiment by Academic Term</h3><p class="source-note" style="font-family:var(--font-mono);font-style:italic;color:var(--ink-faint);margin:.15rem 0 .5rem;">Volume and sentiment for each of the eight grading periods (Term 1 Prelim to Finals, then Term 2 Prelim to Finals), from each submission\'s month. Break / enrollment months (Nov, Dec, Jan, Jun) belong to no grading period and are intentionally not plotted.</p><div class="chart-container" id="chart-host-term-sentiment"></div></div>' +
                '<div class="chart-card"><h3><i class="fas fa-project-diagram"></i> Sentiment Trend by Department</h3><p class="source-note" style="font-family:var(--font-mono);font-style:italic;color:var(--ink-faint);margin:.15rem 0 .5rem;">Department positivity rate per month, size-normalized so trends compare fairly. Each point is tagged with that month\'s raw submission count (n=), so a swing backed by real volume can be told apart from one resting on a handful of low-traffic submissions.</p><div class="chart-container" id="chart-host-department-trend"></div></div>' +
            '</div>' +
            // ---- Per-department rating panels -----------------------------
            // Rating distribution and per-aspect means side by side across all
            // four departments: the leadership-level "where are we weak" view.
            // Suppressed — with the reason shown — whenever the scope is pinned
            // to a single department, because then there is nothing to compare.
            (deptCompareHidden
                ? '<div class="chart-grid"><div class="chart-card">' +
                    '<h3><i class="fas fa-table"></i> Rating Breakdown by Department</h3>' +
                    '<p class="text-muted" style="font-size:.85rem;">Department comparison is hidden while the scope is narrowed to one department (' + scopeNote + '). Clear the department filter — or switch off the faculty preview — to compare all four.</p>' +
                  '</div></div>'
                : '<div class="chart-grid">' +
                    '<div class="chart-card">' +
                        '<h3><i class="fas fa-chart-bar"></i> Rating Distribution by Department</h3>' +
                        '<p class="source-note" style="font-family:var(--font-mono);font-style:italic;color:var(--ink-faint);margin:.15rem 0 .5rem;">Where each department\'s submissions land on the 1-5 scale, all four side by side. Mass at the right-hand end means satisfied students; mass at the left means the opposite. Only submissions that answered the scale are counted.</p>' +
                        '<div class="chart-container" id="chart-host-rating-by-dept"></div>' +
                    '</div>' +
                  '</div>' +
                  // One table per department rather than a single combined
                  // cross-tab. Each department asks a different set of
                  // questions, so the combined table was mostly em-dashes —
                  // one filled cell per row and three dead ones. Full width
                  // below so each table gets room to breathe.
                  '<div class="chart-card">' +
                    '<h3><i class="fas fa-table"></i> Average Rating by Aspect</h3>' +
                    '<p class="source-note" style="font-family:var(--font-mono);font-style:italic;color:var(--ink-faint);margin:.15rem 0 .5rem;">Mean 1-5 score per question, listed strongest first, split into one table per department — &ldquo;Staff are weakest on safety, Facilities on cleanliness&rdquo;. Every department asks a different set of questions, so each table shows only what that department actually asked. n is how many students answered; a high score resting on very few answers is thin evidence.</p>' +
                    '<div id="aspect-tables"></div>' +
                  '</div>') +
            '<div class="chart-grid">' +
                '<div class="chart-card"><h3><i class="fas fa-book"></i> Sentiment by Courses</h3><p class="source-note" style="font-family:var(--font-mono);font-style:italic;color:var(--ink-faint);margin:.15rem 0 .5rem;">Net sentiment score per course: (Positive minus Negative) divided by that course total submissions, times 100. Spans -100 (all negative) through +100 (all positive), so 0 means positives and negatives cancel out. Bars are sorted best to worst. Only submissions that named a course are counted, and a course resting on a handful of submissions can swing to the extremes.</p><div class="chart-container" id="chart-host-course-sentiment"></div></div>' +
            '</div>' +
            '<div class="two-col">' +
                '<div class="card"><div class="card-header"><h3><i class="fas fa-exclamation-circle"></i> Top Complaints</h3></div><p class="source-note" style="color:var(--ink-faint);margin:.15rem .75rem .5rem;">Highest-confidence Negative comments, drawn verbatim from submitted evaluations in ' + scopeNote + '.</p><div id="top-complaints-list"></div></div>' +
                '<div class="card"><div class="card-header"><h3><i class="fas fa-star"></i> Top Appreciations</h3></div><p class="source-note" style="color:var(--ink-faint);margin:.15rem .75rem .5rem;">Highest-confidence Positive comments, drawn verbatim from submitted evaluations in ' + scopeNote + '.</p><div id="top-appreciations-list"></div></div>' +
            '</div>';

        showLoading('Loading analytics...');
        this.compressNotes(container);
        // null lets the API client omit the "?" entirely when nothing is filtered.
        var qs = scopeQs || null;
        try {
            var results = await Promise.all([
                API.getOverallAnalytics(qs),
                API.getMonthlyTrend(qs),
                API.getTopComplaints(5, qs),
                API.getTopAppreciations(5, qs),
                // Per-department rating panels. Suppressed when the scope is
                // already narrowed to a single department, so they are not
                // fetched at all in that case.
                deptCompareHidden ? Promise.resolve(null) : this.fetchDepartmentRatings()
            ]);
            var overall = results[0];
            var monthly = results[1];
            var complaints = results[2];
            var appreciations = results[3];
            var deptRatings = results[4];

            document.getElementById('ana-pos-pct').textContent = (overall.breakdown.positive_pct || 0).toFixed(1) + '%';
            document.getElementById('ana-total').textContent = overall.evaluation_volume || 0;
            document.getElementById('ana-confidence').textContent = overall.average_confidence ? (overall.average_confidence * 100).toFixed(1) + '%' : 'N/A';

            // ---- Per-department rating panels -----------------------------
            // deptRatings is null when the scope is already one department; the
            // markup explains that case instead of drawing a one-bar chart.
            if (deptRatings && deptRatings.length) {
                var DEPT_COLORS = ['#2b3a67', '#2f6f4e', '#b7791f', '#b33a3a'];
                var bandLabels = (((deptRatings[0].ratings) || {}).points || [])
                    .map(function(p) { return p.band + ' · ' + p.label; });
                var anyRated = deptRatings.some(function(d) { return d.ratings && d.ratings.total; });
                var ratingHost = document.getElementById('chart-host-rating-by-dept');
                if (ratingHost) {
                    if (!anyRated) {
                        ratingHost.style.display = 'flex';
                        ratingHost.style.alignItems = 'center';
                        ratingHost.style.justifyContent = 'center';
                        ratingHost.innerHTML = '<p class="text-muted text-center">No rating data available.</p>';
                    } else {
                        setTimeout(function() {
                            var canvas = document.createElement('canvas');
                            ratingHost.innerHTML = '';
                            ratingHost.appendChild(canvas);
                            ADMIN.charts.ratingByDept = new Chart(canvas, {
                                type: 'bar',
                                data: {
                                    labels: bandLabels,
                                    // One dataset per department, so the bands
                                    // can be compared side by side.
                                    datasets: deptRatings.map(function(d, i) {
                                        var pts = (d.ratings && d.ratings.points) || [];
                                        return {
                                            label: d.label,
                                            data: pts.map(function(p) { return p.total || 0; }),
                                            backgroundColor: DEPT_COLORS[i % DEPT_COLORS.length]
                                        };
                                    })
                                },
                                options: {
                                    responsive: true,
                                    maintainAspectRatio: false,
                                    scales: {
                                        // Five long band captions: keep them on
                                        // one line rather than smearing the axis.
                                        x: { ticks: { autoSkip: false, maxRotation: 0, minRotation: 0, font: { size: 9 } } },
                                        y: { beginAtZero: true, ticks: { precision: 0 } }
                                    },
                                    plugins: {
                                        legend: { position: 'bottom' },
                                        tooltip: {
                                            callbacks: {
                                                // The bar is already the band
                                                // total; add that department's
                                                // overall mean for context.
                                                footer: function(items) {
                                                    var d = deptRatings[items[0].datasetIndex];
                                                    return d && d.ratings && d.ratings.average
                                                        ? d.label + ' mean: ' + d.ratings.average.toFixed(2) + ' / 5'
                                                        : '';
                                                }
                                            }
                                        }
                                    }
                                }
                            });
                        }, 100);
                    }
                }

                // ---- Average rating by aspect, one table per department ----
                // Each department is rendered independently: its own rows,
                // its own header, sorted strongest-first (the API already
                // orders points by descending average). No cross-tab and no
                // em-dashes, because a department only ever lists the
                // questions it actually asked.
                var tablesHost = document.getElementById('aspect-tables');
                if (tablesHost) {
                    var withAspects = deptRatings.filter(function(d) {
                        return (d.aspects && d.aspects.points || []).length;
                    });
                    if (!withAspects.length) {
                        tablesHost.innerHTML = '<p class="text-muted text-center">No aspect data available.</p>';
                    } else {
                        tablesHost.innerHTML = '<div class="aspect-tables">' +
                            withAspects.map(function(d) {
                                var points = d.aspects.points;
                                // Mean of the per-aspect means, weighted by how
                                // many students answered each one, so the
                                // headline figure reflects the whole department
                                // rather than an average of averages.
                                var sum = 0;
                                var n = 0;
                                points.forEach(function(p) {
                                    sum += p.average * p.responses;
                                    n += p.responses;
                                });
                                var overall = n ? (sum / n) : null;
                                return '<table class="aspect-table">' +
                                    '<caption>' + escapeHtml(d.label) +
                                        (overall === null ? '' : ' · ' + overall.toFixed(2) + ' overall') +
                                    '</caption>' +
                                    '<thead><tr><th>Question</th><th>Avg</th><th class="col-n">n</th></tr></thead>' +
                                    '<tbody>' +
                                    points.map(function(p) {
                                        var band = Math.max(1, Math.min(5, Math.round(p.average)));
                                        return '<tr><th scope="row">' + escapeHtml(p.label) + '</th>' +
                                            '<td class="t' + band + '" title="' +
                                                escapeHtml(d.label) + ' · ' + escapeHtml(p.label) + ': ' +
                                                p.average.toFixed(2) + ' / 5 from ' + p.responses +
                                                ' student' + (p.responses === 1 ? '' : 's') + '">' +
                                                p.average.toFixed(2) + '</td>' +
                                            '<td class="col-n">' + p.responses + '</td></tr>';
                                    }).join('') +
                                    '</tbody></table>';
                            }).join('') +
                            '</div>';
                    }
                }
            }

            var categories = ['Faculty', 'Staff', 'Facilities', 'Payment'];
            var catData = await Promise.all(categories.map(function(c) { return API.getCategoryAnalytics(c).catch(function() { return null; }); }));

            // Extra analytics sources backing the three added charts. Each is
            // individually guarded so a single failing endpoint degrades to
            // that chart's "No data available." caption instead of blanking
            // the whole tab via the catch block below.
            var extra = await Promise.all([
                API.getTermAnalytics(qs).catch(function() { return null; }),
                Promise.all(categories.map(function(c) {
                    // _qs(c) keeps the date filter while pinning one department:
                    // this chart always compares all four, so only the date part
                    // of the scope applies here.
                    return API.getMonthlyTrend(ADMIN._qs(c)).catch(function() { return null; });
                })),
                API.getCourseAnalytics(qs).catch(function() { return null; })
            ]);
            var termData = extra[0];
            var deptTrends = extra[1];
            var courseData = extra[2];

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

            // ---- Sentiment by Academic Term (volume + sentiment per grading period) ----
            var termPoints = (termData && termData.points) ? termData.points : [];
            var hasTermData = termPoints.some(function(p) { return (p.total || 0) > 0; });
            setTimeout(function() {
                ADMIN.mountChart('chart-host-term-sentiment', hasTermData, function(canvas) {
                    ADMIN.charts.termSentiment = new Chart(canvas, {
                        type: 'bar',
                        data: {
                            labels: termPoints.map(function(p) { return p.term; }),
                            datasets: [
                                { label: 'Positive', data: termPoints.map(function(p) { return p.positive || 0; }), backgroundColor: '#2f6f4e' },
                                { label: 'Neutral', data: termPoints.map(function(p) { return p.neutral || 0; }), backgroundColor: '#b7791f' },
                                { label: 'Negative', data: termPoints.map(function(p) { return p.negative || 0; }), backgroundColor: '#b33a3a' }
                            ]
                        },
                        options: { responsive: true, maintainAspectRatio: false, scales: { x: { stacked: true }, y: { stacked: true, beginAtZero: true } }, plugins: { legend: { position: 'bottom' } } }
                    });
                }, 'No academic term data available.');
            }, 100);

            // ---- Sentiment trend by department over time (one line per department) ----
            // Departments carry very different submission volumes, so each line
            // plots that department's POSITIVITY RATE for the month (Positive
            // share of that month's submissions) instead of raw counts. A month
            // with no submissions for a department stays a gap, not a fake 0%.
            //
            // A rate on its own cannot be read though: 100% off two submissions
            // means something very different from 100% off forty. So each point
            // also carries that month's raw submission volume, which this
            // inline plugin prints as an "n=" count label beside the marker
            // (the tooltip repeats it). A 100% spike tagged "n=1" is visibly
            // thin data rather than a real shift. Chart.js 4 is loaded from a
            // CDN without chartjs-plugin-datalabels, so this is a small inline
            // plugin instead of an extra dependency.
            var deptVolumeLabels = {
                id: 'deptVolumeLabels',
                afterDatasetsDraw: function(chart) {
                    var ctx = chart.ctx;
                    ctx.save();
                    ctx.font = '600 9px monospace';
                    ctx.textAlign = 'center';
                    ctx.textBaseline = 'bottom';
                    chart.data.datasets.forEach(function(dataset, di) {
                        var meta = chart.getDatasetMeta(di);
                        if (meta.hidden || !dataset.volumes) return;
                        meta.data.forEach(function(element, index) {
                            var volume = dataset.volumes[index];
                            // null = no submissions that month, so no marker and
                            // no label either (leave the gap clean).
                            if (volume == null) return;
                            var text = 'n=' + volume;
                            // White halo keeps the tiny label legible where two
                            // departments' lines cross.
                            ctx.lineWidth = 3;
                            ctx.strokeStyle = 'rgba(255,255,255,0.85)';
                            ctx.strokeText(text, element.x, element.y - 6);
                            ctx.fillStyle = dataset.borderColor || '#555';
                            ctx.fillText(text, element.x, element.y - 6);
                        });
                    });
                    ctx.restore();
                }
            };
            var deptColors = { Faculty: '#2b3a67', Staff: '#7c5cbf', Facilities: '#2e7d8f', Payment: '#8a5a2b' };
            var deptMonths = [];
            (deptTrends || []).forEach(function(d) {
                ((d && d.points) || []).forEach(function(p) {
                    if (deptMonths.indexOf(p.period) === -1) deptMonths.push(p.period);
                });
            });
            deptMonths.sort();
            var hasDeptTrend = false;
            var deptDatasets = categories.map(function(c, i) {
                var points = (deptTrends && deptTrends[i] && deptTrends[i].points) ? deptTrends[i].points : [];
                var byMonth = {};
                points.forEach(function(p) { byMonth[p.period] = p; });
                var series = [];
                var volumes = [];
                deptMonths.forEach(function(m) {
                    var point = byMonth[m];
                    if (!point || !point.total) {
                        // No submissions that month: keep the gap (null), and
                        // null the volume too so no "n=0" label is drawn.
                        series.push(null);
                        volumes.push(null);
                        return;
                    }
                    hasDeptTrend = true;
                    series.push(Math.round((point.positive / point.total) * 1000) / 10);
                    volumes.push(point.total);
                });
                return {
                    label: c === 'Payment' ? 'Payments' : c,
                    data: series,
                    // Raw submission count per month, read by the
                    // deptVolumeLabels plugin and the tooltip callback below.
                    volumes: volumes,
                    borderColor: deptColors[c],
                    backgroundColor: deptColors[c],
                    borderWidth: 2,
                    pointRadius: 3,
                    fill: false,
                    tension: 0.35,
                    spanGaps: true
                };
            });
            setTimeout(function() {
                ADMIN.mountChart('chart-host-department-trend', hasDeptTrend, function(canvas) {
                    ADMIN.charts.departmentTrend = new Chart(canvas, {
                        type: 'line',
                        data: { labels: deptMonths, datasets: deptDatasets },
                        // Inline plugin: "n=" volume labels beside each point.
                        plugins: [deptVolumeLabels],
                        options: {
                            responsive: true,
                            maintainAspectRatio: false,
                            interaction: { intersect: false, mode: 'index' },
                            scales: { y: { beginAtZero: true, max: 100, title: { display: true, text: '% Positive' } } },
                            plugins: {
                                legend: { position: 'bottom' },
                                tooltip: {
                                    callbacks: {
                                        label: function(ctx) {
                                            var volume = ctx.dataset.volumes ? ctx.dataset.volumes[ctx.dataIndex] : null;
                                            var text = ctx.dataset.label + ': ' + ctx.formattedValue + '% positive';
                                            return volume == null ? text : text + ' \u00b7 n=' + volume;
                                        }
                                    }
                                }
                            }
                        }
                    });
                }, 'No department trend data available.');
            }, 100);

            // ---- Sentiment by Courses (net sentiment score, best course first) ----
            // One bar per course, scored (Positive - Negative) / total x 100 on
            // a fixed -100..+100 axis, so bar lengths are comparable between
            // courses and the zero line reads as "positives and negatives even
            // out" rather than a missing bar. The API already returns the rows
            // best-to-worst and Chart.js plots the first label of a vertical
            // category axis at the TOP (verified against chart.js 4.4.0, the
            // version index.html loads), so the highest-scoring course lands at
            // the top with no reversal here.
            var coursePoints = (courseData && courseData.points) ? courseData.points : [];
            var hasCourseData = coursePoints.length > 0;
            var courseHost = document.getElementById('chart-host-course-sentiment');
            if (courseHost && hasCourseData) {
                // A program list runs longer than the stylesheet's chart height
                // (280px, or 240px on small screens), so give the bars ~30px
                // each rather than squeezing a dozen into slivers. Only grows --
                // a short list keeps the stylesheet's own height, and a long one
                // is capped so the card cannot run away down the page.
                var courseHeight = Math.max(280, Math.min(560, coursePoints.length * 30 + 70));
                if (courseHeight > courseHost.clientHeight) courseHost.style.height = courseHeight + 'px';
            }
            var courseBarColor = function(score) {
                if (score > 0) return '#2f6f4e';
                if (score < 0) return '#b33a3a';
                return '#b7791f';
            };
            setTimeout(function() {
                ADMIN.mountChart('chart-host-course-sentiment', hasCourseData, function(canvas) {
                    ADMIN.charts.courseSentiment = new Chart(canvas, {
                        type: 'bar',
                        data: {
                            labels: coursePoints.map(function(p) { return p.course; }),
                            datasets: [{
                                label: 'Sentiment score',
                                data: coursePoints.map(function(p) { return p.sentiment_score || 0; }),
                                backgroundColor: coursePoints.map(function(p) { return courseBarColor(p.sentiment_score); }),
                                borderWidth: 0
                            }]
                        },
                        options: {
                            indexAxis: 'y',
                            responsive: true,
                            maintainAspectRatio: false,
                            plugins: {
                                legend: { display: false },
                                tooltip: {
                                    callbacks: {
                                        // Thin data is visible here: a score at the
                                        // extremes carried by "n=1" is a flag, not
                                        // a verdict on the whole program.
                                        label: function(ctx) {
                                            var point = coursePoints[ctx.dataIndex] || {};
                                            return 'Score ' + (point.sentiment_score || 0).toFixed(1) +
                                                ' \u00b7 n=' + (point.total || 0) +
                                                ' (P' + (point.positive || 0) + ' / Neu' + (point.neutral || 0) + ' / Neg' + (point.negative || 0) + ')';
                                        }
                                    }
                                }
                            },
                            scales: {
                                // Fixed bounds keep every course on one ruler.
                                x: {
                                    min: -100,
                                    max: 100,
                                    title: { display: true, text: 'Sentiment score (-100 to +100)' }
                                },
                                // reverse:false pins the descending order as-is:
                                // first (best) course at the top, worst at the
                                // bottom. autoSkip:false keeps every course named.
                                y: { reverse: false, ticks: { autoSkip: false } }
                            }
                        }
                    });
                }, 'No course data available.');
            }, 100);

            var complaintsList = document.getElementById('top-complaints-list');
            if (complaints.items && complaints.items.length > 0) {
                complaintsList.innerHTML = complaints.items.map(function(c) {
                    return '<div style="padding:.5rem 0;border-bottom:1px dashed var(--paper-line);"><p style="font-size:.88rem;">"' + escapeHtml(c.comment.substring(0, 150)) + '"</p><small class="text-muted" style="font-family:var(--font-mono);font-size:.72rem;">' + escapeHtml(c.category) + ' | Confidence: ' + formatNumber(c.confidence) + '</small></div>';
                }).join('');
            } else {
                complaintsList.innerHTML = '<p class="text-muted text-center">No complaints data available.</p>';
            }

            var appreciationsList = document.getElementById('top-appreciations-list');
            if (appreciations.items && appreciations.items.length > 0) {
                appreciationsList.innerHTML = appreciations.items.map(function(a) {
                    return '<div style="padding:.5rem 0;border-bottom:1px dashed var(--paper-line);"><p style="font-size:.88rem;">"' + escapeHtml(a.comment.substring(0, 150)) + '"</p><small class="text-muted" style="font-family:var(--font-mono);font-size:.72rem;">' + escapeHtml(a.category) + ' | Confidence: ' + formatNumber(a.confidence) + '</small></div>';
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
            '<div class="data-lineage-banner" style="font-family:var(--font-mono);font-size:.68rem;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-faint);background:var(--paper-alt,#f1f1ec);border:1px solid #E5E7EB;padding:.4rem .6rem;margin-bottom:.75rem;">' +
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
                '<p class="form-desc">After training in Colab, upload the <strong>metrics JSON</strong> here to record the results. Multilingual MiniLM is the ONLY live inference model — SVM, Naive Bayes and Logistic Regression are the offline research baselines and appear in the comparison table only. Weights are fetched from the private Hugging Face Hub repo at startup, so you do not upload model files here.</p>' +
                '<div class="form-group">' +
                    '<label>Metrics JSON <span style="color:var(--neg);">(required)</span></label>' +
                    '<input type="file" class="form-control" id="import-metrics-file" accept=".json" required />' +
                '</div>' +
                '<div class="form-group"><label>Set as production model (optional)</label>' +
                    '<select class="form-control" id="import-set-production">' +
                        '<option value="">Auto (best weighted F1 among imported)</option>' +
                        '<option value="Multilingual MiniLM">Multilingual MiniLM</option>' +
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
                        result = await API.importModelResults({
                metrics: metricsFile,
                setProduction: document.getElementById('import-set-production').value || null
            });
            resultDiv.innerHTML = '<div class="card" style="border-left:4px solid var(--pos);"><h4 style="color:var(--pos);"><i class="fas fa-check-circle"></i> Import Complete</h4><p><strong>Production model:</strong> ' + result.production_model + '</p><p><strong>Algorithms imported:</strong> ' + result.imported_algorithms.join(', ') + '</p><p style="font-size:.8rem;color:var(--ink-faint);">' + (result.artifacts_updated.length ? 'Model files updated: ' + result.artifacts_updated.join(', ') + '.' : 'No model files were uploaded — only metrics were recorded.') + '</p><button class="btn btn-primary mt-2" onclick="ADMIN.renderMLTab(\'performance\')"><i class="fas fa-chart-bar"></i> View Performance</button></div>';
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
            var rows = filterModelPerfRows(perf.rows);
            // Winner = the model with the highest metrics (max F1-score,
            // accuracy as tie-break), matching the overview table logic.
            var winnerAlgo = null;
            if (rows.length) {
                winnerAlgo = rows.reduce(function(a, b) {
                    var fa = [(a.f1_score || 0), (a.accuracy || 0)];
                    var fb = [(b.f1_score || 0), (b.accuracy || 0)];
                    return (fb[0] > fa[0] || (fb[0] === fa[0] && fb[1] > fa[1])) ? b : a;
                }).algorithm;
            }
            var rowsHtml = rows.map(function(r) {
                var isWinner = winnerAlgo && r.algorithm === winnerAlgo;
                return '<tr' + (isWinner ? ' class="winner-row"' : '') + '><td><strong>' + modelPerfDisplayName(r.algorithm) + '</strong>' +
                    (isWinner ? ' <span class="winner-badge" title="Best-performing model (production choice)"><i class="fas fa-trophy"></i> Best</span>' : '') +
                    '</td><td>' + formatNumber(r.accuracy) + '</td><td>' + formatNumber(r.precision) + '</td><td>' + formatNumber(r.recall) + '</td><td>' + formatNumber(r.f1_score) + '</td><td><button class="btn btn-sm btn-primary" onclick="ADMIN.viewConfusionMatrix(\'' + r.algorithm + '\')" title="Confusion Matrix"><i class="fas fa-th"></i></button> <button class="btn btn-sm btn-outline" onclick="ADMIN.downloadModel(\'' + r.algorithm + '\')" title="Download"><i class="fas fa-download"></i></button></td></tr>';
            }).join('');

            container.innerHTML = '' +
                '<div class="card">' +
                    '<div class="card-header"><h3><i class="fas fa-chart-bar"></i> Model Performance Comparison</h3></div>' +
                    '<p class="source-note" style="color:var(--ink-faint);margin:0 .75rem .5rem;">One row per model, its most recent training run only — measured on that run\'s own held-out test split, not on live submissions.</p>' +
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
                container.innerHTML = '<div class="card"><div class="empty-state"><div class="empty-icon"><i class="fas fa-th"></i></div><h3>No Trained Models Yet</h3><p>Import Colab training results first to view a confusion matrix.</p></div></div>';
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
'<p class="source-note" style="color:var(--ink-faint);margin:0 .75rem .5rem;">Every model import from Colab, one row each, most recent first. "Dataset" is the filename recorded at export time in Colab.</p>' +
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
    // ACTION UPDATES TAB (Feature 2, admin side)
    // Admin CRUD for the public "Action Taken" bulletin. The
    // internal_reference field is for admin tracking only and is
    // never rendered on the public page (see bulletin.js).
    // ============================================================
    actionStatusBadge: function(status) {
        var map = {
            acknowledged: ['badge-acknowledged', 'Acknowledged'],
            in_progress: ['badge-in-progress', 'In Progress'],
            resolved: ['badge-resolved', 'Resolved']
        };
        var cfg = map[status] || map.acknowledged;
        return '<span class="' + cfg[0] + '">' + cfg[1] + '</span>';
    },

    renderActionUpdates: async function(container) {
        container.innerHTML = '<div class="text-center mt-4"><div class="spinner"></div><p>Loading action updates...</p></div>';
        try {
            var posts = await API.getActionUpdates();
            container.innerHTML =
                '<div class="page-header"><div>' +
                    '<span style="font-family:var(--font-mono);font-size:.7rem;letter-spacing:.12em;text-transform:uppercase;color:var(--ink-faint);display:block;margin-bottom:.35rem;">Feedback Loop \u2014 Action Taken</span>' +
                    '<h1>Action Updates</h1>' +
                '</div>' +
                '<button class="btn btn-primary" onclick="ADMIN.showActionForm()"><i class="fas fa-plus"></i> New Update</button></div>' +
                '<p class="source-note">Posts published to the public Action Bulletin (login page \u2192 \u201cWhat we\u2019ve done with your feedback\u201d). Show aggregate outcomes only \u2014 never student names, IDs, or raw comment text. The internal reference is never published.</p>' +
                '<div id="action-form-wrap" class="hidden"></div>' +
                '<div id="action-updates-list"></div>';
            this.renderActionList(posts);
        } catch (error) {
            container.innerHTML = '<div class="page-header"><h1>Action Updates</h1></div><div class="card"><div class="empty-state"><div class="empty-icon"><i class="fas fa-bullhorn"></i></div><h3>Could not load updates</h3><p>' + escapeHtml(error.message) + '</p></div></div>';
        }
    },

    renderActionList: function(posts) {
        var list = document.getElementById('action-updates-list');
        if (!list) return;
        if (!posts || posts.length === 0) {
            list.innerHTML = '<div class="card"><div class="empty-state"><div class="empty-icon"><i class="fas fa-bullhorn"></i></div><h3>No Updates Posted</h3><p>Use \u201cNew Update\u201d to publish the first action taken on student feedback.</p></div></div>';
            return;
        }
        list.innerHTML = posts.map(function(p) {
            return '<div class="card action-post">' +
                '<div class="card-header" style="margin-bottom:.6rem;">' +
                    '<h3>' + escapeHtml(p.title) + ' <span class="cat-badge ' + ADMIN.getCategoryBadgeClass(p.category) + '">' + escapeHtml(p.category) + '</span></h3>' +
                    '<div>' + ADMIN.actionStatusBadge(p.status) + '</div>' +
                '</div>' +
                '<p class="action-summary">' + escapeHtml(p.summary) + '</p>' +
                (p.resolution_note ? '<p class="action-resolution"><strong>Resolution:</strong> ' + escapeHtml(p.resolution_note) + '</p>' : '') +
                (p.internal_reference ? '<p class="source-note" style="margin:.4rem 0 0;"><i class="fas fa-lock"></i> Internal ref (never published): ' + escapeHtml(p.internal_reference) + '</p>' : '') +
                '<div class="action-post-footer">' +
                    '<span class="source-note" style="margin:0;">Posted ' + formatDate(p.date_posted) + (p.date_updated && p.date_updated !== p.date_posted ? ' \u00b7 edited ' + formatDate(p.date_updated) : '') + '</span>' +
                    '<div>' +
                        '<button class="btn btn-sm btn-outline" onclick="ADMIN.showActionForm(\'' + p.id + '\')"><i class="fas fa-edit"></i> Edit</button> ' +
                        '<button class="btn btn-sm btn-outline" onclick="ADMIN.deleteActionUpdate(\'' + p.id + '\')"><i class="fas fa-trash"></i> Delete</button>' +
                    '</div>' +
                '</div></div>';
        }).join('');
    },

    showActionForm: function(editId) {
        var wrap = document.getElementById('action-form-wrap');
        if (!wrap) return;
        var existing = editId ? (this._editingPost || null) : null;
        wrap.classList.remove('hidden');
        wrap.innerHTML = '<div class="card">' +
            '<div class="card-header"><h3>' + (editId ? 'Edit Update' : 'New Action Update') + '</h3>' +
            '<button class="btn btn-sm btn-outline" onclick="document.getElementById(\'action-form-wrap\').classList.add(\'hidden\')"><i class="fas fa-times"></i></button></div>' +
            '<div class="form-group"><label><i class="fas fa-tag"></i> Category</label>' +
            '<select class="form-control" id="action-category">' +
            '<option value="Faculty">Faculty</option><option value="Staff">Staff</option>' +
            '<option value="Payment">Payment</option><option value="Facilities">Facilities</option>' +
            '</select></div>' +
            '<div class="form-group"><label><i class="fas fa-heading"></i> Title</label>' +
            '<input class="form-control" id="action-title" placeholder="e.g. Long cashier lines" maxlength="200"></div>' +
            '<div class="form-group"><label><i class="fas fa-align-left"></i> Summary</label>' +
            '<textarea class="form-control" id="action-summary" rows="3" placeholder="Aggregate outcome — never paste raw comments."></textarea></div>' +
            '<div class="form-group"><label><i class="fas fa-tasks"></i> Status</label>' +
            '<select class="form-control" id="action-status">' +
            '<option value="acknowledged">Acknowledged</option><option value="in_progress">In Progress</option><option value="resolved">Resolved</option>' +
            '</select></div>' +
            '<div class="form-group"><label><i class="fas fa-check-circle"></i> Resolution note (required when Resolved)</label>' +
            '<textarea class="form-control" id="action-resolution" rows="2" placeholder="e.g. Added a second cashier window."></textarea></div>' +
            '<div class="form-group"><label><i class="fas fa-lock"></i> Internal reference (never published)</label>' +
            '<input class="form-control" id="action-internal" placeholder="e.g. feedback spike, Jul 2026" maxlength="200"></div>' +
            '<div class="form-group" style="display:flex;gap:.5rem;justify-content:flex-end;">' +
            '<button class="btn btn-primary" onclick="ADMIN.saveActionUpdate(\'' + (editId || '') + '\')"><i class="fas fa-save"></i> ' + (editId ? 'Save changes' : 'Publish update') + '</button></div>' +
            '<p class="source-note" style="margin:.2rem 0 0;">Publishes to the public Action Bulletin immediately. Internal references stay admin-only.</p>' +
            '</div>';
        if (existing) {
            document.getElementById('action-category').value = existing.category || 'Faculty';
            document.getElementById('action-title').value = existing.title || '';
            document.getElementById('action-summary').value = existing.summary || '';
            document.getElementById('action-status').value = existing.status || 'acknowledged';
            document.getElementById('action-resolution').value = existing.resolution_note || '';
            document.getElementById('action-internal').value = existing.internal_reference || '';
        }
        wrap.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    },

    saveActionUpdate: function(editId) {
        var payload = {
            category: document.getElementById('action-category').value,
            title: document.getElementById('action-title').value.trim(),
            summary: document.getElementById('action-summary').value.trim(),
            status: document.getElementById('action-status').value,
            resolution_note: document.getElementById('action-resolution').value.trim() || null,
            internal_reference: document.getElementById('action-internal').value.trim() || null
        };
        if (payload.title.length < 3) { showToast('Title must be at least 3 characters.', 'warning'); return; }
        if (payload.summary.length < 10) { showToast('Summary must be at least 10 characters.', 'warning'); return; }
        showLoading(editId ? 'Saving...' : 'Publishing...');
        var req = editId ? API.updateActionUpdate(editId, payload) : API.createActionUpdate(payload);
        req.then(function() {
            showToast(editId ? 'Update saved.' : 'Update published to the public bulletin.', 'success');
            var list = document.getElementById('action-form-wrap');
            if (list) list.classList.add('hidden');
            API.getActionUpdates().then(function(posts) { ADMIN.renderActionList(posts); });
        }).catch(function(err) { showToast(escapeHtml(err.message), 'error'); }).finally(function() { hideLoading(); });
    },

    deleteActionUpdate: function(id) {
        if (!confirm('Delete this action update? It will no longer appear on the public bulletin.')) return;
        showLoading('Deleting...');
        API.deleteActionUpdate(id).then(function() {
            showToast('Update deleted.', 'success');
            API.getActionUpdates().then(function(posts) { ADMIN.renderActionList(posts); });
        }).catch(function(err) { showToast(escapeHtml(err.message), 'error'); }).finally(function() { hideLoading(); });
    }
};
