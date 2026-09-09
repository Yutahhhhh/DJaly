#pragma once
#include <QByteArray>
#include <QString>
#include <memory>
#include <functional>
namespace junction {
class AssetCache {
public:
    explicit AssetCache(QString root,quint64 quota=5ULL*1024*1024*1024);
    ~AssetCache();
    static QString hashFile(const QString& path,QString* error=nullptr);
    bool begin(const QString& sha256,quint64 bytes,QString* error=nullptr);
    bool put(const QString& sha256,quint64 offset,const QByteArray& chunk,QString* error=nullptr);
    // Decoder validation is required before publishing an asset as ready.
    bool finalize(const QString& sha256,const std::function<bool(const QString&)>& decoderAccepts,QString* error=nullptr);
    QString resolve(const QString& sha256) const;
    QByteArray receivedBitmap(const QString& sha256) const;
    void pin(const QString& sha256,bool pinned);
private:
    struct Impl; std::unique_ptr<Impl> d;
};
}
