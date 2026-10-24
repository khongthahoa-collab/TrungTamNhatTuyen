const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('static/js/essay-uploads.js', 'utf8');

function setup() {
  const state = { now: 0, timers: new Map(), scheduled: [], alerts: [], events: [], closed: 0 };
  let timerId = 0;
  const element = () => ({
    addEventListener() {}, querySelector: () => element(), classList: { remove() {} },
  });
  const panels = Array.from({ length: 4 }, () => {
    const handlers = {};
    const input = { files: [], value: '', addEventListener: (type, callback) => { handlers[type] = callback; } };
    return {
      count: 0, input, handlers,
      querySelectorAll(selector) {
        return selector === '.essay-image-input' ? [input] : Array(this.count).fill({});
      },
    };
  });
  const form = {
    querySelector: () => ({ value: 'csrf' }),
    addEventListener() {},
    querySelectorAll(selector) {
      return selector === '.essay-upload' ? panels
        : Array(panels.reduce((sum, panel) => sum + panel.count, 0)).fill({});
    },
  };
  const context = {
    window: { dispatchEvent: event => state.events.push(event.type) },
    document: {
      hidden: true, hasFocus: () => false,
      getElementById: id => id === 'examForm' ? form : element(),
      createElement: () => ({
        getContext: () => ({ fillRect() {}, drawImage() {} }),
        toBlob(callback, type, quality) {
          state.encoding = { width: this.width, height: this.height, type, quality };
          callback(state.blob === undefined ? { size: 1024, type } : state.blob);
        },
      }),
    },
    Date: { now: () => state.now },
    setTimeout: callback => { state.timers.set(++timerId, callback); return timerId; },
    clearTimeout: id => state.timers.delete(id),
    Event: class { constructor(type) { this.type = type; } },
    alert: message => state.alerts.push(message),
    console,
    createImageBitmap: async () => ({
      width: state.width || 4000, height: state.height || 3000,
      close: () => { state.closed += 1; },
    }),
    record: (...args) => state.scheduled.push(args),
  };
  const instrumented = source
    .replace('    if (frozen) return;\n    pending += 1;', '    record(panel, action, discard); return;\n    pending += 1;')
    .replace(/\}\)\(\);\s*$/, 'window.compressTest = compress; })();');
  vm.runInNewContext(instrumented, context);
  return { state, panels, context, choose(panel, count) {
    panel.input.files = Array.from({ length: count }, () => ({ name: 'test.png', type: 'image/png', size: 100 }));
    panel.handlers.change();
  } };
}

(async () => {
  const { state, panels, context, choose } = setup();
  choose(panels[0], 2);
  choose(panels[0], 2);
  assert.equal(state.scheduled.length, 2, 'queued photos count toward 3/photo-question limit');
  assert.equal(state.alerts.length, 1);
  choose(panels[1], 3);
  choose(panels[2], 3);
  choose(panels[3], 3);
  assert.equal(state.scheduled.length, 8, 'queued photos count toward 10/attempt limit');
  state.scheduled[0][2]();
  choose(panels[3], 3);
  assert.equal(state.scheduled.length, 11, 'discarded upload frees its reserved slot');

  panels[0].handlers.click();
  assert.equal(context.window.examEssayUploads.isChoosing(), true);
  state.now = 119999;
  assert.equal(context.window.examEssayUploads.isChoosing(), true);
  state.now = 120000;
  assert.equal(context.window.examEssayUploads.isChoosing(), false);
  [...state.timers.values()][0]();
  assert.deepEqual(state.events, ['essay-picker-expired']);
  panels[0].handlers.click();
  panels[0].handlers.cancel();
  assert.equal(context.window.examEssayUploads.isChoosing(), false);
  assert.equal(state.timers.size, 0);

  await context.window.compressTest({ size: 100, type: 'image/png' });
  assert.deepEqual(state.encoding, { width: 2000, height: 1500, type: 'image/jpeg', quality: 0.85 });
  state.width = 1200;
  state.height = 4000;
  await context.window.compressTest({ size: 100, type: 'image/webp' });
  assert.equal(state.encoding.height, 2000);
  assert.equal(state.encoding.width, 600);
  state.width = 600;
  state.height = 400;
  await context.window.compressTest({ size: 100, type: 'image/jpeg' });
  assert.equal(state.encoding.width, 600, 'small images are not enlarged');
  await assert.rejects(context.window.compressTest({ size: 11 * 1024 * 1024, type: 'image/jpeg' }));
  await assert.rejects(context.window.compressTest({ size: 100, type: 'image/svg+xml' }));
  state.blob = null;
  await assert.rejects(context.window.compressTest({ size: 100, type: 'image/jpeg' }));
  state.blob = { size: 1024 * 1024, type: 'image/jpeg' };
  await assert.rejects(context.window.compressTest({ size: 100, type: 'image/jpeg' }));
  assert.equal(state.closed, 5);
  console.log('PASS: queued photo limits, discard reservations, 120-second exemption, cancel, JPEG dimensions/quality, invalid image errors.');
})().catch(error => { console.error(error); process.exitCode = 1; });
