/*
 * Regression tests for independent student evaluation categories.
 * Run with: node frontend/tests/student-category-submission.test.mjs
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import assert from 'node:assert/strict';

const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(here, '..', 'js', 'student.js'), 'utf8');

function createStudent() {
    const requests = [];
    const storage = new Map([
        ['evaluation_draft_faculty', 'professor draft'],
        ['evaluation_draft_staff', 'staff draft'],
        ['evaluation_draft_facilities', 'facilities draft'],
        ['evaluation_draft_payment', 'payments draft'],
    ]);
    const elements = {
        'eval-selection': { classList: classList() },
        'eval-form-content': { classList: classList(), innerHTML: '' },
        'sel-course': { value: 'BSIT/AIT' },
        'sel-year': { value: '2nd Year' },
    };
    const document = {
        getElementById: (id) => elements[id] || null,
        querySelector: () => ({ disabled: false }),
    };
    const localStorage = {
        getItem: (key) => storage.get(key) || null,
        setItem: (key, value) => storage.set(key, value),
        removeItem: (key) => storage.delete(key),
    };
    const sessionStorage = { setItem: () => {}, removeItem: () => {} };
    const window = { addEventListener: () => {} };
    const APP = {
        openModal: (html) => { APP.modal = html; },
        closeModal: () => {},
    };
    const student = new Function(
        'document', 'window', 'localStorage', 'sessionStorage', 'fetch',
        'showToast', 'showLoading', 'hideLoading', 'getApiBase', 'APP',
        source + '\nreturn STUDENT;'
    )(
        document, window, localStorage, sessionStorage,
        async (url, options) => {
            requests.push({ url, options });
            return { ok: true };
        },
        () => {}, () => {}, () => {}, () => 'https://api.test', APP
    );
    return { student, requests, storage, elements, APP };
}

function classList() {
    const values = new Set();
    return {
        add: (value) => values.add(value),
        remove: (value) => values.delete(value),
        contains: (value) => values.has(value),
    };
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

await test('category chooser shows four individual evaluation buttons', () => {
    const { student, elements } = createStudent();
    student.renderCategorySelection();
    const markup = elements['eval-selection'].innerHTML;
    for (const label of [
        'Evaluate Professor', 'Evaluate Facilities', 'Evaluate Staff', 'Evaluate Payments',
    ]) {
        assert.ok(markup.includes(label), `missing ${label} button`);
    }
    assert.equal((markup.match(/class="eval-category-button"/g) || []).length, 4);
});

await test('choosing a category renders only that category form', () => {
    const { student, elements } = createStudent();
    student.facilitiesFormContent = () => '<p>Facilities-only questions</p>';
    student.openCategory('facilities');
    const markup = elements['eval-form-content'].innerHTML;
    assert.match(markup, /Evaluate Facilities/);
    assert.match(markup, /Facilities-only questions/);
    assert.doesNotMatch(markup, /Evaluate Professor|Evaluate Staff|Evaluate Payments/);
    assert.match(markup, /submitEvaluation\('facilities'\)/);
});

await test('submitting one category sends one request and clears only its draft', async () => {
    const { student, requests, storage, APP } = createStudent();
    student.currentCategoryIndex = student.categories.indexOf('facilities');
    student.evaluations.facilities = {
        ratings: { cleanliness: 5 },
        share_your_thoughts: 'Clean and comfortable.',
    };
    student.validateCurrentCategory = () => true;
    student.saveCategoryData = () => {};

    await student.submitEvaluation('facilities');

    assert.equal(requests.length, 1);
    const payload = JSON.parse(requests[0].options.body);
    assert.equal(payload.category, 'Facilities');
    assert.equal(payload.course, 'BSIT/AIT');
    assert.equal(payload.year_level, '2nd Year');
    assert.equal(storage.has('evaluation_draft_facilities'), false);
    assert.equal(storage.get('evaluation_draft_faculty'), 'professor draft');
    assert.equal(storage.get('evaluation_draft_staff'), 'staff draft');
    assert.equal(storage.get('evaluation_draft_payment'), 'payments draft');
    assert.match(APP.modal, /Facilities Evaluation Submitted!/);
    assert.match(APP.modal, /Choose Another Evaluation/);
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
