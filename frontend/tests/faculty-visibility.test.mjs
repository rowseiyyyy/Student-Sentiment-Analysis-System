/*
 * Regression tests for the faculty Analytics visibility gate.
 *
 * The admin's "Manage faculty access" panel decides which charts a faculty
 * account may see. FACULTY.renderAnalytics must honour the map client-side:
 * disabled charts are never fetched, and when NOTHING is shared the
 * "Download Report" button is omitted entirely (the server answers 403 to
 * the export in that state as well) in favour of a friendly empty card.
 *
 * Run with:  node frontend/tests/faculty-visibility.test.mjs
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import assert from 'node:assert/strict';

const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(here, '..', 'js', 'faculty.js'), 'utf8');

// faculty.js is a browser global script, not a module. Evaluate only the
// two pure-UI members (_applyChartVisibility + the header/empty-state part
// of renderAnalytics) with just enough of the DOM and collaborators stubbed.
// The full renderAnalytics also fires data fetches and CHARTS drawing, which
// need no browser here: tests short-circuit before that point.
function loadFaculty({ visibleKeys }) {
    const calls = [];
    const API = {
        getFacultyCharts: () => Promise.resolve({
            charts: ['sentiment_split', 'rating_distribution', 'aspect_averages',
                'sentiment_courses', 'top_comments'].map((key) => ({
                key, visible: visibleKeys.includes(key),
            })),
        }),
        getTopComplaints: () => { calls.push('complaints'); return Promise.resolve({ items: [] }); },
        getTopAppreciations: () => { calls.push('appreciations'); return Promise.resolve({ items: [] }); },
        getCourseAnalytics: () => { calls.push('courses'); return Promise.resolve(null); },
        getOverallAnalytics: () => { calls.push('overall'); return Promise.resolve(null); },
        getRatingDistribution: () => { calls.push('ratings'); return Promise.resolve(null); },
        getAspectAverages: () => { calls.push('aspects'); return Promise.resolve(null); },
    };
    // Minimal element stand-in: innerHTML assignment keeps the raw string so
    // tests can assert on the markup; getElementById/closest/removeChild are
    // only needed by _applyChartVisibility.
    const removed = [];
    function element(id, card = true) {
        return {
            id,
            closest: () => (card ? {
                parentNode: { removeChild: () => removed.push(id) },
            } : null),
        };
    }
    const byId = {
        'faculty-chart-sentiment-split': element('faculty-chart-sentiment-split'),
        'faculty-chart-ratings': element('faculty-chart-ratings'),
        'faculty-chart-aspects': element('faculty-chart-aspects'),
        'faculty-chart-courses': element('faculty-chart-courses'),
        'faculty-top-comments': element('faculty-top-comments'),
        'faculty-ratings-summary': element('faculty-ratings-summary', false),
    };
    const doc = {
        getElementById: (id) => byId[id] || null,
    };
    const CHARTS = {
        sentimentSplit: () => { }, ratingDistribution: () => { },
        aspectAverages: () => { }, sentimentCourses: () => { },
        commentRowHtml: () => '',
    };
    const container = { innerHTML: '' };
    const factory = new Function(
        'API', 'CHARTS', 'document', 'showLoading', 'hideLoading',
        'escapeHtml', 'showToast',
        source + '\nreturn FACULTY;');
    const FACULTY = factory(API, CHARTS, doc,
        () => { }, () => { }, (s) => s, () => { });
    return { FACULTY, container, calls, removed };
}

const results = [];
async function test(name, fn) {
    try {
        await fn();
        results.push({ name, ok: true });
    } catch (err) {
        results.push({ name, ok: false, err });
    }
}

await test('all-disabled hides Download Report and shows the empty state', async () => {
    const { FACULTY, container, calls } = loadFaculty({ visibleKeys: [] });
    await FACULTY.renderAnalytics(container);
    assert.match(container.innerHTML, /No analytics shared/);
    assert.ok(!container.innerHTML.includes('Download Report'),
        'Download Report must be omitted when nothing is shared');
    assert.deepEqual(calls, [], 'no chart endpoint may be called when all are disabled');
});

await test('one enabled chart shows Download Report and fetches only that chart', async () => {
    const { FACULTY, container, calls } = loadFaculty({ visibleKeys: ['sentiment_split'] });
    await FACULTY.renderAnalytics(container);
    assert.ok(container.innerHTML.includes('Download Report'),
        'Download Report must be present while anything is shared');
    assert.deepEqual(calls, ['overall']);
});

await test('top_comments alone fetches exactly its two comment endpoints', async () => {
    const { FACULTY, container, calls } = loadFaculty({ visibleKeys: ['top_comments'] });
    await FACULTY.renderAnalytics(container);
    assert.deepEqual(calls, ['complaints', 'appreciations']);
});

await test('_applyChartVisibility removes only the disabled cards', async () => {
    const { FACULTY, removed } = loadFaculty({ visibleKeys: ['sentiment_split', 'top_comments'] });
    FACULTY._applyChartVisibility(new Set(['sentiment_split', 'top_comments']));
    assert.deepEqual(removed.sort(), [
        'faculty-chart-aspects', 'faculty-chart-courses', 'faculty-chart-ratings',
    ]);
});

let failed = 0;
for (const r of results) {
    if (r.ok) {
        console.log('  PASS  ' + r.name);
    } else {
        failed++;
        console.log('  FAIL  ' + r.name);
        console.log('        ' + (r.err && r.err.message));
    }
}
console.log('\n' + (results.length - failed) + '/' + results.length + ' passed');
process.exit(failed ? 1 : 0);
