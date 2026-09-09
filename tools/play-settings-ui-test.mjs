import assert from 'node:assert/strict';
const engines = await import(process.env.DJALY_PLAYWRIGHT_MODULE || 'playwright');
const browser = await engines[process.env.DJALY_TEST_BROWSER || 'chromium'].launch();
const wav = Buffer.alloc(44 + 44100 * 3 * 2);
wav.write('RIFF'); wav.writeUInt32LE(wav.length - 8, 4); wav.write('WAVEfmt ', 8);
wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22);
wav.writeUInt32LE(44100, 24); wav.writeUInt32LE(88200, 28); wav.writeUInt16LE(2, 32); wav.writeUInt16LE(16, 34);
wav.write('data', 36); wav.writeUInt32LE(wav.length - 44, 40);
try {
  const page = await browser.newPage({ viewport: { width: 1200, height: 850 } });
  const errors = [], saves = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/play/recordings/formats', route => route.fulfill({ json: { formats: [
    { value: 'wav', extension: '.wav', label: 'WAV（非圧縮）' },
    { value: 'flac', extension: '.flac', label: 'FLAC（可逆圧縮）' },
    { value: 'mp3', extension: '.mp3', label: 'MP3（320 kbps）' },
  ] } }));
  await page.route('**/api/play/recordings/123/audio', route => route.fulfill({ contentType: 'audio/wav', body: wav }));
  await page.route('**/api/play/recordings/123', async route => {
    saves.push(route.request().postDataJSON()); await route.fulfill({ json: { id: 123 } });
  });
  await page.goto('http://127.0.0.1:1420/tools/play-settings-fixture.html');
  const events = () => page.locator('#events').textContent().then(JSON.parse);
  await page.getByRole('button', { name: 'rekordbox CUE一括反映' }).click();
  assert.equal((await events())[0].import, 'all');
  await page.getByRole('status').waitFor();
  assert((await page.getByRole('status').textContent()).includes('反映 125 曲'));
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: '音声設定を開く' }).click();
  await page.getByLabel('入力デバイス', { exact: true }).selectOption('USB Microphone');
  await page.getByLabel('マイク入力チャンネル').selectOption('1');
  await page.getByLabel('マイクを出力する').check();
  await page.getByLabel('話している間、DJの音量を自動で下げる').check();
  await page.screenshot({ path: '/tmp/djaly-audio-routing-ui.png' });
  assert.equal(await page.locator('#dj-output-device option').count(), 2, 'input-only device excluded from output picker');
  await page.getByRole('button', { name: '適用', exact: true }).click();
  const applied = (await events()).find(event => event.microphone);
  assert.equal(applied.microphone.channel, 1); assert.equal(applied.microphone.deviceId, 'USB Microphone');
  assert.equal(applied.microphone.enabled, true); assert.equal(applied.microphone.duckingEnabled, true);
  await page.getByRole('button', { name: '録音保存を開く' }).click();
  await page.getByLabel('アーティスト名', { exact: true }).fill('Yutahhh');
  await page.getByLabel('ミックス名', { exact: true }).fill('Night Mix');
  await page.getByRole('combobox', { name: '保存形式' }).click();
  await page.screenshot({ path: '/tmp/djaly-recording-formats-ui.png', animations: 'disabled' });
  await page.getByRole('option', { name: 'MP3（320 kbps）' }).click();
  assert((await page.locator('.dj-recording-filename').textContent()).includes('Yutahhh - Night Mix.mp3'));
  await page.getByRole('button', { name: 'プレビューを再生', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('audio')?.currentTime > 0.1);
  assert((await events()).some(event => event.pausedDecks));
  await page.getByRole('button', { name: 'プレビューを一時停止', exact: true }).click();
  await page.getByRole('button', { name: '保存', exact: true }).click();
  await page.getByRole('button', { name: '録音保存を開く' }).waitFor();
  assert.deepEqual(saves, [{ artist: 'Yutahhh', title: 'Night Mix', format: 'mp3' }]);
  await page.getByRole('button', { name: '録音保存を開く' }).click();
  await page.getByRole('button', { name: 'プレビューを再生', exact: true }).click();
  await page.getByRole('button', { name: 'あとで', exact: true }).click();
  await page.waitForTimeout(250);
  assert.equal(await page.locator('audio').count(), 0, 'closed preview cannot start after awaiting deck pause');
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/cues-rekordbox/import')) {
      assert.equal(route.request().method(), 'POST');
      assert.deepEqual(route.request().postDataJSON(), {});
      return route.fulfill({ json: { imported: 150, skipped: 3, failed: 0, conflicts: 0, errors: [], errors_truncated: 0 } });
    }
    if (path.endsWith('/page') || path.endsWith('/playlists')) return route.fulfill({ json: { items: [], total: 0, limit: 100, offset: 0, has_more: false } });
    if (path.endsWith('/sources') || path.endsWith('/history') || path.endsWith('/recordings') || path.includes('/genres')) return route.fulfill({ json: [] });
    return route.fulfill({ json: {} });
  });
  await page.goto('http://127.0.0.1:1420/tools/play-workspace-fixture.html');
  const bulkButton = page.getByRole('button', { name: 'rekordbox CUE一括反映', exact: true });
  assert.equal(await bulkButton.count(), 1, 'bulk import appears once, never on individual decks');
  await page.screenshot({ path: '/tmp/djaly-bulk-cue-workspace.png', animations: 'disabled' });
  await bulkButton.click();
  await page.getByRole('dialog').waitFor();
  assert((await page.getByRole('dialog').textContent()).includes('反映 150 曲'));
  await page.goto('http://127.0.0.1:1420/tools/recording-client-fixture.html');
  await page.waitForFunction(() => document.querySelector('#result')?.textContent);
  assert.deepEqual(JSON.parse(await page.locator('#result').textContent()), { passed: true, checks: 2 });
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ passed: true, checks: ['input routing', 'ducking option', 'CUE action', 'format dropdown', 'preview playback', 'save format', 'preview cancellation'] }));
} finally { await browser.close(); }
