/**
 * Asiatech Sentiment Analysis - Faculty Module
 * Updated for "Asiatech Feedback Casefile" paper theme design.
 * Faculty dashboard: read-only sentiment summary, charts, and reports.
 * All data fetching, export, and logic preserved.
 */

const FACULTY = {
    currentUser: null,
    charts: {},

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
        this.renderFacultyTab('overview');
    },

    renderFacultyTab(tab) {
        const container = document.getElementById('faculty-content');
        container.innerHTML = '';
        const content = document.createElement('div');
        content.id = 'faculty-tab-content';
        container.appendChild(content);

        switch(tab) {
            case 'overview':
                this.renderOverview(content);
                break;
            case 'analytics':
                this.renderAnalytics(content);
                break;
        }
    },

    // ============================================================
    // OVERVIEW TAB — Paper theme design
    // ============================================================
    async renderOverview(container) {
        container.innerHTML = `<div class="text-center mt-4"><div class="spinner"></div><p>Loading overview...</p></div>`;

        try {
            const overall = await API.getOverallAnalytics();
            const perf = await API.getModelPerformance();

            container.innerHTML = `
                <div class="page-header">
                    <div>
                        <span style="font-family:var(--font-mono);font-size:.7rem;letter-spacing:.12em;text-transform:uppercase;color:var(--ink-faint);display:block;margin-bottom:.35rem;">Faculty Overview</span>
                        <h1><i class="fas fa-chart-pie"></i> Sentiment Overview</h1>
                    </div>
                    <button class="btn btn-success" onclick="FACULTY.exportCSV()">
                        <i class="fas fa-download"></i> Download Report
                    </button>
                </div>

                <div class="stats-grid">
                    <div class="stat-card">
                        <div class="stat-icon green"><i class="fas fa-smile"></i></div>
                        <div class="stat-info">
                            <h3>${overall.breakdown.positive || 0}</h3>
                            <p>Positive Feedbacks</p>
                            <small>${overall.breakdown.positive_pct ? overall.breakdown.positive_pct.toFixed(1) + '%' : ''}</small>
                        </div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-icon yellow"><i class="fas fa-meh"></i></div>
                        <div class="stat-info">
                            <h3>${overall.breakdown.neutral || 0}</h3>
                            <p>Neutral Feedbacks</p>
                            <small>${overall.breakdown.neutral_pct ? overall.breakdown.neutral_pct.toFixed(1) + '%' : ''}</small>
                        </div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-icon red"><i class="fas fa-frown"></i></div>
                        <div class="stat-info">
                            <h3>${overall.breakdown.negative || 0}</h3>
                            <p>Negative Feedbacks</p>
                            <small>${overall.breakdown.negative_pct ? overall.breakdown.negative_pct.toFixed(1) + '%' : ''}</small>
                        </div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-icon blue"><i class="fas fa-file-alt"></i></div>
                        <div class="stat-info">
                            <h3>${overall.evaluation_volume || 0}</h3>
                            <p>Total Evaluations</p>
                        </div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-icon purple"><i class="fas fa-chart-bar"></i></div>
                        <div class="stat-info">
                            <h3>${overall.average_confidence ? overall.average_confidence.toFixed(1) + '%' : 'N/A'}</h3>
                            <p>Avg Confidence</p>
                        </div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-icon blue"><i class="fas fa-trophy"></i></div>
                        <div class="stat-info">
                            <h3 style="font-size:1.1rem;">${perf.best_model || 'N/A'}</h3>
                            <p>Best Model</p>
                        </div>
                    </div>
                </div>

                <div class="chart-grid">
                    <div class="chart-card">
                        <h3><i class="fas fa-chart-pie"></i> Sentiment Distribution</h3>
                        <div class="chart-container"><canvas id="faculty-chart-sentiment"></canvas></div>
                    </div>
                    <div class="chart-card">
                        <h3><i class="fas fa-chart-bar"></i> Category Breakdown</h3>
                        <div class="chart-container"><canvas id="faculty-chart-category"></canvas></div>
                    </div>
                </div>

                <div class="card mt-3">
                    <div class="card-header">
                        <h3><i class="fas fa-table"></i> Model Performance</h3>
                    </div>
                    <div class="table-container">
                        <table class="perf-table">
                            <thead>
                                <tr>
                                    <th>Algorithm</th>
                                    <th>Accuracy</th>
                                    <th>Precision</th>
                                    <th>Recall</th>
                                    <th>F1 Score</th>
                                    <th>Status</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${perf.rows.map(r => `
                                    <tr>
                                        <td><strong>${r.algorithm}</strong> ${r.is_production_model ? '<span class="crown"><i class="fas fa-crown"></i></span>' : ''}</td>
                                        <td>${formatNumber(r.accuracy)}</td>
                                        <td>${formatNumber(r.precision)}</td>
                                        <td>${formatNumber(r.recall)}</td>
                                        <td>${formatNumber(r.f1_score)}</td>
                                        <td>${r.is_production_model ? '<span class="badge badge-positive">Production</span>' : '<span class="badge badge-neutral">Standby</span>'}</td>
                                    </tr>
                                `).join('')}
                                ${perf.rows.length === 0 ? '<tr><td colspan="6" class="text-center text-muted">No training data available.</td></tr>' : ''}
                            </tbody>
                        </table>
                    </div>
                </div>
            `;

            // Render sentiment doughnut chart
            setTimeout(() => {
                const ctx = document.getElementById('faculty-chart-sentiment');
                if (!ctx) return;
                this.charts.sentiment = new Chart(ctx, {
                    type: 'doughnut',
                    data: {
                        labels: ['Positive', 'Neutral', 'Negative'],
                        datasets: [{
                            data: [
                                overall.breakdown.positive || 0,
                                overall.breakdown.neutral || 0,
                                overall.breakdown.negative || 0
                            ],
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
                                        const pct = ((ctx.parsed / total) * 100).toFixed(1);
                                        return `${ctx.label}: ${ctx.parsed} (${pct}%)`;
                                    }
                                }
                            }
                        }
                    }
                });
            }, 100);

            // Category breakdown chart
            setTimeout(async () => {
                const ctx = document.getElementById('faculty-chart-category');
                if (!ctx) return;
                const categories = ['Faculty', 'Staff', 'Facilities', 'Payment'];
                const catData = await Promise.all(
                    categories.map(c => API.getCategoryAnalytics(c).catch(() => null))
                );
                this.charts.category = new Chart(ctx, {
                    type: 'bar',
                    data: {
                        labels: categories,
                        datasets: [
                            { label: 'Positive', data: catData.map(d => d?.breakdown?.positive || 0), backgroundColor: '#2f6f4e' },
                            { label: 'Neutral', data: catData.map(d => d?.breakdown?.neutral || 0), backgroundColor: '#b7791f' },
                            { label: 'Negative', data: catData.map(d => d?.breakdown?.negative || 0), backgroundColor: '#b33a3a' }
                        ]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        scales: { x: { stacked: true }, y: { stacked: true, beginAtZero: true } },
                        plugins: { legend: { position: 'bottom' } }
                    }
                });
            }, 200);

        } catch (error) {
            container.innerHTML = `
                <div class="page-header">
                    <h1><i class="fas fa-chart-pie"></i> Sentiment Overview</h1>
                </div>
                <div class="card">
                    <div class="empty-state">
                        <div class="empty-icon"><i class="fas fa-database"></i></div>
                        <h3>No Data Available</h3>
                        <p>${error.message}</p>
                    </div>
                </div>
            `;
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
                </div>
            </div>
            <div class="chart-grid">
                <div class="chart-card">
                    <h3><i class="fas fa-chart-line"></i> Monthly Trend</h3>
                    <div class="chart-container"><canvas id="faculty-chart-monthly"></canvas></div>
                </div>
                <div class="chart-card">
                    <h3><i class="fas fa-comment-dots"></i> Top Comments</h3>
                    <div id="faculty-top-comments" style="max-height:400px;overflow-y:auto;"></div>
                </div>
            </div>
        `;

        showLoading('Loading analytics...');
        try {
            const [monthly, complaints, appreciations] = await Promise.all([
                API.getMonthlyTrend(),
                API.getTopComplaints(5),
                API.getTopAppreciations(5)
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

            const commentsDiv = document.getElementById('faculty-top-comments');
            let html = '';

            if (complaints.items && complaints.items.length > 0) {
                html += '<h4 style="color:var(--neg);margin-bottom:.5rem;font-family:var(--font-mono);font-size:.72rem;letter-spacing:.06em;text-transform:uppercase;"><i class="fas fa-exclamation-circle"></i> Top Complaints</h4>';
                html += complaints.items.map(c => `
                    <div style="padding:.5rem 0;border-bottom:1px dashed var(--paper-line);">
                        <p style="font-size:.85rem;">"${escapeHtml(c.comment.substring(0, 120))}"</p>
                        <small style="font-family:var(--font-mono);font-size:.72rem;color:var(--ink-faint);">${c.category}</small>
                    </div>
                `).join('');
            }

            if (appreciations.items && appreciations.items.length > 0) {
                html += '<h4 style="color:var(--pos);margin:1rem 0 .5rem;font-family:var(--font-mono);font-size:.72rem;letter-spacing:.06em;text-transform:uppercase;"><i class="fas fa-star"></i> Top Appreciations</h4>';
                html += appreciations.items.map(a => `
                    <div style="padding:.5rem 0;border-bottom:1px dashed var(--paper-line);">
                        <p style="font-size:.85rem;">"${escapeHtml(a.comment.substring(0, 120))}"</p>
                        <small style="font-family:var(--font-mono);font-size:.72rem;color:var(--ink-faint);">${a.category}</small>
                    </div>
                `).join('');
            }

            if (!complaints.items || !complaints.items.length && (!appreciations.items || !appreciations.items.length)) {
                html += '<p class="text-muted text-center">No comment data available.</p>';
            }

            commentsDiv.innerHTML = html;

        } catch (error) {
            container.innerHTML += `
                <div class="card">
                    <div class="empty-state">
                        <div class="empty-icon"><i class="fas fa-exclamation-triangle" style="color:var(--neu);"></i></div>
                        <h3>Analytics Error</h3>
                        <p>${error.message}</p>
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
