// Camera API doubles verify lifecycle and errors; no physical camera is accessed.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
const source = await readFile(new URL('../static/camera.js', import.meta.url), 'utf8');
class Element {
  constructor() { this.listeners = {}; this.hidden = true; this.disabled = false; }
  addEventListener(name, fn) { this.listeners[name] = fn; }
  focus() { this.focused = true; }
  dispatchEvent(event) { this.event = event.type; }
}
const input = new Element(), form = new Element(), start = new Element(), panel = new Element();
const capture = new Element(), video = new Element(), message = new Element(), stop = new Element();
const camera = new Element();
camera.dataset = {error: 'Camera unavailable', ready: 'Ready', taken: 'Captured', captureError: 'Capture failed', filename: 'camera-photo.jpg'};
form.querySelector = () => input;
camera.closest = () => form;
const elements = {'[data-camera-start]':start, '[data-camera-panel]':panel,
  '[data-camera-capture]':capture, video, '[data-camera-message]':message, '[data-camera-stop]':stop};
camera.querySelector = name => elements[name];
video.play = async () => {};
video.videoWidth = 1920; video.videoHeight = 1440;
let tracksStopped = 0, fail = false, captureFail = false;
const stream = {getTracks: () => [{stop() {tracksStopped++;}}]};
class Transfer {
  constructor() {this.files = []; this.items = {add: value => this.files.push(value)};}
}
const windowEvents = {};
vm.runInNewContext(source, {
  document: {querySelectorAll: () => [camera], createElement: () => ({
    getContext: () => captureFail ? null : ({drawImage() {}}), toBlob: callback => callback({type:'image/jpeg'}),
  })},
  navigator: {mediaDevices: {getUserMedia: async constraints => {
    assert.equal(constraints.audio, false);
    assert.equal(constraints.video.facingMode.ideal, 'environment');
    if (fail) throw new Error('Permission denied');
    return stream;
  }}},
  window: {addEventListener: (name, fn) => { windowEvents[name] = fn; }},
  DataTransfer: Transfer,
  File: class {constructor(_data, name, options) {this.name=name; this.type=options.type;}},
  Event: class {constructor(type) {this.type=type;}},
});
assert.equal(start.hidden, false);
await start.listeners.click();
assert.equal(panel.hidden, false);
assert.equal(video.srcObject, stream);
assert.equal(message.textContent, 'Ready');
video.listeners.loadeddata();
assert.equal(capture.disabled, false);
captureFail = true;
await capture.listeners.click();
assert.equal(message.textContent, 'Capture failed');
assert.equal(capture.disabled, false);
captureFail = false;
await capture.listeners.click();
assert.equal(input.files.length, 1);
assert.equal(input.files[0].type, 'image/jpeg');
assert.equal(input.event, 'change');
assert.equal(input.focused, true);
assert.equal(message.textContent, 'Captured');
assert.equal(panel.hidden, true);
assert.equal(tracksStopped, 1);
fail=true;
await start.listeners.click();
assert.equal(message.textContent, 'Camera unavailable');
assert.equal(start.disabled, false);
assert.equal(panel.hidden, true);
fail=false;
await start.listeners.click();
form.listeners.submit();
assert.equal(tracksStopped, 2);
assert.equal(video.srcObject, null);
await start.listeners.click();
windowEvents.pagehide();
assert.equal(tracksStopped, 3);
console.log('PASS: camera opening, rear-camera preference, capture to pending file, permission-error recovery and track cleanup on capture/submit/page exit (API doubles; no hardware test).');
