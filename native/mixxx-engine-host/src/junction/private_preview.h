#pragma once
#include <QJsonObject>
#include <QString>
#include <memory>
namespace junction {
// Independent decoder and bounded PCM queue; never enters EngineMixer.
class PrivatePreview final {
public:
    PrivatePreview();
    ~PrivatePreview();
    QString command(const QString&, const QJsonObject&);
    QJsonObject state() const;
    void mixPfl(float* stereo, unsigned frames) noexcept;
private:
    struct Impl;
    std::unique_ptr<Impl> d;
};
}
