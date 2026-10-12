import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(here, '..', 'js', 'utils.js'), 'utf8');

const api = new Function(
  'window',
  'document',
  `${source}\nreturn { filterModelPerfRows, modelPerfDisplayName };`
)({ ASIATECH_API_BASE: 'http://localhost:8000/api/v1' }, { createElement: () => ({ textContent: '', innerHTML: '' }) });

const rows = [
  { algorithm: 'mBERT Hybrid', accuracy: 0.91 },
  { algorithm: 'Multilingual MiniLM', accuracy: 0.88 },
  { algorithm: 'SVM', accuracy: 0.74 },
  { algorithm: 'Random Forest', accuracy: 0.70 },
];

const visible = api.filterModelPerfRows(rows);
assert.deepEqual(visible.map((row) => row.algorithm), ['mBERT Hybrid', 'Multilingual MiniLM', 'SVM']);
assert.equal(api.modelPerfDisplayName('Multilingual MiniLM'), 'mBERT Hybrid');
assert.equal(api.modelPerfDisplayName('mBERT Hybrid'), 'mBERT Hybrid');
assert.equal(api.modelPerfDisplayName('SVM'), 'SVM');
console.log('model-performance tests passed');
