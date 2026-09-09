#pragma once
#include "pcm_ring.h"
#include <QString>
#include <memory>
namespace junction {
// Runtime supplies one authoritative, frame-ordered PCM stream. Worker owns
// input consumption; PortAudio callback owns device-ring consumption only.
class ProgramOutput {
public:
 ProgramOutput(); ~ProgramOutput();
 PcmRing& inputRing();
 void setTimeline(qint64 localMonotonicNs,quint64 originFrame,quint32 delayFrames=24000);
 bool open(int deviceIndex,QString* error=nullptr);
 void close();
 void setGain(float gain);
 bool startRecording(const QString& path,QString* error=nullptr);
 bool stopRecording(QString* error=nullptr);
 bool recording() const;
 quint64 underruns() const;
 bool isOpen() const;
 double sampleRate() const;
 double deviceLatencySeconds() const;
 float peak() const;
 float rms() const;
 quint64 lateFramesDropped() const;
 double deviceDriftPpm() const;
private:
 struct Impl; std::unique_ptr<Impl> d;
};
}
