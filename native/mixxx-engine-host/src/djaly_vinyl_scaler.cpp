#include <cstring>
// Derived from Mixxx 3ebac449 EngineBufferScaleLinear (GPL-2.0-or-later).
#include "djaly_vinyl_scaler.h"

#include <QtDebug>

#include "engine/readaheadmanager.h"

#include "util/assert.h"
#include "util/math.h"
#include "util/sample.h"

DjalyVinylScaler::DjalyVinylScaler(ReadAheadManager *pReadAheadManager)
    : EngineBufferScaleLinear(pReadAheadManager), m_pReadAheadManager(pReadAheadManager),
      m_bufferInt(SampleUtil::alloc(kiDjalyScaleReadAheadLength)),
      m_bufferIntSize(0),
      m_bClear(false),
      m_dRate(1.0),
      m_dOldRate(1.0),
      m_dCurrentFrame(0.0),
      m_dNextFrame(0.0) {
    (void)vinyl::kernels(); // Construct shared immutable banks before audio starts.
    m_floorSampleOld[0] = 0.0;
    m_floorSampleOld[1] = 0.0;
    SampleUtil::clear(m_bufferInt, kiDjalyScaleReadAheadLength);
}

DjalyVinylScaler::~DjalyVinylScaler() {
    SampleUtil::free(m_bufferInt);
}

void DjalyVinylScaler::setScaleParameters(double base_rate,
                                                 double* pTempoRatio,
                                                 double* pPitchRatio) {
    Q_UNUSED(pPitchRatio);

    m_dOldRate = m_dRate;
    m_dRate = base_rate * *pTempoRatio;
}

void DjalyVinylScaler::clear() {
    m_bClear = true;
    // Clear out buffer and saved sample data
    m_bufferIntSize = 0;
    m_dNextFrame = 0;
    m_floorSampleOld[0] = 0;
    m_floorSampleOld[1] = 0;
}

// Determine if we're changing directions (scratching) and then perform
// a stretch
double DjalyVinylScaler::scaleBuffer(
        CSAMPLE* pOutputBuffer,
        SINT iOutputBufferSize) {
    if (iOutputBufferSize == 0) {
        return 0.0;
    }

    if (m_bClear) {
        m_dOldRate = m_dRate;  // If cleared, don't interpolate rate.
        m_bClear = false;
    }
    double rate_add_old = m_dOldRate; // Smoothly interpolate to new playback rate
    double rate_add_new = m_dRate;
    double frames_read = 0;

    if (rate_add_new * rate_add_old < 0) {
        // Direction has changed!
        // calculate half buffer going one way, and half buffer going
        // the other way.

        // first half: rate goes from old rate to zero
        m_dOldRate = rate_add_old;
        m_dRate = 0.0;
        frames_read += do_scale(pOutputBuffer, getOutputSignal().samples2frames(iOutputBufferSize));

        // reset m_floorSampleOld in a way as we were coming from
        // the other direction
        SINT iNextSample = getOutputSignal().frames2samples(static_cast<SINT>(ceil(m_dNextFrame)));
        if (iNextSample >= 0 && iNextSample + 1 < m_bufferIntSize) {
            m_floorSampleOld[0] = m_bufferInt[iNextSample];
            m_floorSampleOld[1] = m_bufferInt[iNextSample + 1];
        } else {
            m_floorSampleOld[0] = CSAMPLE_ZERO;
            m_floorSampleOld[1] = CSAMPLE_ZERO;
        }

        // if the buffer has extra samples, do a read so RAMAN ends up back where
        // it should be
        SINT iCurSample = getOutputSignal().frames2samples(static_cast<SINT>(ceil(m_dCurrentFrame)));
        SINT extra_samples = m_bufferIntSize - iCurSample - getOutputSignal().getChannelCount();
        if (extra_samples > 0) {
            if (extra_samples % getOutputSignal().getChannelCount() != 0) {
                // extra samples should include the whole frame
                extra_samples -= extra_samples % getOutputSignal().getChannelCount();
                extra_samples += getOutputSignal().getChannelCount();
            }
            //qDebug() << "extra samples" << extra_samples;

            SINT next_samples_read = m_pReadAheadManager->getNextSamples(
                    rate_add_new, m_bufferInt, extra_samples);
            // Consume both the unused forward log and the reverse unwind log.
            // Omitting the forward half makes the reported cursor lag behind PCM.
            frames_read += getOutputSignal().samples2frames(extra_samples + next_samples_read);
        }
        // force a buffer read:
        m_bufferIntSize = 0;
        // make sure the indexes stay correct for interpolation
        m_dCurrentFrame = 0.0 - (m_dCurrentFrame - floor(m_dCurrentFrame));
        m_dNextFrame = 1.0 - (m_dNextFrame - floor(m_dNextFrame));

        // second half: rate goes from zero to new rate
        m_dOldRate = 0.0;
        m_dRate = rate_add_new;
        // pass the address of the frame at the halfway point
        SINT frameOffset =  getOutputSignal().samples2frames(iOutputBufferSize) / 2;
        SINT sampleOffset = getOutputSignal().frames2samples(frameOffset);
        frames_read += do_scale(pOutputBuffer + sampleOffset, iOutputBufferSize - sampleOffset);
    } else {
        frames_read += do_scale(pOutputBuffer, iOutputBufferSize);
    }
    return frames_read;
}

