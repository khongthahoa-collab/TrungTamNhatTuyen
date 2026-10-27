// Run with: node test_tuition_svg_export.js
const fs = require('node:fs');
const assert = require('node:assert/strict');
const { spawnSync, execFileSync } = require('node:child_process');
const { chromium } = require('playwright');

const fixture = spawnSync('./venv/bin/python', ['-c', `
import json
from pathlib import Path
from types import SimpleNamespace
from flask import render_template_string
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
    template = Path('templates/admin/finance/tuition_class_detail.html').read_text()
    group = template[template.index('{% if all_records %}\\n<div class="modal'):template.index('<!-- Modal thông báo học phí cá nhân -->')]
    accounts = [dict(id=i, bank_name='TEST BANK', account_number='000000000' + str(i),
                     account_name='SYNTHETIC', qr_url='/qr') for i in (1, 2)]
    rows = [SimpleNamespace(student=SimpleNamespace(id=i, full_name='Student ' + str(i)),
                            total_due=500000, is_paid=i == 1) for i in (1, 2, 3)]
    with test.app.test_request_context():
        preview = render_template_string(group, all_records=rows, month=10, year=2026,
            cls=SimpleNamespace(id=97, name='TEST CLASS'),
            active_bank_accounts=[SimpleNamespace(**a) for a in accounts],
            group_qr_by_account={1: '/qr', 2: '/qr'})
        individual = render_template_string(template[
            template.index('<!-- Modal thông báo học phí cá nhân -->'):template.index('<style>')])
    print(json.dumps({'body': response.get_data(as_text=True), 'headers': {
        key: response.headers[key] for key in ('Content-Type', 'Content-Security-Policy', 'X-Content-Type-Options')
    }, 'preview': preview, 'individual': individual, 'accounts': accounts}))
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
const groupScript = template.slice(template.indexOf('// Xuất ảnh học phí nhóm'),
  template.indexOf('// Thông báo học phí cá nhân'))
  .replaceAll('{{ cls.id }}', '97').replaceAll('{{ month }}', '10').replaceAll('{{ year }}', '2026');
const individualScript = template.slice(template.indexOf('// Thông báo học phí cá nhân'),
  template.indexOf('// Công tắc "Đã thu đủ"'));
const bootstrapCss = execFileSync('curl', ['-fsSL', '--max-time', '30',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css'], { encoding: 'utf8' });
const bootstrapJs = execFileSync('curl', ['-fsSL', '--max-time', '30',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js'], { encoding: 'utf8' });

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
    await page.setContent('<button class="btn-group-tuition-export" data-export-mode="all">All</button>'
      + '<button class="btn-group-tuition-export" data-export-mode="unpaid">Unpaid</button>'
      + '<button id="individual" data-bs-toggle="modal" data-bs-target="#tuitionReminderModal"'
      + ' data-student-name="SYNTHETIC STUDENT" data-class-name="TEST CLASS"'
      + ' data-month-year="Tháng 10/2026" data-amount="500000" data-remaining="600000" data-debt="100000">Individual</button>'
      + svg.preview + svg.individual);
    await page.addStyleTag({ content: bootstrapCss });
    await page.addStyleTag({ content: template.slice(template.indexOf('<style>') + 7, template.indexOf('</style>')) });
    await page.addScriptTag({ content: bootstrapJs });
    await page.evaluate(accounts => {
      document.querySelectorAll('.btn-group-tuition-export').forEach(button => {
        button.dataset.accounts = JSON.stringify(accounts);
      });
      document.getElementById('individual').dataset.accounts = JSON.stringify(accounts);
      window.copiedImages = 0;
      Object.defineProperty(navigator, 'clipboard', { configurable: true, value: {
        write: async items => {
          const blob = await items[0].getType('image/png');
          if (blob.size < 2000) throw new Error('Empty clipboard image');
          window.copiedImages++;
        },
      } });
    }, svg.accounts);
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.addScriptTag({ content: groupScript + individualScript });
    assert.deepEqual(errors, [], 'Group scripts must initialize');
    let downloadCount = 0;
    page.on('download', () => downloadCount++);
    for (const width of [320, 375, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      await page.locator('#individual').click();
      const individualModal = page.locator('#tuitionReminderModal');
      await individualModal.waitFor({ state: 'visible' });
      await page.locator('#itcQrImg').evaluate(img => img.decode());
      assert.equal(await page.locator('#individualTuitionCard').evaluate(el => {
        const card = el.getBoundingClientRect();
        return el.scrollHeight <= el.clientHeight + 1
          && el.lastElementChild.getBoundingClientRect().bottom <= card.bottom;
      }), true, 'Individual card must enclose all information, not stretch to viewport height');
      assert.equal(await page.locator('#itcDebtRow').isVisible(), true);
      const individualDownload = page.waitForEvent('download');
      await page.locator('#btnDownloadTuitionCard').click();
      const individualFile = await individualDownload;
      assert.equal(individualFile.suggestedFilename(), 'hoc-phi-SYNTHETIC-STUDENT.png');
      const individualStream = await individualFile.createReadStream();
      const individualChunks = [];
      for await (const chunk of individualStream) individualChunks.push(chunk);
      const individualPng = Buffer.concat(individualChunks);
      const cardSize = await page.locator('#individualTuitionCard').evaluate(el => ({
        width: el.offsetWidth, height: el.offsetHeight,
      }));
      assert.ok(Math.abs(individualPng.readUInt32BE(16) - cardSize.width * 2) <= 2);
      assert.ok(Math.abs(individualPng.readUInt32BE(20) - cardSize.height * 2) <= 2,
        'Downloaded PNG must include the complete card height');
      await individualModal.locator('.btn-close').click();
      await individualModal.waitFor({ state: 'hidden' });
      for (const mode of ['unpaid', 'all']) {
        const before = downloadCount;
        await page.locator(`[data-export-mode="${mode}"]`).click();
        assert.deepEqual(errors, [], 'Preview handler must run');
        await page.waitForFunction(() => document.getElementById('groupTuitionModal').classList.contains('show'));
        const modal = page.locator('#groupTuitionModal');
        await modal.waitFor({ state: 'visible' });
        await page.locator('#groupQrImg').evaluate(img => img.decode());
        assert.equal(downloadCount, before, 'Opening preview must not download');
        assert.equal(await modal.locator('.group-tuition-row:visible').count(), mode === 'all' ? 3 : 2);
        assert.deepEqual(await modal.locator('.group-tuition-row:visible .group-tuition-stt').allTextContents(),
          mode === 'all' ? ['1', '2', '3'] : ['1', '2']);
        await modal.locator('input[value="1"]').check();
        assert.equal(await modal.locator('#groupAccountNumber').textContent(), '0000000002');
        assert.equal(await modal.evaluate(el => el.scrollWidth <= el.clientWidth), true, 'Preview must fit mobile');
        const downloaded = page.waitForEvent('download');
        await modal.locator('#btnDownloadGroupTuitionCard').click();
        const groupDownload = await downloaded;
        assert.equal(groupDownload.suggestedFilename(),
          `${mode === 'all' ? 'hoc-phi-nhom' : 'hoc-phi-chua-dong'}-97-T10-2026.png`);
        const stream = await groupDownload.createReadStream();
        const chunks = [];
        for await (const chunk of stream) chunks.push(chunk);
        assert.equal(Buffer.concat(chunks).subarray(0, 8).toString('hex'), '89504e470d0a1a0a');
        await modal.locator('#btnCopyGroupTuitionCard').click();
        await page.waitForFunction(() => !document.getElementById('btnCopyGroupTuitionCard').disabled);
        await modal.locator('.btn-close').click();
        await modal.waitFor({ state: 'hidden' });
      }
    }
    assert.equal(await page.evaluate(() => window.copiedImages), 6);
    assert.deepEqual(errors, []);
    console.log('PASS: full-height individual card and PNG dimensions; safe SVG export; immediate group previews without auto-download; unpaid/all filtering and numbering; account switching; download/copy at 320/375/1440px; broken QR recovery.');
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
