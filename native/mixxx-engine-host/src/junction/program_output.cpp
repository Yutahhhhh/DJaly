#include "../sound_file.h"
#include "program_output.h"
#include "audio_clock.h"
#include <portaudio.h>
#include <samplerate.h>
#include <sndfile.h>
#include <array>
#include <thread>
#include <mutex>
#include <chrono>
#include <cmath>
namespace junction {
struct ProgramOutput::Impl {
 PcmRing input{256,4096,2},device{128,4096,2},record{256,4096,2};
 std::atomic<bool> running{false},recordEnabled{false},fileRunning{false},fileFailed{false};
 std::atomic<int> recordingCallbacks{0};std::atomic<float> gain{1};std::atomic<qint64> t0{0};std::atomic<quint64> origin{0};std::atomic<quint32> delay{24000};
 PaStream* stream=nullptr;std::thread worker,fileWorker;SNDFILE* file=nullptr;bool initialized=false;double outputRate=48000;std::atomic<quint64> missed{0};std::atomic<qint64> queued{0};
 std::atomic<float> meterPeak{0},meterRms{0};std::atomic<double> publishedRate{0},latency{0},drift{0};std::atomic<quint64> lateDropped{0};
 AudioClockAnchor deviceClock{48000};quint64 deviceFrames=0,playbackFrames=0;qint64 playbackOrigin=0;bool playbackPrimed=false;
 static int callback(const void*,void* output,unsigned long frames,const PaStreamCallbackTimeInfo* time,PaStreamCallbackFlags,void* userdata){auto*d=static_cast<Impl*>(userdata);auto*out=static_cast<float*>(output);std::fill_n(out,frames*2,0.f);quint32 offset=0;int discarded=0;std::array<float,8192> discard{};
 qint64 base=d->t0.load();qint64 audibleNs=monotonicNanos();if(time)audibleNs+=qint64(std::max(0.0,time->outputBufferDacTime-time->currentTime)*1e9);
 // Anchor once, then follow the device's frame counter. Re-anchoring every
 // callback to scheduler wakeup time repeatedly drops/inserts audible samples.
 if(base&&!d->playbackPrimed){d->playbackOrigin=qint64(d->origin.load())+(audibleNs-base)*48000/1000000000LL-qint64(d->delay.load());d->playbackFrames=0;d->playbackPrimed=true;}
 qint64 wanted=d->playbackOrigin+qint64(mediaFrameAdvance(d->playbackFrames,quint32(d->outputRate)));d->playbackFrames+=frames;
 while(offset<frames){PcmBlockInfo head;if(!d->device.peek(&head)){d->missed.fetch_add(frames-offset,std::memory_order_relaxed);break;}
  // Rational conversion is rounded independently at ring/block/callback
  // boundaries; allow three wire frames of rounding, never a whole block.
  if(base){qint64 desired=wanted+qint64(offset*48000.0/d->outputRate);qint64 delta=qint64(head.mediaFrame)-desired;
   if(delta>3){quint32 silence=std::min<quint32>(frames-offset,quint32(std::min<double>(frames-offset,std::ceil(delta*d->outputRate/48000.0))));offset+=silence;continue;}
   if(delta < -3&&discarded<4){quint32 skip=std::min<quint32>(4096,quint32(std::min<double>(4096,std::floor(-delta*d->outputRate/48000.0))));auto r=d->device.popBlock(discard.data(),skip);d->queued.fetch_sub(r.frames,std::memory_order_relaxed);d->lateDropped.fetch_add(r.frames,std::memory_order_relaxed);++discarded;continue;}
  }
  if(base&&qint64(head.mediaFrame)<wanted+qint64(offset*48000.0/d->outputRate)-3)break;
  auto r=d->device.popBlock(out+offset*2,quint32(frames-offset));if(!r.frames)break;offset+=r.frames;d->queued.fetch_sub(r.frames,std::memory_order_relaxed);
 }
 float gain=d->gain.load(std::memory_order_relaxed),peak=0;double energy=0;for(unsigned long i=0;i<frames*2;i++){out[i]=std::clamp(out[i]*gain,-1.f,1.f);peak=std::max(peak,std::fabs(out[i]));energy+=out[i]*out[i];}d->meterPeak.store(peak,std::memory_order_relaxed);d->meterRms.store(float(std::sqrt(energy/(frames*2))),std::memory_order_relaxed);
 d->deviceFrames+=frames;if(d->deviceFrames<=25600)d->deviceClock.reset();d->deviceClock.observe(d->deviceFrames,time&&time->outputBufferDacTime>0?qint64(time->outputBufferDacTime*1e9):monotonicNanos());d->drift.store(d->deviceClock.driftPpm(),std::memory_order_relaxed);
 d->recordingCallbacks.fetch_add(1);if(d->recordEnabled.load(std::memory_order_acquire)){PcmBlockInfo info;info.frameCount=quint32(frames);info.channels=2;info.sampleRateHz=quint32(d->outputRate);if(!d->record.push(out,info))d->fileFailed=true;}d->recordingCallbacks.fetch_sub(1);return paContinue;}
 void run(){int err=0;auto*src=src_new(SRC_SINC_FASTEST,2,&err);if(!src)return;std::array<float,8192> in{},out{};quint64 generation=~quint64(0),epoch=~quint64(0),seq=0,outputFrames=0,outputOrigin=0;quint32 inputRate=0;AsrcController controller;
 while(running){PcmBlockInfo peek;if(!input.peek(&peek)){std::this_thread::sleep_for(std::chrono::milliseconds(2));continue;}
 qint64 base=t0.load();if(base){qint64 diff=peek.mediaFrame>=origin.load()?qint64(peek.mediaFrame-origin.load()):-qint64(origin.load()-peek.mediaFrame);qint64 target=base+(diff+delay.load())*1000000000LL/48000;auto now=monotonicNanos();if(target>now+100000000){std::this_thread::sleep_for(std::chrono::milliseconds(2));continue;}if(target+qint64(mediaFrameAdvance(peek.frameCount,peek.sampleRateHz))*1000000000LL/48000<now-20000000){input.popBlock(in.data(),4096);continue;}}
 if(queued.load()>4096){std::this_thread::sleep_for(std::chrono::milliseconds(2));continue;}
 auto r=input.popBlock(in.data(),4096);if(!r.frames||!r.info.sampleRateHz)continue;if(epoch!=r.info.epoch||generation!=r.info.generation||inputRate!=r.info.sampleRateHz){
 // Drain the old converter up to the authoritative boundary before changing
 // rate/epoch. Resetting immediately drops the sinc lookahead before H.
 if(inputRate&&r.info.mediaFrame>=outputOrigin){quint64 boundary=quint64((r.info.mediaFrame-outputOrigin)*outputRate/48000.0);for(int attempt=0;attempt<4&&outputFrames<boundary;attempt++){SRC_DATA tail{};tail.data_in=in.data();tail.data_out=out.data();tail.output_frames=4096;tail.src_ratio=outputRate/inputRate;tail.end_of_input=1;if(src_process(src,&tail)||!tail.output_frames_gen)break;auto count=quint32(std::min<quint64>(tail.output_frames_gen,boundary-outputFrames));PcmBlockInfo old;old.epoch=epoch;old.generation=generation;old.mediaFrame=outputOrigin+mediaFrameAdvance(outputFrames,quint32(outputRate));old.sourceFrame=outputFrames;old.sequence=seq++;old.frameCount=count;old.sampleRateHz=quint32(outputRate);old.channels=2;queued.fetch_add(count);if(!device.push(out.data(),old))queued.fetch_sub(count);outputFrames+=count;}}
 src_reset(src);inputRate=r.info.sampleRateHz;AsrcController::Config config;config.targetFillFrames=std::max(0.0,(double(delay.load())/48000-.1)*r.info.sampleRateHz);config.deadbandFrames=r.info.sampleRateHz*.04;config.proportionalGain=2e-8;config.integralGain=4e-12;config.maxRatioDeviation=.001;controller=AsrcController(config);epoch=r.info.epoch;generation=r.info.generation;outputFrames=0;outputOrigin=r.info.mediaFrame;}
 long used=0;while(used<r.frames){SRC_DATA data{};data.data_in=in.data()+used*2;data.input_frames=r.frames-used;data.data_out=out.data();data.output_frames=4096;data.src_ratio=outputRate/r.info.sampleRateHz*controller.update(input.availableFrames());if(src_process(src,&data))break;used+=data.input_frames_used;if(data.output_frames_gen){auto info=r.info;info.mediaFrame=outputOrigin+mediaFrameAdvance(outputFrames,quint32(outputRate));info.sourceFrame=outputFrames;outputFrames+=data.output_frames_gen;info.sampleRateHz=quint32(outputRate);info.frameCount=quint32(data.output_frames_gen);info.sequence=seq++;queued.fetch_add(info.frameCount);if(!device.push(out.data(),info))queued.fetch_sub(info.frameCount);}if(!data.input_frames_used&&!data.output_frames_gen)break;}
 }src_delete(src);}
};
ProgramOutput::ProgramOutput():d(new Impl){}
ProgramOutput::~ProgramOutput(){close();}
PcmRing&ProgramOutput::inputRing(){return d->input;}
void ProgramOutput::setTimeline(qint64 ns,quint64 frame,quint32 delay){d->origin=frame;d->delay=delay;d->t0=ns;}
bool ProgramOutput::open(int index,QString* error){close();auto fail=[&](QString e){if(error)*error=e;close();return false;};if(Pa_Initialize()!=paNoError)return fail("PortAudio initialization failed");d->initialized=true;if(index<0)return fail("Select an explicit Program output device");auto*info=Pa_GetDeviceInfo(index);if(!info||info->maxOutputChannels<2)return fail("Program needs a stereo output device");d->outputRate=info->defaultSampleRate;d->publishedRate=d->outputRate;d->deviceClock=AudioClockAnchor(quint32(d->outputRate));d->deviceFrames=0;d->playbackPrimed=false;d->playbackFrames=0;d->missed=0;d->lateDropped=0;d->input.drop();d->device.drop();d->queued=0;PaStreamParameters p{};p.device=index;p.channelCount=2;p.sampleFormat=paFloat32;p.suggestedLatency=info->defaultLowOutputLatency;auto err=Pa_OpenStream(&d->stream,nullptr,&p,d->outputRate,256,paNoFlag,Impl::callback,d.get());if(err!=paNoError)return fail(QString::fromUtf8(Pa_GetErrorText(err)));d->latency=Pa_GetStreamInfo(d->stream)->outputLatency;d->running=true;d->worker=std::thread([this]{d->run();});err=Pa_StartStream(d->stream);if(err!=paNoError)return fail(QString::fromUtf8(Pa_GetErrorText(err)));return true;}
void ProgramOutput::close(){if(d->stream){Pa_StopStream(d->stream);Pa_CloseStream(d->stream);d->stream=nullptr;}stopRecording();d->running=false;if(d->worker.joinable())d->worker.join();if(d->initialized){Pa_Terminate();d->initialized=false;}}
void ProgramOutput::setGain(float gain){if(std::isfinite(gain))d->gain=std::clamp(gain,0.f,2.f);}
bool ProgramOutput::startRecording(const QString&path,QString*error){if(d->file||!d->stream){if(error)*error="Program output inactive or recording already active";return false;}SF_INFO info{};info.samplerate=int(d->outputRate);info.channels=2;info.format=SF_FORMAT_WAV|SF_FORMAT_PCM_24;d->file=openSoundFile(path,SFM_WRITE,&info);if(!d->file){if(error)*error="Cannot open Program recording";return false;}d->record.drop();d->fileFailed=false;d->fileRunning=true;d->fileWorker=std::thread([this]{std::array<float,8192> pcm{};while(d->fileRunning||d->record.availableFrames()){auto r=d->record.popBlock(pcm.data(),4096);if(r.frames){if(sf_writef_float(d->file,pcm.data(),r.frames)!=r.frames)d->fileFailed=true;}else std::this_thread::sleep_for(std::chrono::milliseconds(2));}sf_write_sync(d->file);if(sf_close(d->file))d->fileFailed=true;});d->recordEnabled=true;return true;}
bool ProgramOutput::stopRecording(QString*error){d->recordEnabled=false;if(!d->file)return true;
 while(d->recordingCallbacks.load())std::this_thread::sleep_for(std::chrono::milliseconds(1));d->fileRunning=false;if(d->fileWorker.joinable())d->fileWorker.join();d->file=nullptr;if(d->fileFailed){if(error)*error="Program recording write/finalize failed";return false;}return true;}
bool ProgramOutput::recording()const{return d->recordEnabled;}
quint64 ProgramOutput::underruns()const{return d->missed;}
bool ProgramOutput::isOpen()const{return d->running;}
double ProgramOutput::sampleRate()const{return d->publishedRate;}
double ProgramOutput::deviceLatencySeconds()const{return d->latency;}
float ProgramOutput::peak()const{return d->meterPeak;}
float ProgramOutput::rms()const{return d->meterRms;}
quint64 ProgramOutput::lateFramesDropped()const{return d->lateDropped;}
double ProgramOutput::deviceDriftPpm()const{return d->drift;}
}
