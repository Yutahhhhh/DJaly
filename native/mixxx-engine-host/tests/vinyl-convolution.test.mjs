import test from 'node:test';
import {mkdtempSync,writeFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {execFileSync} from 'node:child_process';
test('SIMD stereo convolution agrees with an independent double precision sum',()=>{
 const directory=mkdtempSync(join(tmpdir(),'plumdeck-convolution-'));
 try{
  const source=join(directory,'test.cpp'),binary=join(directory,'test');
  writeFileSync(source,`
#include "vinyl_convolution.h"
#include <vector>
#include <cmath>
#include <cassert>
int main(){
 for(int taps:{2,4,6,128,130,2048,8192}){
  std::vector<float> samples(taps*2),a(taps),b(taps);
  for(int i=0;i<taps;i++){
   samples[i*2]=std::sin(i*.713);samples[i*2+1]=std::cos(i*.371);
   a[i]=std::sin(i*.37)/taps;b[i]=std::cos(i*.57)/taps;
  }
  for(float phase:{0.f,.1f,.5f,.9999f,1.f}){
   double left=0,right=0;
   for(int i=0;i<taps;i++){
    const double weight=double(a[i])+(double(b[i])-a[i])*phase;
    left+=weight*samples[i*2];right+=weight*samples[i*2+1];
   }
   const auto actual=vinyl::convolve(samples.data(),a.data(),b.data(),taps,phase);
   assert(std::abs(actual.left-left)<1e-6);assert(std::abs(actual.right-right)<1e-6);
  }
 }
}`);
  execFileSync('c++',['-std=c++20','-O3','-fsanitize=address,undefined','-I',resolve('native/mixxx-engine-host/src'),source,'-o',binary]);
  execFileSync(binary);
 }finally{rmSync(directory,{recursive:true,force:true});}
});
