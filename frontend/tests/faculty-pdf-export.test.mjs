/*
 * Regression tests for PDF-only chart data labels.
 * Run with: node frontend/tests/faculty-pdf-export.test.mjs
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import assert from 'node:assert/strict';

const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(here, '..', 'js', 'faculty.js'), 'utf8');

function createContext() {
    const labels = [];
    return {
        labels,
        globalCompositeOperation: 'source-over',
        save() {},
        restore() {},
        scale() {},
        setTransform() {},
        fillRect() {},
        measureText: (text) => ({ width: text.length * 6 }),
        strokeText: (text) => labels.push(String(text)),
        fillText() {},
    };
}

function loadFaculty(chart) {
    const context = createContext();
    const exportCharts = [];
    const document = {
        createElement: () => ({
            style: {},
            getContext: () => context,
            toDataURL: () => 'data:image/png;base64,exported-chart',
        }),
    };
    class Chart {
        static getChart(canvas) {
            return canvas === chart.canvas ? chart : null;
        }

        constructor(canvas, config) {
            this.canvas = canvas;
            this.config = config;
            this.data = config.data;
            this.options = config.options;
            this.width = chart.width;
            this.height = chart.height;
            this.ctx = context;
            canvas.width = Math.round(this.width * config.options.devicePixelRatio);
            canvas.height = Math.round(this.height * config.options.devicePixelRatio);
            exportCharts.push(this);
        }

        getDatasetMeta(index) {
            return chart.getDatasetMeta(index);
        }

        destroy() {
            this.destroyed = true;
        }
    }
    const factory = new Function('Chart', 'document', source + '\nreturn FACULTY;');
    return { FACULTY: factory(Chart, document), context, exportCharts };
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

await test('horizontal bar labels include formatted values and skip zero values', () => {
    const chart = {
        width: 400,
        height: 200,
        config: { type: 'bar' },
        options: { indexAxis: 'y' },
        data: { datasets: [{ label: 'Average score', data: [4.5, 0] }] },
        canvas: null,
        getDatasetMeta: () => ({
            data: [
                { getProps: () => ({ x: 200, y: 30, base: 50, width: 150, height: 20 }) },
                { getProps: () => ({ x: 50, y: 60, base: 50, width: 0, height: 20 }) },
            ],
        }),
    };
    const sourceCanvas = { width: 800, height: 400 };
    chart.canvas = sourceCanvas;
    const { FACULTY, context, exportCharts } = loadFaculty(chart);

    assert.equal(FACULTY._chartImageWithDataLabels(sourceCanvas, 200, 100), 'data:image/png;base64,exported-chart');
    assert.deepEqual(context.labels, ['4.50']);
    assert.equal(sourceCanvas.width, 800, 'the live canvas must remain unchanged');
    assert.equal(exportCharts[0].config.options.responsive, false);
    assert.equal(exportCharts[0].config.options.animation, false);
    assert.ok(Math.abs(exportCharts[0].config.options.devicePixelRatio - 300 / 25.4 * 0.5) < 0.001);
    assert.equal(exportCharts[0].destroyed, true, 'the temporary export chart must be released');
});

await test('doughnut labels include slice counts', () => {
    const chart = {
        width: 300,
        height: 200,
        config: { type: 'doughnut' },
        options: {},
        data: { datasets: [{ data: [12] }] },
        canvas: null,
        getDatasetMeta: () => ({
            data: [{
                getProps: () => ({
                    x: 150, y: 100, startAngle: 0, endAngle: Math.PI,
                    innerRadius: 40, outerRadius: 80,
                }),
            }],
        }),
    };
    const sourceCanvas = { width: 600, height: 400 };
    chart.canvas = sourceCanvas;
    const { FACULTY, context } = loadFaculty(chart);

    FACULTY._chartImageWithDataLabels(sourceCanvas, 150, 100);
    assert.deepEqual(context.labels, ['12']);
});

let failed = 0;
for (const result of results) {
    if (result.ok) {
        console.log('  PASS  ' + result.name);
    } else {
        failed++;
        console.log('  FAIL  ' + result.name);
        console.log('        ' + (result.err && result.err.message));
    }
}
console.log('\n' + (results.length - failed) + '/' + results.length + ' passed');
process.exit(failed ? 1 : 0);
