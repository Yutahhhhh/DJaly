#pragma once
#include "authority.h"
#include "audio_clock.h"
#include "producer_tap.h"
#include <QObject>
#include <QTimer>
#include <memory>
#include <functional>
class PlaybackBackend;
namespace junction {
class Runtime final : public QObject {
public:
    explicit Runtime(PlaybackBackend*,QObject* parent=nullptr);
    ~Runtime();
    QJsonObject command(const QString& op,const QJsonObject& params,QString* error);
    QJsonObject snapshot() const;
    bool active() const;
    quint64 currentMediaFrame() const;
    quint64 currentAppliedSequence() const;
    void setCaptureAnchor(quint64 sourceFrame,quint64 mediaFrame);
    quint64 mediaFrameForSource(quint64 sourceFrame,unsigned rate=44100) const;
    QString authorize(const QString&,const QJsonObject&) const;
    void applied(const QString&,const QJsonObject&);
    void capture(const float*,unsigned frames,quint64 sourceFrame,unsigned rate) noexcept;
    bool sharedAudible() const noexcept;
    bool localMasterAudible() const noexcept;
    std::function<QJsonObject()> graphSnapshot;
    std::function<QString(const QJsonObject&)> restoreGraph;
private:
    struct Impl; std::unique_ptr<Impl> d;
};
}
