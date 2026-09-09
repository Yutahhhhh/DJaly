#include "keylock_checkpoint.h"
#include "engine/enginebuffer.h"
#include "engine/bufferscalers/enginebufferscalest.h"
#include "engine/bufferscalers/enginebufferscalerubberband.h"
#include "engine/readaheadmanager.h"
#include "engine/controls/enginecontrol.h"
#include <soundtouch/SoundTouch.h>
namespace junction::keylock {
class Access {
public:
    static bool active(EngineBuffer& e){return e.m_pScale==e.m_pScaleST||e.m_pScale==e.m_pScaleRB;}
    static bool capture(EngineBuffer& e,State& s){
        if(!active(e)||e.m_scratching_old||e.m_bCrossfadeReady)return false;
        s.usesRubberBand=e.m_pScale==e.m_pScaleRB;
        auto& scaler=*e.m_pScale;auto& reader=*e.m_pReadAheadManager;
        if(reader.m_readAheadLog.size()>s.readLog.size())return false;
        if(s.usesRubberBand){auto& rb=*e.m_pScaleRB;if(rb.m_useEngineFiner||!rb.m_pRubberBand||!junction::rb::capture(*rb.m_pRubberBand,s.rubberband))return false;s.backwards=rb.m_bBackwards;s.remainingPadding=rb.m_remainingPaddingInOutput;}
        else{if(!st::capture(*e.m_pScaleST->m_pSoundTouch,s.processor))return false;s.backwards=e.m_pScaleST->m_bBackwards;s.effectiveRate=e.m_pScaleST->m_effectiveRate;}
        s.position=e.m_playPos.value();s.readerPosition=reader.m_currentPosition;s.speed=e.m_speed_old;s.actualSpeed=e.m_actual_speed;s.tempo=e.m_tempo_ratio_old;s.pitch=e.m_pitch_old;s.base=e.m_baserate_old;s.rate=e.m_rate_old;s.reverse=e.m_reverse_old;
        s.scaleBase=scaler.m_dBaseRate;s.scaleTempo=scaler.m_dTempoRatio;s.scalePitch=scaler.m_dPitchRatio;
        s.logSize=0;for(const auto& entry:reader.m_readAheadLog)s.readLog[s.logSize++]={entry.virtualPlaypositionStart,entry.virtualPlaypositionEndNonInclusive};return valid(s);
    }
    static bool restore(EngineBuffer& e,const State& s){
        if(!valid(s))return false;
        auto* selected=s.usesRubberBand?static_cast<EngineBufferScale*>(e.m_pScaleRB):static_cast<EngineBufferScale*>(e.m_pScaleST);
        auto& scaler=*selected;auto& reader=*e.m_pReadAheadManager;
        if(s.usesRubberBand){auto& rb=*e.m_pScaleRB;if(rb.m_useEngineFiner||!rb.m_pRubberBand||!junction::rb::restore(*rb.m_pRubberBand,s.rubberband))return false;rb.m_bBackwards=s.backwards;rb.m_remainingPaddingInOutput=s.remainingPadding;}
        else{if(scaler.getOutputSignal().getSampleRate().value()!=s.processor.sampleRate||!st::restore(*e.m_pScaleST->m_pSoundTouch,s.processor))return false;e.m_pScaleST->m_effectiveRate=s.effectiveRate;e.m_pScaleST->m_bBackwards=s.backwards;}
        // The stage driver is stopped here. Replace the queued cold seek and
        // both cursors together; the next callback continues the existing DSP.
        e.m_queuedSeek.setValue(e.kNoQueuedSeek);e.m_playPos=mixxx::audio::FramePos(s.position);
        for(const auto& control:e.m_engineControls)control->notifySeek(e.m_playPos);
        reader.m_currentPosition=s.readerPosition;reader.m_readAheadLog.clear();for(unsigned i=0;i<s.logSize;i++)reader.m_readAheadLog.emplace_back(s.readLog[i][0],s.readLog[i][1]);reader.m_cacheMissCount=0;reader.m_cacheMissExpected=false;
        e.m_speed_old=s.speed;e.m_actual_speed=s.actualSpeed;e.m_tempo_ratio_old=s.tempo;e.m_pitch_old=s.pitch;e.m_baserate_old=s.base;e.m_rate_old=s.rate;e.m_reverse_old=s.reverse;e.m_scratching_old=false;e.m_pScale=selected;e.m_bScalerChanged=false;e.m_bCrossfadeReady=false;
        scaler.m_dBaseRate=s.scaleBase;scaler.m_dTempoRatio=s.scaleTempo;scaler.m_dPitchRatio=s.scalePitch;e.hintReader(s.rate);return true;
    }
};
bool active(EngineBuffer& engine){return Access::active(engine);}
bool capture(EngineBuffer& engine,State& state){return Access::capture(engine,state);}
bool restore(EngineBuffer& engine,const State& state){return Access::restore(engine,state);}
}
