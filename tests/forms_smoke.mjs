// Lightweight DOM doubles test JS logic only, not rendering or browser APIs.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
const source = await readFile(new URL('../static/forms.js', import.meta.url), 'utf8');
const events = {}, windowEvents = {};
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.dataset = {}; this.listeners = {}; this.attributes = {}; }
  setAttribute(key, value) { this.attributes[key] = value; this[key] = value; }
  getAttribute(key) { return this.attributes[key] ?? null; }
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
const localTime = new Element('time');
localTime.setAttribute('datetime', '2026-07-15 01:00:00');
localTime.textContent = '2026-07-15 01:00:00 UTC';
const winterTime = new Element('time');
winterTime.setAttribute('datetime', '2026-01-15T12:00:00+00:00');
winterTime.textContent = '2026-01-15T12:00:00+00:00 UTC';
const invalidTime = new Element('time');
invalidTime.setAttribute('datetime', 'not-a-date'); invalidTime.textContent = 'unchanged';
const timezoneNotice = new Element('p'); timezoneNotice.hidden = true;
input.closest = () => ({after: node => { previews = node; }});
const document = {
  body: {dataset: {working: 'Sending', networkError: 'Check before retrying', remove: 'Remove', selectedPreview: 'Preview', previewUnavailable: 'Unavailable', timeLocal:'Times use your device’s timezone.'}},
  addEventListener: (key, fn) => { events[key] = fn; },
  createElement: tag => new Element(tag),
  querySelectorAll: selector => selector.startsWith('input') ? [input] : selector === 'time[data-local-time]' ? [localTime,winterTime,invalidTime] : [],
  querySelector: () => timezoneNotice,
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
  // Force a device timezone to check UTC parsing, day boundaries and DST.
  Intl: {DateTimeFormat: class {constructor(_locale, options) {
    return new Intl.DateTimeFormat('en-US', {...options, timeZone:'America/New_York'});
  }}},
  fetch: async (...args) => { requestCount++; return respond(...args); },
  DOMParser: class {parseFromString(text) { return {querySelector: () => ({textContent: text})}; }},
  history: {back() {}},
});
assert.match(localTime.textContent, /Jul 14, 2026/);
assert.match(localTime.textContent, /9:00 PM EDT/);
assert.match(winterTime.textContent, /7:00 AM EST/);
assert.equal(localTime.getAttribute('datetime'), '2026-07-15 01:00:00');
assert.equal(localTime.title, '2026-07-15 01:00:00 UTC');
assert.equal(invalidTime.textContent, 'unchanged');
assert.equal(timezoneNotice.hidden, false);
assert.equal(timezoneNotice.textContent, 'Times use your device’s timezone.');
function form() {
  const value = new Element('form');
  value.setAttribute('method', 'post'); value.setAttribute('action', '/cases/1/submit');
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
// HTML forms expose named controls as properties. name="action" must not
// redirect fetch to the input element instead of the form's actual URL.
const claim = form();
claim.setAttribute('action', '/cases/1/transition');
claim.action = new Element('input');
claim.action.name = 'action'; claim.action.value = 'claim';
respond = async (url) => {
  assert.equal(url, '/cases/1/transition');
  return {ok: true, headers: {get: () => 'application/json'}, json: async () => ({redirect: '/cases/1'})};
};
destination = undefined;
await events.submit(submit(claim));
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
console.log('PASS: JS device-timezone display/UTC parsing/DST/date-boundary handling, named-action assignment, server/network recovery, retry, duplicate prevention, redirect, close cancellation and image previews/removal (DOM doubles; not a browser test).');