// Preserve upstream's per-block and through-zero rate ramps, replacing only
// sample interpolation. ReadAheadManager retains ownership of loop mapping.
double DjalyVinylScaler::do_scale(CSAMPLE* output,SINT samples) {
    const double old=m_dOldRate, next=m_dRate;
    m_dOldRate=next;
    if(samples<=0)return 0;

    const SINT frames=samples/2;
    const double delta=(std::abs(next)-std::abs(old))/frames;
    double speed=std::abs(old),start=m_dNextFrame;
    const auto& bank=vinyl::kernels().select(std::max(std::abs(old),std::abs(next)));
    const auto* oldBank=previousBank_?previousBank_:&bank;
    previousBank_=&bank;
    const int radius=std::max(bank.taps,oldBank->taps)/2;
    const double direction=next==0?old:next;
    for(SINT f=0;f<frames;f++) {
        m_dCurrentFrame=m_dNextFrame;
        auto floor=SINT(std::floor(m_dCurrentFrame));
        if(floor+radius>=m_bufferIntSize/2) {
            const auto remove=std::max<SINT>(0,floor-radius);
            const auto retained=std::max<SINT>(0,m_bufferIntSize/2-remove);
            if(retained)std::memmove(m_bufferInt,m_bufferInt+remove*2,retained*2*sizeof(CSAMPLE));
            m_bufferIntSize=retained*2;m_dCurrentFrame-=remove;m_dNextFrame-=remove;start-=remove;floor-=remove;
            // Bounded reads, including Mixxx's zero-length loop transition.
            for(int attempt=0;attempt<4&&floor+radius>=m_bufferIntSize/2;attempt++) {
                const double remaining=(frames-f)*speed + (frames-f)*(frames-f-1)*delta/2;
                const SINT needed=std::max<SINT>(2,2*SINT(std::ceil(m_dCurrentFrame+remaining+radius+1))-m_bufferIntSize);
                const SINT capacity=std::min<SINT>(kiDjalyScaleReadAheadLength-m_bufferIntSize,needed);
                if(capacity<=0)break;
                const SINT received=m_pReadAheadManager->getNextSamples(direction,m_bufferInt+m_bufferIntSize,capacity);
                if(received<0||received>capacity)break;m_bufferIntSize+=received;
            }
        }
        const double fraction=m_dCurrentFrame-std::floor(m_dCurrentFrame);
        const double phase=fraction*vinyl::Kernels::phases;
        const int first=std::clamp(int(phase),0,vinyl::Kernels::phases-1);
        const float blend=float(phase-first);
        const float* a=bank.coefficients.data()+first*bank.taps;
        const float* b=a+bank.taps;
        float left=0,right=0;
        if(speed!=1 || fraction!=0)for(int tap=0;tap<bank.taps;tap++) {
            const auto frame=floor-bank.taps/2+1+tap;
            const float coefficient=a[tap]+blend*(b[tap]-a[tap]);
            if(frame>=0&&frame*2+1<m_bufferIntSize){left+=coefficient*m_bufferInt[frame*2];right+=coefficient*m_bufferInt[frame*2+1];}
            else if(frame==-1){left+=coefficient*m_floorSampleOld[0];right+=coefficient*m_floorSampleOld[1];}
        }
        // Morph filter banks at the same source phase, without clearing history.
        if(oldBank!=&bank && f<32 && !(speed==1 && fraction==0)){
            float oldLeft=0,oldRight=0;
            const float* a0=oldBank->coefficients.data()+first*oldBank->taps;const float* b0=a0+oldBank->taps;
            for(int tap=0;tap<oldBank->taps;tap++){
                const auto frame=floor-oldBank->taps/2+1+tap;const float weight=a0[tap]+blend*(b0[tap]-a0[tap]);
                if(frame>=0&&frame*2+1<m_bufferIntSize){oldLeft+=weight*m_bufferInt[frame*2];oldRight+=weight*m_bufferInt[frame*2+1];}
                else if(frame==-1){oldLeft+=weight*m_floorSampleOld[0];oldRight+=weight*m_floorSampleOld[1];}
            }
            const float transition=float(f+1)/32;left=oldLeft+transition*(left-oldLeft);right=oldRight+transition*(right-oldRight);
        }
        if(speed==1 && fraction==0 && floor>=0 && floor*2+1<m_bufferIntSize) {left=m_bufferInt[floor*2];right=m_bufferInt[floor*2+1];}
        output[f*2]=left;output[f*2+1]=right;
        if(floor>=0&&floor*2+1<m_bufferIntSize){m_floorSampleOld[0]=m_bufferInt[floor*2];m_floorSampleOld[1]=m_bufferInt[floor*2+1];}
        m_dNextFrame=m_dCurrentFrame+speed;speed+=delta;
    }
    return m_dNextFrame-start;
}
