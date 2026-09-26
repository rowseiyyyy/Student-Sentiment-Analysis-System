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

    // ============================================================
    // ANALYTICS TAB — Paper theme design
    // ============================================================
    async renderAnalytics(container) {
        container.innerHTML = `
            <div class="page-header">
                <div>
                    <span style="font-family:var(--font-mono);font-size:.7rem;letter-spacing:.12em;text-transform:uppercase;color:var(--ink-faint);display:block;margin-bottom:.35rem;">Detailed Analytics</span>
                    <h1><i class="fas fa-chart-line"></i> Trends &amp; insights</h1>
                    <p class="source-note" style="font-family:var(--font-mono);font-style:italic;color:var(--ink-faint);margin:.3rem 0 0;">Faculty view — Professors-category responses only.</p>
                </div>
                <!-- Lived on the (removed) Overview tab; moved here so the
                     report download survives the tab removal. Scoped to
                     Professors on the server for faculty accounts. -->
                <button class="btn btn-success" onclick="FACULTY.exportCSV()">
                    <i class="fas fa-download"></i> Download Report
                </button>
            </div>
            <div class="chart-grid">
                <div class="chart-card">
                    <h3><i class="fas fa-chart-line"></i> Monthly Trend</h3>
                    <div class="chart-container"><canvas id="faculty-chart-monthly"></canvas></div>
                </div>
                <div class="chart-card">
                    <h3><i class="fas fa-comment-dots"></i> Top Comments</h3>
                    <!-- Complaints on the left, appreciations on the right
                         (.faculty-comments-grid); each column scrolls on its
                         own, so neither list has to be scrolled past. -->
                    <div id="faculty-top-comments" class="faculty-comments-grid"></div>
                </div>
            </div>
            <div class="chart-grid">
                <div class="chart-card">
                    <h3><i class="fas fa-book"></i> Sentiment by Courses</h3>
                    <p class="source-note" style="font-family:var(--font-mono);font-style:italic;color:var(--ink-faint);margin:.15rem 0 .5rem;">Net sentiment score per course: (Positive minus Negative) divided by that course total submissions, times 100. Spans -100 (all negative) through +100 (all positive), so bars to the right of zero are net-positive courses. Bars are sorted best to worst, and only submissions that named a course are counted.</p>
                    <div class="chart-container" id="faculty-chart-courses"></div>
                </div>
            </div>
        `;

        showLoading('Loading analytics...');
        try {
            // Professors-only view: the category filter rides along on every
            // panel in this tab, so the Monthly Trend, Top Comments and
            // Sentiment by Courses charts can never mix in Staff /
            // Facilities / Payments rows.
            const scope = `category=${encodeURIComponent(this.SCOPED_CATEGORY)}`;
            const [monthly, complaints, appreciations, courses] = await Promise.all([
                API.getMonthlyTrend(scope),
                API.getTopComplaints(5, scope),
                API.getTopAppreciations(5, scope),
                // Individually guarded: a failure here must degrade to this one
                // chart's "No course data available." caption, not blank the tab.
                API.getCourseAnalytics(scope).catch(() => null)
            ]);

            setTimeout(() => {
                const ctx = document.getElementById('faculty-chart-monthly');
                if (!ctx) return;
                const points = monthly.points || [];
                this.charts.monthly = new Chart(ctx, {
                    type: 'line',
                    data: {
                        labels: points.map(p => p.period),
                        datasets: [
                            { label: 'Positive', data: points.map(p => p.positive), borderColor: '#2f6f4e', backgroundColor: 'rgba(47,111,78,0.1)', fill: true, tension: 0.4 },
                            { label: 'Neutral', data: points.map(p => p.neutral), borderColor: '#b7791f', backgroundColor: 'rgba(183,121,31,0.1)', fill: true, tension: 0.4 },
                            { label: 'Negative', data: points.map(p => p.negative), borderColor: '#b33a3a', backgroundColor: 'rgba(179,58,58,0.1)', fill: true, tension: 0.4 }
                        ]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        interaction: { intersect: false, mode: 'index' },
                        plugins: { legend: { position: 'bottom' } }
                    }
                });
            }, 100);

            // Sentiment by Courses: one horizontal bar per course, scored
            // (Positive - Negative) / total x 100 on a fixed -100..+100 axis so
            // bar lengths stay comparable between programs. The API returns the
            // rows best-to-worst and Chart.js plots the first label of a
            // vertical category axis at the top (chart.js 4.4.0, per
            // index.html), so the best-scoring course sits at the top of the
            // chart with no reversal needed here.
            const coursePoints = (courses && courses.points) ? courses.points : [];
            const courseHost = document.getElementById('faculty-chart-courses');
            if (courseHost && coursePoints.length === 0) {
                // Empty dataset: show the same readable placeholder the admin
                // charts use instead of a broken axis-only canvas.
                courseHost.style.display = 'flex';
                courseHost.style.alignItems = 'center';
                courseHost.style.justifyContent = 'center';
                courseHost.innerHTML = '<p class="text-muted text-center">No course data available.</p>';
            } else if (courseHost) {
                // A program list runs longer than the stylesheet's chart height
                // (280px, or 240px on small screens), so give the bars ~30px
                // each rather than squeezing a dozen of them into slivers. Only
                // grows, and is capped so the card cannot run away down the page.
                const courseHeight = Math.max(280, Math.min(560, coursePoints.length * 30 + 70));
                if (courseHeight > courseHost.clientHeight) courseHost.style.height = `${courseHeight}px`;
                setTimeout(() => {
                    courseHost.innerHTML = '';
                    const canvas = document.createElement('canvas');
                    courseHost.appendChild(canvas);
                    this.charts.courses = new Chart(canvas, {
                        type: 'bar',
                        data: {
                            labels: coursePoints.map(p => p.course),
                            datasets: [{
                                label: 'Sentiment score',
                                data: coursePoints.map(p => p.sentiment_score || 0),
                                backgroundColor: coursePoints.map(p => p.sentiment_score > 0 ? '#2f6f4e' : (p.sentiment_score < 0 ? '#b33a3a' : '#b7791f')),
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
                                        // Shows the submission count, so a score
                                        // carried by a couple of responses is
                                        // readable as thin data.
                                        label: ctx => {
                                            const point = coursePoints[ctx.dataIndex] || {};
                                            return `Score ${(point.sentiment_score || 0).toFixed(1)} \u00b7 n=${point.total || 0} (P${point.positive || 0} / Neu${point.neutral || 0} / Neg${point.negative || 0})`;
                                        }
                                    }
                                }
                            },
                            scales: {
                                x: {
                                    min: -100,
                                    max: 100,
                                    title: { display: true, text: 'Sentiment score (-100 to +100)' }
                                },
                                // reverse:false pins descending order (best
                                // course at the top); autoSkip:false keeps every
                                // course named.
                                y: { reverse: false, ticks: { autoSkip: false } }
                            }
                        }
                    });
                }, 100);
            }

            // Two side-by-side columns: complaints on the left, appreciations
            // on the right. Each column scrolls on its own (.faculty-comments-col)
            // so a long appreciation list no longer pushes the complaints list
            // off-screen. Card styling is unchanged — same h4 headings, same
            // dashed dividers, same truncated quote.
            const commentsDiv = document.getElementById('faculty-top-comments');
            const complaintItems = (complaints && complaints.items) || [];
            const appreciationItems = (appreciations && appreciations.items) || [];

            const commentColumn = (title, color, icon, items) => `
                <div class="faculty-comments-col">
                    <h4 style="color:${color};margin-bottom:.5rem;font-family:var(--font-mono);font-size:.72rem;letter-spacing:.06em;text-transform:uppercase;"><i class="fas ${icon}"></i> ${title}</h4>
                    ${items.length ? items.map(c => `
                        <div style="padding:.5rem 0;border-bottom:1px dashed var(--paper-line);">
                            <p style="font-size:.85rem;">"${escapeHtml(c.comment.substring(0, 120))}"</p>
                            <small style="font-family:var(--font-mono);font-size:.72rem;color:var(--ink-faint);">${escapeHtml(c.category)}</small>
                        </div>
                    `).join('') : '<p class="text-muted">No comments available.</p>'}
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
