// macOS actual WKWebView acceptance, served from a static bundle without HMR.
// Build first: cargo build --manifest-path src-tauri/Cargo.toml --example waveform_validation
// Run: node tools/waveform-wk-test.mjs [seconds=600]
import {build} from 'vite';
import {createServer} from 'node:http';
import {spawn} from 'node:child_process';
import {mkdtemp,readFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
const seconds=Number(process.argv[2]||600);
if(!Number.isInteger(seconds)||seconds<5||seconds>7200)throw Error('Duration must be 5–7200 seconds');
const directory=await mkdtemp(path.join(tmpdir(),'djaly-wk-'));
let server;
try{
 await build({configFile:false,build:{outDir:directory,emptyOutDir:false,lib:{entry:path.resolve('tools/waveform-validation.ts'),formats:['es'],fileName:()=> 'validation.js'}}});
 const html=(await readFile('tools/waveform-validation.html','utf8')).replace('/tools/waveform-validation.ts','/validation.js');
 const script=await readFile(path.join(directory,'validation.js'));
 server=createServer((request,response)=>{
  const route=new URL(request.url,'http://localhost').pathname;
  if(route==='/'||route==='/index.html'){response.setHeader('Content-Type','text/html; charset=utf-8');response.end(html);}
  else if(route==='/validation.js'){response.setHeader('Content-Type','text/javascript');response.end(script);}
  else{response.statusCode=404;response.end();}
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const child=spawn(path.resolve('src-tauri/target/debug/examples/waveform_validation'),[],{stdio:'inherit',env:{...process.env,DJALY_VALIDATION_SECONDS:String(seconds),DJALY_VALIDATION_URL:`http://127.0.0.1:${server.address().port}/index.html`}});
 process.exitCode=await new Promise((resolve,reject)=>{child.once('error',reject);child.once('exit',code=>resolve(code??1));});
}finally{
 if(server)await new Promise(resolve=>server.close(resolve));
 await rm(directory,{recursive:true,force:true});
}
