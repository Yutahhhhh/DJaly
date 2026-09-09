#include "replay_driver.h"

namespace junction {

const char* renderModeName(RenderMode mode) {
    switch (mode) {
    case RenderMode::Cold: return "COLD";
    case RenderMode::WarmOffline: return "WARM_OFFLINE";
    case RenderMode::ArmedRealtime: return "ARMED_REALTIME";
    case RenderMode::Performing: return "PERFORMING";
    }
    return "COLD";
}

const char* graphDriverName(GraphDriver driver) {
    switch (driver) {
    case GraphDriver::None: return "none";
    case GraphDriver::Realtime: return "realtime";
    case GraphDriver::Replay: return "replay";
    }
    return "none";
}

quint64 ReplayDriver::requestTransfer(GraphDriver driver, RenderMode mode) {
    if (pending_.load(std::memory_order_acquire)) return 0;
    const GraphDriver current = owner_.load(std::memory_order_acquire);
    if (current == driver && mode_.load(std::memory_order_acquire) == mode && !pending_.load(std::memory_order_acquire))
        return requestGeneration_.load(std::memory_order_acquire);

    target_.store(driver, std::memory_order_relaxed);
    targetMode_.store(mode, std::memory_order_relaxed);
    const quint64 generation = requestGeneration_.fetch_add(1, std::memory_order_acq_rel) + 1;

    if (current == GraphDriver::None || current == driver) {
        // Nothing to take the graph away from: grant immediately.
        mode_.store(mode, std::memory_order_relaxed);
        owner_.store(driver, std::memory_order_release);
        pending_.store(false, std::memory_order_release);
        transfers_.fetch_add(1, std::memory_order_relaxed);
        return generation;
    }
    // The outgoing owner will see this at its next block boundary. We do not
    // wait for it here; the controller polls transferComplete().
    pending_.store(true, std::memory_order_release);
    return generation;
}

bool ReplayDriver::promoteToPerforming() {
    if (owner_.load(std::memory_order_acquire) != GraphDriver::Realtime) return false;
    if (pending_.load(std::memory_order_acquire)) return false;
    const RenderMode current = mode_.load(std::memory_order_acquire);
    if (current != RenderMode::ArmedRealtime && current != RenderMode::Performing) return false;
    mode_.store(RenderMode::Performing, std::memory_order_release);
    return true;
}

bool ReplayDriver::demoteToArmed() {
    if (owner_.load(std::memory_order_acquire) != GraphDriver::Realtime) return false;
    const RenderMode current = mode_.load(std::memory_order_acquire);
    if (current != RenderMode::Performing && current != RenderMode::ArmedRealtime) return false;
    mode_.store(RenderMode::ArmedRealtime, std::memory_order_release);
    return true;
}

void ReplayDriver::reset(quint64 mediaFrameAnchor) {
    pending_.store(false, std::memory_order_release);
    owner_.store(GraphDriver::None, std::memory_order_release);
    target_.store(GraphDriver::None, std::memory_order_relaxed);
    mode_.store(RenderMode::Cold, std::memory_order_release);
    targetMode_.store(RenderMode::Cold, std::memory_order_relaxed);
    clock_.reanchor(mediaFrameAnchor, 0);
}

DriveGrant ReplayDriver::beginBlock(GraphDriver driver) const {
    DriveGrant grant;
    if (owner_.load(std::memory_order_acquire) != driver) {
        deniedBlocks_.fetch_add(1, std::memory_order_relaxed);
        return grant;
    }
    grant.generation = requestGeneration_.load(std::memory_order_acquire);
    grant.mayProcess = true;
    // Still the owner, but a handover is queued: process this block, then ACK.
    grant.releaseRequested = pending_.load(std::memory_order_acquire) &&
            target_.load(std::memory_order_acquire) != driver;
    return grant;
}

void ReplayDriver::acknowledgeRelease(GraphDriver driver, quint64 lastRenderFrame, quint64 generation) {
    if (!pending_.load(std::memory_order_acquire) || generation != requestGeneration_.load(std::memory_order_acquire)) return;
    if (owner_.load(std::memory_order_acquire) != driver) return;
    releasedAt_.store(lastRenderFrame, std::memory_order_relaxed);
    owner_.store(GraphDriver::None, std::memory_order_release);
    acknowledgedGeneration_.store(generation, std::memory_order_release);
}

bool ReplayDriver::transferComplete(quint64 generation) {
    if (!generation || requestGeneration_.load(std::memory_order_acquire) != generation) return false;
    if (!pending_.load(std::memory_order_acquire)) return true;
    if (acknowledgedGeneration_.load(std::memory_order_acquire) != generation) return false;
    mode_.store(targetMode_.load(std::memory_order_relaxed), std::memory_order_relaxed);
    pending_.store(false, std::memory_order_relaxed);
    owner_.store(target_.load(std::memory_order_relaxed), std::memory_order_release);
    transfers_.fetch_add(1, std::memory_order_relaxed);
    return true;
}

QString ReplayDriver::describe() const {
    return QStringLiteral("mode=%1 owner=%2 pending=%3 gen=%4 renderFrame=%5 mediaFrame=%6")
            .arg(QString::fromLatin1(renderModeName(mode())))
            .arg(QString::fromLatin1(graphDriverName(owner())))
            .arg(transferPending() ? QStringLiteral("yes") : QStringLiteral("no"))
            .arg(requestGeneration())
            .arg(clock_.renderFrame())
            .arg(clock_.mediaFrame());
}

} // namespace junction
