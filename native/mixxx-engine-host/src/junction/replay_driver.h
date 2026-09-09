#pragma once
// Exclusive ownership of the one Mixxx graph (05 §5).
//
// There is exactly one EngineMixer per process because Mixxx's ControlObject
// names ("[Master]", "[Channel1]", ...) are process-global. Junction therefore
// switches that single graph between render modes instead of spawning a second
// one. Two things must never happen:
//
//   * the SoundManager device callback and a replay worker both calling
//     process() on the same graph, and
//   * a callback spinning or waiting for an ACK.
//
// Ownership moves by an asynchronous handshake: the controller *requests* a
// mode, the current owner notices at its next block boundary, stops touching
// the graph and publishes a release ACK with the last frame it rendered, and
// only then is the next owner granted the frame after that. Callbacks only
// ever do lock-free loads and stores.
#include "render_clock.h"
#include <QString>
#include <atomic>

namespace junction {

/// Which concrete driver holds the graph. Kept separate from RenderMode
/// because ArmedRealtime and Performing share the same physical driver and
/// must not trigger a handoff between them.
enum class GraphDriver {
    None,
    /// The realtime audio device callback.
    Realtime,
    /// The offline warm-replay worker.
    Replay,
};

const char* graphDriverName(GraphDriver driver);

/// Result of a driver asking "may I process this block?".
struct DriveGrant {
    /// False means: do not touch the graph, just fill your sink with silence
    /// or idle PCM. Never a reason to block.
    bool mayProcess = false;
    /// True on the block where this driver has just been asked to hand over.
    /// The driver must finish the current block, publish the ACK and stop.
    bool releaseRequested = false;
    quint64 generation = 0;
};

class ReplayDriver {
public:
    ReplayDriver(quint32 sampleRateHz, quint64 mediaFrameAnchor)
        : clock_(sampleRateHz, mediaFrameAnchor) {}

    RenderClock& clock() { return clock_; }
    const RenderClock& clock() const { return clock_; }

    RenderMode mode() const { return mode_.load(std::memory_order_acquire); }
    GraphDriver owner() const { return owner_.load(std::memory_order_acquire); }
    /// Increments on every ownership request; lets a late ACK from a previous
    /// request be recognised and ignored.
    quint64 requestGeneration() const { return requestGeneration_.load(std::memory_order_acquire); }
    bool transferPending() const { return pending_.load(std::memory_order_acquire); }

    // ---- controller side (non-realtime) ----------------------------------

    /// Asks for `driver` to own the graph in `mode`. Returns the request
    /// generation. Idempotent: requesting what is already in effect is a no-op
    /// that returns the current generation.
    quint64 requestTransfer(GraphDriver driver, RenderMode mode);

    /// True once the previous owner acknowledged and the new one was granted.
    bool transferComplete(quint64 generation);

    /// Frame the outgoing owner stopped at, valid after its ACK.
    quint64 releasedAtRenderFrame() const { return releasedAt_.load(std::memory_order_acquire); }

    /// Moves ArmedRealtime -> Performing. This is only an input-gate change on
    /// the driver that already owns the graph, so it must not hand over.
    /// Returns false if the realtime driver is not the owner.
    bool promoteToPerforming();

    /// Drops back from Performing to ArmedRealtime, e.g. after ownership of
    /// the shared stage moves elsewhere. Never moves a performing graph
    /// offline: that would rewind audio that has already been broadcast.
    bool demoteToArmed();

    /// Forces everything back to Cold. Only for teardown.
    void reset(quint64 mediaFrameAnchor);

    // ---- driver side (may run in an audio callback) ----------------------

    /// Lock-free. Tells `driver` whether it may advance the graph this block.
    DriveGrant beginBlock(GraphDriver driver) const;

    /// Publishes the release ACK. Called by the outgoing owner right after it
    /// finished its final block. Safe from a callback: two relaxed stores and
    /// one release store, no waiting.
    void acknowledgeRelease(GraphDriver driver, quint64 lastRenderFrame, quint64 generation);

    // ---- diagnostics ------------------------------------------------------
    quint64 transfers() const { return transfers_.load(std::memory_order_relaxed); }
    /// Counts blocks a non-owner was asked for. Should stay flat once settled;
    /// a rising count means a driver is running that should have stopped.
    quint64 deniedBlocks() const { return deniedBlocks_.load(std::memory_order_relaxed); }
    QString describe() const;

private:
    RenderClock clock_;
    std::atomic<RenderMode> mode_{RenderMode::Cold};
    std::atomic<GraphDriver> owner_{GraphDriver::None};
    std::atomic<GraphDriver> target_{GraphDriver::None};
    std::atomic<RenderMode> targetMode_{RenderMode::Cold};
    std::atomic<bool> pending_{false};
    std::atomic<quint64> requestGeneration_{0};
    std::atomic<quint64> releasedAt_{0}, acknowledgedGeneration_{0};
    std::atomic<quint64> transfers_{0};
    mutable std::atomic<quint64> deniedBlocks_{0};
};

} // namespace junction
