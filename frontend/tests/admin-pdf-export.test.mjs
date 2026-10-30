/*
 * Regression tests for the admin charts-and-analysis PDF report.
 * Run with: node frontend/tests/admin-pdf-export.test.mjs
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import assert from 'node:assert/strict';

const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(here, '..', 'js', 'admin.js'), 'utf8');

function makeCard({ title, canvas, note, table }) {
    const heading = { textContent: title };
    const notes = note ? [{ textContent: note }] : [];
    const rows = table ? [{
        querySelectorAll: () => table.map((value) => ({ textContent: value })),
    }] : [];
    return {
        querySelector: (selector) => selector === 'h3' ? heading : null,
        querySelectorAll: (selector) => {
            if (selector === 'canvas') return canvas ? [canvas] : [];
            if (selector === '.source-note, .text-muted') return notes;
            if (selector === 'table') return table ? [{
                querySelectorAll: () => rows,
            }] : [];
            return [];
        },
    };
}

function loadAdmin(cards) {
    const text = [];
    const images = [];
    const saved = [];
    const errors = [];
    let pages = 1;
    class jsPDF {
        constructor() {
            this.internal = {
                pageSize: { getWidth: () => 297, getHeight: () => 210 },
                getNumberOfPages: () => pages,
            };
        }
        setProperties() {}
        setFont() {}
        setFontSize() {}
        text(value) { text.push(...(Array.isArray(value) ? value : [value])); }
        splitTextToSize(value) { return [value]; }
        addPage() { pages++; }
        addImage(value) { images.push(value); }
        setPage() {}
        save(value) { saved.push(value); }
    }
    const root = {
        querySelectorAll: (selector) => selector === '.chart-card' ? cards : [],
    };
    const document = { getElementById: () => root };
    const factory = new Function(
        'window', 'document', 'FACULTY', 'showToast',
        source + '\nreturn ADMIN;'
    );
    const ADMIN = factory(
        { jspdf: { jsPDF } },
        document,
        { _chartImageWithDataLabels: () => 'data:image/png;base64,high-resolution-chart' },
        (message, type) => { if (type === 'error') errors.push(message); }
    );
    ADMIN.currentTab = 'analytics';
    ADMIN.scopeLabel = () => 'all departments · last 30 days';
    return { ADMIN, text, images, saved, errors, getPages: () => pages };
}

const chartCanvas = { width: 800, height: 400 };
const { ADMIN, text, images, saved, errors, getPages } = loadAdmin([
    makeCard({
        title: 'Sentiment by Category',
        canvas: chartCanvas,
        note: 'Chart analysis note for the selected date range.',
    }),
    makeCard({
        title: 'Average Rating by Aspect',
        table: ['Aspect', 'Average score', 'Responses'],
    }),
]);

ADMIN.exportSummaryPDF();

assert.deepEqual(errors, [], 'report export should not show an error');
assert.equal(images.length, 1, 'the chart should be included');
assert.ok(text.some((line) => String(line).includes('Chart analysis note')),
    'chart analysis notes should be included');
assert.ok(text.some((line) => String(line).includes('Aspect | Average score | Responses')),
    'analysis table rows should be included');
assert.ok(text.some((line) => String(line).includes('all departments · last 30 days')),
    'the active report scope should be included');
assert.equal(getPages(), 3, 'report should include a cover and both analysis sections');
assert.equal(saved.length, 1);
assert.match(saved[0], /^admin-charts-analysis-\d{4}-\d{2}-\d{2}\.pdf$/);

console.log('  PASS  admin PDF includes charts, analysis notes, tables, scope, and pagination');
