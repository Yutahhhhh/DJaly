import assert from 'node:assert/strict';
const engines = await import(process.env.DJALY_PLAYWRIGHT_MODULE || 'playwright');
const browser = await engines[process.env.DJALY_TEST_BROWSER || 'chromium'].launch();
try {
  const page=await browser.newPage({viewport:{width:1440,height:900}}), errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/api/**',route=>route.fulfill({json:{waveform_peaks:[],artwork:null}}));
  await page.goto('http://127.0.0.1:1420/tools/dj-controls-fixture.html');
  const deck=page.locator('.dj-deck').first();
  const events=()=>page.locator('#events').textContent().then(JSON.parse);
  await deck.getByTitle('ループ ON / OFF',{exact:true}).click();
  assert((await events()).some(e=>e.loop===4),'first loop activation creates the selected native beat loop');
  await deck.locator('.dj-performance-pad').first().click();
  assert((await events()).some(e=>e.cue===0 && !e.clear));
  await deck.locator('.dj-performance-pad').first().click({modifiers:['Shift']});
  assert((await events()).some(e=>e.cue===0 && e.clear));
  await deck.getByRole('tab',{name:'BEAT JUMP',exact:true}).click();
  await deck.locator('.dj-performance-pad').first().click();
  assert((await events()).some(e=>e.jump===-32));
  const knob=deck.getByRole('slider',{name:'FILTER',exact:true});
  const box=await knob.boundingBox();
  await page.mouse.move(box.x+box.width/2,box.y+box.height/2);await page.mouse.down();
  await page.mouse.move(box.x+box.width/2,box.y-30,{steps:8});
  await page.waitForFunction(()=>JSON.parse(document.querySelector('#events').textContent).some(e=>e.filter>0));
  await page.mouse.up();
  await knob.dblclick();
  assert.equal((await events()).filter(e=>'filter'in e).at(-1).filter,0);
  await deck.getByRole('tab',{name:'PAD FX',exact:true}).click();
  const fx=deck.getByRole('button',{name:/ECHO/});
  await fx.focus();await page.keyboard.down('Space');await page.keyboard.up('Space');
  const effects=(await events()).filter(e=>e.effect==='echo');
  assert(effects.some(e=>e.enabled));assert.equal(effects.at(-1).enabled,false);
  for (const width of [1440,1024,940]) {
    await page.setViewportSize({width,height:900});
    for (const compact of [false,true]) {
      if (compact) await page.getByRole('button',{name:'Density',exact:true}).click();
      await page.screenshot({path:`/tmp/djaly-controls-${width}-${compact?'compact':'normal'}.png`});
      assert(await deck.getByRole('slider',{name:'Deck A tempo',exact:true}).isVisible());
      if(compact) await page.getByRole('button',{name:'Density',exact:true}).click();
    }
  }
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({passed:true,events:(await events()).length}));
}finally{await browser.close()}
