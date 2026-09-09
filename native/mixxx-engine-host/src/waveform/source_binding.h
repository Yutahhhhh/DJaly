#pragma once
#include "sources/soundsourceproxy.h"
#include <QFileInfo>
#include <QDateTime>
#include <QCryptographicHash>
#include <sys/stat.h>
#include <map>
#include <mutex>
namespace waveform {
inline QString sourceFingerprint(const QString& path) {
    QFileInfo file(path);struct stat info{};if(::stat(path.toUtf8().constData(),&info)!=0)return {};
#ifdef __APPLE__
    const auto nanos=info.st_mtimespec.tv_nsec;
#else
    const auto nanos=info.st_mtim.tv_nsec;
#endif
    return QString::fromLatin1(QCryptographicHash::hash((file.canonicalFilePath()+":"+QString::number(file.size())+":"+QString::number(file.lastModified().toMSecsSinceEpoch())+":"+QString::number(nanos)).toUtf8(),QCryptographicHash::Sha256).toHex());
}
struct SourceBinding { mixxx::SoundSourceProviderPointer provider; int rate=0;QString fingerprint; };
inline std::mutex bindingsMutex;
inline std::map<QString,SourceBinding> bindings;
// Called by CachingReaderWorker after opening, never by the audio callback.
inline void bindSource(const QString& path, const SoundSourceProxy& proxy, const mixxx::AudioSourcePointer& source) {
    if(!source)return;
    std::lock_guard<std::mutex> lock(bindingsMutex);
    if(bindings.size()>=32)bindings.erase(bindings.begin());
    bindings[path]={proxy.getProvider(),int(source->getSignalInfo().getSampleRate().value()),sourceFingerprint(path)};
}
inline SourceBinding sourceBinding(const QString& path) {
    std::lock_guard<std::mutex> lock(bindingsMutex);const auto it=bindings.find(path);return it==bindings.end()?SourceBinding{}:it->second;
}
}
