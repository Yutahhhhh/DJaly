#include "backend.h"
#include <QJsonArray>

namespace {
class UnavailableBackend final : public PlaybackBackend {
public:
    bool available() const override { return false; }
    QString problem() const override {
        return QStringLiteral("This Qt protocol seam was built without Mixxx. Build the upstream-linked target; no audio is produced.");
    }
    QJsonObject audio() const override { return {{"deviceId", QJsonValue::Null}, {"sampleRateHz", 44100}, {"bufferFrames", 512}, {"masterChannels", QJsonArray{0, 1}}, {"pflChannels", QJsonValue::Null}, {"pflApplied", false}, {"applied", false}, {"reason", problem()}}; }
    void load(int, const QString&, quint64) override {}
    void unload(int) override {}
    void play(int, bool) override {}
    void seek(int, double) override {}
    double positionMs(int) const override { return 0; }
    bool playing(int) const override { return false; }
};
}
std::unique_ptr<PlaybackBackend> makeBackend() { return std::make_unique<UnavailableBackend>(); }
