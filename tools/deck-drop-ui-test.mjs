// Start Vite, then run with Playwright installed (Chromium and WebKit supported).
import assert from 'node:assert/strict';
const imported = await import(process.env.PLUMDECK_PLAYWRIGHT_MODULE || 'playwright');
const engines = imported.default ?? imported;
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
      else if (path.endsWith('/waveform-detail')) result = { duration_ms: 180000, bins_per_second: 300, amplitude_scale: 255, peaks: [], low: [], mid: [], high: [] };
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
    const pointerDrag = async target => {
      const from = await source.boundingBox(), to = await target.boundingBox();
      assert(from && to);
      await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
      await page.mouse.down();
      await page.mouse.move(from.x + from.width / 2 + 8, from.y + from.height / 2);
      await page.mouse.move(to.x + to.width / 2, to.y + to.height / 2, { steps: 6 });
      await page.mouse.up();
    };
    const deck = id => page.locator(`article[data-track-drop-deck="${id}"]`);
    // A successful double-click load used to crash while rendering v0.5.10's
    // flat readyTileRanges. The fixture injects that exact wire shape.
    const doubleClickBefore = (await loads()).length;
    await source.dblclick();
    await expectLoad(doubleClickBefore, 'A');
    for (const id of ['A', 'B', 'C', 'D'].slice(0, count)) {
      // Select the opposite deck: drop must ignore activeDeck. Include disabled
      // buttons and nested SVG/controls that React's bubbling can miss.
      await page.getByRole('button', { name: `Select deck ${id === 'A' ? 'B' : 'A'}`, exact: true }).click();
      for (const selector of ['.dj-track-name', '.dj-cover', '.dj-chip--keysync', '.dj-overview', '.dj-deck-controls']) {
        const before = (await loads()).length;
        await pointerDrag(deck(id).locator(selector));
        await expectLoad(before, id);
      }
      const before = (await loads()).length;
      await pointerDrag(page.locator(`.dj-lane[data-track-drop-deck="${id}"]`));
      await expectLoad(before, id);
    }
    // Native file-drop notifications must never be mistaken for an internal
    // track drag. Internal tracks use the same pointer sensor as Setlists so
    // WebView2's OS drag interception cannot swallow the gesture.
    const nativeAt = async (type, id) => {
      const box = await deck(id).locator('.dj-track-name').boundingBox();
      await page.evaluate(({ type, x, y }) => window.deckDropFixture.native(type, x, y), {
        type, x: (box.x + box.width / 2) * scale, y: (box.y + box.height / 2) * scale,
      });
    };
    const before = (await loads()).length;
    await nativeAt('drop', 'A');
    await page.waitForTimeout(100); assert.equal((await loads()).length, before);
    await pointerDrag(page.locator('.dj-master-strip'));
    await page.waitForTimeout(150); assert.equal((await loads()).length, before);
    const mixer = page.locator('.dj-mixer-channel').first();
    if (await mixer.count()) {
      await pointerDrag(mixer);
      await page.waitForTimeout(150); assert.equal((await loads()).length, before);
    }
    // Visual feedback covers the full target surface, not just the waveform.
    const from = await source.boundingBox(); const to = await deck('A').locator('.dj-track-name').boundingBox();
    await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2); await page.mouse.down();
    await page.mouse.move(from.x + from.width / 2 + 8, from.y + from.height / 2); await page.mouse.move(to.x + to.width / 2, to.y + to.height / 2, { steps: 6 });
    assert.equal(await deck('A').getAttribute('data-track-drop-active'), 'true');
    assert.equal(await deck('A').getAttribute('data-track-drop-label'), 'DECK A へロード');
    assert.equal(await page.locator('[data-track-drop-active]').count(), 1);
    await page.screenshot({ path: `/tmp/plumdeck-deck-drop-${engine}-${scale}.png` });
    await page.keyboard.press('Escape');
    await page.mouse.up();
    assert.equal(await page.locator('[data-track-drop-active]').count(), 0);
    assert.deepEqual(errors, []);
    await page.close();
  }
  console.log(JSON.stringify({ browser: engine, checked, passed: true }));
} finally { await browser.close(); }
