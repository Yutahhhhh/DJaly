#include "harness.h"
#include "junction/validation_capture.h"
#include "junction/media_transport.h"
#include <array>
#include <thread>
#include <chrono>
#include <limits>
using namespace junction;
namespace {
PcmBlockInfo block(quint64 frame, quint32 count=256, quint32 rate=48000) {
    PcmBlockInfo info;
    info.epoch=3;info.generation=7;info.mediaFrame=12345+mediaFrameAdvance(frame,rate);
    info.sourceFrame=frame;info.sequence=frame/256;info.frameCount=count;
    info.sampleRateHz=rate;info.channels=2;return info;
}
void compareWithEncoder(quint32 rate) {
    if(!MediaTransport::available())return;
    ValidationCapture local,wire(ValidationCapture::InputDomain::Wire);
    MediaTransport transport("remote",{},{});
    PcmRing input(128,4096,2);
    QString error;
    CHECK(transport.start(false,&error));transport.startProducer(&input);
    std::array<float,512> pcm{};
    for(unsigned n=0;n<120;n++) {
        if(n==20){CHECK(local.begin(24345,2400,3,7,&error));CHECK(wire.begin(24345,2400,3,7,&error));}
        for(unsigned j=0;j<256;j++) {
            const double t=double(n*256+j)/rate;
            pcm[j*2]=float(.3*std::sin(t*2*3.141592653589793*997));
            pcm[j*2+1]=float(.2*std::cos(t*2*3.141592653589793*5311));
        }
        auto info=block(n*256,256,rate);
        CHECK(local.consume(info,pcm.data(),256,&error));CHECK(input.push(pcm.data(),info));
    }
    std::array<float,1920> converted{};
    for(unsigned attempt=0;attempt<2000&&!wire.ready();attempt++) {
        auto got=transport.preCodecRing().popBlock(converted.data(),960);
        if(got.frames)CHECK(wire.consume(got.info,converted.data(),got.frames,&error));
        else std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    transport.close();CHECK(local.ready());CHECK(wire.ready());auto a=local.take(),b=wire.take();
    CHECK(a&&b);CHECK_EQ(a->startMediaFrame,24345ULL);CHECK_EQ(a->samples.size(),4800ULL);
    CHECK_EQ(a->samples.size(),b->samples.size());double maxError=0;
    for(size_t i=0;i<a->samples.size();i++)maxError=std::max(maxError,double(std::fabs(a->samples[i]-b->samples[i])));
    CHECK_NEAR(maxError,0,1e-7);CHECK(!local.take());
}
}
JTEST("validation-capture","native 44100 and 48000 equal actual encoder preCodec PCM") {
    compareWithEncoder(44100);compareWithEncoder(48000);
}
JTEST("validation-capture","rejects missing overlapping and epoch changed input") {
    std::array<float,512> pcm{};QString error;
    for(int variant=0;variant<3;variant++) {
        ValidationCapture capture(ValidationCapture::InputDomain::Wire);
        CHECK(capture.begin(12345,1024,3,7));CHECK(capture.consume(block(0),pcm.data(),256));
        auto bad=block(variant==0?512:variant==1?0:256);if(variant==2)bad.epoch++;
        CHECK(!capture.consume(bad,pcm.data(),256,&error));CHECK(!capture.ready());CHECK(!capture.take());CHECK(!error.isEmpty());
    }
}
JTEST("validation-capture","rejects bounds stale starts non-finite data and false frame anchors") {
    ValidationCapture capture;std::array<float,512> pcm{};QString error;
    CHECK(!capture.begin(std::numeric_limits<quint64>::max()-10,100,3,7));
    CHECK(!capture.begin(12345,24001,3,7));CHECK(capture.consume(block(0),pcm.data(),256));
    CHECK(!capture.begin(12345,100,3,7));CHECK(capture.begin(13000,100,3,7));
    auto wrong=block(256);wrong.mediaFrame+=10;CHECK(!capture.consume(wrong,pcm.data(),256,&error));CHECK(!capture.take());
    capture.reset();CHECK(capture.begin(12345,100,3,7));pcm[0]=std::numeric_limits<float>::quiet_NaN();
    CHECK(!capture.consume(block(0),pcm.data(),256));CHECK(!capture.ready());
}
JTEST("validation-capture","begin preserves continuous SRC history and incomplete windows never publish") {
    ValidationCapture capture;std::array<float,512> pcm{};
    for(unsigned n=0;n<10;n++)CHECK(capture.consume(block(n*256,256,44100),pcm.data(),256));
    CHECK(capture.begin(16000,24000,3,7));CHECK(!capture.take());capture.cancel();
    CHECK(capture.begin(16000,2400,3,7));CHECK(capture.consume(block(2560,256,44100),pcm.data(),256));CHECK(!capture.take());
}
