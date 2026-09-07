#include "host.h"
#include <QDir>
#include <QJsonArray>
#include <QJsonDocument>
#include <QSet>
#include <QUuid>
#include <cmath>
#include <cstdio>

namespace {
constexpr double kMaxSafeId = 9007199254740991.0;
bool integer(const QJsonValue& value) {
    return value.isDouble() && value.toDouble() >= 0 && value.toDouble() <= kMaxSafeId && std::floor(value.toDouble()) == value.toDouble();
}
const QSet<QString> known = {"deck.load", "deck.unload", "deck.play", "deck.pause", "deck.seek", "deck.tempo.set", "deck.keylock.set", "deck.sync.set", "deck.hotcue.set", "deck.hotcue.jump", "deck.hotcue.clear", "deck.loop.set", "deck.loop.enable", "mixer.channel.gain", "mixer.channel.eq", "mixer.channel.pfl", "mixer.crossfader", "mixer.master.gain", "audio.devices.list", "audio.config.get", "audio.config.set", "meters.subscribe"};
const QSet<QString> transport = {"deck.load", "deck.unload", "deck.play", "deck.pause", "deck.seek"};
const QSet<QString> mixerOps = {"mixer.channel.gain", "mixer.crossfader", "mixer.master.gain"};
const QString deckNames[] = {"A", "B"};
}

