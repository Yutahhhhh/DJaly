#pragma once
#include <array>
#include <atomic>
#include <cmath>
#include <QFileInfo>
#include <QJsonArray>
#include <QObject>
#include "control/controlobject.h"
#include "engine/channels/enginedeck.h"
#include "engine/enginebuffer.h"
#include "engine/enginemixer.h"
#include "track/track.h"

class JunctionSamplerDeck final : public EngineDeck {
public:
    using EngineDeck::EngineDeck;
    std::atomic<double> exactFrames{0};
    std::atomic<quint64> audioBlocks{0};
    void postProcess(int samples) override {
        EngineDeck::postProcess(samples);
        const auto value=getEngineBuffer()->getExactPlayPos();
        exactFrames.store(value.isValid()?value.value():0,std::memory_order_release);
        audioBlocks.fetch_add(1,std::memory_order_release);
    }
};

// Main-thread commands, native audio callbacks. EngineMixer owns the channels;
// this bank owns their metadata and uses a QObject context for async load guards.
class SamplerBank final : public QObject {
public:
    SamplerBank(UserSettingsPointer settings, EngineMixer* mixer, EffectsManager* effects) {
        for (int i = 0; i < 64; ++i) {
            auto& s = slots_[i];
            s.group = QStringLiteral("[Sampler%1]").arg(i + 1);
            s.deck = new JunctionSamplerDeck(mixer->registerChannelGroup(s.group), settings, mixer, effects, EngineChannel::CENTER, false);
            mixer->addChannel(s.deck);
            ControlObject::set(ConfigKey(s.group, "main_mix"), 1);
            ControlObject::set(ConfigKey(s.group, "volume"), gain_);
            QObject::connect(s.deck->getEngineBuffer(), &EngineBuffer::trackLoaded, this, [this, i](TrackPointer track, TrackPointer) {
                auto& slot = slots_[i];
                if (!track || track != slot.track) return;
                slot.ready = true; slot.error.clear();

            }, Qt::QueuedConnection);
            QObject::connect(s.deck->getEngineBuffer(), &EngineBuffer::trackLoadFailed, this, [this, i](TrackPointer track, const QString& error) {
                auto& slot = slots_[i];
                if (track != slot.track) return;
                slot.ready = false; slot.error = error;
            }, Qt::QueuedConnection);
        }
    }
    QJsonObject state() const {
        QJsonArray items;
        for (int i = 0; i < 16; ++i) {
            const auto& s = slots_[bank_ * 16 + i];
            items.append(QJsonObject{{"slot", i}, {"path", s.path}, {"name", QFileInfo(s.path).fileName()},
                {"status", s.path.isEmpty() ? "empty" : !s.error.isEmpty() ? "error" : !s.ready ? "loading" : ControlObject::get(ConfigKey(s.group, "play")) > 0 ? "playing" : "ready"},
                {"error", s.error}, {"durationMs", s.ready ? s.track->getDuration() * 1000 : 0}, {"revision", static_cast<double>(s.revision)}});
        }
        return {{"slots", items}, {"gain", gain_}, {"pfl", pfl_}, {"bank", bank_}};
    }
    QJsonObject junctionState() const {
        QJsonArray items;
        for(int i=0;i<64;++i){const auto& s=slots_[i];items.append(QJsonObject{
            {"slot",i},{"path",s.path},{"positionFrames",s.deck->exactFrames.load(std::memory_order_acquire)},
            {"sourceSampleRateHz",s.track?int(s.track->getSampleRate().value()):0},
            {"play",ControlObject::get(ConfigKey(s.group,"play"))>0},{"ready",s.path.isEmpty()||s.ready},
            {"revision",QString::number(s.revision)}});}
        return {{"bank",bank_},{"gain",gain_},{"slots",items}};
    }
    bool junctionLoaded() const {
        for(const auto& s:slots_)if(!s.path.isEmpty()&&(!s.ready||!s.error.isEmpty()))return false;return true;
    }
    QString finalizeJunctionRestore() {
        for(auto& s:slots_)if(!s.restore.isEmpty()){
            if(s.restore["sourceSampleRateHz"].toDouble()!=s.track->getSampleRate().value()||s.restore["positionFrames"].toDouble()>s.track->getDuration()*s.track->getSampleRate().value()){s.error="Sampler asset differs from graph";return s.error;}
            s.deck->getEngineBuffer()->queueNewPlaypos(mixxx::audio::FramePos(s.restore["positionFrames"].toDouble()),EngineBuffer::SEEK_EXACT);
            ControlObject::set(ConfigKey(s.group,"play"),s.restore["play"].toBool()?1:0);
            s.restoreAfter=s.deck->audioBlocks.load()+2;s.restore={};
        }
        return {};
    }
    bool junctionReady() const {
        for(const auto& s:slots_)if(!s.path.isEmpty()&&(!s.ready||!s.error.isEmpty()||!s.restore.isEmpty()||s.deck->audioBlocks.load()<s.restoreAfter))return false;
        return true;
    }
    QString restoreJunction(const QJsonObject& snapshot) {
        const auto bank=snapshot["bank"].toDouble(-1),gain=snapshot["gain"].toDouble(-1);
        if(bank<0||bank>3||bank!=std::floor(bank)||gain<0||gain>1||!std::isfinite(gain))return "Invalid sampler bank or gain";
        const auto items=snapshot["slots"].toArray();if(items.size()!=64)return "Expected all 64 sampler slots";
        for(int i=0;i<64;++i){const auto row=items[i].toObject();const auto path=row["path"].toString();
            if(row["slot"].toInt(-1)!=i||(!path.isEmpty()&&(!QFileInfo(path).isAbsolute()||!QFileInfo(path).isFile()))||!std::isfinite(row["positionFrames"].toDouble(-1))||row["positionFrames"].toDouble(-1)<0)return "Invalid resolved sampler graph";
        }
        stopAll();
        for(int i=0;i<64;++i){const auto row=items[i].toObject();auto& s=slots_[i];s.restore={};s.restoreAfter=0;
            if(row["path"].toString().isEmpty()){command("sampler.eject",{{"slot",i%16},{"bank",i/16}});continue;}
            const auto error=command("sampler.load",{{"slot",i%16},{"bank",i/16},{"path",row["path"]}});if(!error.isEmpty())return error;s.restore=row;
        }
        command("sampler.bank",{{"bank",snapshot["bank"]}});
        return command("sampler.gain",{{"gain",snapshot["gain"]}});
    }
    QString command(const QString& op, const QJsonObject& params) {
        if (op == "sampler.state") return {};
        if (op == "sampler.bank") {
            const auto value = params["bank"];
            if (!value.isDouble() || value.toDouble() != std::floor(value.toDouble()) || value.toDouble() < 0 || value.toDouble() > 3) return "Expected sampler bank 0..3";
            bank_ = value.toInt(); return {};
        }
        if (op == "sampler.stopAll") { stopAll(); return {}; }
        if (op == "sampler.gain" || op == "sampler.pfl") {
            if (op == "sampler.gain") {
                const auto v = params["gain"];
                if (!v.isDouble() || !std::isfinite(v.toDouble()) || v.toDouble() < 0 || v.toDouble() > 1) return "Expected sampler gain 0..1";
                gain_ = v.toDouble();
            } else {
                if (!params["enabled"].isBool()) return "Expected sampler pfl boolean";
                pfl_ = params["enabled"].toBool();
            }
            for (const auto& s : slots_) { ControlObject::set(ConfigKey(s.group, "volume"), gain_); ControlObject::set(ConfigKey(s.group, "pfl"), pfl_ ? 1 : 0); }
            return {};
        }
        const auto index = params["slot"];
        if (!index.isDouble() || !std::isfinite(index.toDouble()) || index.toDouble() != std::floor(index.toDouble()) || index.toDouble() < 0 || index.toDouble() >= 16) return "Expected sampler slot 0..15";
        int targetBank = bank_;
        if (params.contains("bank")) {
            const auto value = params["bank"];
            if (!value.isDouble() || value.toDouble() != std::floor(value.toDouble()) || value.toDouble() < 0 || value.toDouble() > 3) return "Expected sampler bank 0..3";
            targetBank = value.toInt();
        }
        auto& s = slots_[targetBank * 16 + index.toInt()];
        if (op == "sampler.load") {
            const auto path = params["path"].toString();
            if (path.size() > 4096 || !QFileInfo(path).isAbsolute() || !QFileInfo(path).isFile()) return "Expected an existing absolute sample file path";
            ControlObject::set(ConfigKey(s.group, "play"), 0);
            ++s.revision; s.path = path; s.ready = false; s.error.clear();
            s.track = Track::newTemporary(path);
            s.deck->getEngineBuffer()->loadTrack(s.track, false, nullptr);
            return {};
        }
        if (op == "sampler.eject") {
            ControlObject::set(ConfigKey(s.group, "play"), 0);
            ++s.revision; s.track.reset(); s.path.clear(); s.error.clear(); s.ready = false;
            s.deck->getEngineBuffer()->ejectTrack(); return {};
        }
        if (!params["revision"].isUndefined() && params["revision"].toDouble(-1) != static_cast<double>(s.revision)) return "Sample changed; stale pad gesture";
        if (op == "sampler.stop") { ControlObject::set(ConfigKey(s.group, "play"), 0); return {}; }
        if (op == "sampler.play") {
            if (!s.ready || !s.error.isEmpty()) return "Sample is not ready";
            ControlObject::set(ConfigKey(s.group, "playposition"), 0);
            ControlObject::set(ConfigKey(s.group, "play"), 1); return {};
        }
        return "Unknown sampler operation";
    }
    void stopAll() { for (const auto& s : slots_) ControlObject::set(ConfigKey(s.group, "play"), 0); }
private:
    struct Slot { QString group, path, error; JunctionSamplerDeck* deck = nullptr; TrackPointer track; bool ready = false; quint64 revision = 0, restoreAfter = 0; QJsonObject restore; };
    std::array<Slot, 64> slots_;
    int bank_ = 0;
    double gain_ = 0.7;
    bool pfl_ = false;
};
