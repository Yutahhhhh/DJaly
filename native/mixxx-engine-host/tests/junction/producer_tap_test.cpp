#include "harness.h"
#include "junction/producer_tap.h"
using namespace junction;
JTEST("producer-tap","independent consumers receive identical clocked PCM without codec") {
 ProducerTap tap;tap.enable(true,true);float pcm[512];for(int i=0;i<512;i++)pcm[i]=float(i)/512;
 PcmBlockInfo info;info.epoch=7;info.generation=9;info.mediaFrame=80000;info.sourceFrame=73500;info.frameCount=256;info.sampleRateHz=44100;info.channels=2;tap.capture(pcm,info);
 float local[512],net[512];auto a=tap.localRing().popBlock(local,256);auto b=tap.networkRing().popBlock(net,256);CHECK_EQ(a.frames,256U);CHECK_EQ(b.info.mediaFrame,80000ULL);for(int i=0;i<512;i++){CHECK_EQ(local[i],pcm[i]);CHECK_EQ(net[i],pcm[i]);}
 tap.enable(false,true);tap.capture(pcm,info);CHECK_EQ(tap.networkRing().availableFrames(),0U);CHECK_EQ(tap.localRing().availableFrames(),256U);
}