Host::Host(std::unique_ptr<PlaybackBackend> backend) : backend_(std::move(backend)), engineId_(QUuid::createUuid().toString(QUuid::WithoutBraces)) {
    clock_.start();
    resetDeck(0); resetDeck(1);
    backend_->loaded = [this](int index, quint64 generation, QJsonObject metadata, QString error) {
        // Even immediate decoder failures are delivered after the accepted reply.
        QTimer::singleShot(0, this, [this, index, generation, metadata, error] { completed(index, generation, metadata, error); });
    };
    connect(&timer_, &QTimer::timeout, this, [this] { sample(); });
    timer_.start(100);
}
void Host::resetDeck(int index) {
    slots_[index].state = emptyDeck(); slots_[index].state["deck"] = deckNames[index];
    slots_[index].transportTouched = false;
    slots_[index].state["available"] = backend_->implementation() == "mixxx";
}
QJsonObject Host::emptyDeck() {
    return {{"deck", "A"}, {"status", "empty"}, {"track", QJsonValue::Null}, {"positionMs", 0}, {"positionFrames", 0}, {"rate", 1.0}, {"keylock", false}, {"syncEnabled", false}, {"syncLeader", QJsonValue::Null}, {"effectiveBpm", QJsonValue::Null}, {"hotCues", QJsonArray{QJsonValue::Null, QJsonValue::Null, QJsonValue::Null, QJsonValue::Null, QJsonValue::Null, QJsonValue::Null, QJsonValue::Null, QJsonValue::Null}}, {"loopRegion", QJsonValue::Null}, {"lastError", QJsonValue::Null}, {"loadId", QJsonValue::Null}};
}
QJsonObject Host::info() const {
    QJsonArray capabilities;
    if (backend_->available()) capabilities = {"deck.load.async", "deck.transport", "mixer.gain", "mixer.crossfader"};
    return {{"name", backend_->implementation() == "mixxx" ? "djaly-mixxx-engine-host" : "djaly-mixxx-host-unavailable"}, {"version", "0.2.0"}, {"implementation", backend_->implementation()}, {"simulated", false}, {"deterministic", false}, {"audioAvailable", backend_->available()}, {"audioProblem", backend_->problem()}, {"decks", QJsonArray{"A", "B"}}, {"capabilities", capabilities}, {"upstreamCommit", "3ebac449e7e5fe2a0186596657696e87ce8b0e56"}};
}
QJsonObject Host::envelope(const QString& kind) const {
    return {{"protocol", 1}, {"kind", kind}, {"engineId", engineId_}, {"rev", static_cast<qint64>(rev_)}, {"engineTimeMs", static_cast<double>(clock_.elapsed())}};
}
void Host::send(QJsonObject message) const {
    const QByteArray bytes = QJsonDocument(message).toJson(QJsonDocument::Compact) + '\n';
    if (std::fwrite(bytes.constData(), 1, bytes.size(), stdout) != static_cast<size_t>(bytes.size()) || std::fflush(stdout) != 0) std::exit(1);
}
void Host::result(const QJsonObject& cmd, const QJsonObject& data) {
    auto message = envelope("result");
    message.insert("id", cmd["id"]); message.insert("op", cmd["op"]); message.insert("sessionId", sessionId_); message.insert("data", data); send(message);
}
void Host::error(const QJsonObject& cmd, const QString& code, const QString& text) {
    auto message = envelope("error");
    if (integer(cmd["id"])) message.insert("id", cmd["id"]);
    if (cmd["op"].isString()) message.insert("op", cmd["op"]);
    message.insert("error", QJsonObject{{"code", code}, {"message", text}, {"retryable", code == "track_not_ready" || code == "internal"}}); send(message);
}
void Host::malformed(const QString& message) { error({}, "malformed_message", message); }
void Host::event(const QString& name, const QJsonObject& data) {
    auto message = envelope("event"); message.insert("event", name); message.insert("seq", static_cast<qint64>(++seq_)); message.insert("data", data); send(message);
}
QJsonObject Host::snapshot() {
    return {{"rev", static_cast<qint64>(rev_)}, {"seq", static_cast<qint64>(seq_)}, {"engineId", engineId_}, {"sessionId", sessionId_}, {"engineTimeMs", static_cast<double>(clock_.elapsed())}, {"engine", info()}, {"decks", QJsonObject{{"A", slots_[0].state}, {"B", slots_[1].state}}}, {"mixer", backend_->mixer()}, {"audio", backend_->audio()}, {"meters", QJsonObject{{"enabled", false}, {"intervalMs", 100}, {"simulated", false}}}};
}
void Host::line(const QByteArray& bytes) {
    if (bytes.trimmed().isEmpty()) return;
    QJsonParseError parse;
    auto document = QJsonDocument::fromJson(bytes, &parse);
    if (parse.error != QJsonParseError::NoError || !document.isObject()) { malformed("Expected one JSON command object"); return; }
    const auto cmd = document.object();
    const auto op = cmd["op"].toString();
    if (!integer(cmd["id"]) || !cmd["op"].isString() || (!cmd["kind"].isUndefined() && cmd["kind"] != "command")) { error(cmd, "malformed_message", "Invalid command envelope or unsafe integer id"); return; }
    if (!cmd["protocol"].isUndefined() && cmd["protocol"] != 1) { error(cmd, "protocol_version_unsupported", "Only protocol 1 is supported"); return; }
    const auto id = static_cast<quint64>(cmd["id"].toDouble());
    if (op == "session.hello") {
        const auto previous = sessionId_;
        sessionId_ = QUuid::createUuid().toString(QUuid::WithoutBraces); lastId_ = id;
        auto hello = envelope("hello"); hello.insert("id", cmd["id"]); hello.insert("sessionId", sessionId_); hello.insert("engine", info()); hello.insert("protocolVersions", QJsonObject{{"min", 1}, {"max", 1}}); send(hello);
        if (!previous.isEmpty()) event("session.invalidated", {{"sessionId", previous}, {"reason", "superseded"}});
        backend_->start();
        return;
    }
    if (sessionId_.isEmpty()) { error(cmd, "session_required", "Call session.hello first"); return; }
    if (cmd["engineId"] != engineId_) { error(cmd, "engine_mismatch", "Wrong engine instance"); return; }
    if (cmd["sessionId"] != sessionId_) { error(cmd, "session_mismatch", "Expired or missing session"); return; }
    if (id <= lastId_) { error(cmd, "stale_command_id", "Command id must increase"); return; }
    lastId_ = id;
    if (op == "engine.ping") { result(cmd, {{"pong", true}}); return; }
    if (op == "state.snapshot") { result(cmd, snapshot()); return; }
    if (!known.contains(op)) { error(cmd, "unknown_op", "Unknown operation"); return; }
    if (!transport.contains(op) && !mixerOps.contains(op)) { error(cmd, "unsupported_operation", "This host implements deck transport and basic gains only"); return; }
    if (!cmd["params"].isObject()) { error(cmd, "invalid_params", "params must be an object"); return; }
    auto params = cmd["params"].toObject();
    if (!backend_->available()) { error(cmd, "unsupported_operation", backend_->problem()); return; }
    if (mixerOps.contains(op)) {
        const auto value = params[op == "mixer.crossfader" ? "position" : "gain"];
        if (!value.isDouble() || value.toDouble() < (op == "mixer.crossfader" ? -1.0 : 0.0) || value.toDouble() > 1.0) { error(cmd, "invalid_params", "Mixer value outside range"); return; }
        if (op == "mixer.channel.gain") {
            const auto name = params["deck"].toString().toUpper();
            if (name != "A" && name != "B") { error(cmd, "deck_not_found", "Expected deck A or B"); return; }
            backend_->gain(name == "A" ? 0 : 1, value.toDouble());
        } else if (op == "mixer.master.gain") backend_->masterGain(value.toDouble());
        else backend_->crossfader(value.toDouble());
        ++rev_; result(cmd, backend_->mixer()); event("mixer.state", backend_->mixer()); return;
    }
    const auto name = params["deck"].toString().toUpper();
    if (name != "A" && name != "B") { error(cmd, "deck_not_found", "Expected deck A or B"); return; }
    const int index = name == "A" ? 0 : 1;
    auto& slot = slots_[index]; auto& deck_ = slot.state; auto& descriptor_ = slot.descriptor;
    if (op == "deck.load") {
        const auto descriptor = params["track"].toObject();
        if (!descriptor["path"].isString() || !QDir::isAbsolutePath(descriptor["path"].toString()) || descriptor["trackId"].toString().trimmed().isEmpty()) { error(cmd, "invalid_params", "track requires trackId and an absolute local path"); return; }
        if (deck_["status"] == "loading") { error(cmd, "track_not_ready", "Wait for the current load to finish or unload first"); return; }
        descriptor_ = descriptor; slot.generation = ++generation_; ++rev_; resetDeck(index); deck_["status"] = "loading"; deck_["loadId"] = static_cast<qint64>(slot.generation);
        result(cmd, {{"accepted", true}, {"deck", name}, {"loadId", static_cast<qint64>(slot.generation)}}); event("deck.state", deck_);
        backend_->load(index, descriptor["path"].toString(), slot.generation); return;
    }
    if (op == "deck.unload") {
        slot.generation = ++generation_; backend_->unload(index); resetDeck(index); descriptor_ = {}; ++rev_; result(cmd, {{"deck", name}}); event("deck.state", deck_); return;
    }
    if (deck_["status"] == "loading") { error(cmd, "track_not_ready", "Deck is still loading"); return; }
    if (!deck_["track"].isObject()) { error(cmd, "no_track_loaded", "No track loaded"); return; }
    if (op == "deck.seek") {
        const auto value = params["positionMs"];
        if (!value.isDouble() || value.toDouble() < 0 || value.toDouble() > deck_["track"].toObject()["durationMs"].toDouble()) { error(cmd, "invalid_params", "positionMs is outside the track"); return; }
        backend_->seek(index, value.toDouble());
    } else {
        slot.transportTouched = true;
        backend_->play(index, op == "deck.play");
    }
    // Command acceptance is not an invented applied state. The poll below emits
    // the audio engine's observed position / play state on the next Qt tick.
    result(cmd, {{"deck", name}, {"accepted", true}});
}
void Host::completed(int index, quint64 generation, QJsonObject metadata, QString failure) {
    auto& slot = slots_[index]; auto& deck_ = slot.state; auto& descriptor_ = slot.descriptor;
    if (generation != slot.generation || deck_["status"] != "loading") return;
    ++rev_; deck_["loadId"] = QJsonValue::Null;
    if (!failure.isEmpty()) {
        deck_["status"] = "error"; deck_["lastError"] = failure;
        event("deck.load.failed", {{"deck", deckNames[index]}, {"loadId", static_cast<qint64>(generation)}, {"trackId", descriptor_["trackId"]}, {"error", QJsonObject{{"code", "load_failed"}, {"message", failure}}}});
    } else {
        auto track = descriptor_;
        for (auto it = metadata.begin(); it != metadata.end(); ++it) track.insert(it.key(), it.value());
        for (const auto* key : {"title", "artist", "bpm"}) if (!track.contains(key)) track.insert(key, QJsonValue::Null);
        if (!track.contains("beatgridOffsetMs")) track.insert("beatgridOffsetMs", 0);
        deck_["track"] = track; deck_["status"] = "ready";
        event("deck.loaded", {{"deck", deckNames[index]}, {"loadId", static_cast<qint64>(generation)}, {"track", track}});
    }
    event("deck.state", deck_);
}
void Host::sample() {
    sampleDeck(0); sampleDeck(1);
}
void Host::sampleDeck(int index) {
    auto& deck_ = slots_[index].state;
    if (!deck_["track"].isObject()) return;
    const auto track = deck_["track"].toObject();
    const auto position = qBound(0.0, backend_->positionMs(index), track["durationMs"].toDouble());
    const auto previousStatus = deck_["status"].toString();
    const QString status = backend_->playing(index) ? "playing" : (previousStatus == "ready" && !slots_[index].transportTouched ? "ready" : "paused");
    if (position == deck_["positionMs"].toDouble() && status == previousStatus) return;
    deck_["positionMs"] = position; deck_["positionFrames"] = std::floor(position * track["sampleRateHz"].toDouble() / 1000.0); deck_["status"] = status; ++rev_;
    if (status != previousStatus) event("deck.state", deck_);
    event("deck.position", {{"decks", QJsonObject{{deckNames[index], QJsonObject{{"positionMs", position}, {"positionFrames", deck_["positionFrames"]}, {"rate", deck_["rate"]}, {"status", status}}}}}});
}
