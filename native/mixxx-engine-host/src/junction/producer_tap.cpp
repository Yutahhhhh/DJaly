#include "producer_tap.h"
namespace junction {
void ProducerTap::capture(const float* pcm,const PcmBlockInfo& info) noexcept {
    if (!pcm) return;
    if(networkEnabled_.load(std::memory_order_relaxed)) network_.push(pcm,info);
    if(localEnabled_.load(std::memory_order_relaxed)) local_.push(pcm,info);
}
}
