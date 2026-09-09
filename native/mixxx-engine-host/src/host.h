#pragma once

#include "backend.h"
#include <QElapsedTimer>
#include <QJsonObject>
#include <QObject>
#include <QTimer>
#include <array>

class Host final : public QObject {
public:
    explicit Host(std::unique_ptr<PlaybackBackend> backend);
    void line(const QByteArray& line);
    void malformed(const QString& message);
private:
    using QObject::event;
    QJsonObject info() const;
    QJsonObject snapshot();
    QJsonObject envelope(const QString& kind) const;
    void send(QJsonObject message) const;
    void result(const QJsonObject& cmd, const QJsonObject& data);
    void error(const QJsonObject& cmd, const QString& code, const QString& message);
    void event(const QString& name, const QJsonObject& data);
    void resetDeck(int index);
    void releaseScratch(int index, bool finish = true);
    void publishSyncLeader(int commanded);
    static QJsonObject emptyDeck();
    void sample();
    QJsonObject sampleDeck(int index);
    void completed(int index, quint64 generation, QJsonObject metadata, QString error);
    std::unique_ptr<PlaybackBackend> backend_;
    QElapsedTimer clock_;
    QTimer timer_;
    QString engineId_, sessionId_;
    quint64 rev_ = 0, seq_ = 0, lastId_ = 0, generation_ = 0;
    struct DeckSlot {
        QJsonObject state, descriptor;
        quint64 generation = 0;
        quint64 reverseGesture = 0;
        bool transportTouched = false;
        QString scratchGesture;
        qint64 scratchLastInputMs = 0;
        /** 最後に受け取ったスクラッチ位置。離すときはここへ着地させる。 */
        double scratchLastPositionMs = 0;
    };
    std::array<DeckSlot, 4> slots_;
};
