// Start Vite, then run with Playwright installed (Chromium and WebKit supported).
import assert from 'node:assert/strict';
const engines = await import(process.env.PLUMDECK_PLAYWRIGHT_MODULE || 'playwright');
const engine = process.env.PLUMDECK_TEST_BROWSER || 'chromium';
const browser = await engines[engine].launch();
let checked = 0;
try {
  for (const [scale, count, vertical, compact] of [[1, 2, false, false], [1.25, 2, true, true], [1.5, 4, false, true], [2, 4, true, false]]) {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1080 }, deviceScaleFactor: scale });
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    await page.addInitScript(({ count, vertical, compact }) => {
      localStorage.setItem('plumdeck.deckCount', String(count));
      localStorage.setItem('plumdeck.waveformLayout', vertical ? 'vertical' : 'horizontal');
      localStorage.setItem('plumdeck.compactDecks', String(compact));
    }, { count, vertical, compact });
    await page.route('**/api/**', route => {
      const url = new URL(route.request().url()), path = url.pathname;
      const track = { id: 1, title: 'Drop test track', artist: 'Fixture', filepath: '/fixture.wav', duration: 180, bpm: 120, key: '8A' };
      let result = {};
      if (path === '/api/tracks/page' || path === '/api/recommendations/next/page') result = { items: [track], total: 1, limit: 100, offset: 0, has_more: false };
      else if (path.endsWith('/page') || path.endsWith('/playlists')) result = { items: [], total: 0, limit: 100, offset: 0, has_more: false };
      else if (path.endsWith('/sources') || path.endsWith('/history') || path.endsWith('/recordings')) result = [];
      else if (path.endsWith('/performance-metadata')) result = { track_id: 1, revision: 1, cue_points: [], loops: [], beat_grid: null };
      else if (path.endsWith('/waveform-detail')) result = { duration_ms: 180000, bins_per_second: 300, amplitude_scale: 255, peaks: [] };
      else if (path.endsWith('/visual')) result = { waveform_peaks: [], artwork: null };
      return route.fulfill({ json: result });
    });
    await page.goto(`${process.env.PLUMDECK_TEST_URL || 'http://127.0.0.1:1420'}/tools/deck-drop-fixture.html`);
    const source = page.locator('.dj-vtrack-row').first();
    await source.waitFor();
    const loads = () => page.evaluate(() => window.deckDropFixture.loads);
    const expectLoad = async (before, deck) => {
      await page.waitForFunction(n => window.deckDropFixture.loads.length > n, before);
      await page.waitForTimeout(120); // Catch delayed duplicate native dispatch.
      assert.deepEqual((await loads()).slice(before), [{ deck, trackId: '1' }]);
      assert.equal(await page.locator('[data-track-drop-active]').count(), 0);
      checked++;
    };
    const deck = id => page.locator(`article[data-track-drop-deck="${id}"]`);
    for (const id of ['A', 'B', 'C', 'D'].slice(0, count)) {
      // Select the opposite deck: drop must ignore activeDeck. Include disabled
      // buttons and nested SVG/controls that React's bubbling can miss.
      await page.getByRole('button', { name: `Select deck ${id === 'A' ? 'B' : 'A'}`, exact: true }).click();
      for (const selector of ['.dj-track-name', '.dj-cover', '.dj-chip--keysync', '.dj-overview', '.dj-deck-controls']) {
        const before = (await loads()).length;
        await source.dragTo(deck(id).locator(selector));
        await expectLoad(before, id);
      }
      const before = (await loads()).length;
      await source.dragTo(page.locator(`.dj-lane[data-track-drop-deck="${id}"]`));
      await expectLoad(before, id);
    }
    // Exercise real Tauri event decoding and physical -> CSS hit testing.
    const nativeAt = async (type, id) => {
      const box = await deck(id).locator('.dj-track-name').boundingBox();
      await page.evaluate(({ type, x, y }) => window.deckDropFixture.native(type, x, y), {
        type, x: (box.x + box.width / 2) * scale, y: (box.y + box.height / 2) * scale,
      });
    };
    const start = () => source.evaluate(el => {
      window.dropData = new DataTransfer();
      el.dispatchEvent(new DragEvent('dragstart', { bubbles: true, cancelable: true, dataTransfer: window.dropData }));
    });
    const domDrop = id => deck(id).locator('.dj-track-name').evaluate(el => {
      el.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: window.dropData }));
    });
    for (const order of ['native-only', 'native-first', 'DOM-first']) {
      const before = (await loads()).length; await start();
      if (order === 'native-only') { await nativeAt('over', 'A'); await nativeAt('drop', 'A'); }
      else if (order === 'native-first') { await nativeAt('drop', 'B'); await domDrop('A'); }
      else { await domDrop('A'); await nativeAt('drop', 'B'); }
      await expectLoad(before, 'A');
    }
    const before = (await loads()).length;
    await source.dragTo(page.locator('.dj-master-strip'));
    await page.waitForTimeout(150); assert.equal((await loads()).length, before);
    const mixer = page.locator('.dj-mixer-channel').first();
    if (await mixer.count()) {
      await start(); const box = await mixer.boundingBox();
      await page.evaluate(({ x, y }) => window.deckDropFixture.native('drop', x, y), { x: (box.x + box.width / 2) * scale, y: (box.y + box.height / 2) * scale });
      await page.waitForTimeout(150); assert.equal((await loads()).length, before);
    }
    // Visual feedback covers the full target surface, not just the waveform.
    await start(); await nativeAt('over', 'A');
    assert.equal(await deck('A').getAttribute('data-track-drop-active'), 'true');
    assert.equal(await deck('A').getAttribute('data-track-drop-label'), 'DECK A へロード');
    assert.equal(await page.locator('[data-track-drop-active]').count(), 1);
    await page.screenshot({ path: `/tmp/plumdeck-deck-drop-${engine}-${scale}.png` });
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('[data-track-drop-active]').count(), 0);
    assert.deepEqual(errors, []);
    await page.close();
  }
  console.log(JSON.stringify({ browser: engine, checked, passed: true }));
} finally { await browser.close(); }
