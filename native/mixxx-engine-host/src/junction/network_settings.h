#pragma once
#include <QJsonArray>
#include <QJsonObject>
#include <QString>
namespace junction {
// Only temporary, scoped TURN passwords leave this native boundary. The
// administrator's REST secret is stored in Keychain, never in the snapshot.
class NetworkSettings {
public:
    explicit NetworkSettings(bool readStored = true);
    QJsonObject summary() const;
    QString configure(const QJsonObject&);
    QString clear();
    QJsonArray credentials(const QString& sessionId, const QString& peerId,
            qint64 nowMs, QString* error = nullptr) const;
private:
    QJsonObject config_;
    QString storageError_;
    bool saved_ = false;
    bool storageEnabled_ = true;
};
// Validates credential-bearing data arriving through a manual exchange.
// Does not resolve URLs or make requests; bounded and side-effect free.
QString validateNetworkServers(const QJsonArray&, qint64 nowMs);
}
