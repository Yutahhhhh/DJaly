#pragma once
#include "pcm_ring.h"
#include <memory>
#include <optional>
#include <vector>

namespace junction {
// Single non-realtime-thread component. Feed every block, including when no
// comparison is requested: the continuous SRC history is part of the signal.
// Native matches the transport encoder's SRC_SINC_FASTEST, even at 48 kHz.
// Wire accepts already converted preCodec PCM and never filters it again.
class ValidationCapture {
public:
    enum class InputDomain { Native, Wire };
    struct Window {
        quint64 startMediaFrame = 0;
        quint64 epoch = 0;
        quint64 generation = 0;
        std::vector<float> samples; // 48 kHz stereo, exact requested frame count
    };
    explicit ValidationCapture(InputDomain domain = InputDomain::Native);
    ~ValidationCapture();
    bool begin(quint64 startMediaFrame, quint32 frameCount, quint64 epoch,
            quint64 generation, QString* error = nullptr);
    bool consume(const PcmBlockInfo& info, const float* samples, quint32 frames,
            QString* error = nullptr);
    bool ready() const;
    std::optional<Window> take();
    QString error() const;
    void cancel(); // Cancels this window, preserving continuous SRC history.
    void reset(); // Stream/session restart only; also discards SRC history.
private:
    struct Impl;
    std::unique_ptr<Impl> d;
};
}
