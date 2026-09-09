import assert from 'node:assert/strict';
const engines = await import(process.env.DJALY_PLAYWRIGHT_MODULE || 'playwright');
const browser=await engines[process.env.DJALY_TEST_BROWSER || 'chromium'].launch();
try {
  const page=await browser.newPage({viewport:{width:1440,height:900}}), errors=[], requests=[];
  page.on('pageerror',e=>errors.push(e.message));
  let playlists=Array.from({length:20000},(_,i)=>({id:i+1,name:i===0?'Local crate':`Crate ${i+1}`,track_count:0,source:'djaly',editable:true}));
  const track=(id,prefix='Track')=>({id,title:`${prefix} ${id}`,artist:'Fixture artist',filepath:`/fixture/${id}.wav`,duration:180,bpm:120,key:'8A',genre:'House'});
  const envelope=(items,total,limit,offset)=>({items,total,limit,offset,has_more:offset+items.length<total});
  await page.route('**/api/**',async route=>{
    const url=new URL(route.request().url()),path=url.pathname,method=route.request().method();
    const limit=Number(url.searchParams.get('limit')||100),offset=Number(url.searchParams.get('offset')||0);
    requests.push({path,method,offset,query:url.searchParams.get('q')});
    let result;
    if(path==='/api/tracks/page'||path==='/api/recommendations/next/page') {
      const query=url.searchParams.get('q')||'',total=query?3:50000;
      if(query==='error') {await route.fulfill({status:503,json:{detail:'Test outage'}});return;}
      if(query==='old') await new Promise(resolve=>setTimeout(resolve,350));
      result=envelope(Array.from({length:Math.min(limit,Math.max(0,total-offset))},(_,i)=>track(offset+i+1,query||'Track')),total,limit,offset);
    } else if(path==='/api/play/playlists'&&method==='GET') result=envelope(playlists.slice(offset,offset+limit),playlists.length,limit,offset);
    else if(path==='/api/play/playlists'&&method==='POST') {const body=route.request().postDataJSON();result={id:60001,name:body.name,track_count:0,source:'djaly',editable:true};playlists.unshift(result);}
    else if(path==='/api/play/playlists/60001'&&method==='DELETE'){playlists=playlists.filter(p=>p.id!==60001);result={ok:true};}
    else if(path==='/api/play/rekordbox/sources')result=[{id:'rb',name:'Rekordbox',playlist_count:1,member_count:2,unmapped_count:1}];
    else if(path==='/api/play/rekordbox/rb/tree/page')result=envelope(url.searchParams.has('parent_external_id')?[]:[{source_id:'rb',external_id:'mix',parent_external_id:null,name:'Mirror fixture',kind:'playlist',track_count:2,unmapped_count:1}],1,limit,offset);
    else if(path==='/api/play/rekordbox/rb/playlists/mix/tracks/page')result=envelope([{...track(1),position:1,local_track_id:1,resolved:true},{title:'Unresolved fixture',position:2,local_track_id:null,resolved:false,source_filepath:'/missing.wav',duration:180}],2,limit,offset);
    else if(path==='/api/play/rekordbox/rb/playlists/mix/copy') {const playlist={id:60002,name:'Copied mirror',track_count:1,source:'djaly',editable:true};playlists.unshift(playlist);result={playlist,copied:1,skipped_unresolved:1};}
    else if(path.endsWith('/waveform-detail'))result={track_id:1,duration_ms:180000,bins_per_second:300,amplitude_scale:255,peaks:[]};
    else if(path.includes('/tracks/')&&path.includes('/visual'))result={waveform_peaks:[],artwork:null};
    else if(path.endsWith('/tracks'))result=envelope([],0,limit,offset);
    else result={waveform_peaks:[],artwork:null};
    await route.fulfill({json:result});
  });
  await page.goto('http://127.0.0.1:1420/tools/library-ui-fixture.html');
  await page.locator('.dj-track-count').filter({hasText:'50,000'}).waitFor();
  const center=page.locator('.dj-vtrack-scroll');
  assert(await page.locator('.dj-vtrack-row').count()<70,'initial DOM bounded');
  assert(await page.locator('.dj-local-playlist').count()<40,'20k playlists have bounded DOM');
  const right=page.locator('.dj-recommend-scroll');
  for(let i=0;i<4;i++) {await right.evaluate(e=>{e.scrollTop=e.scrollHeight;e.dispatchEvent(new Event('scroll'));});await new Promise(resolve=>setTimeout(resolve,120));}
  await right.evaluate(e=>{e.scrollTop=0;e.dispatchEvent(new Event('scroll'));});
  await page.locator('.dj-recommend-row').getByText('Track 1',{exact:true}).waitFor();
  assert(await page.locator('.dj-recommend-row').count()<50,'earlier recommendations remain reachable with bounded DOM');
  for(let i=0;i<4;i++){
    const before=requests.filter(r=>r.path==='/api/tracks/page').length;
    await center.evaluate(e=>{e.scrollTop=e.scrollHeight;e.dispatchEvent(new Event('scroll'));});
    await page.waitForFunction(()=>document.querySelectorAll('.dj-vtrack-row').length>0);
    await new Promise(resolve=>setTimeout(resolve,120));
    assert(requests.filter(r=>r.path==='/api/tracks/page').length>before,'scroll fetches next page');
  }
  assert(await page.locator('.dj-vtrack-row').count()<70,'DOM bounded after paging');
  await page.getByRole('textbox',{name:'Collectionを検索'}).fill('error');
  await page.getByText('API Error: 503 Test outage',{exact:true}).waitFor();
  await new Promise(resolve=>setTimeout(resolve,350));
  assert.equal(requests.filter(r=>r.query==='error').length,1,'failed page must not auto-retry forever');
  await page.getByRole('textbox',{name:'Collectionを検索'}).fill('old');
  await new Promise(resolve=>setTimeout(resolve,220));
  await page.getByRole('textbox',{name:'Collectionを検索'}).fill('new');
  await page.locator('.dj-track-count').filter({hasText:/^3 曲$/}).waitFor();
  await page.locator('.dj-vtrack-row').filter({hasText:'new 1'}).waitFor();
  await new Promise(resolve=>setTimeout(resolve,400));
  assert.equal(await page.locator('.dj-vtrack-row').filter({hasText:'old 1'}).count(),0,'stale search response discarded');
  await page.getByRole('button',{name:'SEARCH',exact:true}).click();
  await page.getByRole('textbox',{name:'右パネル検索'}).fill('right');
  await page.locator('.dj-recommend-row').filter({hasText:'right 1'}).waitFor();
  assert(await page.locator('.dj-vtrack-row').filter({hasText:'new 1'}).count()===1,'right search independent');
  await page.getByTitle('新規プレイリスト',{exact:true}).click();
  await page.getByRole('dialog').getByRole('textbox',{name:'プレイリスト名',exact:true}).fill('Created in test');
  await page.screenshot({path:'/tmp/djaly-playlist-create-dialog.png',animations:'disabled'});
  await page.getByRole('dialog').getByRole('button',{name:'作成',exact:true}).click();
  await page.getByText('Created in test',{exact:true}).waitFor();
  await page.locator('.dj-local-playlist').filter({hasText:'Created in test'}).hover();
  await page.locator('.dj-local-playlist').filter({hasText:'Created in test'}).getByTitle('削除',{exact:true}).click();
  await page.getByRole('dialog').getByRole('button',{name:'削除',exact:true}).click();
  await page.getByText('Created in test',{exact:true}).waitFor({state:'detached'});
  await page.getByText('Mirror fixture',{exact:true}).click();
  await page.locator('.dj-track-count').filter({hasText:/^2 曲$/}).waitFor();
  await page.getByRole('button',{name:'Djalyへコピー',exact:true}).click();
  await page.getByText('Copied mirror',{exact:true}).waitFor();
  assert(!(await page.locator('.dj-library-notice').textContent()).includes('undefined'));
  await page.screenshot({path:'/tmp/djaly-library-pagination.png'});
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({passed:true,pageRequests:requests.filter(r=>r.path.endsWith('/page')).length,renderedRows:await page.locator('.dj-vtrack-row').count()}));
}finally{await browser.close()}
