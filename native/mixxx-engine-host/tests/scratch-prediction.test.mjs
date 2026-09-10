import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,writeFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {execFileSync} from 'node:child_process';
test('scratch prediction velocity integrates to its position without expiration jumps',()=>{
 const dir=mkdtempSync(join(tmpdir(),'plumdeck-trajectory-'));
 try{
  const source=join(dir,'test.cpp'),binary=join(dir,'test');
  writeFileSync(source,`
#include "scratch_prediction.h"
#include <cassert>
#include <cmath>
int main(){
 for(double window:{8.,20.,60.})for(double velocity:{-.3,1.,-6.,-16.}){
   const double dt=.001;double integral=0;
   for(int step=1;step<=int(3*window/dt);++step){
     const double t=step*dt;
     integral+=scratch::predict(velocity,t-dt/2,window).velocity*dt;
     assert(std::abs(integral-scratch::predict(velocity,t,window).position)<.00001);
   }
   for(double join:{2*window,3*window}){
     auto a=scratch::predict(velocity,join-1e-7,window),b=scratch::predict(velocity,join+1e-7,window);
     assert(std::abs(a.position-b.position)<1e-5);
     assert(std::abs(a.velocity-b.velocity)<1e-5);
   }
   auto end=scratch::predict(velocity,4*window,window);assert(end.position==0&&end.velocity==0);
 }
}`);
  execFileSync('c++',['-std=c++20','-O2','-I',resolve('native/mixxx-engine-host/src'),source,'-o',binary]);
  assert.equal(execFileSync(binary).length,0);
 }finally{rmSync(dir,{recursive:true,force:true});}
});
