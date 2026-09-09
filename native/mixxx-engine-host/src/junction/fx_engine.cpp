#include "fx_checkpoint.h"
#include "ddj_beat_processors.h"
#include "rubberband_state.h"
#include "effects/effectslot.h"
#include "engine/effects/engineeffect.h"
#include "engine/effects/engineeffectchain.h"
#include "effects/backends/builtin/whitenoiseeffect.h"
#include "effects/backends/builtin/flangereffect.h"
#include "effects/backends/builtin/phasereffect.h"
#include "effects/backends/builtin/autopaneffect.h"
#include "effects/backends/builtin/tremoloeffect.h"
#include <rubberband/RubberBandStretcher.h>
#include <sstream>
#include <locale>
namespace junction::fx {
using rb::Cursor;
class Access {
    static EffectProcessor* processor(EngineEffect* effect){
        auto* value=effect->m_pProcessor.get();
        if(auto* wrapper=dynamic_cast<DdjTimedProcessor<FlangerEffect>*>(value))return wrapper->junctionUnderlyingProcessor();
        if(auto* wrapper=dynamic_cast<DdjTimedProcessor<PhaserEffect>*>(value))return wrapper->junctionUnderlyingProcessor();
        if(auto* wrapper=dynamic_cast<DdjTimedProcessor<ReverbEffect>*>(value))return wrapper->junctionUnderlyingProcessor();
        if(auto* wrapper=dynamic_cast<DdjTimedProcessor<EchoEffect>*>(value))return wrapper->junctionUnderlyingProcessor();
        if(auto* wrapper=dynamic_cast<DdjTimedProcessor<PitchShiftEffect>*>(value))return wrapper->junctionUnderlyingProcessor();
        return value;
    }
    static void state(WhiteNoiseGroupState& s,Cursor& c){
        c(s.previous_drywet);c.require(s.previous_drywet>=0&&s.previous_drywet<=1);
        std::string wire;if(!c.reading){std::ostringstream out;out.imbue(std::locale::classic());out<<s.gen;wire=out.str();}
        unsigned size=unsigned(wire.size());c(size);c.require(size>0&&size<=8192);if(!c.ok)return;
        if(c.reading)wire.resize(size);c.array(wire.data(),size);
        if(c.reading&&c.ok){std::istringstream tokens(wire);tokens.imbue(std::locale::classic());uint64_t value=0;unsigned count=0;while(tokens>>value){if(count>=625||value>(count==624?624u:UINT32_MAX)){c.require(false);return;}count++;}c.require(tokens.eof()&&(count==624||count==625));if(!c.ok)return;std::istringstream in(wire);in.imbue(std::locale::classic());in>>s.gen;c.require(!in.fail());in>>std::ws;c.require(in.eof());}
    }
    static void state(FlangerGroupState& s,Cursor& c){
        c(s.delayPos,s.lfoFrames,s.previousPeriodFrames,s.prev_regen,s.prev_mix,s.prev_width,s.prev_manual);
        c.require(s.delayPos<std::size(s.delayLeft));c.array(s.delayLeft,std::size(s.delayLeft));c.array(s.delayRight,std::size(s.delayRight));
    }
    static void state(PhaserGroupState& s,Cursor& c){
        c(s.leftPhase,s.rightPhase,s.oldDepth);c.array(s.oldInLeft,MAXSTAGES);c.array(s.oldInRight,MAXSTAGES);c.array(s.oldOutLeft,MAXSTAGES);c.array(s.oldOutRight,MAXSTAGES);
    }
    static void state(TremoloState& s,Cursor& c){c(s.gain,s.currentFrame,s.quantizeEnabled,s.tripletEnabled);c.require(s.gain>=0&&s.gain<=1);}
    static void state(AutoPanGroupState& s,Cursor& c){
        c(s.time,s.m_dPreviousPeriod,s.frac.ramped,s.frac.maxDifference,s.frac.currentValue,s.frac.initialized);
        auto& delay=*s.pDelay;c(delay.m_delayFrame,delay.m_doStart);c.require(delay.m_delayFrame>=0&&delay.m_delayFrame<panMaxDelay);c.array(delay.m_buf,std::size(delay.m_buf));
    }
    static void delay(DSP::Delay& s,Cursor& c){
        unsigned mask=s.size;c(mask);c.require(mask==s.size);if(!c.ok)return;
        c(s.read,s.write);c.require(s.read<=mask&&s.write<=mask);c.array(s.data,mask+1);
    }
    static void state(ReverbGroupState& s,Cursor& c){
        c(s.sampleRate,s.sendPrevious);c.require((s.sampleRate==44100||s.sampleRate==48000||s.sampleRate==96000)&&s.sendPrevious>=0&&s.sendPrevious<=1);if(!c.ok)return;
        auto& r=s.reverb;if(c.reading)r.setSamplerate(s.sampleRate);
        c(r.f_lfo,r.indiff1,r.indiff2,r.dediff1,r.dediff2);
        auto filter=[&](auto& f){c(f.a0,f.b1,f.y1);};filter(r.input.bandwidth);
        for(auto& d:r.input.lattice)delay(d,c);
        for(auto& m:r.tank.mlattice){c(m.n0,m.width,m.lfo.z,m.lfo.b);c.require(m.lfo.z==0||m.lfo.z==1);c.array(m.lfo.y,2);delay(m.delay,c);c.require(m.n0>=0&&m.width>=0&&m.n0+m.width<=m.delay.size);}
        for(auto& d:r.tank.lattice)delay(d,c);
        for(auto& d:r.tank.delay)delay(d,c);
        for(auto& f:r.tank.damping)filter(f);
        // Tap offsets are immutable topology, not peer-controlled indices.
        for(auto& tap:r.tank.taps){int value=tap;c(value);c.require(value==tap);}
    }
    static void state(EchoGroupState& s,Cursor& c){
        unsigned count=s.delay_buf.size();c(count);c.require(count==44100*6||count==48000*6||count==96000*6);if(!c.ok)return;
        if(c.reading&&count!=s.delay_buf.size())s.delay_buf=mixxx::SampleBuffer(count);
        c(s.prev_send,s.prev_feedback,s.prev_delay_samples,s.write_position,s.ping_pong);
        c.require(s.prev_send>=0&&s.prev_send<=1&&s.prev_feedback>=0&&s.prev_feedback<=1&&s.prev_delay_samples>=0&&s.prev_delay_samples<=int(count)&&s.write_position>=0&&s.write_position<int(count)&&s.ping_pong>=0&&s.ping_pong<int(count));
        c.array(s.delay_buf.data(),count);
    }
    static void state(PitchShiftGroupState& s,Cursor& c){
        if(c.reading){
            auto header=c;uint32_t magic=0;size_t rate=0,channels=0;int options=0;header(magic,rate,channels,options);
            using RB=RubberBand::RubberBandStretcher;
            if(!header.ok||magic!=0x52325331||(rate!=44100&&rate!=48000&&rate!=96000)||channels!=2||(options&~(RB::OptionProcessRealTime|RB::OptionFormantPreserved))||!(options&RB::OptionProcessRealTime)){c.require(false);return;}
            auto restored=std::make_unique<RB>(rate,channels,options);restored->setTimeRatio(2.0);restored->setTimeRatio(1.0);
            c.require(rb::Access::engine(*restored,c));if(c.ok)s.m_pRubberBand=std::move(restored);
        }else c.require(s.m_pRubberBand&&rb::Access::engine(*s.m_pRubberBand,c));
    }
    template<class State>static auto& matrix(EffectProcessor* processor){return dynamic_cast<EffectProcessorImpl<State>*>(processor)->m_channelStateMatrix;}
    template<class State>static bool visit(EffectSlot& slot,Slot& snapshot,const std::function<QString(int)>& names,const std::function<int(const QString&)>& handles,int mode){
        auto* effect=slot.m_pEngineEffect;auto* chain=slot.m_pEngineEffectChain;
        if(!effect||!chain||!dynamic_cast<EffectProcessorImpl<State>*>(processor(effect)))return false;
        auto& states=matrix<State>(processor(effect));
        if(mode==0){
            snapshot.group=slot.getGroup();snapshot.processor=slot.id();
            for(int i=0;i<states.size();i++){auto& outputs=*(states.begin()+i);for(int j=0;j<int(outputs.size());j++)if(outputs[j]){Route route;route.input=names(i);route.output=names(j);route.bytes.resize((std::is_same_v<State,PitchShiftGroupState>||std::is_same_v<State,EchoGroupState>||std::is_same_v<State,ReverbGroupState>)?maxStateBytes:32768);snapshot.routes.push_back(std::move(route));}}
            return !snapshot.routes.empty()&&snapshot.routes.size()<=8;
        }
        if(slot.getGroup()!=snapshot.group||slot.id()!=snapshot.processor)return false;
        if constexpr(std::is_same_v<State,PitchShiftGroupState>){auto* pitch=dynamic_cast<PitchShiftEffect*>(processor(effect));if(!pitch)return false;if(mode==1)snapshot.flags=pitch->m_currentFormant?1:0;else pitch->m_currentFormant=snapshot.flags!=0;}
        if(mode==1){snapshot.chainEnabled=chain->m_enableState;snapshot.mixMode=int(chain->m_mixMode);snapshot.mix=chain->m_dMix;}
        else{chain->m_enableState=snapshot.chainEnabled;chain->m_mixMode=EffectChainMixMode::Type(snapshot.mixMode);chain->m_dMix=snapshot.mix;}
        size_t sequence=0;
        for(auto& route:snapshot.routes){
            int i=-1,j=-1;
            if(mode==2){i=handles(route.input);j=handles(route.output);}
            else{
                size_t index=0;for(int a=0;a<states.size();a++){auto& outputs=*(states.begin()+a);for(int b=0;b<int(outputs.size());b++)if(outputs[b]){if(index++==sequence){i=a;j=b;}}}sequence++;
            }
            if(i<0||i>=states.size()||j<0)return false;auto& outputs=*(states.begin()+i);if(j>=int(outputs.size())||!outputs[j])return false;
            if(i>=effect->m_effectEnableStateForChannelMatrix.size()||i>=chain->m_chainStatusForChannelMatrix.size())return false;
            auto& enabled=*(effect->m_effectEnableStateForChannelMatrix.begin()+i);auto& statuses=*(chain->m_chainStatusForChannelMatrix.begin()+i);
            if(j>=enabled.size()||j>=statuses.size())return false;auto& latch=*(enabled.begin()+j);auto& status=*(statuses.begin()+j);
            if(mode==1){route.enable=unsigned(latch);route.chainEnable=unsigned(status.enableState);route.chainMix=status.oldMixKnob;}
            else{latch=EffectEnableState(route.enable);status.enableState=EffectEnableState(route.chainEnable);status.oldMixKnob=route.chainMix;}
            Cursor c(route.bytes.data(),mode==2?route.size:route.bytes.size(),mode==2);state(*outputs[j],c);if(!c.ok||(mode==2&&c.pos!=route.size))return false;if(mode==1)route.size=c.pos;
        }
        return true;
    }
public:
#ifdef DJALY_JUNCTION_FX_TEST_MAIN
    template<class Processor,class State>static bool continuation(double pitch=.25,int rate=44100){
        mixxx::EngineParameters parameters(mixxx::audio::SampleRate(rate),256);State original(parameters),resumed(parameters);Processor renderer;
        const auto manifest=Processor::getManifest();QMap<QString,EngineEffectParameterPointer> values;for(const auto& parameter:manifest->parameters())values[parameter->id()]=EngineEffectParameterPointer(new EngineEffectParameter(parameter));renderer.loadEngineEffectParameters(values);
        if constexpr(std::is_same_v<State,PitchShiftGroupState>)values["pitch"]->setValue(pitch);
        std::array<float,512> input{},output{},copy{};GroupFeatureState features;features.beat_length=GroupFeatureBeatLength{.5,1};
        Route checkpoint;checkpoint.bytes.resize((std::is_same_v<State,PitchShiftGroupState>||std::is_same_v<State,EchoGroupState>||std::is_same_v<State,ReverbGroupState>)?maxStateBytes:32768);
        for(unsigned block=0;block<240;block++){
            for(unsigned i=0;i<input.size();i++)input[i]=.2*std::sin((block*512+i)*.031)+.05*std::sin((block*512+i)*.127);
            renderer.processChannel(&original,input.data(),output.data(),parameters,EffectEnableState::Enabled,features);
            if(block>=120){renderer.processChannel(&resumed,input.data(),copy.data(),parameters,EffectEnableState::Enabled,features);if(output!=copy)return false;}
            if(block==119){Cursor out(checkpoint.bytes.data(),checkpoint.bytes.size(),false);state(original,out);if(!out.ok)return false;checkpoint.size=out.pos;
                if(!validate<State>(checkpoint))return false;Cursor in(checkpoint.bytes.data(),checkpoint.size,true);state(resumed,in);if(!in.ok||in.pos!=checkpoint.size)return false;
                auto size=checkpoint.size;checkpoint.size--;if(validate<State>(checkpoint))return false;checkpoint.size=size;}
        }
        return true;
    }
#endif
    static bool run(EffectSlot& slot,Slot& s,const std::function<QString(int)>& names,const std::function<int(const QString&)>& handles,int mode){
        const auto id=QString(slot.id()).replace("org.djaly.effects.","org.mixxx.effects.");
        if(id==WhiteNoiseEffect::getId())return visit<WhiteNoiseGroupState>(slot,s,names,handles,mode);
        if(id==FlangerEffect::getId())return visit<FlangerGroupState>(slot,s,names,handles,mode);
        if(id==PhaserEffect::getId())return visit<PhaserGroupState>(slot,s,names,handles,mode);
        if(id==AutoPanEffect::getId())return visit<AutoPanGroupState>(slot,s,names,handles,mode);
        if(id==TremoloEffect::getId())return visit<TremoloState>(slot,s,names,handles,mode);
        if(id==PitchShiftEffect::getId())return visit<PitchShiftGroupState>(slot,s,names,handles,mode);
        if(id==ReverbEffect::getId())return visit<ReverbGroupState>(slot,s,names,handles,mode);
        if(id==EchoEffect::getId())return visit<EchoGroupState>(slot,s,names,handles,mode);
        return false;
    }
    template<class State>static bool validate(const Route& route){State value(mixxx::EngineParameters(mixxx::audio::SampleRate(44100),256));Cursor c(const_cast<uint8_t*>(route.bytes.data()),route.size,true);state(value,c);return c.ok&&c.pos==route.size;}
};
bool supported(const QString& id){return id==WhiteNoiseEffect::getId()||id==FlangerEffect::getId()||id==PhaserEffect::getId()||id==AutoPanEffect::getId()||id==TremoloEffect::getId()||id==DdjTimedProcessor<FlangerEffect>::getId()||id==DdjTimedProcessor<PhaserEffect>::getId()||id==PitchShiftEffect::getId()||id==DdjTimedProcessor<PitchShiftEffect>::getId()||id==EchoEffect::getId()||id==DdjTimedProcessor<EchoEffect>::getId()||id==ReverbEffect::getId()||id==DdjTimedProcessor<ReverbEffect>::getId();}
Slot prepare(EffectSlot& slot,const std::function<QString(int)>& names){Slot result;if(!Access::run(slot,result,names,{},0))return {};return result;}
bool capture(EffectSlot& slot,Slot& s){return Access::run(slot,s,{}, {},1);}
bool restore(EffectSlot& slot,const Slot& s,const std::function<int(const QString&)>& handles){auto& mutableState=const_cast<Slot&>(s);return Access::run(slot,mutableState,{},handles,2);}
bool validateRoute(const QString& processorId,const Route& route){
    const auto id=QString(processorId).replace("org.djaly.effects.","org.mixxx.effects.");
    if(!route.size||route.size>route.bytes.size()||route.size>maxStateBytes)return false;
    if(id==WhiteNoiseEffect::getId())return Access::validate<WhiteNoiseGroupState>(route);
    if(id==FlangerEffect::getId())return Access::validate<FlangerGroupState>(route);
    if(id==PhaserEffect::getId())return Access::validate<PhaserGroupState>(route);
    if(id==AutoPanEffect::getId())return Access::validate<AutoPanGroupState>(route);
    if(id==TremoloEffect::getId())return Access::validate<TremoloState>(route);
    if(id==PitchShiftEffect::getId())return Access::validate<PitchShiftGroupState>(route);
    if(id==ReverbEffect::getId())return Access::validate<ReverbGroupState>(route);
    if(id==EchoEffect::getId())return Access::validate<EchoGroupState>(route);
    return false;
}
}

