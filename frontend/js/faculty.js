/**
 * Asiatech Sentiment Analysis - Faculty Module
 * Updated for "Asiatech Feedback Casefile" paper theme design.
 * Faculty dashboard: read-only sentiment summary, charts, and reports.
 * All data fetching, export, and logic preserved.
 */

const FACULTY = {
    currentUser: null,
    charts: {},

    // A faculty member only ever reviews professor feedback, so every
    // Analytics query is scoped to the Professors category. The backend pins
    // the same scope for the faculty role (app/api/analytics.py
    // _scoped_category), so this is explicit rather than load-bearing.
    SCOPED_CATEGORY: 'Professors',

    init() {
        const user = API.getUser();
        if (user && (user.role === 'faculty' || user.role === 'administrator')) {
            this.currentUser = user;
            this.showDashboard();
        }
    },

    async handleLogin(email, password) {
        showLoading('Logging in...');
        try {
            const result = await API.login(email, password);
            if (result.user.role !== 'faculty') {
                showToast('This login is for faculty members only.', 'warning');
                API.clearAuth();
                hideLoading();
                return;
            }
            API.setAuth(result.access_token, result.user);
            this.currentUser = result.user;
            showToast(`Welcome, ${result.user.full_name}!`, 'success');
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

    logout() {
        API.clearAuth();
        this.currentUser = null;
        this.destroyCharts();
        APP.goToPage('page-login');
        document.getElementById('nav-faculty').style.display = 'none';
    },

    destroyCharts() {
        Object.values(this.charts).forEach(c => { if (c) c.destroy(); });
        this.charts = {};
    },

    showDashboard() {
        APP.goToPage('page-faculty-dashboard');
        document.getElementById('nav-faculty').style.display = 'flex';
        document.getElementById('badge-faculty').textContent = '\u{1F3EB} ' + (this.currentUser ? this.currentUser.full_name : 'Faculty');
        this.renderFacultyTab('analytics');
    },

    renderFacultyTab(tab) {
        const container = document.getElementById('faculty-content');
        container.innerHTML = '';
        const content = document.createElement('div');
        content.id = 'faculty-tab-content';
        container.appendChild(content);

        // Apply the shared layout. Faculty get the geometry an administrator
        // finalized and no controls: LAYOUT.mount() checks the role and
        // returns before inserting any markup. Loading is what makes the
        // finalized layout visible here at all.
        if (typeof LAYOUT !== 'undefined') {
            LAYOUT.load('page-faculty-dashboard').then(() => {
                LAYOUT.mountWhenReady(
                    document.getElementById('faculty-tab-content'),
                    'page-faculty-dashboard'
                );
            });
        }

        // Analytics is the only faculty view (the Overview tab was removed).
        // Anything else falls back to it rather than rendering a blank page —
        // e.g. a stale data-ftab value in a cached index.html.
        switch (tab) {
            case 'analytics':
                this.renderAnalytics(content);
                break;
            default:
                this.renderAnalytics(content);
        }
    },

    // ---- Chart visibility (admin-managed, global for all faculty) --------
    // Removes the card of every chart the administrator has NOT shared with
    // faculty from the freshly rendered Analytics tab. Called synchronously
    // right after the markup is inserted — before any await — so the layout
    // mount never sees a card that is about to disappear, and a disabled
    // chart renders nothing, fetches nothing and leaves no placeholder.
    _applyChartVisibility(enabled) {
        // chart key -> the element that anchors its card.
        const HOSTS = {
            sentiment_split: 'faculty-chart-sentiment-split',
            rating_distribution: 'faculty-chart-ratings',
            aspect_averages: 'faculty-chart-aspects',
            sentiment_courses: 'faculty-chart-courses',
            top_comments: 'faculty-top-comments',
        };
        Object.keys(HOSTS).forEach((key) => {
            if (enabled.has(key)) return;
            const host = document.getElementById(HOSTS[key]);
            const card = host && host.closest('.chart-card');
            if (card && card.parentNode) card.parentNode.removeChild(card);
        });
    },

    // ============================================================
    // ANALYTICS TAB — Paper theme design
    // ============================================================
    async renderAnalytics(container) {
        // Which charts has the administrator shared with faculty? Fetched
        // fresh on every render (page load / tab entry) and never cached:
        // a change applies on the next page load, with no logout/login
        // round-trip. This only decides what to BUILD — every data call
        // below is gated to 403 server-side as well (app/api/analytics.py,
        // _require_faculty_chart).
        let visibility;
        try {
            visibility = await API.getFacultyCharts();
        } catch (error) {
            container.innerHTML = `
                <div class="card">
                    <div class="empty-state">
                        <div class="empty-icon"><i class="fas fa-exclamation-triangle" style="color:var(--neu);"></i></div>
                        <h3>Analytics Error</h3>
                        <p>${escapeHtml(error.message)}</p>
                    </div>
                </div>`;
            return;
        }
        const enabled = new Set((visibility.charts || []).filter(c => c.visible).map(c => c.key));
        const on = (key) => enabled.has(key);

        // The markup below authors all five cards so the captions live in
        // exactly one place; cards for disabled charts are dropped right
        // after this template is assigned.
        container.innerHTML = `
            <div class="page-header">
                <div>
                    <span style="font-family:var(--font-mono);font-size:.7rem;letter-spacing:.12em;text-transform:uppercase;color:var(--ink-faint);display:block;margin-bottom:.35rem;">Detailed Analytics</span>
                    <h1><i class="fas fa-chart-line"></i> Trends &amp; insights</h1>
                    <p class="source-note" style="font-family:var(--font-mono);font-style:italic;color:var(--ink-faint);margin:.3rem 0 0;">Faculty view — Professors-category responses only.</p>
                </div>
                <!-- Lived on the (removed) Overview tab; moved here so the
                     report download survives the tab removal. Scoped to
                     Professors on the server for faculty accounts.
                     With NOTHING shared the button is omitted entirely —
                     the server answers 403 to the export when no chart is
                     enabled (and strips hidden charts' columns otherwise). -->
                ${enabled.size ? `<button class="btn btn-success" onclick="FACULTY.exportCSV()">
                    <i class="fas fa-download"></i> Download Report
                </button>` : ''}
            </div>
            <!-- One grid for every panel below, not one per panel: separate
                 grids each resolved their own auto-fit, so a lone card
                 stretched to the full page width and left dead space beside
                 it. Wide cards opt into span-2 / span-3 and the dense flow
                 backfills the columns they leave free. -->
            <div class="chart-grid">
                <div class="chart-card">
                    <h3><i class="fas fa-chart-pie"></i> Sentiment Split</h3>
                    <p class="source-note" style="font-family:var(--font-mono);font-style:italic;color:var(--ink-faint);margin:.15rem 0 .5rem;">How the Professors-category comments read, all-time: every submission that carries a sentiment, counted once.</p>
                    <div class="chart-container" id="faculty-chart-sentiment-split"></div>
                </div>
                <div class="chart-card">
                    <h3><i class="fas fa-chart-bar"></i> Rating Distribution</h3>
                    <p class="source-note" style="font-family:var(--font-mono);font-style:italic;color:var(--ink-faint);margin:.15rem 0 .5rem;">Each submission&rsquo;s 1-5 average, stacked by that same submission&rsquo;s sentiment — so a tall 4-5 block that is mostly red is the case worth looking at. Comment-only submissions have no rating and are not counted.</p>
                    <div class="chart-container" id="faculty-chart-ratings"></div>
                    <p class="source-note" id="faculty-ratings-summary" style="font-family:var(--font-mono);font-size:.68rem;color:var(--ink-faint);margin:.5rem 0 0;text-align:center;"></p>
                </div>
                <div class="chart-card">
                    <h3><i class="fas fa-star"></i> Average by Aspect</h3>
                    <p class="source-note" style="font-family:var(--font-mono);font-style:italic;color:var(--ink-faint);margin:.15rem 0 .5rem;">Mean 1-5 score per rating aspect, strongest at the top — the &ldquo;strong on clarity, weak on punctuality&rdquo; view. Hover a bar for how many students answered that aspect.</p>
                    <div class="chart-container" id="faculty-chart-aspects"></div>
                </div>
                <div class="chart-card span-3">
                    <h3><i class="fas fa-book"></i> Sentiment by Courses</h3>
                    <p class="source-note" style="font-family:var(--font-mono);font-style:italic;color:var(--ink-faint);margin:.15rem 0 .5rem;">Net sentiment score per course: (Positive minus Negative) divided by that course total submissions, times 100. Spans -100 (all negative) through +100 (all positive), so bars to the right of zero are net-positive courses. Bars are sorted best to worst, and only submissions that named a course are counted.</p>
                    <div class="chart-container" id="faculty-chart-courses"></div>
                </div>
                <div class="chart-card span-3">
                    <h3><i class="fas fa-comment-dots"></i> Top Comments</h3>
                    <!-- Complaints on the left, appreciations on the right
                         (.faculty-comments-grid); each column scrolls on its
                         own, so neither list has to be scrolled past. -->
                    <div id="faculty-top-comments" class="faculty-comments-grid"></div>
                </div>
            </div>
        `;

        // ---- Visibility: empty state, or drop the disabled cards ----------
        if (!enabled.size) {
            // Nothing has been shared with this faculty account yet: a
            // friendly card rather than five empty charts (and no Download
            // Report button — see the header above).
            container.innerHTML = `
                <div class="card">
                    <div class="empty-state">
                        <div class="empty-icon"><i class="fas fa-eye-slash" style="color:var(--ink-faint);"></i></div>
                        <h3>No analytics shared</h3>
                        <p>No analytics have been shared with you yet.</p>
                    </div>
                </div>`;
            return;
        }
        // Disable-by-removal happens here, synchronously — no await between
        // the innerHTML above and this call, so the layout mount (which runs
        // once LAYOUT.load resolves) only ever sees the cards that stay.
        this._applyChartVisibility(enabled);

        showLoading('Loading analytics...');
        try {
            // Professors-only view: the category filter rides along on every
            // panel in this tab, so none of these charts can mix in Staff /
            // Facilities / Payments rows. Only ENABLED charts are fetched at
            // all — a disabled chart's endpoint is never called here, and the
            // server would answer 403 anyway if it were called by hand.
            const scope = `category=${encodeURIComponent(this.SCOPED_CATEGORY)}`;
            const [complaints, appreciations, courses, split, ratings, aspects] =
                await Promise.all([
                    on('top_comments') ? API.getTopComplaints(5, scope) : Promise.resolve(null),
                    on('top_comments') ? API.getTopAppreciations(5, scope) : Promise.resolve(null),
                    // Individually guarded: a failure in one panel must degrade
                    // to that panel's own "no data" caption, not blank the tab.
                    on('sentiment_courses') ? API.getCourseAnalytics(scope).catch(() => null) : Promise.resolve(null),
                    on('sentiment_split') ? API.getOverallAnalytics(scope).catch(() => null) : Promise.resolve(null),
                    on('rating_distribution') ? API.getRatingDistribution(scope).catch(() => null) : Promise.resolve(null),
                    on('aspect_averages') ? API.getAspectAverages(scope).catch(() => null) : Promise.resolve(null)
                ]);

            // The empty-state / canvas helpers and the drawing itself now
            // live in CHARTS (frontend/js/charts.js), so the admin Analytics
            // tab renders these very same panels from the same code.

            // ---- Sentiment split (doughnut) --------------------------------
            // The only "how many" view on this tab: /analytics/overall, scoped.
            CHARTS.sentimentSplit(
                document.getElementById('faculty-chart-sentiment-split'),
                split, this.charts, 'split'
            );

            // ---- Rating distribution (stacked 1-5 histogram) ---------------
            // The API returns all five bands zero-filled, so the x-axis keeps a
            // stable 1-5 scale instead of collapsing to whichever bands happen
            // to hold data. Each stack segment is the sentiment of the
            // submissions that landed in that band.
            CHARTS.ratingDistribution(
                document.getElementById('faculty-chart-ratings'),
                ratings,
                document.getElementById('faculty-ratings-summary'),
                this.charts, 'ratings'
            );

            // ---- Average by aspect (horizontal bars, fixed 1-5 axis) ---------
            // The API sorts strongest-first, which is the order Chart.js plots
            // a vertical category axis (first label at the top), so no reversal
            // is needed and the weakest aspect lands at the bottom.
            CHARTS.aspectAverages(
                document.getElementById('faculty-chart-aspects'),
                aspects, this.charts, 'aspects'
            );

            // Sentiment by Courses: one horizontal bar per course, scored
            // (Positive - Negative) / total x 100 on a fixed -100..+100 axis so
            // bar lengths stay comparable between programs. The API returns the
            // rows best-to-worst and Chart.js plots the first label of a
            // vertical category axis at the top (chart.js 4.4.0, per
            // index.html), so the best-scoring course sits at the top of the
            // chart with no reversal needed here.
            CHARTS.sentimentCourses(
                document.getElementById('faculty-chart-courses'),
                courses, this.charts, 'courses'
            );

            // Two side-by-side columns: complaints on the left, appreciations
            // on the right. Each column scrolls on its own (.faculty-comments-col)
            // so a long appreciation list no longer pushes the complaints list
            // off-screen. Card styling is unchanged — same h4 headings, same
            // dashed dividers, same truncated quote.
            const commentsDiv = document.getElementById('faculty-top-comments');
            // Null when the Top Comments card was dropped by the visibility
            // pass — then there is nothing to fill in.
            if (commentsDiv) {
                const complaintItems = (complaints && complaints.items) || [];
                const appreciationItems = (appreciations && appreciations.items) || [];

                const commentColumn = (title, color, icon, items) => `
                    <div class="faculty-comments-col">
                        <h4 style="color:${color};margin-bottom:.5rem;font-family:var(--font-mono);font-size:.72rem;letter-spacing:.06em;text-transform:uppercase;"><i class="fas ${icon}"></i> ${title}</h4>
                        ${items.length ? items.map(c => CHARTS.commentRowHtml(c, { truncate: 120 })).join('') : '<p class="text-muted">No comments available.</p>'}
                    </div>
                `;

                if (!complaintItems.length && !appreciationItems.length) {
                    commentsDiv.innerHTML =
                        '<p class="text-muted text-center">No comment data available.</p>';
                } else {
                    commentsDiv.innerHTML =
                        commentColumn('Top Complaints', 'var(--neg)', 'fa-exclamation-circle', complaintItems) +
                        commentColumn('Top Appreciations', 'var(--pos)', 'fa-star', appreciationItems);
                }
            }

        } catch (error) {
            container.innerHTML += `
                <div class="card">
                    <div class="empty-state">
                        <div class="empty-icon"><i class="fas fa-exclamation-triangle" style="color:var(--neu);"></i></div>
                        <h3>Analytics Error</h3>
                        <p>${escapeHtml(error.message)}</p>
                    </div>
                </div>
            `;
        } finally {
            hideLoading();
        }
    },

    async exportCSV() {
        try {
            await API.exportCsv();
            showToast('Report downloaded successfully!', 'success');
        } catch (error) {
            showToast('Export failed: ' + error.message, 'error');
        }
    }
};
