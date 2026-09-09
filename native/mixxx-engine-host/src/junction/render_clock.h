#pragma once
// The frame clock that advances the single Mixxx graph (05 §5).
//
// During offline warm replay the graph must be driven by *processed frames*,
// not by wall time: a machine that replays eight seconds of history in one
// second must reproduce the same automatic events at the same musical
// positions. RenderClock therefore exposes a "virtual render time" derived
// from the frame counter. Network timeouts, UI elapsed time and connection
// deadlines keep using the real monotonic clock — they are not musical.
#include <QtGlobal>
#include <atomic>

namespace junction {

/// Who is allowed to advance the graph, and what the local monitor may hear.
/// Exactly one owner at a time; the transitions are handshaked (see
/// ReplayDriver).
enum class RenderMode {
    /// Nobody drives the graph. Assets and processors load asynchronously.
    Cold,
    /// A dedicated replay worker drives it over historical frames. The device
    /// callback emits idle PCM and the shared monitor is muted.
    WarmOffline,
    /// One realtime audio driver owns it at device rate, matched to the
    /// session clock, but shared performance input is still refused.
    ArmedRealtime,
    /// Normal performance: same realtime driver, shared input accepted.
    Performing,
};

const char* renderModeName(RenderMode mode);

/// Frame counter plus the media-timeline anchor for the frame it is about to
/// render. Cheap to read from an audio callback.
class RenderClock {
public:
    RenderClock(quint32 sampleRateHz, quint64 mediaFrameAnchor)
        : sampleRateHz_(sampleRateHz), mediaFrameAnchor_(mediaFrameAnchor) {}

    quint32 sampleRateHz() const { return sampleRateHz_; }
    void setSampleRate(quint32 sampleRateHz) { sampleRateHz_ = sampleRateHz; }

    /// Frames rendered since this clock was created or reanchored.
    quint64 renderFrame() const { return renderFrame_.load(std::memory_order_acquire); }
    /// Session media frame corresponding to renderFrame() == 0.
    quint64 mediaFrameAnchor() const { return mediaFrameAnchor_.load(std::memory_order_acquire); }

    /// Session media frame of the next frame to be rendered. Native rate and
    /// wire rate differ (44.1 kHz vs 48 kHz), so the conversion is explicit
    /// rather than an implicit 1:1 assumption.
    quint64 mediaFrame() const { return mediaFrameForRender(renderFrame()); }
    quint64 mediaFrameForRender(quint64 renderFrame) const {
        if (sampleRateHz_ == 0) return mediaFrameAnchor();
        // 147 native frames : 160 wire frames at 44.1 kHz. Done in integer
        // arithmetic on the full counter so a long set does not accumulate
        // rounding error.
        const quint64 seconds = renderFrame / sampleRateHz_;
        const quint64 remainder = renderFrame % sampleRateHz_;
        return mediaFrameAnchor() + seconds * kWireRate + (remainder * kWireRate) / sampleRateHz_;
    }

    /// Virtual render time in nanoseconds. In WarmOffline this is what
    /// gesture releases and other rendered-time schedules must consult, so a
    /// fast replay does not fire them twice or at the wrong musical position.
    qint64 virtualNanos() const {
        if (sampleRateHz_ == 0) return 0;
        const quint64 frames = renderFrame();
        return static_cast<qint64>((frames / sampleRateHz_) * 1000000000ULL +
                ((frames % sampleRateHz_) * 1000000000ULL) / sampleRateHz_);
    }

    /// Advances by one processed block. Called only by the current owner.
    void advance(quint32 frames) { renderFrame_.store(renderFrame_.load(std::memory_order_relaxed) + frames, std::memory_order_release); }

    /// Re-anchors when ownership moves from replay to realtime. The frame
    /// counter keeps running; only its media mapping is corrected.
    void reanchor(quint64 mediaFrameAnchor, quint64 renderFrame) {
        mediaFrameAnchor_.store(mediaFrameAnchor, std::memory_order_release);
        renderFrame_.store(renderFrame, std::memory_order_release);
    }

private:
    static constexpr quint64 kWireRate = 48000;
    quint32 sampleRateHz_;
    std::atomic<quint64> mediaFrameAnchor_;
    std::atomic<quint64> renderFrame_{0};
};

} // namespace junction