#ifdef DJALY_JUNCTION_FX_TEST_MAIN
#include <QCoreApplication>
#include <cstdio>
int main(int argc,char** argv){
 QCoreApplication app(argc,argv);unsigned failed=0;
 const auto check=[&](const char* name,bool ok){std::printf("%s %s\n",ok?"PASS":"FAIL",name);if(!ok)failed++;};
 check("whitenoise continuation",junction::fx::Access::continuation<WhiteNoiseEffect,WhiteNoiseGroupState>());
 check("flanger continuation",junction::fx::Access::continuation<FlangerEffect,FlangerGroupState>());
 check("phaser continuation",junction::fx::Access::continuation<PhaserEffect,PhaserGroupState>());
 check("autopan continuation",junction::fx::Access::continuation<AutoPanEffect,AutoPanGroupState>());
 check("reverb continuation",junction::fx::Access::continuation<ReverbEffect,ReverbGroupState>());
 check("echo continuation",junction::fx::Access::continuation<EchoEffect,EchoGroupState>());
 check("pitchshift continuation",junction::fx::Access::continuation<PitchShiftEffect,PitchShiftGroupState>());
 check("pitchshift 96k reverse pitch",junction::fx::Access::continuation<PitchShiftEffect,PitchShiftGroupState>(-.25,96000));
 check("tremolo continuation",junction::fx::Access::continuation<TremoloEffect,TremoloState>());
 return failed?1:0;
}
#endif
