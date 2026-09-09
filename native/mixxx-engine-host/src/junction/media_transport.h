#pragma once
#include "pcm_ring.h"
#include <functional>
#include <memory>
#include <QStringList>
namespace junction {
struct StreamManifest {
    QString streamId,producerPeerId;
    quint64 epoch=0,generation=0,mediaFrameOrigin=0;
    quint32 ssrc=0,rtpTimestampOrigin=0;
    quint32 codecLookaheadFrames=312;
};
class MediaTransport {
public:
    struct Callbacks {
        std::function<void(bool,QString,QString,QString)> localDescription;
        std::function<void(bool,QString,QString)> localCandidate;
        std::function<void(QByteArray)> control,bulk,validation;
        std::function<void(QString)> error;
        std::function<void(StreamManifest)> producerManifest;
    };
    struct Identity { QString certificatePath,keyPath,fingerprint; };
    static std::shared_ptr<Identity> createIdentity(const QString& directory,QString* error=nullptr);
    MediaTransport(QString authenticatedPeerId,QStringList iceServers,Callbacks callbacks,std::shared_ptr<Identity> identity={},bool forceRelay=false);
    ~MediaTransport();
    bool start(bool offerer,QString* error=nullptr);
    void close();
    bool remoteDescription(bool bulk,const QString& sdp,const QString& type,const QString& authenticatedFingerprint,QString* error=nullptr);
    bool remoteCandidate(bool bulk,const QString& candidate,const QString& mid);
    bool sendControl(const QByteArray&),sendBulk(const QByteArray&),sendValidation(const QByteArray&);
    bool setSendManifest(const StreamManifest&),setReceiveManifest(const StreamManifest&);
    void startProducer(PcmRing*);
    void enableAutomaticManifest(bool enabled);
    bool acknowledgeSendManifest(const QString& streamId);
    PcmRing& decodedRing();
    PcmRing& preCodecRing();
    struct Statistics { quint64 receivedPackets=0,senderReports=0,receivedReports=0,nacksSent=0,retransmittedPackets=0; };
    Statistics statistics() const;
    bool selectedRelay(bool bulk=false) const;
    // Requests repair only while the packet is inside the decoder's deadline.
    bool requestRetransmission(quint64 mediaFrame);
    static bool available();
private:
    struct Impl; std::unique_ptr<Impl> d;
};
}
