#pragma once
#include "session_protocol.h"
#include <QSet>
namespace junction {
class Authority {
public:
    QString sessionId,host,local,owner,next,handoffId;
    quint64 epoch=1,throughSeq=0,revision=0,fenceFrame=0,cutoverFrame=0;
    QString phase="playing";
    std::optional<HandoffCommitMessage> committed;
    static bool localOnly(const QString& op);
    QString authorize(const QString& op,const QJsonObject& ticket,quint64 frame) const;
    QString prepare(const QString& target);
    QString fence(quint64 frame,quint64 watermark);
    QString commit(const HandoffCommitMessage& message,const QString& authenticatedSender);
    QString cancel();
    void advance(quint64 frame);
    QString recover(const QString& producer,quint64 newEpoch,quint64 frame);
};
}
