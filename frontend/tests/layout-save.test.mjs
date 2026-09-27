/*
 * Regression tests for the layout save payload.
 *
 * The bug these cover: `PUT /dashboard-layout/{page}` requires every widget to
 * carry BOTH `w` and `h` (WidgetSize in app/schemas/dashboard_layout.py), but
 * `_sizes` only records what the admin actually TOUCHED. A width drag wrote
 * `wp` alone and a reorder wrote `order` alone, so the document sent on save was
 * `{"page:card": {"wp": 720}}`, the server answered 422, and every save reported
 * "Could not save the layout" no matter what had been changed.
 *
 * Run with:  node frontend/tests/layout-save.test.mjs
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import assert from 'node:assert/strict';

const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(here, '..', 'js', 'layout.js'), 'utf8');

// layout.js is a browser global script, not a module. Evaluate it with just
// enough of the DOM to exercise the geometry, rather than pulling in a headless
// browser: the save path is pure bookkeeping over `_sizes`.
const win = { innerWidth: 1600, getComputedStyle: () => ({ columnGap: '18px' }) };
const doc = { styleSheets: [] };
const API = { calls: [] };
API.saveDashboardLayout = (name, widgets) => {
    API.calls.push({ name, widgets });
    return Promise.resolve({ ok: true });
};
const factory = new Function('window', 'document', 'console', 'API',
    source + '\nreturn LAYOUT;');
const LAYOUT = factory(win, doc, console, API);

// A minimal widget stand-in. `span` is the authored .span-N class, `h` the
// height its target renders at, `onChart` whether it has a chart body.
function widget(id, opts = {}) {
    const classes = ['chart-card'];
    if (opts.span) classes.push('span-' + opts.span);
    const target = {
        getBoundingClientRect: () => ({ height: opts.h == null ? 300 : opts.h, width: 400 }),
    };
    return {
        id,
        nodeType: 1,
        classList: {
            _c: classes,
            contains: (c) => classes.indexOf(c) !== -1,
        },
        style: { gridColumn: opts.applied || '' },
        parentElement: { children: [], clientWidth: 0 },
        querySelector: (sel) => (sel === '.chart-container' && opts.onChart !== false ? target : null),
    };
}

// Point LAYOUT at a fixed set of widgets, bypassing the real DOM walk.
function withWidgets(widgets) {
    LAYOUT._currentPage = 'page-admin-dashboard';
    LAYOUT._root = { querySelectorAll: () => [] };
    LAYOUT.entries = function () {
        return Object.keys(widgets).map((key) => ({
            key, el: widgets[key], section: widgets[key].parentElement,
            sectionIndex: 0, widgetIndex: 0,
        }));
    };
    // A 3-column grid: the desktop .chart-grid, which is what the authored
    // column count resolves to against the real stylesheet.
    LAYOUT._authoredCols = () => 3;
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

// Every record the serializer emits must satisfy the server's WidgetSize
// contract, which is the invariant the 422 broke.
function assertValidWidget(rec) {
    assert.ok(Number.isInteger(rec.w), 'w must be an integer, got ' + JSON.stringify(rec));
    assert.ok(rec.w >= 1 && rec.w <= 6, 'w out of range: ' + rec.w);
    assert.ok(Number.isInteger(rec.h), 'h must be an integer, got ' + JSON.stringify(rec));
    assert.ok(rec.h >= 120 && rec.h <= 1600, 'h out of range: ' + rec.h);
    if (rec.wp != null) {
        assert.ok(rec.wp >= 120 && rec.wp <= 4000, 'wp out of range: ' + rec.wp);
    }
    if (rec.order != null) {
        assert.ok(rec.order >= 0 && rec.order <= 500, 'order out of range: ' + rec.order);
    }
}

await test('a width resize alone produces a saveable payload', async () => {
    // What a right-edge drag leaves behind: `wp` and nothing else.
    const el = widget('chart-a', { span: 2, h: 320 });
    withWidgets({ 'page-admin-dashboard:chart-a': el });
    LAYOUT._sizes = { 'page-admin-dashboard:chart-a': { wp: 720 } };

    const rec = LAYOUT._serialized()['page-admin-dashboard:chart-a'];
    assertValidWidget(rec);
    assert.equal(rec.wp, 720, 'the pixel width is preserved');
    assert.equal(rec.w, 2, 'w falls back to the authored span');
    assert.equal(rec.h, 320, 'h is measured from the height target');
});

await test('a height resize alone produces a saveable payload', async () => {
    const el = widget('chart-b', { span: 1, h: 260 });
    withWidgets({ 'page-admin-dashboard:chart-b': el });
    LAYOUT._sizes = { 'page-admin-dashboard:chart-b': { h: 500 } };

    const rec = LAYOUT._serialized()['page-admin-dashboard:chart-b'];
    assertValidWidget(rec);
    assert.equal(rec.h, 500);
    assert.equal(rec.w, 1);
});

await test('a reorder alone produces a saveable payload', async () => {
    // _moveRelative stamps only `order` on every widget in the section.
    const el = widget('chart-c', { span: 3, h: 300 });
    withWidgets({ 'page-admin-dashboard:chart-c': el });
    LAYOUT._sizes = { 'page-admin-dashboard:chart-c': { order: 0 } };

    const rec = LAYOUT._serialized()['page-admin-dashboard:chart-c'];
    assertValidWidget(rec);
    assert.equal(rec.order, 0);
});

await test('a corner resize carries every field', async () => {
    const el = widget('chart-d', { span: 2, h: 300 });
    withWidgets({ 'page-admin-dashboard:chart-d': el });
    LAYOUT._sizes = { 'page-admin-dashboard:chart-d': { wp: 640, h: 450, order: 2 } };

    const rec = LAYOUT._serialized()['page-admin-dashboard:chart-d'];
    assertValidWidget(rec);
    assert.deepEqual(rec, { w: 2, h: 450, wp: 640, order: 2 });
});

await test('an unmeasured card falls back to the minimum height, not 0', async () => {
    // A card that is hidden or not yet laid out measures 0. Storing that would
    // be below the server's MIN_H and would 422 all over again.
    const el = widget('chart-e', { span: 2, h: 0 });
    withWidgets({ 'page-admin-dashboard:chart-e': el });
    LAYOUT._sizes = { 'page-admin-dashboard:chart-e': { wp: 400 } };

    const rec = LAYOUT._serialized()['page-admin-dashboard:chart-e'];
    assertValidWidget(rec);
    assert.equal(rec.h, LAYOUT.MIN_H);
});

await test('measured heights are snapped to the step and clamped to the cap', async () => {
    const el = widget('chart-f', { span: 1, h: 337 });
    withWidgets({ 'page-admin-dashboard:chart-f': el });
    LAYOUT._sizes = { 'page-admin-dashboard:chart-f': { wp: 300 } };
    assert.equal(LAYOUT._serialized()['page-admin-dashboard:chart-f'].h, 340);

    const tall = widget('chart-g', { span: 1, h: 5000 });
    withWidgets({ 'page-admin-dashboard:chart-g': tall });
    LAYOUT._sizes = { 'page-admin-dashboard:chart-g': { wp: 300 } };
    assert.equal(LAYOUT._serialized()['page-admin-dashboard:chart-g'].h, LAYOUT.MAX_H);
});

await test('a phone viewport stores a single column', async () => {
    // Below the breakpoint the pixel width is dropped entirely, so the column
    // count is all that is left to describe the card.
    const el = widget('chart-h', { span: 3, h: 300 });
    withWidgets({ 'page-admin-dashboard:chart-h': el });
    LAYOUT._sizes = { 'page-admin-dashboard:chart-h': { wp: 900 } };
    win.innerWidth = 420;
    try {
        const rec = LAYOUT._serialized()['page-admin-dashboard:chart-h'];
        assertValidWidget(rec);
        assert.equal(rec.w, 1);
    } finally {
        win.innerWidth = 1600;
    }
});

await test('save() sends the normalized document, not the raw records', async () => {
    const el = widget('chart-i', { span: 2, h: 300 });
    withWidgets({ 'page-admin-dashboard:chart-i': el });
    LAYOUT._sizes = { 'page-admin-dashboard:chart-i': { wp: 720 } };
    LAYOUT.canEdit = () => true;
    API.calls.length = 0;

    const ok = await LAYOUT.save();
    assert.equal(ok, true, 'save() reports success');
    assert.equal(API.calls.length, 1);
    assert.equal(API.calls[0].name, 'admin_dashboard');
    assertValidWidget(API.calls[0].widgets['page-admin-dashboard:chart-i']);
});

await test('an untouched layout saves as an empty document', async () => {
    withWidgets({});
    LAYOUT._sizes = {};
    LAYOUT.canEdit = () => true;
    API.calls.length = 0;

    assert.equal(await LAYOUT.save(), true);
    assert.deepEqual(API.calls[0].widgets, {});
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