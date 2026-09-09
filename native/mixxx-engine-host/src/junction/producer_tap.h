#pragma once
#include "pcm_ring.h"
namespace junction {
class ProducerTap {
public:
    ProducerTap(): network_(128,4096,2), local_(128,4096,2) {}
    void enable(bool network, bool local) { networkEnabled_.store(network); localEnabled_.store(local); }
    void capture(const float* pcm, const PcmBlockInfo& info) noexcept;
    PcmRing& networkRing() { return network_; }
    PcmRing& localRing() { return local_; }
private:
    PcmRing network_,local_;
    std::atomic<bool> networkEnabled_{false},localEnabled_{false};
};
}
