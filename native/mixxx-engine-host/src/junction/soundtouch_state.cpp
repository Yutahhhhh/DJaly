#include "soundtouch_state.h"
#include "ddj_checkpoint.h"
#include <soundtouch/SoundTouch.h>
#include "TDStretch.h"
#include "RateTransposer.h"
#include "InterpolateCubic.h"
#include <algorithm>
#include <cmath>
namespace junction::st {
class Access {
    static bool save(soundtouch::FIFOSampleBuffer& from,Fifo& to){
        if(from.numSamples()>maxFrames||to.samples.size()!=maxFrames*2)return false;
        to.frames=from.numSamples();std::copy_n(from.ptrBegin(),to.frames*2,to.samples.begin());return true;
    }
    static void load(soundtouch::FIFOSampleBuffer& to,const Fifo& from){to.clear();to.setChannels(2);to.putSamples(from.samples.data(),from.frames);}
public:
    static bool capture(soundtouch::SoundTouch& engine,State& s){
        auto& t=*engine.pTDStretch;auto& r=*engine.pRateTransposer;auto* cubic=dynamic_cast<soundtouch::InterpolateCubic*>(r.pTransposer);
        if(!cubic||engine.channels!=2||t.channels!=2||cubic->numChannels!=2||t.overlapLength<0||unsigned(t.overlapLength)>maxFrames)return false;
        s.virtualRate=engine.virtualRate;s.virtualTempo=engine.virtualTempo;s.virtualPitch=engine.virtualPitch;s.rate=engine.rate;s.tempo=engine.tempo;
        s.expected=engine.samplesExpectedOut;s.outputCount=engine.samplesOutput;s.rateSet=engine.bSrateSet;s.rateOutput=engine.output==engine.pRateTransposer;
        if(!s.rateOutput&&engine.output!=engine.pTDStretch)return false;
        s.sampleRate=t.sampleRate;s.filterLength=r.pAAFilter->getLength();s.antiAlias=r.bUseAAFilter;s.fraction=cubic->fract;
        s.quick=t.bQuickSeek;s.autoSequence=t.bAutoSeqSetting;s.autoSeek=t.bAutoSeekSetting;s.beginning=t.isBeginning;
        s.sequenceMs=t.sequenceMs;s.seekMs=t.seekWindowMs;s.overlapMs=t.overlapMs;s.overlapLength=t.overlapLength;s.seekLength=t.seekLength;s.windowLength=t.seekWindowLength;s.sampleReq=t.sampleReq;
        s.skipFraction=t.skipFract;s.maxNorm=t.maxnorm;s.maxNormFloat=t.maxnormf;
        if(!save(t.inputBuffer,s.buffers[0])||!save(t.outputBuffer,s.buffers[1])||!save(r.inputBuffer,s.buffers[2])||!save(r.midBuffer,s.buffers[3])||!save(r.outputBuffer,s.buffers[4]))return false;
        auto& mid=s.buffers[5];if(mid.samples.size()!=maxFrames*2)return false;mid.frames=t.overlapLength;std::copy_n(t.pMidBuffer,mid.frames*2,mid.samples.begin());return valid(s);
    }
    static bool restore(soundtouch::SoundTouch& engine,const State& s){
        if(!valid(s))return false;
        engine.clear();engine.setChannels(2);engine.setSampleRate(s.sampleRate);
        engine.setSetting(SETTING_USE_QUICKSEEK,s.quick);engine.setSetting(SETTING_USE_AA_FILTER,s.antiAlias);engine.setSetting(SETTING_AA_FILTER_LENGTH,s.filterLength);
        engine.setSetting(SETTING_SEQUENCE_MS,s.autoSequence?0:s.sequenceMs);engine.setSetting(SETTING_SEEKWINDOW_MS,s.autoSeek?0:s.seekMs);engine.setSetting(SETTING_OVERLAP_MS,s.overlapMs);
        engine.setRate(s.virtualRate);engine.setTempo(s.virtualTempo);engine.setPitch(s.virtualPitch);
        auto& t=*engine.pTDStretch;auto& r=*engine.pRateTransposer;auto* cubic=dynamic_cast<soundtouch::InterpolateCubic*>(r.pTransposer);
        if(!cubic||t.overlapLength!=s.overlapLength||t.seekLength!=s.seekLength||t.seekWindowLength!=s.windowLength||t.sampleReq!=s.sampleReq||std::abs(engine.rate-s.rate)>1e-12||std::abs(engine.tempo-s.tempo)>1e-12)return false;
        engine.bSrateSet=s.rateSet;engine.samplesExpectedOut=s.expected;engine.samplesOutput=s.outputCount;engine.output=s.rateOutput?static_cast<soundtouch::FIFOSamplePipe*>(engine.pRateTransposer):engine.pTDStretch;
        t.skipFract=s.skipFraction;t.maxnorm=s.maxNorm;t.maxnormf=s.maxNormFloat;t.isBeginning=s.beginning;cubic->fract=s.fraction;
        load(t.inputBuffer,s.buffers[0]);load(t.outputBuffer,s.buffers[1]);load(r.inputBuffer,s.buffers[2]);load(r.midBuffer,s.buffers[3]);load(r.outputBuffer,s.buffers[4]);std::copy_n(s.buffers[5].samples.data(),s.overlapLength*2,t.pMidBuffer);return true;
    }
};
bool valid(const State& s){
    for(double v:{s.virtualRate,s.virtualTempo,s.virtualPitch,s.rate,s.tempo})if(!ddj::finite(v)||v<1.0/256||v>256)return false;
    if(!ddj::finite(s.expected)||s.expected<0||s.expected>1e15||s.outputCount<0||s.outputCount>1000000000000000LL||!ddj::finite(s.fraction)||s.fraction<0||s.fraction>=1||!ddj::finite(s.skipFraction)||s.skipFraction<0||s.skipFraction>=1||!ddj::finite(s.maxNormFloat))return false;
    if((s.sampleRate!=44100&&s.sampleRate!=48000)||s.filterLength<8||s.filterLength>256||s.filterLength%8||s.sequenceMs<0||s.sequenceMs>1000||s.seekMs<0||s.seekMs>1000||s.overlapMs<1||s.overlapMs>1000||s.overlapLength<0||s.overlapLength>int(maxFrames)||s.seekLength<0||s.seekLength>int(maxFrames)||s.windowLength<0||s.windowLength>int(maxFrames)||s.sampleReq<0||s.sampleReq>int(maxFrames))return false;
    for(const auto& b:s.buffers){if(b.frames>maxFrames||b.samples.size()<b.frames*2)return false;for(unsigned i=0;i<b.frames*2;i++)if(!ddj::finite(b.samples[i]))return false;}
    return s.buffers[5].frames==unsigned(s.overlapLength);
}
bool capture(soundtouch::SoundTouch& engine,State& state){return Access::capture(engine,state);}
bool restore(soundtouch::SoundTouch& engine,const State& state){return Access::restore(engine,state);}
void write(QDataStream& out,const State& s){
    out<<quint32(1)<<s.virtualRate<<s.virtualTempo<<s.virtualPitch<<s.rate<<s.tempo<<s.expected<<s.fraction<<s.skipFraction<<qint64(s.outputCount)<<quint32(s.sampleRate)<<quint32(s.filterLength)<<quint64(s.maxNorm)<<double(s.maxNormFloat);
    out<<quint8(s.rateSet)<<quint8(s.rateOutput)<<quint8(s.antiAlias)<<quint8(s.quick)<<quint8(s.autoSequence)<<quint8(s.autoSeek)<<quint8(s.beginning);
    for(int v:{s.sequenceMs,s.seekMs,s.overlapMs,s.overlapLength,s.seekLength,s.windowLength,s.sampleReq})out<<qint32(v);
    for(const auto& b:s.buffers){out<<quint32(b.frames);for(unsigned i=0;i<b.frames*2;i++)out<<quint32(std::bit_cast<quint32>(b.samples[i]));}
}
bool read(QDataStream& in,State& s){
    quint32 version=0,rate=0,length=0;quint64 norm=0;qint64 count=0;double normf=0;
    in>>version;if(version!=1)return false;
    in>>s.virtualRate>>s.virtualTempo>>s.virtualPitch>>s.rate>>s.tempo>>s.expected>>s.fraction>>s.skipFraction>>count>>rate>>length>>norm>>normf;
    s.outputCount=count;s.sampleRate=rate;s.filterLength=length;s.maxNorm=norm;s.maxNormFloat=float(normf);
    for(bool* v:{&s.rateSet,&s.rateOutput,&s.antiAlias,&s.quick,&s.autoSequence,&s.autoSeek,&s.beginning}){quint8 b=0;in>>b;if(b>1)return false;*v=b;}
    for(int* v:{&s.sequenceMs,&s.seekMs,&s.overlapMs,&s.overlapLength,&s.seekLength,&s.windowLength,&s.sampleReq}){qint32 n=0;in>>n;*v=n;}
    for(auto& b:s.buffers){quint32 frames=0;in>>frames;if(frames>maxFrames||qint64(frames)*8>in.device()->bytesAvailable())return false;b.frames=frames;for(unsigned i=0;i<frames*2;i++){quint32 bits=0;in>>bits;b.samples[i]=std::bit_cast<float>(bits);}}
    return in.status()==QDataStream::Ok&&valid(s);
}
}
