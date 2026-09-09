#include "validation_capture.h"
#include <samplerate.h>
#include <array>
#include <limits>
#include <cmath>

namespace junction {
struct ValidationCapture::Impl {
    InputDomain domain;
    SRC_STATE* src = nullptr;
    bool initialized = false, active = false, complete = false;
    quint32 rate = 0, requestedFrames = 0;
    quint64 epoch = 0, generation = 0, sourceOrigin = 0, sourceEnd = 0;
    quint64 mediaOrigin = 0, outputFrames = 0, collected = 0;
    Window window;
    QString failure;
    std::array<float, 8192> converted{};

    explicit Impl(InputDomain input) : domain(input) {
        int status = 0;
        src = src_new(SRC_SINC_FASTEST, 2, &status);
    }
    ~Impl() { if (src) src_delete(src); }

    bool fail(const QString& reason, QString* error) {
        failure = reason;
        if (error) *error = reason;
        active = complete = false;
        window.samples.clear();
        return false;
    }

    bool append(quint64 frame, const float* samples, quint32 frames, QString* error) {
        if (!active || complete) return true;
        if (epoch != window.epoch || generation != window.generation)
            return fail("Validation stream epoch or generation changed", error);
        const quint64 expected = window.startMediaFrame + collected;
        if (frame > expected)
            return fail("Validation media frames are missing", error);
        if (frame + frames <= window.startMediaFrame) return true;
        const quint64 offset = expected > frame ? expected - frame : 0;
        if (offset >= frames) return true;
        const quint32 count = quint32(std::min<quint64>(frames - offset,
                requestedFrames - collected));
        std::copy_n(samples + offset * 2, count * 2,
                window.samples.data() + collected * 2);
        collected += count;
        complete = collected == requestedFrames;
        return true;
    }
};

ValidationCapture::ValidationCapture(InputDomain domain) : d(new Impl(domain)) {}
ValidationCapture::~ValidationCapture() = default;

bool ValidationCapture::begin(quint64 start, quint32 frames, quint64 epoch,
        quint64 generation, QString* error) {
    cancel();
    if (!frames || frames > 24000 || start > std::numeric_limits<quint64>::max() - frames)
        return d->fail("Validation window exceeds frame bounds", error);
    if (!d->src) return d->fail("Validation SRC unavailable", error);
    if (d->initialized && (epoch != d->epoch || generation != d->generation))
        return d->fail("Validation request targets a different stream", error);
    if (d->initialized && start < d->mediaOrigin + d->outputFrames)
        return d->fail("Validation window starts in already consumed audio", error);
    d->window = Window{start, epoch, generation, std::vector<float>(frames * 2)};
    d->requestedFrames = frames;
    d->collected = 0;
    d->active = true;
    return true;
}

bool ValidationCapture::consume(const PcmBlockInfo& info, const float* samples,
        quint32 frames, QString* error) {
    if (!samples || !frames || frames > 4096 || info.frameCount != frames ||
            info.channels != 2 || info.sampleRateHz < 8000 || info.sampleRateHz > 192000 ||
            info.sourceFrame > std::numeric_limits<quint64>::max() - frames ||
            info.mediaFrame > std::numeric_limits<quint64>::max() - 24576 ||
            (d->domain == InputDomain::Wire && info.sampleRateHz != 48000))
        return d->fail("Invalid validation PCM block", error);
    for (quint32 i = 0; i < frames * 2; ++i)
        if (!std::isfinite(samples[i])) return d->fail("Non-finite validation PCM", error);
    if (!d->src) return d->fail("Validation SRC unavailable", error);

    bool discontinuity = false;
    if (d->initialized) {
        discontinuity = info.epoch != d->epoch || info.generation != d->generation ||
                info.sampleRateHz != d->rate || info.sourceFrame != d->sourceEnd;
        if (!discontinuity) {
            const quint64 expected = d->mediaOrigin +
                    mediaFrameAdvance(info.sourceFrame - d->sourceOrigin, d->rate);
            const quint64 difference = expected > info.mediaFrame ?
                    expected - info.mediaFrame : info.mediaFrame - expected;
            // Two rational floors can differ by one at a sliced 44.1k block.
            discontinuity = difference > (d->rate == 48000 ? 0U : 1U);
        }
    }
    if (!d->initialized || discontinuity) {
        if (discontinuity) d->fail("Validation source gap, overlap, or stream change", error);
        src_reset(d->src);
        d->initialized = true;
        d->epoch = info.epoch;
        d->generation = info.generation;
        d->rate = info.sampleRateHz;
        d->sourceOrigin = info.sourceFrame;
        d->mediaOrigin = info.mediaFrame;
        d->outputFrames = 0;
    }
    d->sourceEnd = info.sourceFrame + frames;
    bool ok = !discontinuity;
    if (d->domain == InputDomain::Wire) {
        ok = d->append(info.mediaFrame, samples, frames, error) && ok;
        d->outputFrames += frames;
        return ok;
    }
    long used = 0;
    while (used < frames) {
        SRC_DATA data{};
        data.data_in = samples + used * 2;
        data.input_frames = frames - used;
        data.data_out = d->converted.data();
        data.output_frames = 4096;
        data.src_ratio = 48000.0 / d->rate;
        if (src_process(d->src, &data)) return d->fail("Validation SRC processing failed", error);
        used += data.input_frames_used;
        if (data.output_frames_gen) {
            ok = d->append(d->mediaOrigin + d->outputFrames, d->converted.data(),
                    quint32(data.output_frames_gen), error) && ok;
            d->outputFrames += quint64(data.output_frames_gen);
        }
        if (!data.input_frames_used && !data.output_frames_gen)
            return d->fail("Validation SRC made no progress", error);
    }
    return ok;
}

bool ValidationCapture::ready() const { return d->active && d->complete; }
std::optional<ValidationCapture::Window> ValidationCapture::take() {
    if (!ready()) return std::nullopt;
    auto result = std::move(d->window);
    d->active = d->complete = false;
    return result;
}
QString ValidationCapture::error() const { return d->failure; }
void ValidationCapture::cancel() {
    d->active = d->complete = false;
    d->failure.clear();
    d->window.samples.clear();
    d->collected = d->requestedFrames = 0;
}
void ValidationCapture::reset() {
    cancel();
    d->initialized = false;
    d->outputFrames = 0;
    if (d->src) src_reset(d->src);
}
}
