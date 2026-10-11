// Lightweight DOM doubles test JS logic only, not rendering or browser APIs.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
const source = await readFile(new URL('../static/forms.js', import.meta.url), 'utf8');
const events = {}, windowEvents = {};
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.dataset = {}; this.listeners = {}; }
  setAttribute(key, value) { this[key] = value; }
  removeAttribute(key) { delete this[key]; }
  append(...items) { this.children.push(...items); }
  prepend(item) { this.children.unshift(item); }
  replaceChildren() { this.children = []; }
  addEventListener(key, fn) { this.listeners[key] = fn; }
  focus() { this.focused = true; }
  remove() { this.removed = true; }
}
const input = new Element('input');
input.files = [{name: 'synthetic-a.png'}, {name: 'synthetic-b.png'}];
let previews;
input.closest = () => ({after: node => { previews = node; }});
const document = {
  body: {dataset: {working: 'Sending', networkError: 'Check before retrying', remove: 'Remove', selectedPreview: 'Preview', previewUnavailable: 'Unavailable'}},
  addEventListener: (key, fn) => { events[key] = fn; },
  createElement: tag => new Element(tag),
  querySelectorAll: selector => selector.startsWith('input') ? [input] : [],
  getElementById: () => null,
};
let requestCount = 0, respond, destination, confirms = true;
class FormData { append() {} }
class Transfer {
  constructor() { this.files = []; this.items = {add: item => this.files.push(item)}; }
}
const window = {
  fetch: true, FormData,
  confirm: () => confirms,
  addEventListener: (key, fn) => { windowEvents[key] = fn; },
  location: {href: 'http://localhost/cases/1', origin: 'http://localhost', assign: url => { destination = url; }},
};
class LocalURL extends URL {
  static createObjectURL() { return 'blob:synthetic'; }
  static revokeObjectURL() {}
}
vm.runInNewContext(source, {
  document, window, FormData, DataTransfer: Transfer, URL: LocalURL,
  fetch: async (...args) => { requestCount++; return respond(...args); },
  DOMParser: class {parseFromString(text) { return {querySelector: () => ({textContent: text})}; }},
  history: {back() {}},
});
function form() {
  const value = new Element('form');
  value.method = 'post'; value.action = '/cases/1/submit';
  value.button = new Element('button');
  value.querySelector = selector => selector === '[data-confirm]' ? value.confirmation : value.box;
  value.querySelectorAll = selector => selector.startsWith('[data-disabled')
    ? (value.button.dataset.disabledBySubmit ? [value.button] : []) : [value.button];
  value.append = box => { value.box = box; };
  return value;
}
function submit(target) { return {target, preventDefault() {this.prevented = true;}}; }
const bad = form();
respond = async () => ({ok: false, text: async () => 'Consent required'});
await events.submit(submit(bad));
assert.equal(bad.box.textContent, 'Consent required');
assert.equal(bad.button.disabled, false);
assert.equal(bad.dataset.submitting, undefined);
assert.equal(bad.box.role, 'alert');
assert.equal(bad.box.focused, true);
respond = async () => { throw new Error('Network failed'); };
await events.submit(submit(bad));
assert.equal(bad.box.textContent, 'Check before retrying');
assert.equal(bad.button.disabled, false);
let resolve;
respond = () => new Promise(done => { resolve = done; });
const busy = form();
const pending = events.submit(submit(busy));
const before = requestCount;
const duplicate = submit(busy);
await events.submit(duplicate);
assert.equal(requestCount, before);
assert.equal(duplicate.prevented, true);
resolve({ok: false, text: async () => 'Retry'});
await pending;
assert.equal(busy.button.disabled, false);
respond = async (_url, options) => {
  assert.equal(options.headers['X-Form-Response'], 'json');
  return {ok: true, headers: {get: () => 'application/json'}, json: async () => ({redirect: '/cases/1'})};
};
await events.submit(submit(busy));
assert.equal(destination, 'http://localhost/cases/1');
const close = form(); close.confirmation = {dataset: {confirm: 'Close?'}}; confirms = false;
const closeEvent = submit(close); const previous = requestCount;
await events.submit(closeEvent);
assert.equal(closeEvent.prevented, true);
assert.equal(requestCount, previous);
input.listeners.change();
assert.equal(previews.children.length, 2);
assert.equal(previews.children[0].children[1].textContent, 'synthetic-a.png');
previews.children[0].children[2].listeners.click();
assert.deepEqual(input.files.map(file => file.name), ['synthetic-b.png']);
assert.equal(previews.children.length, 1);
assert.equal(input.focused, true);
console.log('PASS: JS server error/network recovery, retry, duplicate prevention, committed redirect, close cancellation, two previews and pre-upload removal (DOM doubles; not a browser test).');
