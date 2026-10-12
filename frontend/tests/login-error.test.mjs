import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const appSource = readFileSync(join(here, '..', 'js', 'app.js'), 'utf8');

function makeForm() {
  const form = {
    children: [],
    firstChild: null,
    insertBefore(node, ref) {
      if (!this.firstChild) this.firstChild = node;
      this.children.push(node);
      this._error = node;
    },
    querySelector(selector) {
      return selector === '.login-form-error' ? this._error || null : null;
    },
    remove() {
      this._error = null;
      this.children = [];
      this.firstChild = null;
    },
  };
  return form;
}

const elements = { 'login-form-credential': makeForm() };
const documentStub = {
  getElementById(id) { return elements[id] || null; },
  querySelectorAll() { return []; },
  addEventListener() {},
  createElement(tag) {
    return {
      tagName: tag.toUpperCase(),
      className: '',
      textContent: '',
      setAttribute() {},
      remove() {},
    };
  },
};

const APP = new Function('document', 'STUDENT', 'ADMIN', 'FACULTY', `${appSource}; return APP;`)(
  documentStub,
  { handleLogin() {} },
  { handleLogin() {} },
  { handleLogin() {} }
);

APP.showCredentialError('Invalid email or password.');
assert.equal(elements['login-form-credential'].querySelector('.login-form-error').textContent, 'Invalid email or password.');
APP.clearCredentialError();
assert.equal(elements['login-form-credential'].querySelector('.login-form-error'), null);
console.log('login error handling tests passed');
