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

        showLoading('Loading analytics...');
        try {
            // Professors-only view: the category filter rides along on every
            // panel in this tab, so none of these charts can mix in Staff /
            // Facilities / Payments rows.
            const scope = `category=${encodeURIComponent(this.SCOPED_CATEGORY)}`;
            const [complaints, appreciations, courses, split, ratings, aspects] =
                await Promise.all([
                    API.getTopComplaints(5, scope),
                    API.getTopAppreciations(5, scope),
                    // Individually guarded: a failure in one panel must degrade
                    // to that panel's own "no data" caption, not blank the tab.
                    API.getCourseAnalytics(scope).catch(() => null),
                    API.getOverallAnalytics(scope).catch(() => null),
                    API.getRatingDistribution(scope).catch(() => null),
                    API.getAspectAverages(scope).catch(() => null)
                ]);

            // Shared empty-state for a panel with nothing to draw: the same
            // readable caption the courses chart uses, instead of a bare axis.
            const showEmpty = (host, message) => {
                host.style.display = 'flex';
                host.style.alignItems = 'center';
                host.style.justifyContent = 'center';
                host.innerHTML = `<p class="text-muted text-center">${message}</p>`;
            };
            // A canvas is created by hand (rather than declared in the markup)
            // so one host can serve either the chart or the caption.
            const mountCanvas = (host) => {
                host.style.display = '';
                host.innerHTML = '';
                const canvas = document.createElement('canvas');
                host.appendChild(canvas);
                return canvas;
            };

            // ---- Sentiment split (doughnut) --------------------------------
            // The only "how many" view on this tab: /analytics/overall, scoped.
            const splitHost = document.getElementById('faculty-chart-sentiment-split');
            const breakdown = (split && split.breakdown) || {};
            if (splitHost) {
                if (!breakdown.total) {
                    showEmpty(splitHost, 'No sentiment data available.');
                } else {
                    setTimeout(() => {
                        this.charts.split = new Chart(mountCanvas(splitHost), {
                            type: 'doughnut',
                            data: {
                                labels: ['Positive', 'Neutral', 'Negative'],
                                datasets: [{
                                    data: [breakdown.positive || 0, breakdown.neutral || 0, breakdown.negative || 0],
                                    backgroundColor: ['#2f6f4e', '#b7791f', '#b33a3a'],
                                    borderWidth: 2,
                                    borderColor: '#f8f9f5'
                                }]
                            },
                            options: {
                                responsive: true,
                                maintainAspectRatio: false,
                                plugins: {
                                    legend: { position: 'bottom' },
                                    tooltip: {
                                        callbacks: {
                                            label: (ctx) => {
                                                const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
                                                const pct = total ? ((ctx.parsed / total) * 100).toFixed(1) : '0.0';
                                                return `${ctx.label}: ${ctx.parsed} (${pct}%)`;
                                            }
                                        }
                                    }
                                }
                            }
                        });
                    }, 100);
                }
            }

            // ---- Rating distribution (stacked 1-5 histogram) ---------------
            // The API returns all five bands zero-filled, so the x-axis keeps a
            // stable 1-5 scale instead of collapsing to whichever bands happen
            // to hold data. Each stack segment is the sentiment of the
            // submissions that landed in that band.
            const ratingsHost = document.getElementById('faculty-chart-ratings');
            const bands = (ratings && ratings.points) || [];
            const ratingsSummary = document.getElementById('faculty-ratings-summary');
            if (ratingsHost) {
                if (!ratings || !ratings.total) {
                    showEmpty(ratingsHost, 'No rating data available.');
                    if (ratingsSummary) ratingsSummary.textContent = '';
                } else {
                    if (ratingsSummary) {
                        const mean = typeof ratings.average === 'number'
                            ? ratings.average.toFixed(2) : '—';
                        ratingsSummary.textContent =
                            `Mean rating ${mean} / 5 · ${ratings.total} rated submission${ratings.total === 1 ? '' : 's'}`;
                    }
                    setTimeout(() => {
                        this.charts.ratings = new Chart(mountCanvas(ratingsHost), {
                            type: 'bar',
                            data: {
                                labels: bands.map(b => `${b.band} · ${b.label}`),
                                datasets: [
                                    { label: 'Positive', data: bands.map(b => b.positive || 0), backgroundColor: '#2f6f4e' },
                                    { label: 'Neutral', data: bands.map(b => b.neutral || 0), backgroundColor: '#b7791f' },
                                    { label: 'Negative', data: bands.map(b => b.negative || 0), backgroundColor: '#b33a3a' }
                                ]
                            },
                            options: {
                                responsive: true,
                                maintainAspectRatio: false,
                                scales: {
                                    x: { stacked: true },
                                    // Submissions are whole people: no fractional ticks.
                                    y: { stacked: true, beginAtZero: true, ticks: { precision: 0 } }
                                },
                                plugins: {
                                    legend: { position: 'bottom' },
                                    tooltip: {
                                        callbacks: {
                                            // Add the band's own total to the
                                            // per-segment default, so a tooltip
                                            // reads "Negative: 3" plus "5 in band".
                                            footer: (items) => {
                                                const band = bands[items[0].dataIndex];
                                                return band ? `Total in band: ${band.total}` : '';
                                            }
                                        }
                                    }
                                }
                            }
                        });
                    }, 100);
                }
            }

            // ---- Average by aspect (horizontal bars, fixed 1-5 axis) ---------
            // The API sorts strongest-first, which is the order Chart.js plots
            // a vertical category axis (first label at the top), so no reversal
            // is needed and the weakest aspect lands at the bottom.
            const aspectsHost = document.getElementById('faculty-chart-aspects');
            const aspectPoints = (aspects && aspects.points) || [];
            if (aspectsHost) {
                if (!aspectPoints.length) {
                    showEmpty(aspectsHost, 'No aspect data available.');
                } else {
                    // ~30px per bar so nine aspects don't collapse into
                    // slivers, same growth rule the courses chart uses.
                    const height = Math.max(280, Math.min(560, aspectPoints.length * 30 + 70));
                    if (height > aspectsHost.clientHeight) aspectsHost.style.height = `${height}px`;
                    setTimeout(() => {
                        this.charts.aspects = new Chart(mountCanvas(aspectsHost), {
                            type: 'bar',
                            data: {
                                labels: aspectPoints.map(p => p.label),
                                datasets: [{
                                    label: 'Average score',
                                    data: aspectPoints.map(p => p.average || 0),
                                    // Colour bands the 1-5 scale the way the
                                    // paper theme colours sentiment elsewhere.
                                    backgroundColor: aspectPoints.map(p =>
                                        p.average >= 4 ? '#2f6f4e' : (p.average >= 3 ? '#b7791f' : '#b33a3a')),
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
                                            // A 4.6 from three students must not
                                            // read like a 4.6 from three hundred.
                                            label: ctx => {
                                                const point = aspectPoints[ctx.dataIndex] || {};
                                                return `Average ${(point.average || 0).toFixed(2)} / 5 · n=${point.responses || 0}`;
                                            }
                                        }
                                    }
                                },
                                scales: {
                                    // Fixed 1-5 so bar lengths are comparable
                                    // between aspects and between reloads.
                                    x: { min: 1, max: 5, ticks: { stepSize: 1 } },
                                    y: { ticks: { autoSkip: false } }
                                }
                            }
                        });
                    }, 100);
                }
            }

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
