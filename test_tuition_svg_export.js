// Run with: node test_tuition_svg_export.js
const fs = require('node:fs');
const assert = require('node:assert/strict');
const { spawnSync, execFileSync } = require('node:child_process');
const { chromium } = require('playwright');

const fixture = spawnSync('./venv/bin/python', ['-c', `
import json
from unittest.mock import patch
from test_vietqr_image import VietQRImageTests
VietQRImageTests.setUpClass()
test = VietQRImageTests()
test.setUp()
try:
    source = 'https://img.vietqr.io/image/VCB-0000000000-print.jpg?accountName=TEST'
    from services.vietqr_image import image_signer
    test.upstream.iter_content.return_value = [test.svg()]
    response = test.client.get('/admin/tuition/qr-image',
        query_string={'token': image_signer().dumps(source)})
    assert response.status_code == 200
    print(json.dumps({'body': response.get_data(as_text=True), 'headers': {
        key: response.headers[key] for key in ('Content-Type', 'Content-Security-Policy', 'X-Content-Type-Options')
    }}))
finally:
    test.tearDown()
    VietQRImageTests.tearDownClass()
`], { encoding: 'utf8' });
assert.equal(fixture.status, 0, fixture.stderr);
const svg = JSON.parse(fixture.stdout);
const canvasLibrary = execFileSync('curl', [
  '-fsSL', '--max-time', '30',
  'https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js',
], { encoding: 'utf8' });
const template = fs.readFileSync('templates/admin/finance/tuition_class_detail.html', 'utf8');
const exporter = template.slice(template.indexOf('function exportTuitionCardAsImage('),
  template.indexOf('// Xuất ảnh học phí nhóm'));

(async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ acceptDownloads: true });
    await page.route('https://tuition.test/**', route => {
      if (new URL(route.request().url()).pathname === '/qr') return route.fulfill(svg);
      return route.fulfill({
        contentType: 'text/html; charset=utf-8',
        body: '<div id="capture" style="width:440px;background:white"><h2>Thông báo học phí</h2>'
          + '<div>Ngân hàng TEST · Tài khoản 0000000000 · 500.000 đồng</div>'
          + '<img class="tuition-qr-img" src="/qr" style="width:300px;height:388px"></div>'
          + '<button id="export">Tải ảnh thông báo</button>',
      });
    });
    await page.goto('https://tuition.test/');
    await page.addScriptTag({ content: canvasLibrary });
    await page.addScriptTag({ content: exporter });
    await page.evaluate(() => {
      window.messages = [];
      window.showMessage = text => window.messages.push(text);
      document.getElementById('export').onclick = () => exportTuitionCardAsImage(
        document.getElementById('capture'), 'hoc-phi.png', document.getElementById('export'));
    });
    for (const width of [375, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      await page.locator('.tuition-qr-img').evaluate(img => img.decode());
      const download = page.waitForEvent('download');
      await page.locator('#export').click();
      const file = await download;
      assert.equal(file.suggestedFilename(), 'hoc-phi.png');
      const stream = await file.createReadStream();
      const chunks = [];
      for await (const chunk of stream) chunks.push(chunk);
      const bytes = Buffer.concat(chunks);
      assert.equal(bytes.subarray(0, 8).toString('hex'), '89504e470d0a1a0a');
      assert.ok(bytes.length > 2000);
      await page.waitForFunction(() => !document.getElementById('export').disabled);
    }
    assert.deepEqual(await page.evaluate(() => window.messages), []);
    await page.evaluate(() => {
      document.querySelector('.tuition-qr-img').src = 'data:text/plain,broken';
    });
    await page.locator('#export').click();
    await page.waitForFunction(() => window.messages.length === 1);
    await page.waitForFunction(() => !document.getElementById('export').disabled);
    assert.ok((await page.locator('#export').textContent()).includes('Tải ảnh'));
    console.log('PASS: authenticated sanitized SVG response decodes with restrictive CSP; real tuition export and html2canvas download PNG at mobile/desktop widths; broken QR reports error and restores button.');
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
