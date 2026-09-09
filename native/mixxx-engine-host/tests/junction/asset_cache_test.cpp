#include "harness.h"
#include "junction/asset_cache.h"
#include "junction/ids.h"
#include <QTemporaryDir>
#include <QFile>
using namespace junction;
JTEST("asset-cache","resumes verified chunks and atomically publishes only decoder accepted bytes") {
 QTemporaryDir dir;QByteArray data(40000,'x');QString id=sha256Hex(data);QString error;
 {AssetCache c(dir.path());CHECK(c.begin(id,data.size(),&error));CHECK(c.put(id,0,data.left(32768),&error));CHECK(!c.put(id,0,QByteArray(32768,'z'),&error));CHECK(c.resolve(id).isEmpty());}
 AssetCache c(dir.path());CHECK(c.begin(id,data.size(),&error));CHECK(c.receivedBitmap(id)[0]);CHECK(c.put(id,32768,data.mid(32768),&error));CHECK(!c.finalize(id,[](auto){return false;},&error));CHECK(c.finalize(id,[](auto){return true;},&error));CHECK(!c.resolve(id).isEmpty());
 QFile f(c.resolve(id));CHECK(f.open(QIODevice::ReadWrite));f.write("bad");f.close();CHECK(c.resolve(id).isEmpty());
}
JTEST("asset-cache","rejects traversal symlink escape and quota overrun") {QTemporaryDir dir;AssetCache c(dir.path(),1024);CHECK(!c.begin("../x",10));CHECK(!c.begin(QString(64,'a'),1025));QFile::link("/tmp",dir.path()+"/"+QString(64,'a')+".partial");CHECK(!c.begin(QString(64,'a'),100));}

#include "junction/ddj_checkpoint.h"
JTEST("dsp-checkpoint","96 kHz preallocated routes preserve live Roll state and reject unsupported capacity") {
 QTemporaryDir directory;const auto path=directory.path()+"/state";
 junction::ddj::Snapshot original;original.processor="org.djaly.effects.roll";
 junction::ddj::Route route;route.input="[Master]";route.output="[Master]";route.rate=96000;
 route.state.ring.resize(96000*8);route.state.ring[1024]=.375f;route.state.write=69376;route.state.captured=69376;route.state.loopLength=11025;route.state.loopRead=58351;route.state.phase=.2926;original.routes.push_back(route);
 CHECK(junction::ddj::write(path,original));junction::ddj::Snapshot restored;CHECK(junction::ddj::read(path,&restored));
 CHECK_EQ(restored.routes[0].rate,96000U);CHECK_EQ(restored.routes[0].state.loopRead,58351ULL);CHECK_EQ(restored.routes[0].state.ring[1024],.375f);
 original.routes[0].rate=192000;CHECK(junction::ddj::write(path,original));CHECK(!junction::ddj::read(path,nullptr));
}

#include "junction/soundtouch_state.h"
#include <soundtouch/SoundTouch.h>
#include <QBuffer>
JTEST("soundtouch-state","partial FIFO checkpoint resumes stereo tempo and pitch bit exactly") {
 for(const auto settings:std::array<std::array<double,3>,2>{{{1.02,.97,48000.0/44100},{.82,1.07,.8}}}){
 soundtouch::SoundTouch original,copy;for(auto* p:{&original,&copy}){p->setSampleRate(44100);p->setChannels(2);p->setTempo(settings[0]);p->setPitch(settings[1]);p->setRate(settings[2]);p->setSetting(SETTING_USE_QUICKSEEK,1);}
 float input[1024],output[1024],other[1024];unsigned cursor=0;
 auto feed=[&]{for(unsigned i=0;i<512;i++,cursor++){input[i*2]=.3f*std::sin(cursor*.035+cursor*cursor*1e-9);input[i*2+1]=.2f*std::sin(cursor*.057);}};
 for(int n=0;n<500;n++){feed();original.putSamples(input,512);while(original.numSamples()>17)original.receiveSamples(output,std::min(512u,original.numSamples()-17));}
 junction::st::State saved;CHECK(junction::st::capture(original,saved));QByteArray bytes;QDataStream writer(&bytes,QIODevice::WriteOnly);writer.setByteOrder(QDataStream::LittleEndian);junction::st::write(writer,saved);
 junction::st::State decoded;QDataStream reader(bytes);reader.setByteOrder(QDataStream::LittleEndian);CHECK(junction::st::read(reader,decoded));CHECK(junction::st::restore(copy,decoded));
 unsigned compared=0;for(int n=0;n<100;n++){feed();original.putSamples(input,512);copy.putSamples(input,512);const auto count=original.receiveSamples(output,512);CHECK_EQ(copy.receiveSamples(other,512),count);for(unsigned i=0;i<count*2;i++)CHECK_EQ(output[i],other[i]);compared+=count;}
 CHECK(compared>40000);decoded.fraction=2;CHECK(!junction::st::restore(copy,decoded));QDataStream truncated(bytes.left(bytes.size()-1));truncated.setByteOrder(QDataStream::LittleEndian);CHECK(!junction::st::read(truncated,decoded));
 }
}

