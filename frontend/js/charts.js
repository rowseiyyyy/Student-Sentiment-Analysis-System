/* ============================================================
   CHARTS — shared Chart.js renderers for the faculty-facing panels.

   One module owns the drawing code for every chart that appears on BOTH the
   admin Analytics tab and the faculty dashboard, so the two views can never
   drift apart: a colour, tooltip or empty-state change lands in both at once,
   and the admin Analytics tab renders the faculty charts from the very same
   code the faculty view uses (no duplicated build-up).

   Contract
   --------
   Every renderer takes (host, data, store, key):
     host  - the .chart-container element to draw into (missing host = no-op,
             so a chart hidden by visibility settings is simply skipped).
     data  - the raw API payload for that panel (or null when the fetch was
             skipped/failed); each renderer degrades to its own readable
             empty-state caption instead of an axis-only canvas.
     store - the page's chart registry (FACULTY.charts / ADMIN.charts) and
             key, so the page's destroyCharts() keeps working unchanged.
   Drawing waits 100ms so the layout has settled (the same delay both views
   used before this module existed).

   Loaded after utils.js/api.js and before admin.js/faculty.js (index.html).
   ============================================================ */

const CHARTS = {
    // Shared empty-state for a panel with nothing to draw: a readable
    // caption centred in the card, never a bare axis.
    showEmpty(host, message) {
        if (!host) return;
        host.style.display = 'flex';
        host.style.alignItems = 'center';
        host.style.justifyContent = 'center';
        host.innerHTML = `<p class="text-muted text-center">${message}</p>`;
    },

    // A canvas created by hand (rather than declared in the markup) so one
    // host can serve either the chart or the caption.
    mountCanvas(host) {
        host.style.display = '';
        host.style.alignItems = '';
        host.style.justifyContent = '';
        host.innerHTML = '';
        const canvas = document.createElement('canvas');
        host.appendChild(canvas);
        return canvas;
    },

    // Drop the previous instance for this key before redrawing, so a
    // re-render never trips Chart.js' "canvas already in use" guard.
    _release(store, key) {
        const previous = store && store[key];
        if (previous && typeof previous.destroy === 'function') {
            try { previous.destroy(); } catch (e) { /* already gone */ }
        }
        if (store) store[key] = null;
    },

    // A program/aspect list runs longer than the stylesheet's chart height
    // (280px, or 240px on small screens): give the bars ~30px each rather
    // than squeezing a dozen of them into slivers. Only grows, and is capped
    // so the card cannot run away down the page.
    listHeight(count) {
        return Math.max(280, Math.min(560, count * 30 + 70));
    },

    _grow(host, height) {
        if (host && height > host.clientHeight) host.style.height = `${height}px`;
    },

    // ---- Sentiment Split (doughnut) ------------------------------------
    // data: /analytics/overall payload. The "how many" view: every
    // submission that carries a sentiment, counted once.
    sentimentSplit(host, data, store, key) {
        if (!host) return;
        const breakdown = (data && data.breakdown) || {};
        if (!breakdown.total) {
            this.showEmpty(host, 'No sentiment data available.');
            return;
        }
        setTimeout(() => {
            this._release(store, key);
            store[key] = new Chart(this.mountCanvas(host), {
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
    },

    // ---- Rating Distribution (stacked 1-5 histogram) --------------------
    // data: /analytics/ratings/distribution payload. The API returns all
    // five bands zero-filled, so the x-axis keeps a stable 1-5 scale instead
    // of collapsing to whichever bands happen to hold data. Each stack
    // segment is the sentiment of the submissions that landed in that band.
    // summaryEl (optional) gets the "Mean rating x / 5 · n rated" caption.
    ratingDistribution(host, data, summaryEl, store, key) {
        if (!host) return;
        const bands = (data && data.points) || [];
        if (!data || !data.total) {
            this.showEmpty(host, 'No rating data available.');
            if (summaryEl) summaryEl.textContent = '';
            return;
        }
        if (summaryEl) {
            const mean = typeof data.average === 'number' ? data.average.toFixed(2) : '—';
            summaryEl.textContent =
                `Mean rating ${mean} / 5 · ${data.total} rated submission${data.total === 1 ? '' : 's'}`;
        }
        setTimeout(() => {
            this._release(store, key);
            store[key] = new Chart(this.mountCanvas(host), {
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
                                // Add the band's own total to the per-segment
                                // default, so a tooltip reads "Negative: 3"
                                // plus "5 in band".
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
    },

    // ---- Average by Aspect (horizontal bars, fixed 1-5 axis) ------------
    // data: /analytics/ratings/aspects payload. The API sorts strongest-
    // first, which is the order Chart.js plots a vertical category axis
    // (first label at the top), so no reversal is needed and the weakest
    // aspect lands at the bottom.
    aspectAverages(host, data, store, key) {
        if (!host) return;
        const points = (data && data.points) || [];
        if (!points.length) {
            this.showEmpty(host, 'No aspect data available.');
            return;
        }
        // ~30px per bar so nine aspects don't collapse into slivers — the
        // same growth rule the courses chart uses.
        this._grow(host, this.listHeight(points.length));
        setTimeout(() => {
            this._release(store, key);
            store[key] = new Chart(this.mountCanvas(host), {
                type: 'bar',
                data: {
                    labels: points.map(p => p.label),
                    datasets: [{
                        label: 'Average score',
                        data: points.map(p => p.average || 0),
                        // Colour bands the 1-5 scale the way the paper theme
                        // colours sentiment elsewhere.
                        backgroundColor: points.map(p =>
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
                                // A 4.6 from three students must not read like
                                // a 4.6 from three hundred.
                                label: ctx => {
                                    const point = points[ctx.dataIndex] || {};
                                    return `Average ${(point.average || 0).toFixed(2)} / 5 · n=${point.responses || 0}`;
                                }
                            }
                        }
                    },
                    scales: {
                        // Fixed 1-5 so bar lengths are comparable between
                        // aspects and between reloads.
                        x: { min: 1, max: 5, ticks: { stepSize: 1 } },
                        y: { ticks: { autoSkip: false } }
                    }
                }
            });
        }, 100);
    },


    // ---- Sentiment by Courses (net sentiment, -100..+100) ---------------
    // data: /analytics/courses payload ({points: [...]} or null). One bar
    // per course, scored (Positive - Negative) / total x 100 on a fixed
    // -100..+100 axis so bar lengths stay comparable between programs. The
    // API returns the rows best-to-worst and Chart.js plots the first label
    // of a vertical category axis at the TOP (chart.js 4.4.0, per
    // index.html), so the best-scoring course sits at the top with no
    // reversal needed here.
    sentimentCourses(host, data, store, key) {
        if (!host) return;
        const points = (data && data.points) || [];
        if (!points.length) {
            // Empty dataset: the same readable placeholder the admin charts
            // use instead of a broken axis-only canvas.
            this.showEmpty(host, 'No course data available.');
            return;
        }
        this._grow(host, this.listHeight(points.length));
        const scoreColor = (score) =>
            score > 0 ? '#2f6f4e' : (score < 0 ? '#b33a3a' : '#b7791f');
        setTimeout(() => {
            this._release(store, key);
            store[key] = new Chart(this.mountCanvas(host), {
                type: 'bar',
                data: {
                    labels: points.map(p => p.course),
                    datasets: [{
                        label: 'Sentiment score',
                        data: points.map(p => p.sentiment_score || 0),
                        backgroundColor: points.map(p => scoreColor(p.sentiment_score)),
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
                                // carried by a couple of responses is readable
                                // as thin data.
                                label: ctx => {
                                    const point = points[ctx.dataIndex] || {};
                                    return `Score ${(point.sentiment_score || 0).toFixed(1)} · n=${point.total || 0} (P${point.positive || 0} / Neu${point.neutral || 0} / Neg${point.negative || 0})`;
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
                        // reverse:false pins descending order (best course at
                        // the top); autoSkip:false keeps every course named.
                        y: { reverse: false, ticks: { autoSkip: false } }
                    }
                }
            });
        }, 100);
    },


    // ---- Comment row (Top Complaints / Top Appreciations) ---------------
    // The quote-row markup shared by both views; each page keeps its own
    // column/card wrapper around it.
    //   truncate       - max characters shown before the cut.
    //   showConfidence - append the model confidence (admin presentation).
    commentRowHtml(item, opts = {}) {
        const truncate = opts.truncate || 150;
        const text = escapeHtml(String(item.comment || '').substring(0, truncate));
        const meta = escapeHtml(item.category || '');
        const confidence = opts.showConfidence
            ? ' | Confidence: ' + formatNumber(item.confidence)
            : '';
        const size = opts.showConfidence ? '.88rem' : '.85rem';
        const smallStyle = opts.showConfidence
            ? 'class="text-muted" style="font-family:var(--font-mono);font-size:.72rem;"'
            : 'style="font-family:var(--font-mono);font-size:.72rem;color:var(--ink-faint);"';
        return '<div style="padding:.5rem 0;border-bottom:1px dashed var(--paper-line);">' +
            `<p style="font-size:${size};">"${text}"</p>` +
            `<small ${smallStyle}>${meta}${confidence}</small></div>`;
    },
};
