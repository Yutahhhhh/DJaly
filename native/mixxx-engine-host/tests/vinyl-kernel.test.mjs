import test from 'node:test';import assert from 'node:assert/strict';
import {mkdtemp,writeFile} from 'node:fs/promises';import {tmpdir} from 'node:os';import path from 'node:path';import {execFileSync} from 'node:child_process';
test('vinyl kernels preserve DC/passband and suppress above-Nyquist tones across rate banks',async()=>{
 const directory=await mkdtemp(path.join(tmpdir(),'plumdeck-vinyl-kernel-'));
 const source=String.raw`
#include "vinyl_kernel.h"
#include <complex>
#include <cassert>
#include <iostream>
int main(){const auto& kernels=vinyl::kernels();double worstPass=0,worstStop=-300;size_t bytes=0;
for(const auto& b:kernels.banks)bytes+=b.coefficients.size()*sizeof(float);
for(double rate:{1.01,1.2,1.5,2.0,3.0,6.0,8.0,12.0,16.0,32.0,64.0}){
 const auto& b=kernels.select(rate);
 for(int phase:{0,7,16,31}){
 double dc=0;for(int t=0;t<b.taps;t++)dc+=b.coefficients[phase*b.taps+t];assert(std::abs(dc-1)<1e-6);
 for(double fraction:{.1,.2,.3,.35,.4,.5,.55}){
  const double frequency=fraction/rate;std::complex<double> response{};
  for(int t=0;t<b.taps;t++)response+=double(b.coefficients[phase*b.taps+t])*std::polar(1.0,-2*3.141592653589793*frequency*t);
  const double db=20*std::log10(std::abs(response));
  if(fraction<=.4){worstPass=std::max(worstPass,std::abs(db));if(std::abs(db)>=.5)std::cerr<<rate<<" "<<fraction<<" "<<db<<"\n";assert(std::abs(db)<.5);}
  if(fraction>=.5){worstStop=std::max(worstStop,db);if(db>=-60)std::cerr<<rate<<" "<<fraction<<" "<<db<<"\n";assert(db<-60);}
 }
}}
std::cout<<"passbandMaxDb="<<worstPass<<" stopbandMaxDb="<<worstStop<<" kernelBytes="<<bytes<<"\n";
assert(bytes<16*1024*1024);
}`;
 const cpp=path.join(directory,'test.cpp'),binary=path.join(directory,'test');await writeFile(cpp,source);
 execFileSync('c++',['-std=c++20','-O3','-I',path.resolve(import.meta.dirname,'../src'),cpp,'-o',binary]);
 assert.match(execFileSync(binary,{encoding:'utf8'}),/passbandMaxDb=/);
});