#include "junction/keylock_checkpoint.h"
JTEST("keylock-asset","portable engine cursors and DSP state reject duplicate decks and truncation") {
 QTemporaryDir directory;const auto path=directory.path()+"/keylock";
 soundtouch::SoundTouch processor;processor.setSampleRate(44100);processor.setChannels(2);processor.setTempo(1.02);
 junction::keylock::Snapshot snapshot;snapshot.emplace_back();auto& state=snapshot.back();state.deck=3;state.position=98765.25;state.readerPosition=201728;state.speed=1.02;state.rate=1.02;state.logSize=1;state.readLog[0]={197530.5,201728};
 float samples[1024]={};processor.putSamples(samples,512);CHECK(junction::st::capture(processor,state.processor));CHECK(junction::keylock::write(path,snapshot));
 junction::keylock::Snapshot decoded;CHECK(junction::keylock::read(path,&decoded));CHECK_EQ(decoded[0].position,98765.25);CHECK_EQ(decoded[0].readLog[0][1],201728.0);
 snapshot.push_back(snapshot[0]);CHECK(junction::keylock::write(path,snapshot));CHECK(!junction::keylock::read(path,nullptr));snapshot.pop_back();CHECK(junction::keylock::write(path,snapshot));QFile file(path);CHECK(file.open(QIODevice::ReadWrite));CHECK(file.resize(file.size()-1));file.close();CHECK(!junction::keylock::read(path,nullptr));
}

#include "junction/rubberband_state.h"
#include <rubberband/RubberBandStretcher.h>
JTEST("rubberband-state","R2 retains bit-identical PCM after pitch and tempo changes with queued output") {
 using RB=RubberBand::RubberBandStretcher;
 for(int options:{int(RB::OptionProcessRealTime),int(RB::OptionProcessRealTime|RB::OptionEngineFaster|RB::OptionThreadingNever|RB::OptionPitchHighConsistency)})
 for(double pitch:{48000.0/44100.0,0.97}){
  RB original(44100,2,options),resumed(44100,2,options);original.setTimeRatio(2.0);original.setTimeRatio(1.0);resumed.setTimeRatio(2.0);resumed.setTimeRatio(1.0);original.setMaxProcessSize(512);resumed.setMaxProcessSize(512);original.setTimeRatio(1.0/1.02);original.setPitchScale(pitch);
  std::array<float,512> left{},right{},outL{},outR{},copyL{},copyR{};const float* input[]={left.data(),right.data()};float* output[]={outL.data(),outR.data()};float* copy[]={copyL.data(),copyR.data()};size_t total=0;
  for(int block=0;block<160;block++){
   for(int i=0;i<512;i++){double t=(block*512+i)/44100.0;left[i]=0.2*std::sin(t*2*3.141592653589793*(440+17*t));right[i]=0.14*std::sin(t*2*3.141592653589793*733.37)+left[i]*.3;}
   original.process(input,512,false);if(block>=80)resumed.process(input,512,false);
   if(block>=80)CHECK_EQ(original.available(),resumed.available());
   while(original.available()>17){size_t count=std::min(original.available()-17,512);CHECK_EQ(original.retrieve(output,count),count);if(block>=80){CHECK_EQ(resumed.retrieve(copy,count),count);for(size_t i=0;i<count;i++){CHECK_EQ(outL[i],copyL[i]);CHECK_EQ(outR[i],copyR[i]);}total+=count;}}
   if(block==79){junction::rb::State state;CHECK(junction::rb::capture(original,state));CHECK(state.size>1000);CHECK(junction::rb::validate(state));CHECK(junction::rb::restore(resumed,state));auto length=state.size;state.size=length-1;CHECK(!junction::rb::validate(state));state.size=length;state.bytes[0]^=1;CHECK(!junction::rb::validate(state));}
  }
  CHECK(total>30000);
 }
}
