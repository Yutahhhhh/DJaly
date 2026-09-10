// Derived from Mixxx 3ebac449 EngineBufferScaleLinear (GPL-2.0-or-later).
#pragma once

#include "engine/bufferscalers/enginebufferscalelinear.h"
#include "vinyl_kernel.h"

class ReadAheadManager;

/** Number of samples to read ahead */
constexpr int kiplumdeckScaleReadAheadLength = 32768;

class PlumdeckVinylScaler : public EngineBufferScaleLinear  {
  public:
    explicit PlumdeckVinylScaler(
            ReadAheadManager* pReadAheadManager);
    ~PlumdeckVinylScaler() override;

    double scaleBuffer(
            CSAMPLE* pOutputBuffer,
            SINT iOutputBufferSize) override;
    void clear() override;

    void setScaleParameters(double base_rate,
                            double* pTempoRatio,
                             double* pPitchRatio) override;

  private:
    void onSampleRateChanged() override {}

    double do_scale(CSAMPLE* buf, SINT buf_size);

    // The read-ahead manager that we use to fetch samples
    ReadAheadManager* m_pReadAheadManager;

    // Buffer for handling calls to ReadAheadManager
    CSAMPLE* m_bufferInt;
    SINT m_bufferIntSize;

    CSAMPLE m_floorSampleOld[2];
    const vinyl::Bank* previousBank_ = nullptr;

    bool m_bClear;
    double m_dRate;
    double m_dOldRate;
    // Zero speed does not change the orientation of already buffered samples.
    // Preserve it so + -> 0 -> - unwinds the forward read-ahead as + -> - does.
    int m_bufferDirection = 1;

    double m_dCurrentFrame;
    double m_dNextFrame;
};
