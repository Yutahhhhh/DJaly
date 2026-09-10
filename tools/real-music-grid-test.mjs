// Requires the isolated API from real_music_grid_probe.py --serve 18421 and Vite.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {writeFile} from 'node:fs/promises';
import path from 'node:path';
const {webkit}=await import(process.env.DJALY_PLAYWRIGHT_MODULE||'playwright');
const child=spawn(process.env.DJALY_TEST_HOST||path.resolve('native/mixxx-engine-host/build-upstream/djaly-mixxx-engine-host'),[],{env:{...process.env,DJALY_MIXXX_OUTPUT_DEVICE:'BlackHole 2ch'}});
let id=0,hello,stderr='';const pending=new Map(),commands=[];
const exited=new Promise(r=>child.once('exit',code=>r(code)));
child.stderr.on('data',data=>{stderr+=data;});
createInterface({input:child.stdout}).on('line',line=>{const m=JSON.parse(line);pending.get(m.id)?.(m);});
async function command(op,params={}){
 const current=++id;commands.push(op);
 const reply=new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error(`timeout ${op}`)),10000);pending.set(current,m=>{clearTimeout(timer);pending.delete(current);resolve(m);});});
 child.stdin.write(JSON.stringify({id:current,op,params,...(hello?{engineId:hello.engineId,sessionId:hello.sessionId}:{})})+'\n');
 const m=await reply;assert.notEqual(m.kind,'error',JSON.stringify(m));return m.data??m;
}
const browser=await webkit.launch();
try{
 hello=await command('session.hello');
 for(let i=0;i<200;i++){if((await command('state.snapshot')).audio.applied)break;await new Promise(r=>setTimeout(r,25));}
 const bundle=await fetch('http://127.0.0.1:18421/validation/bundle').then(r=>r.json());
 for(let track=0;track<bundle.length;track++){
  const page=await browser.newPage({viewport:{width:1240,height:800},deviceScaleFactor:2});
  const errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
  await page.route('**/validation/native',async route=>{
   try{const p=route.request().postDataJSON();await route.fulfill({json:await command(p.op,p.params)});}
   catch(e){errors.push(String(e));await route.fulfill({status:500,body:String(e)});}
  });
  await page.route(/\/(?:api\/|validation\/bundle)/,async route=>{
   const url=new URL(route.request().url());const response=await route.fetch({url:'http://127.0.0.1:18421'+url.pathname+url.search});
   if(response.status()>=400)errors.push(`${response.status()} ${url.pathname}`);
   await route.fulfill({response});
  });
  await page.goto(`http://127.0.0.1:1420/tools/real-music-grid-fixture.html?track=${track}`);
  await page.getByRole('group',{name:'ビートグリッド編集'}).waitFor({timeout:30000});
  const result=()=>page.locator('#result').textContent().then(JSON.parse);
  const before=await result(),seekCount=commands.filter(op=>op==='deck.seek').length;
  const box=await page.getByRole('slider',{name:'Deck A scroll waveform'}).boundingBox();
  await page.mouse.move(box.x+box.width/2,box.y+box.height/2);await page.mouse.down();
  await page.mouse.move(box.x+box.width/2+35,box.y+box.height/2,{steps:10});await page.mouse.up();
  await page.waitForFunction(value=>JSON.parse(document.querySelector('#result').textContent).grid.first_beat_ms!==value,before.grid.first_beat_ms);
  await page.getByTitle('拍の間隔を狭める（細かく）', {exact:true}).click();
  await page.getByRole('button',{name:'保存・適用'}).click();
  await page.waitForFunction(()=>JSON.parse(document.querySelector('#result').textContent).saved===1);
  assert.equal(commands.filter(op=>op==='deck.seek').length,seekCount,'Grid edits must not seek');
  await page.getByRole('button',{name:'▶',exact:true}).click();
  await page.waitForFunction(()=>JSON.parse(document.querySelector('#result').textContent).playing);
  await page.keyboard.down('Alt');await page.mouse.move(box.x+box.width/2,box.y+box.height/2);await page.mouse.down();
  await page.mouse.move(box.x+box.width/2+25,box.y+box.height/2,{steps:10});await page.mouse.up();await page.keyboard.up('Alt');
  await page.getByRole('button',{name:'Ⅱ',exact:true}).click();
  await page.waitForFunction(()=>!JSON.parse(document.querySelector('#result').textContent).playing);
  await page.screenshot({path:`/tmp/djaly-real-grid-${track}.png`});
  assert.equal(await page.locator('#error').textContent(),'');assert.deepEqual(errors,[]);
  console.log(JSON.stringify({track,codec:bundle[track].codec,saved:(await result()).saved,consoleErrors:errors.length}));
  await page.close();
 }
}finally{
 await browser.close();child.stdin.end();assert.equal(await exited,0);await writeFile('/tmp/djaly-real-ui-native-stderr.log',stderr);
}
