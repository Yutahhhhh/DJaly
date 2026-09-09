#include "rubberband_state.h"
#include "rubberband/RubberBandStretcher.h"
#include "faster/R2Stretcher.h"
#include "faster/StretcherChannelData.h"
#include "common/MovingMedian.h"
#include "common/Resampler.h"
#include "common/StretchCalculator.h"
#include "common.h"
#define MAX_CHANNELS 128
#include "sinc_fields.h"
namespace junction::rb {
using namespace RubberBand;
template<class T>void Access::ring(RingBuffer<T>& b,Cursor& c){
    int capacity=b.getSize();c(capacity);int count=b.getReadSpace();c(count);c.require(capacity>=0&&capacity<=1048576&&count>=0&&count<=capacity&&count<=b.getSize());
    int reader=b.m_reader.load();
    for(int i=0;i<count&&c.ok;i++){T v=c.reading?T{}:b.m_buffer[(reader+i)%b.m_size];c(v);if(c.reading)b.m_buffer[i]=v;}
    if(c.reading&&c.ok){b.m_reader=0;b.m_writer=count;}
}
template<class T>void Access::median(MovingMedian<T>& m,Cursor& c){
    auto& b=m.m_buffer;c.equal(b.getSize());c(m.m_fill,m.m_percentile);
    c.require(m.m_fill>=0&&m.m_fill<=b.getSize()&&m.m_percentile>=0&&m.m_percentile<=100);
    c.array(m.m_sortspace.data(),m.m_fill);
    int count=b.getReadSpace();c(count);c.require(count==m.m_fill);
    int reader=b.m_reader;
    for(int i=0;i<count&&c.ok;i++){T v=c.reading?T{}:b.m_buffer[(reader+i)%b.m_size];c(v);if(c.reading)b.m_buffer[i]=v;}
    if(c.reading&&c.ok){b.m_reader=0;b.m_writer=count;}
}
bool Access::sinc(void* ptr,Cursor& c){
    auto& s=*static_cast<SRC_STATE*>(ptr);
    c.require(std::strstr(src_get_version(),"0.2.2")&&s.mode==SRC_MODE_PROCESS&&s.channels>0&&s.channels<=2&&s.private_data&&!s.callback_func);
    if(!c.ok)return false;
    auto& f=*static_cast<SINC_FILTER*>(s.private_data);
    c.require(f.sinc_magic_marker==MAKE_MAGIC(' ','s','i','n','c',' ')&&f.b_len>0&&f.b_len<262144);
    c.equal(s.channels);c.equal(f.coeff_half_len);c.equal(f.index_inc);c.equal(f.b_len);
    c(s.last_ratio,s.last_position,s.error,f.in_count,f.in_used,f.out_count,f.out_gen,f.src_ratio,f.input_index,f.b_current,f.b_end,f.b_real_end);
    c.require(s.last_ratio>=0&&s.last_ratio<=256&&s.last_position>=0&&s.last_position<=1&&s.error==SRC_ERR_NO_ERROR&&f.b_current>=0&&f.b_current<f.b_len&&f.b_end>=0&&f.b_end<=f.b_len&&f.b_real_end>=-1&&f.b_real_end<=f.b_len);
    c.array(f.buffer,f.b_len);return c.ok;
}
bool Access::r2(R2Stretcher& e,Cursor& c){
    c.require(e.m_realtime&&!e.m_threaded&&e.m_channels>0&&e.m_channels<=2);
    c.equal(uint32_t{0x52325331});c.equal(e.m_sampleRate);c.equal(e.m_channels);c.equal(e.m_options);
    double time=e.m_timeRatio,pitch=e.m_pitchScale;size_t maxProcess=e.m_maxProcessSize;c(time,pitch,maxProcess);
    c.require(time>0&&time<=256&&pitch>0&&pitch<=256&&maxProcess<=65536);
    if(!c.ok)return false;
    if(c.reading){e.setTimeRatio(time);e.setPitchScale(pitch);if(maxProcess)e.setMaxProcessSize(maxProcess);}
    c.equal(e.m_fftSize);c.equal(e.m_aWindowSize);c.equal(e.m_sWindowSize);c.equal(e.m_increment);c.equal(e.m_outbufSize);c.equal(e.m_baseFftSize);c.equal(e.m_rateMultiple);
    c(e.m_expectedInputDuration,e.m_inputDuration,e.m_mode,e.m_detectorType,e.m_silentHistory,e.m_freq0,e.m_freq1,e.m_freq2);
    c.require(e.m_mode==R2Stretcher::Processing||e.m_mode==R2Stretcher::JustCreated);
    c.require(e.m_detectorType>=CompoundAudioCurve::PercussiveDetector&&e.m_detectorType<=CompoundAudioCurve::SoftDetector);
    c.require(e.m_phaseResetDf.empty()&&e.m_silence.empty()&&e.m_outputIncrements.empty());
    auto& d=*e.m_phaseResetAudioCurve;
    c(d.m_type,d.m_lastHf,d.m_lastResult,d.m_risingCount);c.require(d.m_type==e.m_detectorType);
    c.array(d.m_percussive.m_prevMag,e.m_fftSize/2+1);
    auto* hf=dynamic_cast<MovingMedian<double>*>(d.m_hfFilter);auto* derivative=dynamic_cast<MovingMedian<double>*>(d.m_hfDerivFilter);
    c.require(hf&&derivative);if(!c.ok)return false;median(*hf,c);median(*derivative,c);
    auto& s=*e.m_stretchCalculator;c.equal(s.m_sampleRate);c.equal(s.m_increment);
    c(s.m_prevDf,s.m_prevRatio,s.m_prevTimeRatio,s.m_justReset,s.m_transientAmnesty,s.m_useHardPeaks,s.m_inFrameCounter,s.m_frameCheckpoint.first,s.m_frameCheckpoint.second,s.m_outFrameCounter);
    c.require(s.m_keyFrameMap.empty()&&s.m_peaks.empty());
    for(auto* channel:e.m_channelData){
        auto& a=*channel;ring(*a.inbuf,c);ring(*a.outbuf,c);
        const auto bins=e.m_fftSize/2+1;c.array(a.prevPhase,bins);c.array(a.prevError,bins);c.array(a.unwrappedPhase,bins);
        c(a.accumulatorFill,a.unityResetLow,a.unchanged,a.prevIncrement,a.chunkCount,a.inCount,a.outCount);
        c.require(a.accumulatorFill<=size_t(a.inbuf->getSize())&&a.prevIncrement<=65536);
        // All history arrays are zero-initialized at their allocated capacity.
        c.array(a.accumulator,a.inbuf->getSize());c.array(a.windowAccumulator,a.inbuf->getSize());
        c(a.interpolatorScale);c.require(a.interpolatorScale>=0&&a.interpolatorScale<=65536);if(a.interpolatorScale>0)c.array(a.interpolator,a.inbuf->getSize());
        int64_t input=a.inputSize;bool draining=a.draining,complete=a.outputComplete;c(input,draining,complete);c.require(input>=-1);
        if(c.reading&&c.ok){a.inputSize=input;a.draining=draining;a.outputComplete=complete;}
        bool has=a.resampler!=nullptr;c.equal(has);if(has)c.require(resampler(*a.resampler,c));
    }
    return c.ok;
}
bool capture(RubberBandStretcher& e,State& s){s.size=0;Cursor c(s.bytes.data(),s.bytes.size(),false);if(!Access::engine(e,c))return false;s.size=c.pos;return true;}
bool restore(RubberBandStretcher& e,const State& s){if(!s.size||s.size>s.bytes.size())return false;Cursor c(const_cast<uint8_t*>(s.bytes.data()),s.size,true);return Access::engine(e,c)&&c.pos==s.size;}
bool validate(const State& s){
    if(!s.size||s.size>s.bytes.size())return false;
    Cursor c(const_cast<uint8_t*>(s.bytes.data()),s.size,true);
    uint32_t magic=0;size_t rate=0,channels=0;int options=0;c(magic,rate,channels,options);
    using RB=RubberBandStretcher;
    constexpr int allowed=RB::OptionProcessRealTime|RB::OptionTransientsMixed|RB::OptionTransientsSmooth|RB::OptionDetectorPercussive|RB::OptionDetectorSoft|RB::OptionPhaseIndependent|RB::OptionThreadingNever|RB::OptionWindowShort|RB::OptionWindowLong|RB::OptionSmoothingOn|RB::OptionFormantPreserved|RB::OptionPitchHighQuality|RB::OptionPitchHighConsistency|RB::OptionChannelsTogether;
    if(!c.ok||magic!=0x52325331||(rate!=44100&&rate!=48000&&rate!=96000)||channels!=2||(options&~allowed)||!(options&RB::OptionProcessRealTime))return false;
    RB candidate(rate,channels,options);candidate.setTimeRatio(2.0);candidate.setTimeRatio(1.0);
    return restore(candidate,s);
}

}
