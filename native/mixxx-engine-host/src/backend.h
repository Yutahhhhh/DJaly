#pragma once
#include <QJsonObject>
#include <QString>
#include <functional>
#include <memory>

// Main-thread boundary. Implementations must marshal controls through Mixxx's
// control machinery; JSON and these callbacks never run in an audio callback.
class PlaybackBackend {
public:
    virtual ~PlaybackBackend() = default;
    virtual bool available() const = 0;
    virtual QString implementation() const { return "unavailable"; }
    virtual void start() {}
    virtual QString problem() const = 0;
    virtual QJsonObject audio() const = 0;
    virtual QJsonObject mixer() const {
        const auto channel = [](const QString& deck) { return QJsonObject{{"deck", deck}, {"gain", 0.0}, {"eqLow", 1.0}, {"eqMid", 1.0}, {"eqHigh", 1.0}, {"pfl", false}, {"available", false}}; };
        return {{"available", false}, {"crossfader", 0.0}, {"masterGain", 0.0}, {"headphoneGain", 0.0}, {"headphoneMix", 0.0}, {"channels", QJsonObject{{"A", channel("A")}, {"B", channel("B")}}}};
    }
    virtual void load(int deck, const QString& path, quint64 generation) = 0;
    virtual void unload(int deck) = 0;
    virtual void play(int deck, bool enabled) = 0;
    virtual void seek(int deck, double positionMs) = 0;
    virtual double positionMs(int deck) const = 0;
    virtual bool playing(int deck) const = 0;
    virtual void gain(int, double) {}
    virtual void masterGain(double) {}
    virtual void crossfader(double) {}
    std::function<void(int, quint64, QJsonObject, QString)> loaded;
};
std::unique_ptr<PlaybackBackend> makeBackend();
