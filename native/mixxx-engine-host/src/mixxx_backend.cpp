// DJaly-owned adapter. Upstream APIs pinned to Mixxx 2.5.6 / 3ebac449.
#include "backend.h"
#include <QCoreApplication>
#include <QFileInfo>
#include <QJsonArray>
#include <QTemporaryDir>
#include <QTimer>
#include <array>
#include "control/control.h"
#include "control/controlindicatortimer.h"
#include "control/controlobject.h"
#include "effects/effectsmanager.h"
#include "engine/channels/enginedeck.h"
#include "engine/enginebuffer.h"
#include "engine/enginemixer.h"
#include "soundio/soundmanager.h"
#include "sources/soundsourceproxy.h"
#include "track/track.h"
#include "util/cmdlineargs.h"

namespace {
const QString groups[] = {QStringLiteral("[Channel1]"), QStringLiteral("[Channel2]")};
const QString names[] = {"A", "B"};
class MixxxBackend final : public QObject, public PlaybackBackend {
public:
    MixxxBackend() = default;
    QString implementation() const override { return "mixxx"; }
    void start() override {
        if (started_) return;
        started_ = true;
        QTimer::singleShot(0, this, [this] { initialize(); });
    }
    void initialize() {
        if (!profile_.isValid()) { problem_ = "Cannot create isolated Mixxx profile"; return; }
        // Everything Mixxx writes stays in this disposable profile. No library DB.
        CmdlineArgs::Instance().setSettingsPath(profile_.path());
        settings_ = UserSettingsPointer(new UserSettings(profile_.filePath("mixxx.cfg")));
        ControlDoublePrivate::setUserConfig(settings_);
        indicator_ = std::make_unique<mixxx::ControlIndicatorTimer>();
        handles_ = std::make_shared<ChannelHandleFactory>();
        deckCount_ = std::make_unique<ControlObject>(ConfigKey("[App]", "num_decks"));
        samplerCount_ = std::make_unique<ControlObject>(ConfigKey("[App]", "num_samplers"));
        previewCount_ = std::make_unique<ControlObject>(ConfigKey("[App]", "num_preview_decks"));
        effects_ = std::make_unique<EffectsManager>(settings_, handles_);
        mixer_ = std::make_unique<EngineMixer>(settings_, "[Master]", effects_.get(), handles_, false);
        for (int index = 0; index < 2; ++index) {
            decks_[index] = new EngineDeck(mixer_->registerChannelGroup(groups[index]), settings_, mixer_.get(), effects_.get(), index == 0 ? EngineChannel::LEFT : EngineChannel::RIGHT, true);
            mixer_->addChannel(decks_[index]); // mixer owns/deletes the decks.
            ControlObject::set(ConfigKey(groups[index], "main_mix"), 1);
            ControlObject::set(ConfigKey(groups[index], "volume"), 1);
        }
        deckCount_->set(2);
        ControlObject::set(ConfigKey("[Master]", "gain"), 0.5);
        if (!SoundSourceProxy::registerProviders()) { problem_ = "Mixxx decoder provider registration failed"; return; }
        for (int index = 0; index < 2; ++index) {
            auto* buffer = decks_[index]->getEngineBuffer();
            QObject::connect(buffer, &EngineBuffer::trackLoaded, this, [this, index](TrackPointer track, TrackPointer) {
                if (!track || track != tracks_[index]) return; // nullptr is eject.
                if (loaded) loaded(index, generations_[index], {{"durationMs", track->getDuration() * 1000.0}, {"sampleRateHz", static_cast<int>(track->getSampleRate().value())}, {"channels", track->getChannels()}}, {});
            }, Qt::QueuedConnection);
            QObject::connect(buffer, &EngineBuffer::trackLoadFailed, this, [this, index](TrackPointer track, const QString& reason) {
                if (track == tracks_[index] && loaded) loaded(index, generations_[index], {}, reason);
            }, Qt::QueuedConnection);
        }
        sound_ = std::make_unique<SoundManager>(settings_, mixer_.get());
        sound_->setConfiguredDeckCount(2);
        const AudioOutput main(AudioPathType::Main, 0, mixxx::audio::ChannelCount::stereo());
        sound_->registerOutput(main, mixer_.get());
        // SoundManager unconditionally configures its internal Network Device
        // RecordBroadcast output, even when broadcasting/sidechain is disabled.
        // The source must exist; no network worker or listener is started.
        sound_->registerOutput(AudioOutput(AudioPathType::RecordBroadcast, 0, mixxx::audio::ChannelCount::stereo()), mixer_.get());
        auto config = sound_->getConfig();
        config.clearInputs(); config.clearOutputs(); config.setDeckCount(2);
        // Explicit device name keeps smoke tests on the intended virtual/built-in
        // device. Never select the DDJ-1000 or an arbitrary output implicitly.
        const auto wanted = qEnvironmentVariable("DJALY_MIXXX_OUTPUT_DEVICE");
        if (wanted.isEmpty()) { problem_ = "Set DJALY_MIXXX_OUTPUT_DEVICE to an exact Core Audio output display name"; return; }
        auto devices = sound_->getDeviceList(MIXXX_PORTAUDIO_COREAUDIO_STRING, true, false);
        SoundDevicePointer selected;
        for (const auto& device : devices) {
            qInfo() << "DJaly output device:" << device->getDisplayName();
            if (device->getDisplayName() == wanted) {
                if (selected) { problem_ = "Ambiguous output display name"; return; }
                selected = device;
            }
        }
        if (!selected) { problem_ = "Requested Core Audio output not found: " + wanted; return; }
        config.setAPI(MIXXX_PORTAUDIO_COREAUDIO_STRING);
        config.setSampleRate(mixxx::audio::SampleRate(44100));
        config.setAudioBufferSizeIndex(4);
        config.addOutput(selected->getDeviceId(), main);
        auto status = sound_->setConfig(config);
        if (status != SoundDeviceStatus::Ok) { problem_ = sound_->getLastErrorMessage(status); return; }
        output_ = selected->getDisplayName(); problem_.clear(); available_ = true;
    }
    ~MixxxBackend() override {
        sound_.reset(); // Stops callbacks before any engine-owned memory is freed.
        mixer_.reset(); decks_ = {}; effects_.reset();
    }
    bool available() const override { return available_; }
    QString problem() const override { return problem_; }
    QJsonObject audio() const override {
        return {{"deviceId", output_}, {"sampleRateHz", 44100}, {"bufferFrames", 512}, {"masterChannels", QJsonArray{0, 1}}, {"pflChannels", QJsonValue::Null}, {"pflApplied", false}, {"applied", available_}, {"reason", problem_}};
    }
    QJsonObject mixer() const override {
        auto value = PlaybackBackend::mixer();
        if (!mixer_) return value;
        value["available"] = available_;
        value["eqAvailable"] = false; value["pflAvailable"] = false;
        value["crossfader"] = ControlObject::get(ConfigKey("[Master]", "crossfader"));
        value["masterGain"] = ControlObject::get(ConfigKey("[Master]", "gain"));
        value["headphoneGain"] = ControlObject::get(ConfigKey("[Master]", "headGain"));
        value["headphoneMix"] = ControlObject::get(ConfigKey("[Master]", "headMix"));
        auto channels = value["channels"].toObject();
        for (int index = 0; index < 2; ++index) {
            auto channel = channels[names[index]].toObject(); channel["available"] = available_;
            channel["gain"] = ControlObject::get(ConfigKey(groups[index], "volume")); channel["pfl"] = ControlObject::get(ConfigKey(groups[index], "pfl")) > 0;
            channels[names[index]] = channel;
        }
        value["channels"] = channels;
        return value;
    }
    void load(int index, const QString& path, quint64 generation) override {
        generations_[index] = generation;
        tracks_[index] = Track::newTemporary(path);
        decks_[index]->getEngineBuffer()->loadTrack(tracks_[index], false, nullptr);
    }
    void unload(int index) override {
        ++generations_[index]; tracks_[index].reset();
        ControlObject::set(ConfigKey(groups[index], "play"), 0);
        decks_[index]->getEngineBuffer()->ejectTrack();
    }
    void play(int index, bool enabled) override { ControlObject::set(ConfigKey(groups[index], "play"), enabled ? 1 : 0); }
    void seek(int index, double ms) override {
        if (tracks_[index] && tracks_[index]->getDuration() > 0) ControlObject::set(ConfigKey(groups[index], "playposition"), ms / (1000.0 * tracks_[index]->getDuration()));
    }
    double positionMs(int index) const override {
        return tracks_[index] ? ControlObject::get(ConfigKey(groups[index], "playposition")) * tracks_[index]->getDuration() * 1000.0 : 0;
    }
    bool playing(int index) const override { return ControlObject::get(ConfigKey(groups[index], "play")) > 0; }
    void gain(int index, double value) override { ControlObject::set(ConfigKey(groups[index], "volume"), value); }
    void masterGain(double value) override { ControlObject::set(ConfigKey("[Master]", "gain"), value); }
    void crossfader(double value) override { ControlObject::set(ConfigKey("[Master]", "crossfader"), value); }
private:
    QTemporaryDir profile_;
    UserSettingsPointer settings_;
    std::unique_ptr<mixxx::ControlIndicatorTimer> indicator_;
    ChannelHandleFactoryPointer handles_;
    std::unique_ptr<ControlObject> deckCount_, samplerCount_, previewCount_;
    std::unique_ptr<EffectsManager> effects_;
    std::unique_ptr<EngineMixer> mixer_;
    std::array<EngineDeck*, 2> decks_{};
    std::unique_ptr<SoundManager> sound_;
    std::array<TrackPointer, 2> tracks_;
    std::array<quint64, 2> generations_{};
    bool available_ = false, started_ = false;
    QString problem_ = "Mixxx audio initialization has not completed", output_;
};
}
std::unique_ptr<PlaybackBackend> makeBackend() { return std::make_unique<MixxxBackend>(); }
