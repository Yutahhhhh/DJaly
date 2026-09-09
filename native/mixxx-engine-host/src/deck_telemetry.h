#pragma once
#include <array>
#include <atomic>
#include <chrono>
#include <cstdint>

namespace deckclock {
inline double monotonicUs() noexcept {
    return std::chrono::duration<double, std::micro>(std::chrono::steady_clock::now().time_since_epoch()).count();
}
// Only accessed by the engine callback. Shared by all four deck anchors.
inline std::uint64_t outputFrameEnd = 0, audioConfigEpoch = 0;
inline double outputRate = 0;
inline unsigned outputFrames = 0;
inline std::atomic<bool> configChanged{false};
inline void beginAudio(unsigned frames, double rate) noexcept {
    if (configChanged.exchange(false,std::memory_order_relaxed) || rate != outputRate || frames != outputFrames) {
        ++audioConfigEpoch; outputFrameEnd = 0; outputRate = rate; outputFrames = frames;
    }
    outputFrameEnd += frames;
}
struct Boundary { std::uint64_t epoch = 0; unsigned kind = 0; };
inline thread_local Boundary* currentBoundary = nullptr;
inline void boundary(unsigned kind) noexcept {
    if (currentBoundary) { ++currentBoundary->epoch; currentBoundary->kind = kind; }
}
struct Point {
    std::uint64_t sequence, config, outputEnd, generation, trajectory, applied;
    double start, end, sourceRate, outputRate, nativeUs, velocity;
    unsigned frames, boundary;
    bool playing, scratching, nativeInput;
};
template<class T, unsigned Capacity> class Ring {
    std::array<T, Capacity> rows_{};
    std::atomic<unsigned> write_{0}, read_{0}, dropped_{0};
public:
    bool push(const T& row, unsigned reserve = 0) noexcept {
        const auto write = write_.load(std::memory_order_relaxed);
        if (write - read_.load(std::memory_order_acquire) >= Capacity - reserve) {
            dropped_.fetch_add(1, std::memory_order_relaxed); return false;
        }
        rows_[write % Capacity] = row;
        write_.store(write + 1, std::memory_order_release); return true;
    }
    bool pop(T& row) noexcept {
        const auto read = read_.load(std::memory_order_relaxed);
        if (read == write_.load(std::memory_order_acquire)) return false;
        row = rows_[read % Capacity]; read_.store(read + 1, std::memory_order_release); return true;
    }
    unsigned dropped() const noexcept { return dropped_.load(std::memory_order_relaxed); }
};
inline Ring<double,2048> callbackDurations;
inline std::atomic<unsigned> lateCallbacks{0}, xruns{0};
struct CallbackScope {
    double start=monotonicUs();
    ~CallbackScope() noexcept {
        const double elapsed=monotonicUs()-start;callbackDurations.push(elapsed);
        if(outputRate>0&&elapsed>outputFrames*1e6/outputRate)lateCallbacks.fetch_add(1,std::memory_order_relaxed);
    }
};

}
