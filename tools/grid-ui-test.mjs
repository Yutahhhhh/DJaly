import assert from 'node:assert/strict';
const engines = await import(process.env.DJALY_PLAYWRIGHT_MODULE || 'playwright');
const browser = await engines[process.env.DJALY_TEST_BROWSER || 'chromium'].launch();
try {
  const page = await browser.newPage({viewport:{width:1200,height:800},deviceScaleFactor:2});
  const errors=[]; page.on('pageerror', e=>errors.push(e.message));
  await page.route('**/api/**', async route => {
    const detail = route.request().url().includes('waveform-detail');
    const peaks=Array.from({length:detail?9000:500},(_,i)=>Math.round((0.12+0.7*Math.exp(-((i%(detail?150:8))/(detail?16:1.5))))*(detail?255:1)));
    await route.fulfill({json:detail?{track_id:1,duration_ms:30000,bins_per_second:300,amplitude_scale:255,peaks,low:peaks,mid:peaks.map(v=>v*.4),high:peaks.map(v=>v*.2)}:{waveform_peaks:peaks,artwork:null,lyrics:''}});
  });
  await page.goto('http://127.0.0.1:1420/tools/grid-ui-fixture.html');
  const result=()=>page.locator('#result').textContent().then(JSON.parse);
  await page.getByRole('group',{name:'ビートグリッド編集'}).waitFor();
  const canvas=page.getByRole('slider',{name:'Deck A scroll waveform'});
  const box=await canvas.boundingBox();
  await page.mouse.move(box.x+box.width/2,box.y+box.height/2);await page.mouse.down();
  await page.mouse.move(box.x+box.width/2+60,box.y+box.height/2,{steps:10});await page.mouse.up();
  await page.waitForFunction(()=>JSON.parse(document.querySelector('#result').textContent).first>100);
  const shifted=await result(); assert.equal(shifted.seekCount,0);
  await page.getByTitle('拍の間隔を狭める（細かく）', {exact:true}).click();
  assert(Math.abs((await result()).beats[10]-shifted.beats[10])<1e-6,'anchor must follow grid shift before BPM edits');
  await page.getByRole('button',{name:'元に戻す',exact:true}).click();
  await page.getByRole('button',{name:'元に戻す',exact:true}).click();assert.equal((await result()).first,100);
  await page.getByTitle('拍の間隔を狭める（細かく）', {exact:true}).click();
  assert((await result()).beats.includes(5100),'selected anchor must not move');
  await page.keyboard.down('Alt'); await page.mouse.move(box.x+box.width/2,box.y+box.height/2);await page.mouse.down();await page.mouse.move(box.x+box.width/2+30,box.y+box.height/2,{steps:5});await page.mouse.up();await page.keyboard.up('Alt');
  assert.equal((await result()).seekCount,0);
  const scratch = JSON.parse(await page.locator('#scratch-result').textContent());
  assert.equal(scratch[0].phase,'begin'); assert.equal(scratch.at(-1).phase,'end');
  assert(scratch.some(c=>c.phase==='move' && c.positionMs<0));
  await page.getByRole('button',{name:'保存・適用'}).click();assert((await result()).saved);
  await page.getByRole('button',{name:'グリッド解析',exact:true}).click();await page.getByText('Djaly解析・小節頭は要確認',{exact:true}).waitFor();
  await page.getByRole('button',{name:'rekordboxから読込'}).click();
  await page.getByText('rekordbox',{exact:true}).waitFor();
  await page.screenshot({path:'/tmp/djaly-grid-source-editor.png'});
  await page.getByRole('button',{name:'▶',exact:true}).click();
  const beforeResize=(await result()).position;
  for(const width of [940,1600,1024,1400]){
    await page.setViewportSize({width,height:800});
    const overflow=await page.locator('.dj-grid-editor__row').evaluateAll(rows=>rows.some(r=>r.scrollWidth>r.clientWidth+1));
    assert.equal(overflow,false,`editor row overflow at ${width}`);
  }
  await page.waitForFunction(start=>JSON.parse(document.querySelector('#result').textContent).position>start+200,beforeResize);
  await page.getByRole('button',{name:'Ⅱ',exact:true}).click();
  assert(await canvas.evaluate(c=>c.width<=8192 && c.height<=8192));
  await page.getByRole('button',{name:'縦横切替'}).click();await page.getByRole('button',{name:'密度切替'}).click();
  await page.screenshot({path:'/tmp/djaly-grid-source-editor-vertical.png'});
  assert.deepEqual(errors,[]);console.log(JSON.stringify({passed:true,gridDragSeekCount:shifted.seekCount,shiftedFirstBeatMs:shifted.first,screenshots:['/tmp/djaly-grid-source-editor.png','/tmp/djaly-grid-source-editor-vertical.png']}));
} finally {await browser.close()}
