import assert from 'node:assert/strict';
const engines = await import(process.env.PLUMDECK_PLAYWRIGHT_MODULE || 'playwright');
const name = process.env.PLUMDECK_TEST_BROWSER || 'webkit';
const browser = await engines[name].launch();
try {
  const page = await browser.newPage({ viewport: { width: 1200, height: 800 }, deviceScaleFactor: 2 });
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  await page.route('**/api/**', route => {
    const peaks = Array.from({length: 54000}, (_,i) => 30 + 190 * Math.exp(-(i % 150) / 15));
    return route.fulfill({ json: { duration_ms: 180000, bins_per_second: 300, amplitude_scale: 255, peaks, low: peaks, mid: peaks, high: peaks } });
  });
  await page.goto('http://127.0.0.1:1420/tools/scratch-ui-fixture.html');
  const canvas = page.getByRole('slider', { name: 'Deck A scroll waveform' });
  const result = () => page.locator('#result').textContent().then(JSON.parse);
  const waitEnd = () => page.waitForFunction(() => {
    const v = JSON.parse(document.querySelector('#result').textContent); return v.commands.at(-1)?.phase === 'end';
  });
  const box = await canvas.boundingBox();
  await page.mouse.move(box.x + 500, box.y + 100); await page.mouse.down();
  await page.mouse.move(box.x + 600, box.y + 100, {steps: 20});
  await page.waitForFunction(expected => {
    const last = JSON.parse(document.querySelector('#result').textContent).commands.at(-1);
    return last?.phase === 'move' && Math.abs(last.positionMs - expected) < 2;
  }, -100 / box.width * 8000);
  const afterMove = await result();
  assert.equal(afterMove.seeks, 0);
  assert.equal(afterMove.commands[0].phase, 'begin'); assert.equal(afterMove.commands[0].positionMs, 0);
  const firstTravel = afterMove.commands.at(-1).positionMs;
  assert(Math.abs(firstTravel + 100 / box.width * 8000) < 2, 'source-time travel must match frozen gesture scale');
  // Keep holding while resize events arrive; movement must keep its original scale.
  for (const width of [1800, 940, 2400, 1200]) await page.setViewportSize({width, height:800});
  await page.mouse.move(box.x + 650, box.y + 100, {steps: 10});
  await page.mouse.up(); await waitEnd();
  assert(Math.abs((await result()).commands.at(-1).positionMs + 150 / box.width * 8000) < 2);
  // Capture cancellation releases scratch, and is not converted to a seek.
  await page.mouse.down(); await canvas.dispatchEvent('pointercancel', {pointerId:1}); await page.mouse.up(); await waitEnd();
  await page.mouse.down(); await page.evaluate(() => window.dispatchEvent(new Event('blur'))); await page.mouse.up(); await waitEnd();
  // Track changes and unmount also release a held platter.
  await page.mouse.down(); await page.getByRole('button', {name:'Track', exact:true}).dispatchEvent('click'); await page.mouse.up(); await waitEnd();
  await page.mouse.down(); await page.getByRole('button', {name:'Mount', exact:true}).dispatchEvent('click'); await page.mouse.up(); await waitEnd();
  await page.getByRole('button', {name:'Mount', exact:true}).click();
  await page.getByRole('button', {name:'Orientation', exact:true}).click();
  const vb = await canvas.boundingBox();
  await page.mouse.move(vb.x + 40, vb.y + 250); await page.mouse.down(); await page.mouse.move(vb.x + 40, vb.y + 300, {steps:10}); await page.mouse.up(); await waitEnd();
  const final = await result(); assert.equal(final.seeks, 0); assert.deepEqual(errors, []);
  assert(Math.abs(final.commands.at(-1).positionMs + 50 / vb.height * 8000) < 2);
  await page.screenshot({path:`/tmp/plumdeck-scratch-${name}.png`});
  console.log(JSON.stringify({browser:name,passed:true,commands:final.commands.length,seeks:final.seeks}));
} finally { await browser.close(); }
