#pragma once
#include <array>
#include <vector>
#include <cstdint>
#include <QDataStream>
namespace soundtouch { class SoundTouch; }
namespace junction::st {
constexpr unsigned maxFrames=65536;
struct Fifo { unsigned frames=0;std::vector<float> samples;Fifo():samples(maxFrames*2){} };
struct State {
    double virtualRate=1,virtualTempo=1,virtualPitch=1,rate=1,tempo=1,expected=0,fraction=0,skipFraction=0;
    std::int64_t outputCount=0;
    unsigned sampleRate=44100,filterLength=64;std::uint64_t maxNorm=0;float maxNormFloat=0;
    bool rateSet=false,rateOutput=false,antiAlias=true,quick=true,autoSequence=true,autoSeek=true,beginning=true;
    int sequenceMs=0,seekMs=0,overlapMs=8,overlapLength=0,seekLength=0,windowLength=0,sampleReq=0;
    std::array<Fifo,6> buffers; // stretch input/output, rate input/mid/output, overlap
};
bool capture(soundtouch::SoundTouch&,State&); // exclusive graph ownership; no allocation
bool restore(soundtouch::SoundTouch&,const State&); // exclusive ownership; non-RT
bool valid(const State&);
void write(QDataStream&,const State&);
bool read(QDataStream&,State&);
}
