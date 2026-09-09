#pragma once
#include "source_binding.h"
#include <QJsonObject>
#include <QJsonArray>
#include <QString>
#include <atomic>
#include <condition_variable>
#include <deque>
#include <map>
#include <mutex>
#include <thread>
namespace waveform {
class Manager {
public:
    Manager();
    ~Manager();
    QJsonObject ensure(const QString& path, quint64 generation);
    QJsonObject manifest(const QString& key);
    QJsonObject lease(const QString& key,const QString& resource);
    void release(const QString& lease);
    QJsonObject requestRange(const QJsonObject& request);
    void cancelRequest(const QString& id);
    void invalidate(const QString& key);
private:
    struct Job {QString path,key,fingerprint;quint64 generation;SourceBinding binding;};
    struct Window {Job job;QString id;SINT start,end;};
    void pcm(const Window& window);
    std::map<QString,Job> assets_;
    std::deque<Window> windows_;
    std::map<QString,QString> requests_;
    void run(); void analyze(const Job& job); void prune();
    QString root_, activeKey_;
    quint64 diskBytes_=0;
    std::atomic<bool> stop_{false};
    std::mutex mutex_;
    std::condition_variable wake_;
    std::deque<Job> jobs_;
    std::map<QString,QJsonObject> manifests_;
    struct Lease {QString key;double until;};
    std::map<QString,Lease> leases_;
    std::thread worker_;
};
}
