#pragma once
#if defined(__aarch64__)
#include <arm_neon.h>
#endif

namespace vinyl {
struct Stereo { float left=0, right=0; };

// All taps refer to resident, interleaved stereo samples. Boundary handling is
// outside this hot loop. SIMD changes only summation order, not the kernel,
// phase, tap count, cutoff, or source trajectory.
inline Stereo convolve(const float* samples, const float* a, const float* b,
        int taps, float phase) noexcept {
    Stereo result;
    int tap=0;
#if defined(__aarch64__)
    auto left=vdupq_n_f32(0), right=vdupq_n_f32(0);
    for (;tap+4<=taps;tap+=4) {
        const auto av=vld1q_f32(a+tap), bv=vld1q_f32(b+tap);
        const auto weights=vfmaq_n_f32(av,vsubq_f32(bv,av),phase);
        const auto input=vld2q_f32(samples+tap*2);
        left=vfmaq_f32(left,input.val[0],weights);
        right=vfmaq_f32(right,input.val[1],weights);
    }
    result.left=vaddvq_f32(left);result.right=vaddvq_f32(right);
#endif
    for (;tap<taps;++tap) {
        const float weight=a[tap]+phase*(b[tap]-a[tap]);
        result.left+=samples[tap*2]*weight;
        result.right+=samples[tap*2+1]*weight;
    }
    return result;
}
}
