import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,writeFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {execFileSync} from 'node:child_process';
test('native streaming pyramid preserves antiphase peaks, weighted energy, filters and SPSC bounds',()=>{
 const dir=mkdtempSync(join(tmpdir(),'plumdeck-pyramid-'));
 try{
 const source=join(dir,'test.cpp'),binary=join(dir,'test');
 writeFileSync(source,`
#include "waveform/pyramid.h"
#include "deck_telemetry.h"
#include <cassert>
#include <iostream>
int main(){
 std::array<std::vector<waveform::Bin>,26> levels;
 waveform::Pyramid pyramid(48000,[&](unsigned l,std::uint64_t,const auto& bins){levels[l].insert(levels[l].end(),bins.begin(),bins.end());});
 const unsigned count=262147;double energy=0;
 for(unsigned f=0;f<count;++f){double x=f%997==0?1:std::sin(f*.13)*.25;energy+=x*x;pyramid.sample(x,-x);}pyramid.finish();
 assert(levels[0].size()==(count+63)/64);
 for(const auto& level:levels){if(level.empty())continue;double total=0;unsigned n=0;for(const auto& bin:level){n+=bin.count;total+=bin.squares[0][0];assert(bin.min[0]==-bin.max[1]);assert(bin.max[0]==-bin.min[1]);}assert(n==count);assert(std::abs(total-energy)<1e-7);}
 assert(levels[0].back().count==3);
 waveform::Biquad low(48000,250,false), high(48000,2500,true);double lowEnergy=0,highEnergy=0;
 for(int i=0;i<96000;++i){double x=std::sin(2*3.141592653589793*100*i/48000);double l=low.process(x),h=high.process(x);if(i>48000){lowEnergy+=l*l;highEnergy+=h*h;}}
 assert(lowEnergy>23000);assert(highEnergy<1);
 deckclock::Ring<int,4> ring;for(int i=0;i<4;i++)assert(ring.push(i));assert(!ring.push(9));assert(ring.dropped()==1);int value;for(int i=0;i<4;i++){assert(ring.pop(value));assert(value==i);}assert(!ring.pop(value));
 std::cout<<"ok";
}`);
 execFileSync('c++',['-std=c++20','-O2','-I',resolve('native/mixxx-engine-host/src'),source,'-o',binary],{stdio:'pipe'});
 assert.equal(execFileSync(binary,{encoding:'utf8'}),'ok');
 }finally{rmSync(dir,{recursive:true,force:true});}
});
