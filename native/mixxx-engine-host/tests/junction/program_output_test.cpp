#include "harness.h"
#include "junction/program_output.h"
#include "junction/audio_clock.h"
#include <portaudio.h>
#include <sndfile.h>
#include <QTemporaryDir>
#include <QFileInfo>
#include <thread>
#include <chrono>
#include <vector>
#include <cstdlib>
using namespace junction;
namespace {
struct Capture {std::vector<float> pcm;size_t written=0;};
int captureCallback(const void* input,void*,unsigned long frames,const PaStreamCallbackTimeInfo*,PaStreamCallbackFlags,void* user){auto*c=static_cast<Capture*>(user);size_t count=std::min<size_t>(frames*2,c->pcm.size()-c->written);if(input)std::copy_n(static_cast<const float*>(input),count,c->pcm.data()+c->written);c->written+=count;return paContinue;}
void deviceTone(unsigned sourceRate,double skewPpm,unsigned blocks=300,bool splice=false) {
 CHECK_EQ(Pa_Initialize(),paNoError);int device=-1;for(int i=0;i<Pa_GetDeviceCount();i++){auto*d=Pa_GetDeviceInfo(i);if(d&&QString::fromUtf8(d->name)=="BlackHole 2ch"){device=i;break;}}Pa_Terminate();CHECK(device>=0);
 QTemporaryDir dir;QString path=dir.path()+"/program.wav",error;ProgramOutput program;CHECK(program.open(device,&error));CHECK(program.isOpen());CHECK(program.sampleRate()>0);Capture capture;capture.pcm.resize(size_t(program.sampleRate()*(blocks/100.0+2))*2);PaStream* captureStream=nullptr;PaStreamParameters input{};input.device=device;input.channelCount=2;input.sampleFormat=paFloat32;input.suggestedLatency=Pa_GetDeviceInfo(device)->defaultLowInputLatency;CHECK_EQ(Pa_OpenStream(&captureStream,&input,nullptr,program.sampleRate(),256,paNoFlag,captureCallback,&capture),paNoError);CHECK_EQ(Pa_StartStream(captureStream),paNoError);program.setGain(.5f);CHECK(program.startRecording(path,&error));
 qint64 t0=monotonicNanos();program.setTimeline(t0,0,24000);auto start=std::chrono::steady_clock::now();unsigned frames=sourceRate/100;std::vector<float> pcm(std::max(frames,480U)*2);quint64 sourceFrame=0;double maxPeak=0;
 for(unsigned block=0;block<blocks;block++){if(splice&&block==blocks/2){sourceRate=48000;frames=480;sourceFrame=0;}for(unsigned i=0;i<frames;i++){double t=(sourceFrame+i)/double(sourceRate)+(splice&&block>=blocks/2?blocks*.005:0);pcm[i*2]=.2f*float(std::sin(2*3.141592653589793*220*t+(splice?.3:0)));pcm[i*2+1]=.2f*float(std::sin(2*3.141592653589793*331*t+(splice?.3:0)));}PcmBlockInfo info;info.epoch=splice&&block>=blocks/2?2:1;info.generation=info.epoch;info.mediaFrame=(splice&&block>=blocks/2?blocks*240:0)+mediaFrameAdvance(sourceFrame,sourceRate);info.sourceFrame=sourceFrame;info.sequence=block;info.frameCount=frames;info.sampleRateHz=sourceRate;info.channels=2;CHECK(program.inputRing().push(pcm.data(),info));sourceFrame+=frames;maxPeak=std::max(maxPeak,double(program.peak()));std::this_thread::sleep_until(start+std::chrono::nanoseconds(qint64((block+1)*10000000.0/(1+skewPpm/1e6))));}
 std::this_thread::sleep_for(std::chrono::milliseconds(650));auto late=program.lateFramesDropped();auto drift=program.deviceDriftPpm();CHECK(program.stopRecording(&error));CHECK(!program.recording());CHECK_EQ(Pa_StopStream(captureStream),paNoError);CHECK_EQ(Pa_CloseStream(captureStream),paNoError);program.close();SF_INFO info{};auto*f=sf_open(path.toUtf8().constData(),SFM_READ,&info);CHECK(f);CHECK(info.frames>info.samplerate*3);std::vector<float> audio(size_t(info.frames)*2);CHECK_EQ(sf_readf_float(f,audio.data(),info.frames),info.frames);sf_close(f);
 double energy[2]={};int zeros=0,maxZeros=0;size_t begin=size_t(info.samplerate*.8),end=size_t(info.samplerate*(blocks/100.0-.2));int crossings[2]={};double maxStep=0;for(size_t i=begin;i<end;i++){bool zero=true;for(int c=0;c<2;c++){float v=audio[i*2+c];energy[c]+=v*v;maxStep=std::max(maxStep,double(std::fabs(v-audio[(i-1)*2+c])));if(std::fabs(v)>1e-6)zero=false;if(v>=0&&audio[(i-1)*2+c]<0)crossings[c]++;}zeros=zero?zeros+1:0;maxZeros=std::max(maxZeros,zeros);}
 double seconds=double(end-begin)/info.samplerate;double rms0=std::sqrt(energy[0]/(end-begin)),rms1=std::sqrt(energy[1]/(end-begin));std::printf("  Program %u Hz skew %.0f ppm -> %d Hz: rms %.6f/%.6f, Hz %.2f/%.2f, max silence %d frames, late %llu, device drift %.1f ppm\n",sourceRate,skewPpm,info.samplerate,rms0,rms1,crossings[0]/seconds,crossings[1]/seconds,maxZeros,(unsigned long long)late,drift);
 CHECK_NEAR(rms0,.0707107,.002);CHECK_NEAR(rms1,.0707107,.002);CHECK_NEAR(crossings[0]/seconds,220.,1);CHECK_NEAR(crossings[1]/seconds,331.,1);CHECK(maxZeros<16);CHECK(maxPeak>.09);CHECK(maxStep<.012);CHECK(late<32);
 CHECK(capture.written>end*2);double capturedEnergy=0;int captureZeros=0,maxCaptureZeros=0;for(size_t i=begin;i<end;i++){auto l=capture.pcm[i*2],r=capture.pcm[i*2+1];capturedEnergy+=l*l+r*r;captureZeros=(std::fabs(l)+std::fabs(r)<1e-6)?captureZeros+1:0;maxCaptureZeros=std::max(maxCaptureZeros,captureZeros);}double capturedRms=std::sqrt(capturedEnergy/((end-begin)*2));std::printf("  BlackHole input capture rms %.6f, max silence %d frames\n",capturedRms,maxCaptureZeros);CHECK_NEAR(capturedRms,.0707107,.002);CHECK(maxCaptureZeros<16);
}
}
JTEST("program-output","explicit device required") {ProgramOutput p;QString error;CHECK(!p.open(-1,&error));CHECK(!error.isEmpty());}
JTEST("program-output-device","BlackHole native local 44100 and wire 48000 waveform gain and finalize") {if(!std::getenv("JUNCTION_AUDIO_DEVICE_TEST"))return;deviceTone(44100,0);deviceTone(48000,0);deviceTone(48000,200);}

JTEST("program-output-long-device","BlackHole thirty-second realtime 200ppm clock skew") {if(!std::getenv("JUNCTION_AUDIO_LONG_TEST"))return;deviceTone(48000,200,3000);}

JTEST("program-output-splice-device","BlackHole old native overlap to new wire epoch at H") {if(!std::getenv("JUNCTION_AUDIO_DEVICE_TEST"))return;deviceTone(44100,0,300,true);}
