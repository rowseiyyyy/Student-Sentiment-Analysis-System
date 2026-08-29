/**
 * Asiatech Sentiment Analysis — Public "Action Taken" Bulletin
 * Read-only, unauthenticated, aggregate view. Renders ONLY category,
 * title, summary, status badge, resolution note, and date — never raw
 * comments, student ids, evaluation ids, or admin internal references.
 * Kept separate from ADMIN so the public page cannot accidentally
 * render admin-only data.
 */

const BULLETIN = {
    render(container, data) {
        const posts = (data && data.posts) || [];
        const stats = {};
        ((data && data.category_stats) || []).forEach(s => { stats[s.category] = s; });

        const statusBadge = (status) => {
            const map = {
                acknowledged: ['badge-acknowledged', 'Acknowledged'],
                in_progress: ['badge-in-progress', 'In Progress'],
                resolved: ['badge-resolved', 'Resolved']
            };
            const cfg = map[status] || map.acknowledged;
            return '<span class="' + cfg[0] + '">' + cfg[1] + '</span>';
        };

        let bodyHtml;
        if (posts.length === 0) {
            bodyHtml = '<div class="card"><div class="empty-state">' +
                '<div class="empty-icon"><i class="fas fa-bullhorn"></i></div>' +
                '<h3>No Updates Yet</h3>' +
                '<p>When the school acts on student feedback, the outcome will be posted here. Check back soon.</p>' +
                '</div></div>';
        } else {
            // Group by category, most recent post first within each group.
            const groups = {};
            posts.forEach(p => {
                const cat = p.category || 'General';
                (groups[cat] = groups[cat] || []).push(p);
            });

            bodyHtml = Object.keys(groups).map(cat => {
                const stat = stats[cat];
                const statLine = stat && stat.total_this_month > 0
                    ? '<p class="source-note">' +
                      escapeHtml(String(stat.total_this_month)) + ' piece' + (stat.total_this_month === 1 ? '' : 's') +
                      ' of feedback like this were received this month' +
                      (stat.negative_this_month > 0
                          ? ' (' + escapeHtml(String(stat.negative_this_month)) + ' flagged negative)'
                          : '') +
                      '. Individual responses always remain anonymous.</p>'
                    : '<p class="source-note">Aggregate feedback counts are shown once submissions are received this month. Individual responses always remain anonymous.</p>';
                const cards = groups[cat].map(p =>
                    '<div class="card bulletin-card">' +
                        '<div class="bulletin-card-header">' +
                            '<h3>' + escapeHtml(p.title) + '</h3>' +
                            statusBadge(p.status) +
                        '</div>' +
                        '<p class="bulletin-summary">' + escapeHtml(p.summary) + '</p>' +
                        (p.resolution_note
                            ? '<div class="bulletin-resolution"><i class="fas fa-check-circle"></i> ' + escapeHtml(p.resolution_note) + '</div>'
                            : '') +
                        '<span class="bulletin-date">Posted ' + escapeHtml(formatDate(p.date_posted)) + '</span>' +
                    '</div>'
                ).join('');
                return '<div class="bulletin-group">' +
                    '<div class="bulletin-group-header">' +
                        '<h2><i class="fas fa-folder-open"></i> ' + escapeHtml(cat) + '</h2>' +
                    '</div>' +
                    statLine +
                    cards +
                '</div>';
            }).join('');
        }

        container.innerHTML = '' +
            '<div class="page-header">' +
                '<div>' +
                    '<span class="page-kicker">Public Bulletin — No Sign-in Required</span>' +
                    '<h1>Action Taken</h1>' +
                '</div>' +
            '</div>' +
            '<p class="source-note bulletin-intro">Your feedback was heard. Below are the actions the school has taken in response to student feedback, grouped by area. No individual responses or names are ever shown here.</p>' +
            bodyHtml;
    }
};
