#include "../sound_file.h"
#include "runtime.h"
#include "media_transport.h"
#include "program_output.h"
#include "asset_cache.h"
#include "validation.h"
#include "validation_capture.h"
#include "manual_exchange.h"
#include "ice_servers.h"
#include "network_settings.h"
#include <samplerate.h>
#include "../backend.h"
#include <QJsonDocument>
#include <QDebug>
#include <QUrl>
#include <QUrlQuery>
#include <QStandardPaths>
#include <QTemporaryDir>
#include <QDateTime>
#include <QFile>
#include <QFileInfo>
#include <QSaveFile>
#include "../platform_file.h"
#ifdef __APPLE__
#include <IOKit/pwr_mgt/IOPMLib.h>
#endif
#include <QDir>
#include <QPointer>
#include <QThread>
#include <QQueue>
#include <future>
#include <cmath>
#include <array>
#include <map>
#include <sndfile.h>
#if defined(PLUMDECK_JUNCTION_WITH_LIBDATACHANNEL)
#include <rtc/rtc.hpp>
#endif
namespace junction {
namespace {
QByteArray json(const QJsonObject& v) {return QJsonDocument(v).toJson(QJsonDocument::Compact);}
QString fingerprint() {return QStringLiteral("mixxx-3ebac449e7e5fe2a0186596657696e87ce8b0e56-junction-3");}
bool validOrigin(const QUrl& u) {
    return u.isValid() && !u.host().isEmpty() && u.userInfo().isEmpty() && u.fragment().isEmpty() && u.query().isEmpty() && (u.scheme()=="wss" || (u.scheme()=="ws" && (u.host()=="127.0.0.1" || u.host()=="localhost" || u.host()=="::1")));
}
QJsonObject streamJson(const StreamManifest& m) {return {{"streamId",m.streamId},{"producerPeerId",m.producerPeerId},{"epoch",u64(m.epoch)},{"generation",u64(m.generation)},{"mediaFrameOrigin",u64(m.mediaFrameOrigin)},{"ssrc",double(m.ssrc)},{"rtpTimestampOrigin",double(m.rtpTimestampOrigin)},{"codecLookaheadFrames",int(m.codecLookaheadFrames)}};}
std::optional<StreamManifest> readStream(const QJsonObject& o) {
    auto epoch=parseU64(o["epoch"]),gen=parseU64(o["generation"]),origin=parseU64(o["mediaFrameOrigin"]);
    if(!epoch || !gen || !origin || !validOpaqueId(o["streamId"].toString()) || !validOpaqueId(o["producerPeerId"].toString())) return {};
    const double ssrc=o["ssrc"].toDouble(-1),rtp=o["rtpTimestampOrigin"].toDouble(-1);
    if(ssrc<0 || ssrc>4294967295.0 || rtp<0 || rtp>4294967295.0 || std::floor(ssrc)!=ssrc || std::floor(rtp)!=rtp) return {};
    return StreamManifest{o["streamId"].toString(),o["producerPeerId"].toString(),*epoch,*gen,*origin,quint32(ssrc),quint32(rtp)};
}
}
struct Runtime::Impl {
    Runtime* q;
#ifdef __APPLE__
    IOPMAssertionID sleepLease=kIOPMNullAssertionID;
#endif
    PlaybackBackend* backend;Authority auth;MediaTimeline timeline;ClockEstimator clock;
    ProducerTap tap;ProgramOutput program;AssetCache cache;
    QTemporaryDir identityDir;
    std::shared_ptr<MediaTransport::Identity> identity;
    // One manual offer/answer round for one DJ. The peer id it belongs to is
    // stable across re-exchange; only `generation` and `attempt` move.
    struct ManualAttempt {
        ExchangeState state=ExchangeState::Idle;
        QString inviteId,inviteText,responseText,noticeText,detail,errorCode,waitingFor=QStringLiteral("none");
        QJsonArray ice;
        QString answerSdp[2],answerType[2],answerFingerprint,answerName,answerDigest;
        bool answerPending=false;
        quint64 generation=0,attempt=0;
        qint64 expiresAt=0,collectDeadline=0,connectDeadline=0;
        unsigned retries=0;
        void clearArtifacts(){
            inviteText.clear();responseText.clear();answerPending=false;answerFingerprint.clear();
            answerName.clear();answerDigest.clear();
            for(auto& value:answerSdp)value.clear();
            for(auto& value:answerType)value.clear();
        }
    };
    // `candidate` is a replacement connection attempt built while `transport`
    // is still carrying audio. It is promoted only once it actually connects,
    // so a manual re-exchange never interrupts an established peer.
    struct Peer {QString id,name,fp;bool approved=false,hello=false,producing=false,endingAck=false;std::unique_ptr<MediaTransport> transport;QQueue<QByteArray> pending;
        qint64 lastControlAt=0;quint64 serial=0,candidateSerial=0;std::unique_ptr<MediaTransport> candidate,retiring; qint64 retireAt=0;ManualAttempt manual;};
    std::map<QString,std::unique_ptr<Peer>> peers;
#if defined(PLUMDECK_JUNCTION_WITH_LIBDATACHANNEL)
    std::shared_ptr<rtc::WebSocket> signal;
#endif
    QTimer timer;quint64 ticks=0,controlSeq=0;QString origin,room,name,displayName,token,recovery,invite,problem,connection="disconnected",programState="idle";
    QStringList iceServers;bool iceReady=false;QQueue<QJsonObject> deferredSignals;QJsonObject pendingInvite,graph,preparedGraph;QJsonArray participantRoster;
    bool hosting=false,adopt=false,programOpened=false,prepared=false,ready=false;
    QStringList reasons;quint32 delay=24000;int programDevice=-1,maxPeers=8;
    qint64 inviteExpiry=0,turnRefreshAt=0,fenceDeadline=0,lastSharedChange=0,reconnectAt=0,endingAt=0;bool endingHost=false;unsigned reconnectAttempts=0;bool graphDirty=false;quint64 generation=1,graphSeq=0,signalGeneration=0;
    bool aligned=false,finalCheckpoint=false,validationSent=false;
    quint64 validationStart=0,validationEnd=0;
    QString validationId;unsigned validationRound=0;
    ValidationCapture validationCapture;
    std::map<QString,std::vector<float>> validationPcm;
    struct ValidationReceive {QString sender;QByteArray bytes;std::vector<bool> chunks;};
    std::map<QString,ValidationReceive> validationReceiving;
    QQueue<QByteArray> validationOutgoing;
    QString validationTarget;
    struct ProgramBlock {PcmBlockInfo info;std::vector<float> samples;};
    std::map<quint64,ProgramBlock> programPending,backupPending;
    quint64 programEnqueuedThrough=0; qint64 ownerAudioAt=0;quint64 recoveryUntil=0,recoveryResumeFrame=0,recoveryEpoch=0;
    QString backupOwner;quint64 backupEpoch=0;

    std::atomic<bool> captureEnabled{false},audible{true},separateLocalMaster{true};
    std::atomic<quint64> lastCaptureSourceEnd{0};
    std::atomic<quint64> blockSequence{0},captureEpoch{1},sourceAnchor{UINT64_MAX},mediaAnchor{0};
    std::atomic<qint64> timelineAnchor{0};
    std::atomic<quint64> pendingAnchorSource{0},pendingAnchorMedia{0},pendingAnchorRevision{0};
    quint64 appliedAnchorRevision=0;
    std::atomic<quint64> captureGeneration{1},scheduledEpoch{0},scheduledFrame{UINT64_MAX};
    std::array<float,8192> pcm{};
    std::map<QString,QString> assets;
    std::map<QString,QSet<QString>> assetWaiters;
    std::map<QString,QString> assetKinds;
    QString pendingGraphAsset;bool preserveWarmGraph=false;QString exportHandoff;
    QSet<QString> requestedAssets,pinnedAssets;
    QString validationAwaitingAck;
    struct Outgoing {QString peer,hash,path;quint64 offset=0;};
    QQueue<Outgoing> outgoing;
    std::future<std::pair<QJsonObject,std::map<QString,QString>>> exportJob;
    quint64 exportRevision=0;
    QJsonObject privateState;
    // --- manual (signalling-free) exchange -------------------------------
    bool manual=false;QByteArray hostCertificatePem;QString pinnedHostFingerprint;
    quint64 serialCounter=0;
    QString manualDetail,manualErrorCode;
    std::unique_ptr<MediaTransport> networkProbe;
    QJsonObject networkTestResult;
    qint64 networkTestDeadline=0;
    NetworkSettings network;
    explicit Impl(Runtime* owner,PlaybackBackend* b):q(owner),backend(b),cache(QStandardPaths::writableLocation(QStandardPaths::CacheLocation)+"/junction") {
        timer.setInterval(5);QObject::connect(&timer,&QTimer::timeout,q,[this]{tick();});timer.start();
    }
    quint64 now() const {return hosting?timeline.now():timeline.frameAt(clock.toHostNanos(monotonicNanos()));}
    template<class F> void post(F fn) {QMetaObject::invokeMethod(q,std::move(fn),Qt::QueuedConnection);}
    void fail(const QString& text) {if(qEnvironmentVariableIsSet("PLUMDECK_JUNCTION_TRACE"))qWarning()<<"junction failure"<<hosting<<text;problem=text;reasons={text};ready=false;}
    void signalSend(QJsonObject m) {
#if defined(PLUMDECK_JUNCTION_WITH_LIBDATACHANNEL)
        m["v"]=1;
        if(signal && signal->isOpen()) {try{signal->send(json(m).toStdString());}catch(const std::exception&){fail("接続サービスへ送信できません");}}
#else
        Q_UNUSED(m);
#endif
    }
    void queue(Peer& p,const QString& type,QJsonObject payload) {
        if(p.pending.size()>=64&&(type=="session.snapshot"||type=="clock.probe"))return;
        if(p.pending.size()>=128) {p.pending.clear();if(manual)manualSetState(p,ExchangeState::NeedsExchange,"このDJへの制御通信が混雑しています。接続情報を作り直してください","control_backpressure");else fail("制御通信が混雑しています");return;}
        p.pending.enqueue(json({{"version",1},{"sessionId",auth.sessionId},{"senderPeerId",auth.local},{"epoch",u64(auth.epoch)},{"messageId",secureRandomHex(12)},{"type",type},{"payload",payload}}));
    }
    void broadcast(const QString& type,const QJsonObject& payload) {for(auto& [id,p]:peers)if(p->approved&&p->transport)queue(*p,type,payload);}
    /// `wire` strips everything a remote peer must not see. Exchange packets
    /// carry another DJ's invite/response/notice text and never go on the wire.
    QJsonObject publicState(bool wire=false) const {
        QJsonArray participants;
        if(!auth.local.isEmpty())participants.append(QJsonObject{{"peerId",auth.local},{"displayName",displayName},{"approved",true},{"isHost",hosting},{"isPerformer",auth.owner==auth.local},{"isNextUp",auth.next==auth.local},{"status",connection}});
        for(const auto& [id,p]:peers){
            QJsonObject row{{"peerId",id},{"displayName",p->name},{"approved",p->approved},{"isHost",id==auth.host},{"isPerformer",id==auth.owner},{"isNextUp",id==auth.next},{"status",p->hello?"connected":p->approved?"connecting":"pending"}};
            if(manual&&!wire)row["exchange"]=manualExchangeJson(*p);
            participants.append(row);
        }
        if(!hosting)for(const auto& value:participantRoster){const auto row=value.toObject();const auto id=row["peerId"].toString();if(!validOpaqueId(id)||id==auth.local||peers.count(id))continue;
            participants.append(QJsonObject{{"peerId",id},{"displayName",sanitizeDisplayName(row["displayName"].toString())},{"approved",row["approved"].toBool()},{"isHost",id==auth.host},{"isPerformer",id==auth.owner},{"isNextUp",id==auth.next},{"status",row["status"].toString()}});
        }
        QJsonArray why;for(const auto& r:reasons)why.append(r);
        return {{"active",!auth.sessionId.isEmpty()},{"sessionId",auth.sessionId},{"localPeerId",auth.local},{"hostPeerId",auth.host},{"performerPeerId",auth.owner},{"nextPeerId",auth.next},{"epoch",u64(auth.epoch)},{"revision",double(auth.revision)},{"sessionName",name},{"handoffState",auth.phase},{"handoffId",auth.handoffId},{"participants",participants},{"readiness",QJsonObject{{"ready",ready},{"reasons",why}}},{"connection",QJsonObject{{"state",connection},{"detail",problem}}},{"program",QJsonObject{{"state",programState},{"localMonitor",separateLocalMaster.load()?"direct":"program-delayed"},{"outputDevice",QString::number(programDevice)},{"recording",program.recording()},{"underruns",u64(program.underruns())},{"meter",double(program.peak())},{"rms",double(program.rms())},{"sampleRateHz",int(program.sampleRate())},{"deviceLatencySeconds",program.deviceLatencySeconds()}}},{"invite",hosting?invite:QString{}},{"privatePreview",backend->privatePreviewState()},{"exchange",wire?QJsonObject{{"mode",manual?QStringLiteral("manual"):QStringLiteral("server")}}:exchangeState()}};
    }
    /// Session-level exchange summary. For a guest it mirrors the attempt with
    /// the host, which is the only one it has.
    QJsonObject exchangeState() const {
        QJsonObject value{{"mode",manual?QStringLiteral("manual"):QStringLiteral("server")}};
        if(!manual){value["state"]=exchangeStateName(connection=="connected"?ExchangeState::Connected:connection=="disconnected"?ExchangeState::Idle:ExchangeState::Connecting);
            if(!problem.isEmpty())value["detail"]=problem;return value;}
        const Peer* subject=nullptr;
        if(!hosting){auto i=peers.find(auth.host);if(i!=peers.end())subject=i->second.get();}
        else{
            // The host's own card summarises the attempt that most needs the
            // user: an approval first, then anything still being produced.
            for(const auto& [id,p]:peers){
                const auto state=p->manual.state;
                if(state==ExchangeState::ApprovalPending){subject=p.get();break;}
                if(!subject&&(state==ExchangeState::Collecting||state==ExchangeState::InviteReady))subject=p.get();
            }
        }
        value["state"]=exchangeStateName(subject?subject->manual.state:ExchangeState::Idle);
        if(subject){
            if(!subject->manual.detail.isEmpty())value["detail"]=subject->manual.detail;
            if(!subject->manual.errorCode.isEmpty())value["errorCode"]=subject->manual.errorCode;
            if(!subject->manual.responseText.isEmpty())value["responseText"]=subject->manual.responseText;
            if(!subject->manual.inviteId.isEmpty())value["inviteId"]=subject->manual.inviteId;
            if(subject->manual.expiresAt)value["expiresAt"]=double(subject->manual.expiresAt);
        }else if(!manualDetail.isEmpty())value["detail"]=manualDetail;
        if(!manualErrorCode.isEmpty())value["errorCode"]=manualErrorCode;
        return value;
    }
    void updateInvite() {
        if(!hosting || room.isEmpty())return;
        QUrl u("plumdeck-junction://join");QUrlQuery query;
        query.addQueryItem("version","1");query.addQueryItem("signaling",origin);query.addQueryItem("room",room);query.addQueryItem("token",token);query.addQueryItem("host",identity->fingerprint);query.addQueryItem("expiresAt",QString::number(inviteExpiry));u.setQuery(query);invite=u.toString(QUrl::FullyEncoded);
    }
    QString connect(bool host) {
        hosting=host;QString error;
#ifdef __APPLE__
        if(sleepLease==kIOPMNullAssertionID)IOPMAssertionCreateWithName(kIOPMAssertionTypePreventUserIdleSystemSleep,kIOPMAssertionLevelOn,CFSTR("plumdeck Junction audio session"),&sleepLease);
#elif defined(_WIN32)
        SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED);
#endif
        if(!identity)identity=MediaTransport::createIdentity(identityDir.path(),&error);if(!identity)return error;
#if defined(PLUMDECK_JUNCTION_WITH_LIBDATACHANNEL)
        rtc::WebSocket::Configuration config;config.maxMessageSize=65536;
        signal=std::make_shared<rtc::WebSocket>(config);
        QPointer<Runtime> safe=q;const auto serial=++signalGeneration;
        signal->onMessage([safe,serial](rtc::message_variant data){if(!safe)return;if(auto* s=std::get_if<std::string>(&data)){if(s->size()>65536)return;auto bytes=QByteArray(s->data(),int(s->size()));QMetaObject::invokeMethod(safe,[safe,bytes,serial]{if(safe&&safe->d->signalGeneration==serial)safe->d->onSignal(QJsonDocument::fromJson(bytes).object());},Qt::QueuedConnection);}});
        signal->onClosed([safe,serial]{if(safe)QMetaObject::invokeMethod(safe,[safe,serial]{if(safe&&safe->d->signalGeneration==serial){safe->d->connection="reconnecting";if(safe->d->hosting)safe->d->reconnectAt=monotonicNanos()+1000000000LL;safe->d->problem="接続サービスとの接続が切れました。確立済み音声は継続します";}},Qt::QueuedConnection);});
        signal->onError([safe,serial](std::string){if(safe)QMetaObject::invokeMethod(safe,[safe,serial]{if(safe&&safe->d->signalGeneration==serial){safe->d->fail("接続サービスへ接続できません");if(safe->d->hosting)safe->d->reconnectAt=monotonicNanos()+2000000000LL;}},Qt::QueuedConnection);});
        try{signal->open(origin.toStdString());}catch(const std::exception&){return "接続サービスへ接続できません";}
        connection="connecting";return {};
#else
        return "このビルドにはWebRTCが含まれていません";
#endif
    }
    /// Brings up a manual session. Nothing is contacted: the host mints its own
    /// session and peer identifiers and is immediately live locally.
    QString startManual(bool host) {
        manual=true;hosting=host;QString error;
#ifdef __APPLE__
        if(sleepLease==kIOPMNullAssertionID)IOPMAssertionCreateWithName(kIOPMAssertionTypePreventUserIdleSystemSleep,kIOPMAssertionLevelOn,CFSTR("plumdeck Junction audio session"),&sleepLease);
#elif defined(_WIN32)
        SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED);
#endif
        if(!MediaTransport::available())return "このビルドにはWebRTCが含まれていません";
        if(!identity)identity=MediaTransport::createIdentity(identityDir.path(),&error);
        if(!identity)return error.isEmpty()?QStringLiteral("この端末の識別情報を作成できません"):error;
        hostCertificatePem=readCertificatePem(identity->certificatePath);
        if(hostCertificatePem.isEmpty())return "この端末の証明書を読み込めません";
        // Manual mode needs no negotiated TURN credentials before it can build
        // a transport; servers are resolved per attempt from local settings.
        iceReady=true;
        if(host){
            auth.local=secureRandomHex(16);auth.host=auth.local;auth.owner=auth.local;
            pinnedHostFingerprint=identity->fingerprint;
            timeline.start(monotonicNanos());timelineAnchor.store(timeline.originNanos());
            captureEnabled.store(true);tap.enable(false,true);
            connection="connected";problem.clear();openProgram();
        }
        return {};
    }
    void onSignal(const QJsonObject& m) {
        if(m["v"]!=1)return;
        const auto type=m["type"].toString();
        if(type=="server.hello") {
            if(hosting)signalSend({{"type","host.register"},{"roomLocator",room},{"inviteTokenHash",sha256Hex(token.toUtf8())},{"inviteExpiresAt",double(inviteExpiry)},{"hostFingerprint",identity->fingerprint},{"recoverySecret",recovery},{"sessionName",name},{"maxPeers",maxPeers}});
            else signalSend({{"type","guest.join"},{"roomLocator",room},{"inviteToken",token},{"displayName",displayName},{"peerFingerprint",identity->fingerprint}});
        } else if(type=="host.registered") {
            room=m["roomLocator"].toString();const auto registered=m["hostPeerId"].toString();
            if(auth.local.isEmpty()){auth.local=registered;auth.host=auth.local;auth.owner=auth.local;timeline.start(monotonicNanos());timelineAnchor.store(timeline.originNanos());captureEnabled.store(true);tap.enable(false,true);}
            else if(registered!=auth.local){fail("接続サービスの識別情報が変わりました。確立済み音声は継続します");return;}
            reconnectAt=0;reconnectAttempts=0;connection="connected";problem.clear();signalSend({{"type","turn.credentials"}});updateInvite();openProgram();
        } else if(type=="join.pending") {auth.local=m["peerId"].toString();auth.host=m["hostPeerId"].toString();connection="pending";}
        else if(type=="join.accepted") {auth.local=m["peerId"].toString();auth.host=m["hostPeerId"].toString();connection="connecting";auto p=std::make_unique<Peer>();p->id=auth.host;p->name="ホスト";p->fp=pendingInvite["host"].toString();p->approved=true;peers[auth.host]=std::move(p);signalSend({{"type","turn.credentials"}});}
        else if(type=="room.join_request" && hosting) {const auto id=m["guestPeerId"].toString();if(!validOpaqueId(id))return;auto p=std::make_unique<Peer>();p->id=id;p->name=sanitizeDisplayName(m["displayName"].toString());p->fp=m["peerFingerprint"].toString();peers[id]=std::move(p);++auth.revision;}
        else if(type=="signal.deliver") {
            const auto id=m["fromPeerId"].toString();auto i=peers.find(id);if(i==peers.end()||!i->second->approved)return;auto& p=*i->second;if(!p.transport)makePeer(p,false);
            const auto payload=m["payload"].toObject();QString error;
            if(payload["kind"]=="description") {if(!p.transport->remoteDescription(payload["bulk"].toBool(),payload["sdp"].toString(),payload["descriptionType"].toString(),p.fp,&error))fail(error);}
            else if(payload["kind"]=="candidate")p.transport->remoteCandidate(payload["bulk"].toBool(),payload["candidate"].toString(),payload["mid"].toString());
        } else if(type=="join.rejected" || type=="error") {fail(type=="join.rejected"?QStringLiteral("参加できません: ")+m["reason"].toString():m["message"].toString());connection="error";}
        else if(type=="signaling.unavailable") {connection="reconnecting";problem="接続サービスは利用できません。確立済みP2P音声は継続します";}
        else if(type=="room.closed") {stop();connection="disconnected";problem="ホストがセッションを終了しました";}
        else if(type=="peer.gone") {const auto id=m["peerId"].toString();if(id==auth.owner&&(!auth.committed||now()>=auth.cutoverFrame))beginRecovery("プレイ担当者との接続が切れました");peers.erase(id);++auth.revision;}
        else if(type=="turn.credentials") {
            // Credentials stay native; never included in snapshots or logs.
            iceServers=iceServerUrls(m["iceServers"].toArray());
            const auto lifetime=std::clamp<qint64>(qint64(m["expiresAt"].toDouble())-QDateTime::currentMSecsSinceEpoch(),1000,3600000);
            turnRefreshAt=monotonicNanos()+std::max<qint64>(1000,lifetime-std::min<qint64>(60000,lifetime/2))*1000000;
            iceReady=true;for(auto& [id,p]:peers)if(p->approved&&!p->transport)makePeer(*p,hosting);
            while(!deferredSignals.isEmpty())onSignal(deferredSignals.dequeue());
        }
    }
    /// Resolves the slot a callback belongs to. A stale serial means the
    /// attempt was replaced or cancelled while the callback was in flight;
    /// every callback below drops out rather than touching the new attempt.
    MediaTransport* transportForSerial(Peer& p,quint64 serial) const {
        if(serial&&p.serial==serial)return p.transport.get();
        if(serial&&p.candidateSerial==serial)return p.candidate.get();
        return nullptr;
    }
    Peer* peerForSerial(const QString& id,quint64 serial) {
        auto i=peers.find(id);if(i==peers.end())return nullptr;
        return transportForSerial(*i->second,serial)?i->second.get():nullptr;
    }
    /// True while the callback belongs to the slot that is allowed to carry
    /// session traffic. A not-yet-promoted candidate is admitted first.
    bool liveSerial(Peer& p,quint64 serial) {
        if(p.candidateSerial==serial)manualPromoteIfReady(p);
        return p.serial==serial;
    }
    std::unique_ptr<MediaTransport> buildTransport(const QString& id,quint64 serial,bool offerer,const QStringList& servers,QString* error) {
        QPointer<Runtime> safe=q;
        MediaTransport::Callbacks callbacks;
        // Manual mode aggregates candidates instead of trickling them, so the
        // description/candidate callbacks below are inert without signalling.
        callbacks.gatheringComplete=[safe,id,serial](bool){if(safe)QMetaObject::invokeMethod(safe,[safe,id,serial]{if(!safe)return;auto* p=safe->d->peerForSerial(id,serial);if(p)safe->d->manualCollected(*p,serial);},Qt::QueuedConnection);};
        callbacks.linkState=[safe,id,serial](bool,LinkState state){if(safe)QMetaObject::invokeMethod(safe,[safe,id,serial,state]{if(!safe)return;auto* p=safe->d->peerForSerial(id,serial);if(p)safe->d->manualLinkChanged(*p,serial,state);},Qt::QueuedConnection);};
        callbacks.localDescription=[safe,id,serial](bool bulk,QString sdp,QString type,QString){if(safe)QMetaObject::invokeMethod(safe,[safe,id,serial,bulk,sdp,type]{if(!safe||safe->d->manual)return;auto* p=safe->d->peerForSerial(id,serial);if(p)safe->d->signalSend({{"type","signal.relay"},{"toPeerId",id},{"payload",QJsonObject{{"kind","description"},{"bulk",bulk},{"sdp",sdp},{"descriptionType",type}}}});},Qt::QueuedConnection);};
        callbacks.localCandidate=[safe,id,serial](bool bulk,QString candidate,QString mid){if(safe)QMetaObject::invokeMethod(safe,[safe,id,serial,bulk,candidate,mid]{if(!safe||safe->d->manual)return;auto* p=safe->d->peerForSerial(id,serial);if(p)safe->d->signalSend({{"type","signal.relay"},{"toPeerId",id},{"payload",QJsonObject{{"kind","candidate"},{"bulk",bulk},{"candidate",candidate},{"mid",mid}}}});},Qt::QueuedConnection);};
        callbacks.producerManifest=[safe,id,serial](StreamManifest manifest){if(safe)QMetaObject::invokeMethod(safe,[safe,id,serial,manifest]{if(!safe)return;auto* p=safe->d->peerForSerial(id,serial);if(p&&safe->d->liveSerial(*p,serial))safe->d->queue(*p,"peer.hello",{{"fingerprint",fingerprint()},{"displayName",safe->d->displayName},{"stream",streamJson(manifest)}});},Qt::QueuedConnection);};
        callbacks.control=[safe,id,serial](QByteArray bytes){if(safe)QMetaObject::invokeMethod(safe,[safe,id,serial,bytes]{if(!safe)return;auto* p=safe->d->peerForSerial(id,serial);if(p&&safe->d->liveSerial(*p,serial))safe->d->control(id,bytes);},Qt::QueuedConnection);};
        callbacks.validation=[safe,id,serial](QByteArray bytes){if(safe)QMetaObject::invokeMethod(safe,[safe,id,serial,bytes]{if(!safe)return;auto* p=safe->d->peerForSerial(id,serial);if(p&&safe->d->liveSerial(*p,serial))safe->d->validationChunk(id,bytes);},Qt::QueuedConnection);};
        callbacks.bulk=[safe,id,serial](QByteArray bytes){if(safe)QMetaObject::invokeMethod(safe,[safe,id,serial,bytes]{if(!safe)return;auto* p=safe->d->peerForSerial(id,serial);if(p&&safe->d->liveSerial(*p,serial))safe->d->bulk(id,bytes);},Qt::QueuedConnection);};
        // A transport-level failure is scoped to its own peer. It must never
        // tear down the shared session or another DJ's connection.
        callbacks.error=[safe,id,serial](QString failure){if(safe)QMetaObject::invokeMethod(safe,[safe,id,serial,failure]{if(!safe)return;auto* p=safe->d->peerForSerial(id,serial);if(!p)return;
            if(safe->d->manual){if(serial!=safe->d->attemptSerial(*p)||exchangeStateTerminal(p->manual.state))return;safe->d->manualSetState(*p,ExchangeState::Failed,failure,QStringLiteral("transport"));}
            else safe->d->fail(failure);},Qt::QueuedConnection);};
        auto transport=std::make_unique<MediaTransport>(id,servers,std::move(callbacks),identity,qEnvironmentVariable("PLUMDECK_JUNCTION_FORCE_RELAY")=="1");
        if(!transport->start(offerer,error))return {};
        return transport;
    }
    void makePeer(Peer& p,bool offerer) {
        if(!iceReady||p.transport)return;
        const auto serial=++serialCounter;p.serial=serial;QString error;
        auto transport=buildTransport(p.id,serial,offerer,iceServers,&error);
        if(!transport){p.serial=0;fail(error);return;}
        p.transport=std::move(transport);
        queue(p,"peer.hello",{{"fingerprint",fingerprint()},{"displayName",displayName}});
        if(hosting)queue(p,"session.snapshot",wireState());
    }
    // ---------------------------------------------------------------------
    // Manual exchange
    // ---------------------------------------------------------------------
    MediaTransport* attemptSlot(Peer& p) const {return p.candidate?p.candidate.get():p.transport.get();}
    quint64 attemptSerial(const Peer& p) const {return p.candidate?p.candidateSerial:p.serial;}
    void manualSetState(Peer& p,ExchangeState state,const QString& detail={},const QString& code={}) {
        p.manual.state=state;p.manual.detail=detail;p.manual.errorCode=code;
        if(!hosting&&!p.candidate){
            if(state==ExchangeState::Connected)connection="connected";
            else if(state==ExchangeState::Interrupted)connection="reconnecting";
            else if(state==ExchangeState::NeedsExchange||state==ExchangeState::Failed)connection="error";
        }
        p.manual.waitingFor=state==ExchangeState::InviteReady?QStringLiteral("guest")
            :state==ExchangeState::ResponseReady||state==ExchangeState::AwaitingHost?QStringLiteral("host")
            :state==ExchangeState::ApprovalPending||state==ExchangeState::Collecting?QStringLiteral("local")
            :QStringLiteral("none");
        ++auth.revision;
    }
    /// Starts one connection attempt for `p`. When the peer already has a live
    /// transport the attempt is built alongside it as a replacement candidate,
    /// so an established connection keeps carrying audio until the new one is
    /// actually up.
    QString manualStartAttempt(Peer& p,bool offerer,const QJsonArray& remoteIce) {
        const bool replacement=p.transport&&p.transport->aggregateLinkState()==LinkState::Connected;
        const auto serial=++serialCounter;QString error;
        auto transport=buildTransport(p.id,serial,offerer,iceServerUrls(remoteIce),&error);
        if(!transport)return error.isEmpty()?QStringLiteral("接続を開始できません"):error;
        if(replacement){p.candidate=std::move(transport);p.candidateSerial=serial;}
        else{
            // Not connected: replace outright and drop any older candidate so
            // exactly one attempt is ever gathering for this peer.
            p.candidate.reset();p.candidateSerial=0;
            if(p.transport)p.transport->close();
            p.transport=std::move(transport);p.serial=serial;p.hello=false;p.producing=false;p.pending.clear();
        }
        p.manual.retries=0;p.manual.clearArtifacts();p.manual.noticeText.clear();
        p.manual.collectDeadline=monotonicNanos()+30000000000LL;p.manual.connectDeadline=0;
        manualSetState(p,ExchangeState::Collecting,QStringLiteral("音声・操作と楽曲転送の両方の接続先を収集しています。完了までお待ちください"));
        if(!replacement)queue(p,"peer.hello",{{"fingerprint",fingerprint()},{"displayName",displayName}});
        return {};
    }
    /// Both connections finished gathering: the aggregated descriptions are
    /// now complete and the packet can be produced.
    void manualCollected(Peer& p,quint64 serial) {
        if(!manual||serial!=attemptSerial(p))return;
        auto* transport=attemptSlot(p);
        if(!transport||!transport->readyForManualExport())return;
        if(p.manual.state!=ExchangeState::Collecting)return;
        p.manual.collectDeadline=0;
        const auto failure=hosting?manualBuildInvite(p):manualBuildResponse(p);
        if(!failure.isEmpty()){manualSetState(p,ExchangeState::Failed,failure,QStringLiteral("packet"));return;}
    }
    QString manualPacketBase(Peer& p,ExchangePacket& packet) const {
        packet.sessionId=auth.sessionId;packet.sessionName=name;packet.inviteId=p.manual.inviteId;
        packet.hostPeerId=auth.host;packet.hostName=hosting?displayName:p.name;
        packet.hostFingerprint=hosting?identity->fingerprint:pinnedHostFingerprint;
        packet.peerId=hosting?p.id:auth.local;packet.generation=p.manual.generation;packet.attempt=p.manual.attempt;
        packet.expiresAt=p.manual.expiresAt;
        if(packet.hostFingerprint.isEmpty())return QStringLiteral("ホストの識別情報がありません");
        return {};
    }
    QString manualSign(ExchangePacket& packet) const {
        if(hostCertificatePem.isEmpty())return QStringLiteral("この端末の証明書を読み込めません");
        packet.certificatePem=hostCertificatePem;QString failure;
        packet.signature=signExchangePayload(identity->keyPath,packet.canonicalPayload(),&failure);
        return packet.signature.isEmpty()?failure:QString{};
    }
    QString manualBuildInvite(Peer& p) {
        auto* transport=attemptSlot(p);if(!transport)return QStringLiteral("接続を開始できません");
        ExchangePacket packet;packet.kind=ExchangeKind::Invite;
        auto failure=manualPacketBase(p,packet);if(!failure.isEmpty())return failure;
        for(int index=0;index<2;++index){
            QString type,fp;const auto sdp=transport->aggregatedDescription(index==1,&type,&fp);
            if(sdp.isEmpty()||!sdp.contains("a=candidate:")||fp!=identity->fingerprint)return QStringLiteral("接続情報を作成できません");
            packet.description[index]={type,sdp};
        }
        if(hosting)packet.iceServers=p.manual.ice;
        failure=manualSign(packet);if(!failure.isEmpty())return failure;
        const auto text=encodeExchangePacket(packet,&failure);if(text.isEmpty())return failure;
        p.manual.inviteText=text;p.manual.responseText.clear();
        manualSetState(p,ExchangeState::InviteReady,QStringLiteral("この接続情報を相手に渡してください"));
        return {};
    }
    QString manualBuildResponse(Peer& p) {
        auto* transport=attemptSlot(p);if(!transport)return QStringLiteral("接続を開始できません");
        ExchangePacket packet;packet.kind=ExchangeKind::Response;
        auto failure=manualPacketBase(p,packet);if(!failure.isEmpty())return failure;
        packet.peerName=displayName;packet.peerFingerprint=identity->fingerprint;
        for(int index=0;index<2;++index){
            QString type,fp;const auto sdp=transport->aggregatedDescription(index==1,&type,&fp);
            if(sdp.isEmpty()||!sdp.contains("a=candidate:")||fp!=identity->fingerprint)return QStringLiteral("接続情報を作成できません");
            packet.description[index]={type,sdp};
        }
        if(hosting)packet.iceServers=p.manual.ice;
        failure=manualSign(packet);if(!failure.isEmpty())return failure;
        const auto text=encodeExchangePacket(packet,&failure);if(text.isEmpty())return failure;
        p.manual.responseText=text;
        // Producing the text is local work only. It is never evidence that the
        // host has received, read or accepted anything.
        manualSetState(p,ExchangeState::ResponseReady,QStringLiteral("この応答をホストに渡してください"));
        return {};
    }
    /// Applies an imported answer. Only reached after the host has approved.
    QString manualApplyAnswer(Peer& p) {
        auto* transport=attemptSlot(p);
        if(!transport||!p.manual.answerPending)return QStringLiteral("応答が読み込まれていません");
        for(int index=0;index<2;++index){
            QString failure;
            if(!transport->remoteDescription(index==1,p.manual.answerSdp[index],p.manual.answerType[index],p.manual.answerFingerprint,&failure))
                return failure.isEmpty()?QStringLiteral("応答を適用できません"):failure;
        }
        p.fp=p.manual.answerFingerprint;
        if(!p.manual.answerName.isEmpty())p.name=p.manual.answerName;
        p.manual.answerPending=false;
        p.manual.connectDeadline=monotonicNanos()+45000000000LL;
        manualSetState(p,ExchangeState::Connecting,QStringLiteral("接続しています"));
        return {};
    }
    /// Promotes a replacement candidate once it is genuinely connected. The
    /// previously established transport is only dropped at that point.
    void manualPromoteIfReady(Peer& p) {
        if(!p.candidate||p.candidate->aggregateLinkState()!=LinkState::Connected)return;
        if(p.transport){
            if(p.producing){p.transport->close();p.candidate->inheritProducerHistory(*p.transport);}
            else {p.retiring=std::move(p.transport);p.retireAt=monotonicNanos()+500000000LL;}
        }
        p.transport=std::move(p.candidate);p.serial=p.candidateSerial;
        p.candidate.reset();p.candidateSerial=0;
        // The new link starts from a clean handshake; the peer id, approval and
        // authenticated fingerprint are deliberately preserved.
        p.hello=false;p.producing=false;p.lastControlAt=monotonicNanos();p.pending.clear();
        queue(p,"peer.hello",{{"fingerprint",fingerprint()},{"displayName",displayName}});
        if(hosting)queue(p,"session.snapshot",wireState());
        if(!hosting&&(auth.owner==auth.local||auth.next==auth.local))sendManifest(p);
        p.manual.collectDeadline=0;p.manual.connectDeadline=0;
        manualSetState(p,ExchangeState::Connected,QStringLiteral("接続しました"));
    }
    void manualLinkChanged(Peer& p,quint64 serial,LinkState state) {
        if(!manual)return;
        if(serial==p.candidateSerial){if(state==LinkState::Connected)manualPromoteIfReady(p);
            else if(state==LinkState::Failed)manualSetState(p,ExchangeState::NeedsExchange,QStringLiteral("再接続できませんでした。接続情報を作り直してください"),QStringLiteral("candidate_failed"));
            return;}
        if(serial!=p.serial||p.candidate||exchangeStateTerminal(p.manual.state))return;
        if(state==LinkState::Connected&&p.transport->aggregateLinkState()==LinkState::Connected){p.manual.connectDeadline=0;p.manual.retries=0;manualSetState(p,ExchangeState::Connected,QStringLiteral("接続しました"));}
        else if(state==LinkState::Disconnected){
            // A transient outage is not a manual re-exchange. The performer,
            // the epoch and the authorisation all stay exactly as they are.
            if(!p.candidate&&!exchangeStateTerminal(p.manual.state))manualSetState(p,ExchangeState::Interrupted,QStringLiteral("接続が不安定です。復旧を待っています"),QStringLiteral("interrupted"));
        }
        else if(state==LinkState::Failed)manualSetState(p,ExchangeState::NeedsExchange,QStringLiteral("接続が切れました。接続情報を作り直してください"),QStringLiteral("link_failed"));
    }
    /// Signed offline notice. Without a channel to the other end, the only
    /// honest option is a transferable packet the user delivers by hand.
    QString manualBuildNotice(Peer& p,const QString& reason,const QString& text) {
        if(!hosting)return QStringLiteral("通知はホストだけが発行できます");
        ExchangePacket packet;packet.kind=ExchangeKind::Notice;
        auto failure=manualPacketBase(p,packet);if(!failure.isEmpty())return failure;
        packet.noticeReason=reason;packet.noticeText=text.left(200);
        packet.expiresAt=QDateTime::currentMSecsSinceEpoch()+7LL*24*3600*1000;
        failure=manualSign(packet);if(!failure.isEmpty())return failure;
        const auto encoded=encodeExchangePacket(packet,&failure);if(encoded.isEmpty())return failure;
        p.manual.noticeText=encoded;return {};
    }
    QJsonObject manualExchangeJson(const Peer& p) const {
        QJsonObject value{{"state",exchangeStateName(p.manual.state)},{"waitingFor",p.manual.waitingFor}};
        if(!p.manual.detail.isEmpty())value["detail"]=p.manual.detail;
        if(!p.manual.errorCode.isEmpty())value["errorCode"]=p.manual.errorCode;
        if(!p.manual.inviteText.isEmpty())value["inviteText"]=p.manual.inviteText;
        if(!p.manual.noticeText.isEmpty())value["noticeText"]=p.manual.noticeText;
        if(!p.manual.inviteId.isEmpty())value["inviteId"]=p.manual.inviteId;
        if(p.manual.expiresAt)value["expiresAt"]=double(p.manual.expiresAt);
        if(p.manual.attempt)value["attempt"]=double(p.manual.attempt);
        const auto* transport=p.candidate?p.candidate.get():p.transport.get();
        if(transport&&p.manual.state==ExchangeState::Connected)
            value["route"]=transport->selectedRelay(false)||transport->selectedRelay(true)
                ?(transport->selectedRelay(false)&&transport->selectedRelay(true)?QStringLiteral("relay"):QStringLiteral("mixed"))
                :QStringLiteral("direct");
        else value["route"]=QStringLiteral("unknown");
        return value;
    }
    void discardAttempt(Peer& p) {
        if(p.candidate){p.candidateSerial=0;p.candidate.reset();}
        else if(p.transport&&p.transport->aggregateLinkState()!=LinkState::Connected){p.serial=0;p.transport.reset();p.hello=false;p.pending.clear();}
        p.manual.collectDeadline=0;p.manual.connectDeadline=0;p.manual.clearArtifacts();
    }
    QString acceptManualInvite(const ExchangePacket& packet,bool initial) {
        if(packet.kind!=ExchangeKind::Invite)return "ホストから届いた招待を取り込んでください";
        if(!initial&&(packet.sessionId!=auth.sessionId||packet.peerId!=auth.local||packet.hostPeerId!=auth.host||packet.hostFingerprint!=pinnedHostFingerprint))return "別のセッション・参加者への招待です";
        QString failure;
        if(!verifyExchangeSignature(packet,initial?packet.hostFingerprint:pinnedHostFingerprint,&failure))return failure;
        if(initial){
            auth.sessionId=packet.sessionId;auth.local=packet.peerId;auth.host=packet.hostPeerId;auth.owner=auth.host;
            name=packet.sessionName;pinnedHostFingerprint=packet.hostFingerprint;audible.store(false);connection="pending";
            auto peer=std::make_unique<Peer>();peer->id=auth.host;peer->name=packet.hostName;peer->fp=packet.hostFingerprint;peer->approved=true;peers[auth.host]=std::move(peer);
        }
        auto& peer=*peers.at(auth.host);
        if(!initial&&packet.generation<=peer.manual.generation)return "取り込み済み、または古い招待です。ホストから新しい招待を受け取ってください";
        peer.manual.inviteId=packet.inviteId;peer.manual.generation=packet.generation;peer.manual.attempt=packet.attempt;peer.manual.expiresAt=packet.expiresAt;
        // The host supplies only bounded, expiring TURN credentials. Local STUN
        // may supplement them but a guest's saved TURN is not redistributed.
        QJsonArray servers=packet.iceServers;
        const auto local=network.credentials(auth.sessionId,auth.local,QDateTime::currentMSecsSinceEpoch());
        for(const auto& item:local)servers.append(item);
        failure=manualStartAttempt(peer,false,servers);if(!failure.isEmpty())return failure;
        auto* transport=attemptSlot(peer);
        for(int i=0;i<2;++i)if(!transport->remoteDescription(i==1,packet.description[i].sdp,packet.description[i].type,pinnedHostFingerprint,&failure)){discardAttempt(peer);manualSetState(peer,ExchangeState::Failed,failure);return failure;}
        return {};
    }
    QJsonObject testNetwork(bool start) {
        if(networkProbe){
            if(networkProbe->readyForManualExport()){
                const bool relay=networkProbe->aggregatedDescription(false).contains(" typ relay")&&networkProbe->aggregatedDescription(true).contains(" typ relay");
                networkTestResult={{"state",relay?"success":"failure"},{"detail",relay?"中継用の接続先を取得できました。相手との接続成立は招待・返答の交換後に確認します":"中継用の接続先を取得できませんでした。URL・資格情報と回線を確認してください"}};
                networkProbe.reset();networkTestDeadline=0;
            }else if(monotonicNanos()>=networkTestDeadline){networkProbe.reset();networkTestDeadline=0;networkTestResult={{"state","timeout"},{"detail","30秒以内に中継用の接続先を取得できませんでした"}};}
            return networkTestResult;
        }
        if(!start)return networkTestResult;
        QString failure;auto servers=network.credentials(secureRandomHex(16),secureRandomHex(16),QDateTime::currentMSecsSinceEpoch(),&failure);
        bool hasTurn=false;for(const auto& v:servers)hasTurn|=v.toObject().contains("credential");
        if(!hasTurn)return {{"state","failure"},{"detail",failure.isEmpty()?QStringLiteral("中継設定を適用してからテストしてください"):failure}};
        networkProbe=std::make_unique<MediaTransport>(secureRandomHex(16),iceServerUrls(servers),MediaTransport::Callbacks{},nullptr,true);
        if(!networkProbe->start(true,&failure)){networkProbe.reset();return {{"state","failure"},{"detail",failure}};}
        networkTestDeadline=monotonicNanos()+30000000000LL;
        networkTestResult={{"state","checking"},{"detail","中継用の接続先を収集しています"}};return networkTestResult;
    }
    /// Deadlines and expiry for every manual attempt. Runs from the session
    /// tick so one peer's timeout never touches another's.
    void manualTick() {
        if(!manual)return;
        const auto nowNanos=monotonicNanos(),nowMs=QDateTime::currentMSecsSinceEpoch();
        for(auto& [id,p]:peers){
            auto& attempt=p->manual;
            if(p->retiring){if(hosting)route(p->retiring->decodedRing(),id);if(nowNanos>=p->retireAt)p->retiring.reset();}
            if(attempt.state==ExchangeState::Connected&&p->lastControlAt&&nowNanos-p->lastControlAt>3000000000LL){manualSetState(*p,ExchangeState::Interrupted,"通信が途切れています。15秒間、同じ接続の復旧を待ちます");attempt.connectDeadline=nowNanos+15000000000LL;}
            if(p->candidate)manualPromoteIfReady(*p);
            if(attempt.collectDeadline&&nowNanos>=attempt.collectDeadline){
                discardAttempt(*p);
                manualSetState(*p,ExchangeState::Failed,QStringLiteral("接続情報を作成できませんでした。ネットワーク設定を確認して、もう一度お試しください"),QStringLiteral("gathering_timeout"));
            }
            if(attempt.state==ExchangeState::Connecting&&attempt.connectDeadline&&nowNanos>=attempt.connectDeadline){
                attempt.connectDeadline=0;
                if(attempt.state==ExchangeState::Connecting){discardAttempt(*p);
                    manualSetState(*p,ExchangeState::NeedsExchange,QStringLiteral("時間内に接続できませんでした。接続情報を作り直してください"),QStringLiteral("connect_timeout"));}
            }
            const bool waiting=attempt.state==ExchangeState::InviteReady||attempt.state==ExchangeState::ResponseReady
                ||attempt.state==ExchangeState::AwaitingHost||attempt.state==ExchangeState::ApprovalPending;
            if(attempt.state==ExchangeState::Interrupted){if(!attempt.connectDeadline)attempt.connectDeadline=nowNanos+15000000000LL;else if(nowNanos>=attempt.connectDeadline){discardAttempt(*p);manualSetState(*p,ExchangeState::NeedsExchange,"接続が戻りません。ホストから新しい接続情報を受け取ってください");}}
            if(waiting&&attempt.expiresAt&&nowMs>=attempt.expiresAt){
                discardAttempt(*p);
                manualSetState(*p,ExchangeState::Expired,QStringLiteral("接続情報の期限が切れました。作り直してください"),QStringLiteral("expired"));
            }
        }
    }
    QJsonObject wireState() const {auto s=publicState(true);s.remove("invite");s.remove("privatePreview");s.remove("program");s["timelineOriginNanos"]=QString::number(timeline.originNanos());s["timelineOriginFrame"]=u64(timeline.originFrame());s["programDelayFrames"]=int(delay);s["engineFingerprint"]=fingerprint();if(auth.committed)s["commit"]=auth.committed->toJson();return s;}
    void sendManifest(Peer& p) {
        if(p.producing)return;
        p.producing=true;
        StreamManifest m{secureRandomHex(12),auth.local,captureEpoch.load(),captureGeneration.load(),0,1,0};
        p.transport->enableAutomaticManifest(true);p.transport->setSendManifest(m);p.transport->startProducer(&tap.networkRing());tap.enable(true,true);captureEnabled.store(true);
    }
    void control(const QString& id,const QByteArray& bytes) {
        auto i=peers.find(id);if(i==peers.end())return;auto& p=*i->second;
        Envelope envelope;auto decoded=decodeEnvelopeBytes(bytes,&envelope,id);if(!decoded.ok())return;
        if(!hosting && auth.sessionId=="pending" && id==auth.host && envelope.type==MessageType::SessionSnapshot)auth.sessionId=envelope.sessionId;
        if(envelope.sessionId!=auth.sessionId)return;
        p.lastControlAt=monotonicNanos();
        if(manual&&p.manual.state==ExchangeState::Interrupted&&p.transport&&p.transport->aggregateLinkState()==LinkState::Connected){p.manual.connectDeadline=0;manualSetState(p,ExchangeState::Connected,"通信が復旧しました");}
        const auto payload=envelope.payload;
        if(envelope.type==MessageType::SessionSnapshot && payload["engineFingerprint"]!=fingerprint()){fail("エンジンのバージョンが一致しません");return;}
        if(!p.hello && envelope.type!=MessageType::PeerHello && envelope.type!=MessageType::SessionSnapshot)return;
        if(envelope.type==MessageType::PeerHello){if(payload["fingerprint"]!=fingerprint()){p.hello=false;if(manual){discardAttempt(p);manualSetState(p,ExchangeState::Failed,"エンジンのバージョンが一致しません。両方のアプリを更新してください","version_mismatch");}else fail("エンジンのバージョンが一致しません");return;}const bool firstHello=!p.hello;p.hello=true;if(firstHello)queue(p,"peer.hello",{{"fingerprint",fingerprint()},{"displayName",displayName}});p.name=payload.contains("displayName")?sanitizeDisplayName(payload["displayName"].toString()):p.name;if(!manual||p.transport->aggregateLinkState()==LinkState::Connected)connection="connected";
            if(payload["stream"].isObject()){auto m=readStream(payload["stream"].toObject());if(m && m->producerPeerId==id && (id==auth.owner || id==auth.next) && (m->epoch==auth.epoch || (auth.committed&&m->epoch==auth.committed->newEpoch))){p.transport->setReceiveManifest(*m);queue(p,"peer.hello",{{"fingerprint",fingerprint()},{"streamAck",m->streamId}});}}
            else if(payload["streamAck"].isString())p.transport->acknowledgeSendManifest(payload["streamAck"].toString());
            else if(!hosting && (auth.owner==auth.local || auth.next==auth.local))sendManifest(p);
        } else if(envelope.type==MessageType::SessionSnapshot && id==auth.host && !hosting) {
            const auto epoch=parseU64(payload["epoch"]);if(!epoch||*epoch<auth.epoch)return;
            if(payload["commit"].isObject()&&!auth.committed){
                auto commit=HandoffCommitMessage::fromJson(payload["commit"].toObject());
                if(commit&&commit->sessionId==auth.sessionId&&commit->newEpoch>auth.epoch){
                    auth.epoch=commit->oldEpoch;auth.owner=commit->oldOwner;auth.next=commit->newOwner;auth.phase="fenced";auth.handoffId=commit->handoffId;auth.fenceFrame=commit->fencedAtMediaFrame;auth.throughSeq=commit->lastAppliedSeq;
                    if(auth.commit(*commit,id).isEmpty()){scheduleCaptureCommit(*commit);auth.advance(now());}
                }
            }
            if(manual&&auth.phase=="recovery"&&payload["handoffState"]=="playing"){problem.clear();reasons.clear();}
            if(!auth.committed){auth.epoch=*epoch;auth.owner=payload["performerPeerId"].toString();auth.next=payload["nextPeerId"].toString();auth.phase=payload["handoffState"].toString();auth.handoffId=payload["handoffId"].toString();}
            name=payload["sessionName"].toString();if(payload["participants"].toArray().size()<=8)participantRoster=payload["participants"].toArray();
            bool valid=false;const auto t0=payload["timelineOriginNanos"].toString().toLongLong(&valid);auto f0=parseU64(payload["timelineOriginFrame"]);if(valid&&f0)timeline.adopt(t0,*f0);
            if(!p.hello)queue(p,"peer.hello",{{"fingerprint",fingerprint()},{"displayName",displayName}});if(!captureEnabled.load())captureEpoch.store(auth.epoch);audible.store(auth.owner==auth.local);++auth.revision;
        } else if(envelope.type==MessageType::ClockProbeRequest) {queue(p,"clock.reply",{{"t1",payload["t1"]},{"t2",QString::number(monotonicNanos())},{"t3",QString::number(monotonicNanos())}});}
        else if(envelope.type==MessageType::ClockProbeReply && id==auth.host) {bool a,b,c;auto t1=payload["t1"].toString().toLongLong(&a),t2=payload["t2"].toString().toLongLong(&b),t3=payload["t3"].toString().toLongLong(&c);if(a&&b&&c){clock.add({t1,t2,t3,monotonicNanos()});timelineAnchor.store(clock.toLocalNanos(timeline.originNanos()));}}
        else if(envelope.type==MessageType::HandoffRequest && hosting && p.approved){const auto target=payload["targetPeerId"].toString(id);auto it=peers.find(target);if(target!=auth.local && (it==peers.end() || !it->second->approved))return;auto error=auth.prepare(target);if(!error.isEmpty()){fail(error);return;}resetPreparation();broadcast("handoff.prepare",{{"targetPeerId",target},{"handoffId",auth.handoffId}});if(auth.owner==auth.local)startExport();}
        else if(envelope.type==MessageType::HandoffPrepare && id==auth.host) {auth.next=payload["targetPeerId"].toString();auth.handoffId=payload["handoffId"].toString();auth.phase="preparing";resetPreparation();if(auth.owner==auth.local)startExport();if(auth.next==auth.local){captureEpoch.store(auth.epoch);sendManifest(p);}}
        else if(envelope.type==MessageType::GraphApplied && (id==auth.owner||id==auth.host) && auth.phase=="preparing"){
            ready=false;reasons={"演奏の変更に同期しています"};if(auth.next==auth.local)prepared=false;
            if(hosting)broadcast("graph.applied",payload);
        }
        else if(envelope.type==MessageType::GraphManifest && (id==auth.owner||id==auth.host) && payload["handoffId"]==auth.handoffId){
            const auto hash=payload["assetId"].toString();const auto size=parseU64(payload["sizeBytes"]);
            if(!validHexDigest(hash,32)||!size||*size>8*1024*1024)return;
            pendingGraphAsset=hash;assetKinds[hash]="junction-graph-v1";preserveWarmGraph=prepared&&aligned&&auth.phase=="fenced"&&payload["throughSeq"]==preparedGraph["throughSeq"];prepared=false;ready=false;if(!preserveWarmGraph)aligned=false;
            if(hosting&&auth.next!=auth.local){auto next=peers.find(auth.next);if(next!=peers.end())queue(*next->second,"graph.manifest",payload);}
            const auto cached=cache.resolve(hash);if(!cached.isEmpty()){assets[hash]=cached;assetReceived(hash);}
            else if(!requestedAssets.contains(hash)){requestedAssets.insert(hash);queue(p,"asset.request",{{"assetId",hash}});}
        }
        else if(envelope.type==MessageType::GraphCheckpoint && (id==auth.owner || id==auth.host)) {preparedGraph=payload["graph"].toObject();prepared=false;aligned=false;ready=false;if(hosting && auth.next!=auth.local){auto n=peers.find(auth.next);if(n!=peers.end())queue(*n->second,"graph.checkpoint",payload);}if(auth.next==auth.local || hosting)requestAssets(p);}
        else if(envelope.type==MessageType::AssetRequest) {auto hash=payload["assetId"].toString();if(!validHexDigest(hash,32))return;auto asset=assets.find(hash);if(asset==assets.end()){
                if(hosting && id!=auth.owner && (hash==pendingGraphAsset||references(graph).contains(hash)||references(preparedGraph).contains(hash)) && assetWaiters.size()<128){
                    assetWaiters[hash].insert(id);auto owner=peers.find(auth.owner);
                    if(owner!=peers.end()&&!requestedAssets.contains(hash)){requestedAssets.insert(hash);queue(*owner->second,"asset.request",{{"assetId",hash}});}
                }return;
            }if(payload["receiverReady"].toBool()){bool queued=false;for(const auto& job:outgoing)if(job.peer==id&&job.hash==hash){queued=true;break;}if(!queued&&outgoing.size()<256)outgoing.enqueue({id,hash,asset->second,0});}else queue(p,"asset.manifest",{{"assetId",hash},{"sizeBytes",u64(quint64(QFileInfo(asset->second).size()))}});}
        else if(envelope.type==MessageType::AssetManifest && (id==auth.owner||id==auth.host)){const auto hash=payload["assetId"].toString();const auto size=parseU64(payload["sizeBytes"]);QString error;if(size&&requestedAssets.contains(hash)){if(!cache.begin(hash,*size,&error))fail(error);else queue(p,"asset.request",{{"assetId",hash},{"receiverReady",true}});}}
        else if(envelope.type==MessageType::AssetComplete && (id==auth.owner||id==auth.host)){finishAsset(payload["assetId"].toString());}
        else if(envelope.type==MessageType::HandoffCancel && id==auth.host && payload["handoffId"].toString()==auth.handoffId){if(auth.cancel().isEmpty()){prepared=false;ready=false;audible.store(auth.owner==auth.local);}}
        else if(envelope.type==MessageType::HandoffReady && hosting && id==auth.next && payload["handoffId"]==auth.handoffId){
            if(payload["requestFence"].toBool()){QString failure;q->command("handoff.accept",{},&failure);if(!failure.isEmpty())fail(failure);return;}
            ready=payload["ready"].toBool();reasons.clear();if(!ready)reasons.append(payload["reason"].toString());
            if(ready&&auth.phase=="fenced"&&payload["stage"]=="fenced"&&parseU64(payload["throughSeq"])==std::optional<quint64>(auth.throughSeq)&&!validationStart){beginValidation(now()+24000);requestValidationCapture(validationStart);}
        }
        else if(envelope.type==MessageType::HandoffFence && id==auth.host && payload["handoffId"]==auth.handoffId){auto frame=parseU64(payload["frame"]);if(frame&&auth.phase=="preparing"){auth.fence(*frame,controlSeq);finalCheckpoint=false;fenceDeadline=monotonicNanos()+6000000000LL;ready=false;}}
        else if(envelope.type==MessageType::HandoffFenced && (id==auth.owner || id==auth.host) && payload["handoffId"]==auth.handoffId){auto frame=parseU64(payload["fencedAtMediaFrame"]),seq=parseU64(payload["lastAppliedSeq"]);if(frame&&seq&&auth.phase=="fenced"){auth.fenceFrame=*frame;auth.throughSeq=*seq;if(hosting)broadcast("handoff.fenced",payload);}}
        else if(envelope.type==MessageType::ValidationWindow){
            if(payload["stage"]=="received" && id==auth.host && payload["payloadSha256"]==validationAwaitingAck){validationAwaitingAck.clear();}
            else if(payload["stage"]=="align"&&id==auth.host&&auth.next==auth.local&&payload["handoffId"]==auth.handoffId){
                auto start=parseU64(payload["startMediaFrame"]);const int lag=payload["lagFrames"].toInt(1000);if(start&&std::abs(lag)<=256&&auth.phase=="fenced")alignValidation(lag,*start);
            }
            else if(payload["stage"]=="capture" && id==auth.host && payload["handoffId"]==auth.handoffId){auto start=parseU64(payload["startMediaFrame"]);if(start&&*start>now()&&*start-now()<=480000)beginValidation(*start);}
            else if(hosting && (id==auth.owner||id==auth.next) && payload["handoffId"]==auth.handoffId && payload["sampleRateHz"]==48000 && payload["channels"]==2 && parseU64(payload["startMediaFrame"])==std::optional<quint64>(validationStart)){
                int count=payload["frameCount"].toInt();auto hash=payload["payloadSha256"].toString();if(count==12000&&validHexDigest(hash,32)&&validationReceiving.size()<4){validationReceiving.emplace(hash,ValidationReceive{id,QByteArray(count*8,0),std::vector<bool>(size_t((count*8+32767)/32768),false)});queue(p,"validation.window",{{"stage","received"},{"payloadSha256",hash},{"handoffId",auth.handoffId}});}
            }
        }
        else if(envelope.type==MessageType::HandoffCommit && id==auth.host){auto commit=HandoffCommitMessage::fromJson(payload);if(commit){auto failure=applyCommit(*commit,id);if(!failure.isEmpty())fail(failure);else scheduleCaptureCommit(*commit);}}

        else if(envelope.type==MessageType::SessionRecovery&&id==auth.host){
            if(manual&&payload["stage"]=="active"&&auth.owner==auth.local&&!auth.committed){q->setCaptureAnchor(lastCaptureSourceEnd.load(),now());captureEnabled.store(true);sendManifest(p);}
            if(payload["stage"]=="scheduled"){auto frame=parseU64(payload["frame"]),epoch=parseU64(payload["epoch"]);if(frame&&epoch&&*epoch>auth.epoch){recoveryResumeFrame=*frame;recoveryEpoch=*epoch;}}
            auth.phase="recovery";fail(payload["reason"].toString("配信を復旧中です"));
        }
        else if(envelope.type==MessageType::SessionEnd){
            if(hosting&&endingAt&&payload["ack"].toBool())p.endingAck=true;
            else if(id==auth.host&&!hosting){queue(p,"session.end",{{"ack",true}});connection="closing";endingAt=monotonicNanos()+200000000LL;}
        }
        else if(envelope.type==MessageType::PeerLeave){if(id==auth.owner)beginRecovery("プレイ担当者が退出しました");peers.erase(id);}
    }
    bool validateAsset(const QString& hash,const QString& path) const {
        auto kind=assetKinds.find(hash);
        if(kind!=assetKinds.end()&&kind->second=="junction-graph-v1"){
            QFile file(path);if(file.size()>8*1024*1024||!file.open(QIODevice::ReadOnly))return false;
            const auto object=QJsonDocument::fromJson(file.readAll()).object();return object["schema"]==1&&object["decks"].toArray().size()==4;
        }
        if(kind!=assetKinds.end()&&(kind->second=="plumdeck-ddj-dsp-v1"||kind->second=="plumdeck-keylock-v1"||kind->second=="plumdeck-fx-v1"))return backend->validateDspAsset(path);
        SF_INFO info{};auto* f=openSoundFile(path,SFM_READ,&info);if(f)sf_close(f);return f!=nullptr;
    }
    void sendGraph(Peer& peer,const QJsonObject& value) {
        const auto bytes=json(value);if(bytes.size()>8*1024*1024){fail("演奏状態が転送上限を超えています");return;}
        const auto hash=sha256Hex(bytes),path=identityDir.path()+"/"+hash+".graph";
        if(assets.count(hash)==0){QSaveFile file(path);if(!file.open(QIODevice::WriteOnly)||file.write(bytes)!=bytes.size()||!file.commit()){fail("演奏状態を準備できません");return;}assets[hash]=path;}
        assetKinds[hash]="junction-graph-v1";
        queue(peer,"graph.manifest",{{"assetId",hash},{"sizeBytes",u64(quint64(bytes.size()))},{"throughSeq",value["throughSeq"]},{"handoffId",auth.handoffId}});
    }
    static QSet<QString> references(const QJsonValue& value){
        QSet<QString> result;
        std::function<void(const QJsonValue&)> visit=[&](const QJsonValue& v){
            if(v.isArray()){for(const auto& x:v.toArray())visit(x);return;}
            if(!v.isObject())return;const auto object=v.toObject();const auto hash=object["assetId"].toString();if(validHexDigest(hash,32))result.insert(hash);
            for(auto it=object.begin();it!=object.end();++it)visit(it.value());
        };visit(value);return result;
    }
    // Only our immutable transfer capsules are removed. User audio and the
    // graph currently loaded in the engine retain their separate lifetimes.
    void pruneCapsules(){
        if(exportJob.valid())return;
        auto keep=references(graph)|references(preparedGraph)|requestedAssets|pinnedAssets;
        keep.insert(pendingGraphAsset);for(const auto& job:outgoing)keep.insert(job.hash);
        for(const auto& [hash,waiters]:assetWaiters)keep.insert(hash);
        const auto cutoff=QDateTime::currentDateTimeUtc().addSecs(-120);
        const QDir directory(identityDir.path());
        for(const auto& file:directory.entryInfoList({"*.dsp","*.graph"},QDir::Files)){
            const auto hash=file.completeBaseName();
            if(!validHexDigest(hash,32)||file.isSymLink()||file.lastModified()>cutoff||keep.contains(hash))continue;
            if(QFile::remove(file.absoluteFilePath())){assets.erase(hash);assetKinds.erase(hash);}
        }
        // Eviction may have removed unpinned cache entries. Never advertise a
        // stale file path as an available source in a later handoff.
        for(auto it=assets.begin();it!=assets.end();)if(!keep.contains(it->first)&&!QFileInfo::exists(it->second)){assetKinds.erase(it->first);it=assets.erase(it);}else ++it;
    }
    void resetPreparation(){
        prepared=false;aligned=false;ready=false;finalCheckpoint=false;preserveWarmGraph=false;graphDirty=false;
        graph={};preparedGraph={};pendingGraphAsset.clear();validationRound=0;validationStart=0;validationCapture.cancel();validationReceiving.clear();validationOutgoing.clear();validationPcm.clear();fenceDeadline=0;
        reasons={"音源と演奏状態を準備しています"};
    }
    void startExport() {
        if(exportJob.valid())return;
        pruneCapsules();
        quint64 temporaryBytes=0;for(const auto& file:QDir(identityDir.path()).entryInfoList({"*.dsp","*.graph"},QDir::Files))temporaryBytes+=quint64(file.size());
        if(temporaryBytes>512ULL*1024*1024){fail("一時的な転送データが上限に達しました。準備を取り消し、しばらくしてから再試行してください");return;}
        auto local=backend->junctionGraph();if(local.isEmpty())return;bool renderValid=false;const auto render=local["renderFrame"].toString().toULongLong(&renderValid);local["atMediaFrame"]=u64(renderValid?q->mediaFrameForSource(render):now());if(!local.contains("throughSeq"))local["throughSeq"]=u64(controlSeq);exportRevision=auth.revision;exportHandoff=auth.handoffId;
        const auto transferDirectory=identityDir.path();
        exportJob=std::async(std::launch::async,[local,transferDirectory]()mutable{
            std::map<QString,QString> paths;
            std::function<QJsonValue(QJsonValue)> visit=[&](QJsonValue v)->QJsonValue{
                if(v.isArray()){QJsonArray a;for(const auto& x:v.toArray())a.append(visit(x));return a;}
                if(!v.isObject())return v;
                auto o=v.toObject();
                if(o.contains("path")){auto path=o.take("path").toString();if(!path.isEmpty()){auto hash=AssetCache::hashFile(path);if(!hash.isEmpty()){
                    // The backend reuses its checkpoint slot. Keep an immutable,
                    // content-addressed copy for outstanding peer transfers.
                    if(o["format"]=="plumdeck-ddj-dsp-v1"||o["format"]=="plumdeck-keylock-v1"||o["format"]=="plumdeck-fx-v1"){
                        const auto stable=transferDirectory+"/"+hash+".dsp";
                        if(!QFileInfo::exists(stable)&&!QFile::copy(path,stable)){o["assetError"]="DSP状態を保存できません";return o;}
                        path=stable;
                    }
                    paths[hash]=path;o["assetId"]=hash;
                }else o["assetError"]="音源を読み込めません";}o.remove("trackId");o.remove("localTrackId");}
                for(auto it=o.begin();it!=o.end();++it)it.value()=visit(it.value());
                return o;
            };
            return std::make_pair(visit(local).toObject(),paths);
        });
    }
    void requestAssets(Peer& source) {
        std::function<void(QJsonValue)> walk=[&](QJsonValue v){if(v.isArray()){for(const auto& x:v.toArray())walk(x);return;}if(!v.isObject())return;auto o=v.toObject();auto hash=o["assetId"].toString();if(o["format"]=="plumdeck-ddj-dsp-v1"||o["format"]=="plumdeck-keylock-v1"||o["format"]=="plumdeck-fx-v1")assetKinds[hash]=o["format"].toString();if(!hash.isEmpty() && assets.find(hash)==assets.end()){auto path=cache.resolve(hash);if(path.isEmpty()){if(!requestedAssets.contains(hash)){requestedAssets.insert(hash);queue(source,"asset.request",{{"assetId",hash}});}}else assets[hash]=path;}for(auto it=o.begin();it!=o.end();++it)walk(it.value());};walk(preparedGraph);tryPrepare();
    }
    void tryPrepare() {
        if(preparedGraph.isEmpty() || prepared || auth.next!=auth.local)return;
        bool missing=false;std::function<QJsonValue(QJsonValue)> visit=[&](QJsonValue v)->QJsonValue{if(v.isArray()){QJsonArray a;for(const auto& x:v.toArray())a.append(visit(x));return a;}if(!v.isObject())return v;auto o=v.toObject();o.remove("path");auto hash=o["assetId"].toString();if(!hash.isEmpty()){auto it=assets.find(hash);if(it==assets.end())missing=true;else{o["path"]=it->second;}}for(auto it=o.begin();it!=o.end();++it)if(it.key()!="path")it.value()=visit(it.value());return o;};
        auto local=visit(preparedGraph).toObject();if(missing){reasons={"音源を受信しています"};return;}
        const auto nextPins=references(preparedGraph);for(const auto& hash:nextPins)cache.pin(hash,true);
        const auto error=backend->restoreJunctionGraph(local);if(!error.isEmpty()){for(const auto& hash:nextPins-pinnedAssets)cache.pin(hash,false);fail(error);return;}
        for(const auto& hash:pinnedAssets-nextPins)cache.pin(hash,false);pinnedAssets=nextPins;
        prepared=true;aligned=false;reasons={"音声の位置と状態を確認しています"};
    }
    void bulk(const QString& id,const QByteArray& bytes) {
        if(bytes.size()<72 || bytes.size()>72+32768 || (id!=auth.owner && id!=auth.host))return;
        auto hash=QString::fromLatin1(bytes.constData(),64);quint64 offset=0;for(int n=64;n<72;++n)offset=(offset<<8)|quint8(bytes[n]);QString error;
        if(!cache.put(hash,offset,bytes.mid(72),&error)){fail(error);return;}
        // Completion is tested after each chunk: bulk and reliable control are
        // separate connections, so their arrival order is deliberately free.
        finishAsset(hash);
    }
    void finishAsset(const QString& hash){
        const auto bitmap=cache.receivedBitmap(hash);if(bitmap.isEmpty()||bitmap.contains(char(0)))return;
        QString failure;if(cache.finalize(hash,[this,hash](const QString& path){return validateAsset(hash,path);},&failure))assetReceived(hash);else fail(failure);
    }
    void assetReceived(const QString& hash) {
        assets[hash]=cache.resolve(hash);requestedAssets.remove(hash);
        auto waiters=assetWaiters.find(hash);if(waiters!=assetWaiters.end()){
            for(const auto& id:waiters->second){auto p=peers.find(id);if(p!=peers.end())queue(*p->second,"asset.manifest",{{"assetId",hash},{"sizeBytes",u64(quint64(QFileInfo(assets[hash]).size()))}});}
            assetWaiters.erase(waiters);
        }
        if(hash==pendingGraphAsset){
            QFile file(assets[hash]);if(!file.open(QIODevice::ReadOnly)||file.size()>8*1024*1024){fail("演奏状態を読み込めません");return;}
            preparedGraph=QJsonDocument::fromJson(file.readAll()).object();pendingGraphAsset.clear();
            if(preserveWarmGraph){prepared=true;preserveWarmGraph=false;return;}
            auto source=peers.find(hosting?auth.owner:auth.host);if(source!=peers.end())requestAssets(*source->second);
        }
        tryPrepare();
    }
    void pumpAssets() {
        if(outgoing.isEmpty())return;
        auto& job=outgoing.head();auto peer=peers.find(job.peer);if(peer==peers.end()||!peer->second->transport){outgoing.dequeue();return;}
        QFile f(job.path);if(!f.open(QIODevice::ReadOnly)){outgoing.dequeue();fail("転送元の音源を開けません");return;}
        f.seek(qint64(job.offset));auto bytes=f.read(32768);
        if(bytes.isEmpty()){queue(*peer->second,"asset.complete",{{"assetId",job.hash}});outgoing.dequeue();return;}
        QByteArray packet=job.hash.toLatin1();for(int n=7;n>=0;--n)packet.append(char(job.offset>>(n*8)));packet+=bytes;
        if(peer->second->transport->sendBulk(packet))job.offset+=quint64(bytes.size());
    }
    void openProgram() {
        if(!hosting || programOpened)return;
        QString error;program.setTimeline(timeline.originNanos(),timeline.originFrame(),delay);
        if(program.open(programDevice,&error)){
            programOpened=true;programState="running";separateLocalMaster.store(true);
            const auto localName=backend->audio()["deviceId"].toString();
            for(const auto& v:backend->audioDevices()["devices"].toArray()){const auto device=v.toObject();if(device["id"].toString().section(':',-1)==QString::number(programDevice)&&device["name"].toString()==localName)separateLocalMaster.store(false);}
        }else {programState="error";fail(error);}
    }
    void beginRecovery(const QString& reason){
        if(auth.phase=="recovery")return;
        auth.phase="recovery";recoveryUntil=now()+48000;ready=false;validationStart=0;fail(reason);
        if(hosting){
            if(auth.committed){backupOwner=auth.committed->oldOwner;backupEpoch=auth.committed->oldEpoch;}
            for(auto& [frame,block]:backupPending)if(frame>=programEnqueuedThrough)programPending.try_emplace(frame,block);
            broadcast("session.recovery",{{"stage","active"},{"reason",reason},{"fallbackUntil",u64(recoveryUntil)}});
        }
        ++auth.revision;
    }
    void collectValidation(const float* samples,const PcmBlockInfo& info) {
        QString failure;
        if(!validationCapture.consume(info,samples,info.frameCount,&failure)&&validationStart&&!validationSent)fail(failure);
    }
    void route(PcmRing& ring,const QString& producer) {
        for(int count=0;count<8;++count){auto result=ring.popBlock(pcm.data(),4096);if(!result.frames)return;
            if(producer==auth.local)collectValidation(pcm.data(),result.info);
            if(!hosting||!programOpened)continue;
            auto info=result.info;
            if(producer==auth.owner&&info.epoch==auth.epoch){
                ownerAudioAt=monotonicNanos();
                // A returned live stream resumes its existing owner and epoch.
                // Only the explicit recovery action can select the host instead.
                if(manual&&auth.phase=="recovery"&&!auth.committed&&!recoveryResumeFrame&&info.mediaFrame+4800>=now()&&info.mediaFrame<=now()+4800){auth.phase="playing";recoveryUntil=0;problem.clear();reasons.clear();++auth.revision;broadcast("session.snapshot",wireState());}
            }
            if(auth.committed&&producer==auth.committed->oldOwner&&info.epoch==auth.committed->oldEpoch){
                backupPending.insert_or_assign(info.mediaFrame,ProgramBlock{info,std::vector<float>(pcm.data(),pcm.data()+info.frameCount*2)});
                while(backupPending.size()>384)backupPending.erase(backupPending.begin());
            }
            const auto allowed=[&](quint64 f){if(f<programEnqueuedThrough)return false;if(auth.phase=="recovery"){if(recoveryResumeFrame&&f>=recoveryResumeFrame)return producer==auth.host&&info.epoch==recoveryEpoch;return f<recoveryUntil&&producer==backupOwner&&info.epoch==backupEpoch;}if(auth.committed)return f<auth.cutoverFrame?producer==auth.committed->oldOwner&&info.epoch==auth.committed->oldEpoch:producer==auth.committed->newOwner&&info.epoch==auth.committed->newEpoch;return producer==auth.owner&&info.epoch==auth.epoch;};
            quint32 begin=0,end=info.frameCount;
            while(begin<end&&!allowed(info.mediaFrame+mediaFrameAdvance(begin,info.sampleRateHz)))++begin;
            while(end>begin&&!allowed(info.mediaFrame+mediaFrameAdvance(end-1,info.sampleRateHz)))--end;
            if(begin==end)continue;
            info.mediaFrame+=mediaFrameAdvance(begin,info.sampleRateHz);info.sourceFrame+=begin;info.frameCount=end-begin;
            if(programPending.size()<512)programPending.try_emplace(info.mediaFrame,ProgramBlock{info,std::vector<float>(pcm.data()+begin*2,pcm.data()+end*2)});
        }
    }
    void requestValidationCapture(quint64 start){
        for(auto& [id,p]:peers)if(p->approved&&(id==auth.owner||id==auth.next))queue(*p,"validation.window",{{"stage","capture"},{"startMediaFrame",u64(start)},{"handoffId",auth.handoffId}});
    }
    void beginValidation(quint64 start) {
        if(qEnvironmentVariableIsSet("PLUMDECK_JUNCTION_TRACE"))qWarning()<<"junction validation begin"<<hosting<<start<<captureEpoch.load()<<captureGeneration.load();
        validationStart=start;validationEnd=start+12000;validationId=secureRandomHex(16);validationPcm.clear();validationReceiving.clear();validationOutgoing.clear();validationAwaitingAck.clear();
        validationSent=auth.local!=auth.owner&&auth.local!=auth.next;
        if(validationSent){validationCapture.cancel();return;}
        QString failure;if(!validationCapture.begin(start,12000,captureEpoch.load(),captureGeneration.load(),&failure))fail(failure);
    }
    void finishValidation() {
        if(!validationStart||validationSent)return;
        auto window=validationCapture.take();if(!window)return;
        validationSent=true;auto wire=std::move(window->samples);
        if(qEnvironmentVariableIsSet("PLUMDECK_JUNCTION_TRACE"))qWarning()<<"junction validation complete"<<hosting<<wire.size();
        if(hosting){validationPcm[auth.local]=wire;checkValidation();return;}
        auto p=peers.find(auth.host);if(p==peers.end())return;
        QByteArray bytes(reinterpret_cast<const char*>(wire.data()),qsizetype(wire.size()*sizeof(float)));
        const auto hash=sha256Hex(bytes);queue(*p->second,"validation.window",{{"windowId",validationId},{"handoffId",auth.handoffId},{"startMediaFrame",u64(validationStart)},{"sampleRateHz",48000},{"channels",2},{"frameCount",int(wire.size()/2)},{"payloadSha256",hash}});
        validationTarget=auth.host;validationAwaitingAck=hash;
        for(int offset=0;offset<bytes.size();offset+=32768){QByteArray chunk=hash.toLatin1();for(int n=7;n>=0;--n)chunk.append(char(quint64(offset)>>(n*8)));chunk+=bytes.mid(offset,32768);validationOutgoing.enqueue(chunk);}
    }
    void validationChunk(const QString& sender,const QByteArray& chunk) {
        if(chunk.size()<72||chunk.size()>32840)return;
        auto it=validationReceiving.find(QString::fromLatin1(chunk.constData(),64));if(it==validationReceiving.end()||it->second.sender!=sender)return;
        quint64 offset=0;for(int n=64;n<72;++n)offset=(offset<<8)|quint8(chunk[n]);auto& rx=it->second;const auto size=quint64(chunk.size()-72);
        if(offset%32768||offset>=quint64(rx.bytes.size())||size!=std::min(quint64(32768),quint64(rx.bytes.size())-offset)||offset/32768>=rx.chunks.size())return;
        std::memcpy(rx.bytes.data()+offset,chunk.constData()+72,size);rx.chunks[offset/32768]=true;
        if(std::all_of(rx.chunks.begin(),rx.chunks.end(),[](bool x){return x;})){
            const bool valid=sha256Hex(rx.bytes)==it->first;
            if(valid){std::vector<float> samples(size_t(rx.bytes.size()/4));std::memcpy(samples.data(),rx.bytes.constData(),size_t(rx.bytes.size()));validationPcm[sender]=std::move(samples);}
            validationReceiving.erase(it);if(valid)checkValidation();
        }
    }
    QString applyCommit(const HandoffCommitMessage& commit,const QString& sender) {
        auto next=auth;const auto failure=next.commit(commit,sender);if(!failure.isEmpty())return failure;
        const auto directory=QStandardPaths::writableLocation(QStandardPaths::CacheLocation)+"/junction";
        if(!QDir().mkpath(directory))return "引き継ぎ状態を保存できません";
        QSaveFile file(directory+"/"+auth.sessionId+".commit");
        const auto bytes=json(commit.toJson());
        if(!file.open(QIODevice::WriteOnly)||file.write(bytes)!=bytes.size()||!file.flush()||platform_file::sync(file.handle())!=0||!file.commit())return "引き継ぎ状態を保存できません";
        auth=std::move(next);return {};
    }
    void scheduleCaptureCommit(const HandoffCommitMessage& commit) {
        if(auth.local==commit.newOwner){scheduledEpoch.store(commit.newEpoch,std::memory_order_relaxed);scheduledFrame.store(commit.effectiveMediaFrame,std::memory_order_release);}
    }
    void alignValidation(int lag,quint64 start){
        const auto source=lastCaptureSourceEnd.load(std::memory_order_acquire);
        const auto media=q->mediaFrameForSource(source);
        if(lag>0&&media<quint64(lag))return;
        q->setCaptureAnchor(source,lag>=0?media-quint64(lag):media+quint64(-lag));
        QPointer<Runtime> safe=q;const auto handoff=auth.handoffId;
        QTimer::singleShot(50,q,[safe,start,handoff]{if(safe&&safe->d->auth.phase=="fenced"&&safe->d->auth.handoffId==handoff)safe->d->beginValidation(start);});
    }
    void checkValidation() {
        if(!hosting||validationPcm.count(auth.owner)==0||validationPcm.count(auth.next)==0)return;
        const auto match=compareAudio(validationPcm[auth.owner],validationPcm[auth.next]);
        if(qEnvironmentVariableIsSet("PLUMDECK_JUNCTION_TRACE"))qWarning()<<"junction validation match"<<match.ready<<match.lagFrames<<match.correlation<<match.levelDb<<match.fractionalLagFrames;
        if(!match.ready){
            fail(QStringLiteral("音声の位置を調整中です（ずれ %1 samples）").arg(match.lagFrames));
            if(validationRound++<3){
                const bool adjust=match.correlation>=.99&&std::abs(match.levelDb)<=.25&&match.lagFrames;
                const auto start=now()+(adjust?24000:48000);
                // Finite FX tails may still be warming. Recheck a later raw
                // window under the same gate and original fence deadline.
                if(adjust&&auth.next==auth.local)alignValidation(match.lagFrames,start);
                else{
                    if(adjust){auto target=peers.find(auth.next);if(target!=peers.end())queue(*target->second,"validation.window",{{"stage","align"},{"lagFrames",match.lagFrames},{"startMediaFrame",u64(start)},{"handoffId",auth.handoffId}});}
                    beginValidation(start);
                }
                for(auto& [id,p]:peers)if((id==auth.owner||id==auth.next)&&(!adjust||id!=auth.next)&&p->approved)queue(*p,"validation.window",{{"stage","capture"},{"startMediaFrame",u64(start)},{"handoffId",auth.handoffId}});
            }
            return;
        }
        HandoffCommitMessage commit;commit.sessionId=auth.sessionId;commit.handoffId=auth.handoffId;commit.oldEpoch=auth.epoch;commit.newEpoch=auth.epoch+1;commit.oldOwner=auth.owner;commit.newOwner=auth.next;commit.effectiveMediaFrame=now()+24000;commit.fencedAtMediaFrame=auth.fenceFrame;commit.lastAppliedSeq=auth.throughSeq;commit.capsuleRevision=auth.revision;
        const auto failure=applyCommit(commit,auth.local);if(!failure.isEmpty()){fail(failure);return;}
        ownerAudioAt=monotonicNanos();scheduleCaptureCommit(commit);broadcast("handoff.commit",commit.toJson());ready=true;problem.clear();reasons.clear();
    }
    void tick() {
        ++ticks;if(networkProbe)testNetwork(false);if(auth.sessionId.isEmpty())return;
        manualTick();
#if defined(PLUMDECK_JUNCTION_WITH_LIBDATACHANNEL)
        if(turnRefreshAt&&monotonicNanos()>=turnRefreshAt&&signal&&signal->isOpen()){
            turnRefreshAt=monotonicNanos()+5000000000LL;signalSend({{"type","turn.credentials"}});
        }
        if(hosting&&reconnectAt&&monotonicNanos()>=reconnectAt){
            reconnectAt=monotonicNanos()+qint64(std::min(8u,1u<<std::min(3u,reconnectAttempts++)))*1000000000LL;
            if(signal){signal->resetCallbacks();signal->forceClose();signal.reset();}
            const auto failure=connect(true);if(!failure.isEmpty())fail(failure);
        }
#endif
        if(recoveryResumeFrame&&now()>=recoveryResumeFrame){
            auth.owner=auth.host;auth.epoch=recoveryEpoch;auth.cutoverFrame=recoveryResumeFrame;auth.phase="switching";auth.committed.reset();auth.next.clear();auth.handoffId.clear();recoveryResumeFrame=0;recoveryUntil=0;backupPending.clear();problem.clear();reasons.clear();ownerAudioAt=monotonicNanos();++auth.revision;
        }
        auth.advance(now());audible.store(auth.local==auth.owner);
        for(auto& [id,p]:peers){if(!p->transport)continue;for(int n=0;n<8&&!p->pending.isEmpty();++n){if(!p->transport->sendControl(p->pending.head()))break;p->pending.dequeue();}if(hosting)route(p->transport->decodedRing(),id);}
        if(endingAt){bool acknowledged=hosting;for(const auto& [id,p]:peers)if(p->approved&&!p->endingAck)acknowledged=false;
            if(acknowledged||monotonicNanos()>=endingAt){signalSend({{"type",endingHost?"room.close":"peer.leave"}});stop();return;}
        }
        route(tap.localRing(),auth.local);
        if(hosting&&auth.owner!=auth.local&&ownerAudioAt&&monotonicNanos()-ownerAudioAt>300000000LL&&auth.phase!="recovery"&&(!auth.committed||now()>auth.cutoverFrame+14400))beginRecovery("プレイ担当者の音声が届いていません。配信を復旧中です");
        if(ticks%20==0 && hosting)broadcast("session.snapshot",wireState());
        if(ticks%200==0){if(hosting)signalSend({{"type","host.heartbeat"}});else{auto p=peers.find(auth.host);if(p!=peers.end()&&p->second->transport)queue(*p->second,"clock.probe",{{"t1",QString::number(monotonicNanos())}});}}
        if(exportJob.valid() && exportJob.wait_for(std::chrono::seconds(0))==std::future_status::ready){auto result=exportJob.get();if(exportHandoff!=auth.handoffId)return;graph=result.first;assets.insert(result.second.begin(),result.second.end());
            if(auth.phase=="preparing"||auth.phase=="fenced"){if(hosting){if(auth.next==auth.local){preparedGraph=graph;tryPrepare();}else{auto p=peers.find(auth.next);if(p!=peers.end())sendGraph(*p->second,graph);}}else{auto p=peers.find(auth.host);if(p!=peers.end())sendGraph(*p->second,graph);}}}
        if(prepared && auth.next==auth.local && (auth.phase=="preparing"||auth.phase=="fenced") && backend->junctionGraphReady() && ticks%20==0 && (hosting||clock.ready())){
            if(!aligned){auto failure=backend->alignJunctionGraph(now());if(failure.isEmpty())aligned=true;else fail(failure);}
            else if(backend->junctionGraphReady()){
                ready=true;reasons={"最終の音声照合を待っています"};auto p=peers.find(auth.host);if(p!=peers.end())queue(*p->second,"handoff.ready",{{"ready",true},{"stage",auth.phase},{"throughSeq",preparedGraph["throughSeq"]},{"handoffId",auth.handoffId}});
                if(hosting&&auth.phase=="fenced"&&!validationStart){beginValidation(now()+24000);requestValidationCapture(validationStart);}
            }
        }
        if(auth.phase=="preparing"&&auth.owner==auth.local&&graphDirty&&monotonicNanos()-lastSharedChange>=250000000&&!exportJob.valid()){graphDirty=false;graph={};startExport();}
        if((auth.phase=="preparing"||(auth.phase=="fenced"&&finalCheckpoint))&&auth.owner==auth.local&&graph.isEmpty()&&!exportJob.valid())startExport();
        if(auth.phase=="fenced"&&auth.owner==auth.local&&now()>=auth.fenceFrame+960&&!finalCheckpoint){
            auth.throughSeq=controlSeq;finalCheckpoint=true;graph={};startExport();broadcast("handoff.fenced",{{"fencedAtMediaFrame",u64(auth.fenceFrame)},{"lastAppliedSeq",u64(controlSeq)},{"handoffId",auth.handoffId}});
        }
        if(auth.phase=="fenced"&&fenceDeadline&&monotonicNanos()>fenceDeadline){if(hosting){broadcast("handoff.cancel",{{"handoffId",auth.handoffId},{"reason","timeout"}});auth.cancel();fail("音声の照合が時間内に完了しませんでした。演奏は継続しています");}validationStart=0;}
        finishValidation();
        if(!validationOutgoing.isEmpty()&&validationAwaitingAck.isEmpty()){auto p=peers.find(validationTarget);if(p!=peers.end()&&p->second->transport&&p->second->transport->sendValidation(validationOutgoing.head()))validationOutgoing.dequeue();}
        while(!programPending.empty()&&programPending.begin()->first+delay/2<now()){
            auto it=programPending.begin();if(!program.inputRing().push(it->second.samples.data(),it->second.info))break;programEnqueuedThrough=it->second.info.mediaFrame+mediaFrameAdvance(it->second.info.frameCount,it->second.info.sampleRateHz);programPending.erase(it);
        }
        if(auth.phase=="switching"&&now()>auth.cutoverFrame+delay+48000){auth.phase="playing";backupPending.clear();backupOwner.clear();scheduledFrame.store(UINT64_MAX);scheduledEpoch.store(0);if(auth.local!=auth.owner){for(auto& [id,p]:peers)if(p->producing){p->transport->startProducer(nullptr);p->producing=false;}tap.enable(false,hosting);if(!hosting)captureEnabled.store(false);}auth.committed.reset();auth.next.clear();auth.handoffId.clear();validationStart=0;finalCheckpoint=false;ready=false;prepared=false;reasons.clear();++auth.revision;}

        if(ticks%4==0)pumpAssets();
        if(ticks%2000==0)pruneCapsules();
    }
    void stop() {
        ++signalGeneration;
#ifdef __APPLE__
        if(sleepLease!=kIOPMNullAssertionID){IOPMAssertionRelease(sleepLease);sleepLease=kIOPMNullAssertionID;}
#elif defined(_WIN32)
        SetThreadExecutionState(ES_CONTINUOUS);
#endif
        captureEnabled.store(false);tap.enable(false,false);audible.store(true);separateLocalMaster.store(true);
        peers.clear();program.close();programOpened=false;programState="stopped";
#if defined(PLUMDECK_JUNCTION_WITH_LIBDATACHANNEL)
        if(signal){signal->resetCallbacks();signal->forceClose();signal.reset();}
#endif
        endingAt=0;endingHost=false;reconnectAt=0;reconnectAttempts=0;turnRefreshAt=0;iceReady=false;iceServers.clear();deferredSignals.clear();identity.reset();manual=false;manualDetail.clear();manualErrorCode.clear();hostCertificatePem.clear();pinnedHostFingerprint.clear();participantRoster={};auth=Authority{};timeline=MediaTimeline{};clock.reset();q->setCaptureAnchor(UINT64_MAX,0);captureEpoch.store(1);scheduledFrame.store(UINT64_MAX);scheduledEpoch.store(0);sourceAnchor.store(UINT64_MAX);connection="disconnected";problem.clear();reasons.clear();invite.clear();ready=false;prepared=false;preparedGraph={};outgoing.clear();programEnqueuedThrough=0;backupPending.clear();backupOwner.clear();recoveryResumeFrame=0;recoveryUntil=0;ownerAudioAt=0;assetWaiters.clear();requestedAssets.clear();programPending.clear();validationReceiving.clear();validationOutgoing.clear();validationStart=0;validationCapture.reset();finalCheckpoint=false;aligned=false;graph={};
    }
};
Runtime::Runtime(PlaybackBackend* backend,QObject* parent):QObject(parent),d(std::make_unique<Impl>(this,backend)){}
Runtime::~Runtime(){d->stop();}
quint64 Runtime::currentAppliedSequence()const{return d->controlSeq;}
quint64 Runtime::currentMediaFrame()const{return d->now();}
void Runtime::setCaptureAnchor(quint64 source,quint64 media){
    d->pendingAnchorRevision.fetch_add(1,std::memory_order_acq_rel);d->pendingAnchorSource.store(source,std::memory_order_relaxed);d->pendingAnchorMedia.store(media,std::memory_order_relaxed);d->pendingAnchorRevision.fetch_add(1,std::memory_order_release);
}
quint64 Runtime::mediaFrameForSource(quint64 source,unsigned rate)const{
    const bool pending=d->pendingAnchorRevision.load(std::memory_order_acquire)>0;
    const auto anchor=pending?d->pendingAnchorSource.load():d->sourceAnchor.load();
    const auto media=pending?d->pendingAnchorMedia.load():d->mediaAnchor.load();
    if(anchor==UINT64_MAX)return d->now();
    if(source>=anchor)return media+mediaFrameAdvance(source-anchor,rate);
    const auto back=mediaFrameAdvance(anchor-source,rate);return media>back?media-back:0;
}
bool Runtime::active()const{return !d->auth.sessionId.isEmpty();}
QJsonObject Runtime::snapshot()const{return d->publicState();}
bool Runtime::localMasterAudible()const noexcept{return d->separateLocalMaster.load(std::memory_order_relaxed);}
bool Runtime::sharedAudible()const noexcept{return d->audible.load(std::memory_order_relaxed);}
QString Runtime::authorize(const QString& op,const QJsonObject& p)const{if(op=="audio.config.set"&&d->auth.local!=d->auth.owner){const auto mic=p["microphone"].toObject();if(mic.size()==1&&mic["enabled"].isBool()&&!mic["enabled"].toBool())return {};}d->auth.advance(d->now());return d->auth.authorize(op,p["_junction"].toObject(),d->now());}
void Runtime::applied(const QString& op,const QJsonObject& params){if(!active()||d->auth.local!=d->auth.owner||Authority::localOnly(op)||Authority::readOnlyQuery(op))return;++d->controlSeq;++d->auth.revision;if(d->auth.phase=="preparing"){d->ready=false;d->graphDirty=true;d->lastSharedChange=monotonicNanos();d->reasons={"演奏の変更に同期しています"};d->broadcast("graph.applied",{{"throughSeq",u64(d->controlSeq)}});}Q_UNUSED(params);}
void Runtime::capture(const float* pcm,unsigned frames,quint64 sourceFrame,unsigned rate)noexcept{
    if(!d->captureEnabled.load(std::memory_order_relaxed))return;
    const auto revision=d->pendingAnchorRevision.load(std::memory_order_acquire);
    if(!(revision&1)&&revision!=d->appliedAnchorRevision){
        const auto source=d->pendingAnchorSource.load(std::memory_order_relaxed),media=d->pendingAnchorMedia.load(std::memory_order_relaxed);
        if(revision==d->pendingAnchorRevision.load(std::memory_order_acquire)){
            d->sourceAnchor.store(source,std::memory_order_relaxed);d->mediaAnchor.store(media,std::memory_order_relaxed);d->appliedAnchorRevision=revision;d->captureGeneration.fetch_add(1,std::memory_order_relaxed);
        }
    }
    auto anchor=d->sourceAnchor.load(std::memory_order_relaxed);
    if(anchor==UINT64_MAX||sourceFrame<anchor){if(anchor!=UINT64_MAX)d->captureGeneration.fetch_add(1,std::memory_order_relaxed);d->sourceAnchor.store(sourceFrame,std::memory_order_relaxed);anchor=sourceFrame;const auto ns=monotonicNanos()-d->timelineAnchor.load(std::memory_order_relaxed);d->mediaAnchor.store(ns>0?quint64(ns/1000000000)*48000+quint64(ns%1000000000)*48000/1000000000:0,std::memory_order_relaxed);}
    d->lastCaptureSourceEnd.store(sourceFrame+frames,std::memory_order_release);
    PcmBlockInfo info;info.epoch=d->captureEpoch.load(std::memory_order_relaxed);info.sourceFrame=sourceFrame;info.mediaFrame=d->mediaAnchor.load(std::memory_order_relaxed)+mediaFrameAdvance(sourceFrame-anchor,rate);info.frameCount=frames;info.sampleRateHz=rate;info.channels=2;info.sequence=d->blockSequence.fetch_add(1,std::memory_order_relaxed);info.generation=d->captureGeneration.load(std::memory_order_relaxed);
    const auto cutover=d->scheduledFrame.load(std::memory_order_acquire);
    const auto nextEpoch=d->scheduledEpoch.load(std::memory_order_relaxed);
    if(nextEpoch&&info.mediaFrame+mediaFrameAdvance(frames,rate)>cutover){
        const quint32 before=info.mediaFrame>=cutover?0:std::min(quint64(frames),((cutover-info.mediaFrame)*rate+47999)/48000);
        if(before){auto old=info;old.frameCount=before;d->tap.capture(pcm,old);info.sequence=d->blockSequence.fetch_add(1,std::memory_order_relaxed);}
        info.epoch=nextEpoch;info.sourceFrame+=before;info.mediaFrame+=mediaFrameAdvance(before,rate);info.frameCount-=before;d->captureEpoch.store(nextEpoch,std::memory_order_relaxed);
        if(info.frameCount)d->tap.capture(pcm+before*2,info);
    }else d->tap.capture(pcm,info);
}
QJsonObject Runtime::command(const QString& op,const QJsonObject& p,QString* error){
    auto reject=[&](const QString& reason){if(error)*error=reason;return QJsonObject{};};
    if(op=="snapshot")return snapshot();
    if(op.startsWith("network.")){
        if(op=="network.get")return d->network.summary();
        if(op=="network.test"){
            if(p["cancel"].toBool()){d->networkProbe.reset();d->networkTestDeadline=0;d->networkTestResult={{"state","failure"},{"detail","接続テストを中止しました"}};return d->networkTestResult;}
            return d->testNetwork(!p["poll"].toBool());
        }
        if(op=="network.configure"||op=="network.clear"){
            auto failure=op=="network.clear"?d->network.clear():d->network.configure(p);if(!failure.isEmpty())return reject(failure);
            d->networkProbe.reset();d->networkTestResult={};return d->network.summary();
        }
    }
    if(op=="exchange.inspect"){
        QString failure,code;auto packet=decodeExchangePacket(p["text"].toString(),QDateTime::currentMSecsSinceEpoch(),&failure,&code);
        if(!packet||!failure.isEmpty())return reject(failure);
        if(!verifyExchangeSignature(*packet,packet->descriptionFingerprint(),&failure))return reject(failure);
        return packet->sanitized();
    }
    const auto input=p["text"].toString(p["invite"].toString());
    const bool manualCreate=op=="create"&&(p["exchangeMode"]=="manual"||p["signalingUrl"].toString().isEmpty());
    const bool manualJoin=op=="join"&&input.startsWith("PLUMDECK-JUNCTION-");
    if(manualCreate||manualJoin){
        if(active())return reject("参加中のセッションを終了してから操作してください");
        if(!d->backend->available()||!MediaTransport::available())return reject("音声エンジンとWebRTCの準備が必要です");
        const auto displayName=sanitizeDisplayName(p["displayName"].toString());if(displayName.isEmpty())return reject("表示名を入力してください");
        QString failure,code;std::optional<ExchangePacket> packet;
        if(manualJoin){packet=decodeExchangePacket(input,QDateTime::currentMSecsSinceEpoch(),&failure,&code);if(!packet||!failure.isEmpty())return reject(failure);if(packet->kind!=ExchangeKind::Invite)return reject("ホストから届いた招待を取り込んでください");if(!verifyExchangeSignature(*packet,packet->hostFingerprint,&failure))return reject(failure);}
        if(manualCreate&&!p["adoptCurrent"].toBool()){
            bool sounding=d->backend->audio()["microphone"].toObject()["enabled"].toBool();for(int deck=0;deck<4;++deck)sounding|=d->backend->playing(deck);
            for(const auto& row:d->backend->samplerState()["slots"].toArray())sounding|=row.toObject()["playing"].toBool();
            if(sounding)return reject("現在の演奏を使う場合は「現在の演奏をこのセッションで使う」を選択してください");
        }
        d->displayName=displayName;d->name=p["sessionName"].toString(displayName+" のセッション").trimmed().left(80);if(d->name.isEmpty())return reject("セッション名を入力してください");
        bool ok=false;d->programDevice=p["programDevice"].toString().toInt(&ok);if(!ok)d->programDevice=-1;
        if(manualCreate)d->auth.sessionId=secureRandomHex(16);
        failure=d->startManual(manualCreate);if(failure.isEmpty()&&manualJoin)failure=d->acceptManualInvite(*packet,true);
        if(!failure.isEmpty()){d->stop();return reject(failure);}return snapshot();
    }
    if(d->manual&&active()){
        if(op=="invite.create"){
            if(!d->hosting)return reject("ホストだけが招待を作成できます");
            const auto requested=p["peerId"].toString();auto i=d->peers.find(requested);
            if(!requested.isEmpty()&&i==d->peers.end())return reject("参加者が見つかりません");
            if(requested.isEmpty()){
                if(d->peers.size()>=7){
                    auto unused=std::find_if(d->peers.begin(),d->peers.end(),[](const auto& item){return !item.second->approved&&exchangeStateTerminal(item.second->manual.state);});
                    if(unused!=d->peers.end())d->peers.erase(unused);
                    else return reject("このセッションはホストを含め8人までです。不要な招待を取り消してください");
                }
                auto peer=std::make_unique<Impl::Peer>();peer->id=secureRandomHex(16);peer->name="招待中のDJ";auto id=peer->id;i=d->peers.emplace(id,std::move(peer)).first;
            }
            auto& peer=*i->second;QString failure;
            auto ice=d->network.credentials(d->auth.sessionId,peer.id,QDateTime::currentMSecsSinceEpoch(),&failure);if(!failure.isEmpty())return reject(failure);
            peer.manual.ice=ice;peer.manual.inviteId=secureRandomHex(16);++peer.manual.generation;++peer.manual.attempt;peer.manual.expiresAt=QDateTime::currentMSecsSinceEpoch()+900000;
            for(const auto& v:ice)if(v.toObject().contains("expiresAt"))peer.manual.expiresAt=std::min(peer.manual.expiresAt,qint64(v.toObject()["expiresAt"].toDouble()));
            failure=d->manualStartAttempt(peer,true,ice);if(!failure.isEmpty()){d->manualSetState(peer,ExchangeState::Failed,failure);return reject(failure);}return snapshot();
        }
        if(op=="exchange.import"){
            QString failure,code;auto packet=decodeExchangePacket(input,QDateTime::currentMSecsSinceEpoch(),&failure,&code);if(!packet||!failure.isEmpty())return reject(failure);
            if(packet->sessionId!=d->auth.sessionId||packet->hostPeerId!=d->auth.host)return reject("別のセッションへの接続情報です");
            if(!d->hosting&&packet->kind==ExchangeKind::Invite){failure=d->acceptManualInvite(*packet,false);if(!failure.isEmpty())return reject(failure);return snapshot();}
            auto i=d->peers.find(d->hosting?packet->peerId:d->auth.host);if(i==d->peers.end())return reject("対応する招待が見つかりません");auto& peer=*i->second;
            if(packet->inviteId!=peer.manual.inviteId||packet->generation!=peer.manual.generation||packet->attempt!=peer.manual.attempt)return reject("別の招待、または更新前の接続情報です。最新の招待への返答を取り込んでください");
            if(d->hosting){
                if(packet->kind!=ExchangeKind::Response)return reject("DJから届いた返答を取り込んでください");
                if(packet->hostFingerprint!=d->identity->fingerprint||packet->expiresAt!=peer.manual.expiresAt)return reject("招待と返答の識別情報が一致しません");
                if(exchangeStateTerminal(peer.manual.state))return reject("この招待は取り消し済み、または無効です。新しい招待を作成してください");
                if(!verifyExchangeSignature(*packet,packet->peerFingerprint,&failure))return reject(failure);
                if(peer.approved&&!peer.fp.isEmpty()&&packet->peerFingerprint!=peer.fp)return reject("接続済みDJと異なる端末の返答です。別の参加者として招待してください");
                const auto digest=sha256Hex(packet->canonicalPayload());if(digest==peer.manual.answerDigest)return reject("この返答は取り込み済みです。参加者カードで次の操作を確認してください");
                if(peer.manual.state!=ExchangeState::InviteReady)return reject("この招待の返答はすでに取り込まれています。必要なら招待を作り直してください");
                peer.manual.answerDigest=digest;peer.manual.answerPending=true;peer.manual.answerName=packet->peerName;peer.name=packet->peerName;peer.manual.answerFingerprint=packet->peerFingerprint;
                for(int j=0;j<2;++j){peer.manual.answerSdp[j]=packet->description[j].sdp;peer.manual.answerType[j]=packet->description[j].type;}
                d->manualSetState(peer,ExchangeState::ApprovalPending,"表示名だけでは本人確認になりません。返答の送り主を確認して、参加を許可してください");return snapshot();
            }
            if(packet->kind!=ExchangeKind::Notice||packet->peerId!=d->auth.local)return reject("ホストから届いた招待・通知を取り込んでください");
            if(!verifyExchangeSignature(*packet,d->pinnedHostFingerprint,&failure))return reject(failure);
            d->discardAttempt(peer);d->manualSetState(peer,packet->noticeReason=="rejected"?ExchangeState::Rejected:ExchangeState::Cancelled,packet->noticeText);return snapshot();
        }
        if(op=="invite.cancel"||op=="peer.retry"||op=="peer.approve"){
            const auto id=d->hosting?p["peerId"].toString():d->auth.host;auto i=d->peers.find(id);if(i==d->peers.end())return reject("参加者が見つかりません");auto& peer=*i->second;
            if(op=="peer.retry"){
                if(peer.transport&&peer.transport->aggregateLinkState()==LinkState::Connected){d->discardAttempt(peer);d->manualSetState(peer,ExchangeState::Connected,"接続は継続しています");return snapshot();}
                if(peer.manual.state==ExchangeState::Interrupted&&peer.manual.retries++<2){peer.manual.connectDeadline=monotonicNanos()+15000000000LL;return snapshot();}
                d->discardAttempt(peer);d->manualSetState(peer,ExchangeState::NeedsExchange,"新しい接続情報の交換が必要です。ホストがこの参加者の招待を作り直してください");return snapshot();
            }
            if(op=="peer.approve"){
                if(!d->hosting)return reject("ホストだけが参加を承認できます");
                if(peer.manual.state!=ExchangeState::ApprovalPending)return reject("返答を取り込んでから参加を許可してください");
                if(!p["accept"].isBool())return reject("参加を許可するか指定してください");
                if(p["accept"].toBool()){
                    if(peer.manual.expiresAt<=QDateTime::currentMSecsSinceEpoch())return reject("招待の期限が切れました。作り直してください");
                    auto failure=d->manualApplyAnswer(peer);if(!failure.isEmpty()){d->discardAttempt(peer);d->manualSetState(peer,ExchangeState::Failed,failure);return reject(failure);}peer.approved=true;return snapshot();
                }
            }
            const bool rejection=op=="peer.approve";QString notice;
            if(d->hosting){auto failure=d->manualBuildNotice(peer,rejection?"rejected":"cancelled",rejection?"ホストが参加を許可しませんでした":"ホストがこの招待を取り消しました");if(!failure.isEmpty())return reject(failure);notice=peer.manual.noticeText;}
            d->discardAttempt(peer);peer.manual.noticeText=notice;d->manualSetState(peer,rejection?ExchangeState::Rejected:ExchangeState::Cancelled,d->hosting?"招待を取り消しました。相手には通知をコピーして送ってください":"接続操作を取り消しました。ホストから新しい招待を受け取ってください");return snapshot();
        }
    }
    if(op=="create"||op=="join"){
        if(active())return reject("参加中のセッションを終了してから操作してください");
        if(!d->backend->available()||!MediaTransport::available())return reject("音声エンジンとWebRTCの準備が必要です");
        d->displayName=sanitizeDisplayName(p["displayName"].toString());if(d->displayName.isEmpty())return reject("表示名を入力してください");
        d->origin=p["signalingUrl"].toString();d->hosting=op=="create";
        if(!d->hosting){QUrl u(p["invite"].toString());QUrlQuery query(u);if(u.scheme()!="plumdeck-junction"||u.host()!="join"||query.queryItemValue("version")!="1")return reject("招待が無効です");d->origin=query.queryItemValue("signaling");d->room=query.queryItemValue("room");d->token=query.queryItemValue("token");bool ok;d->inviteExpiry=query.queryItemValue("expiresAt").toLongLong(&ok);if(!ok||d->inviteExpiry<=QDateTime::currentMSecsSinceEpoch()||!validOpaqueId(d->room)||d->token.size()<22||d->token.size()>128)return reject("招待が無効、または期限切れです");d->pendingInvite={{"host",query.queryItemValue("host")}};if(d->pendingInvite["host"].toString().size()!=64)return reject("ホストの識別情報が無効です");}
        if(!validOrigin(QUrl(d->origin)))return reject("WSS接続先を設定してください。開発用WSはローカルホストで利用できます");
        if(d->hosting&&!p["adoptCurrent"].toBool()){
            bool sounding=d->backend->audio()["microphone"].toObject()["enabled"].toBool();
            for(int deck=0;deck<4;++deck)sounding|=d->backend->playing(deck);
            const auto sampler=d->backend->samplerState();for(const auto& row:sampler["slots"].toArray())sounding|=row.toObject()["playing"].toBool();
            if(sounding)return reject("現在の演奏を使う場合は「現在の演奏をこのセッションで使う」を選択してください");
        }
        d->name=p["sessionName"].toString(d->displayName+" のセッション").left(80);d->maxPeers=p["maxPeers"].toInt(8);if(d->maxPeers<2||d->maxPeers>64)return reject("参加人数は2〜64人で指定してください");
        bool deviceOk=false;d->programDevice=p["programDevice"].toString().toInt(&deviceOk);if(!deviceOk)d->programDevice=-1;
        if(d->hosting){d->room=secureRandomHex(16);d->token=secureRandomToken(24);d->recovery=secureRandomToken(32);d->inviteExpiry=QDateTime::currentMSecsSinceEpoch()+3600000;d->auth.sessionId=secureRandomHex(16);d->adopt=p["adoptCurrent"].toBool();}
        else{d->auth.sessionId="pending";d->audible.store(false);}
        const auto failure=d->connect(d->hosting);if(!failure.isEmpty()){d->stop();return reject(failure);}return snapshot();
    }
    if(!active())return reject("セッションに参加していません");
    if(op.startsWith("private.")){const auto failure=d->backend->privatePreviewCommand(op,p);if(!failure.isEmpty())return reject(failure);return snapshot();}
    if(op=="leave"||op=="end"){
        if(op=="leave"&&d->auth.owner==d->auth.local&&d->peers.size()>0)return reject("演奏を引き継いでから退出してください");
        if(op=="end"&&!d->hosting)return reject("ホストだけがセッションを終了できます");
        if(!d->endingAt){d->endingHost=d->hosting;d->endingAt=monotonicNanos()+(d->hosting?2000000000LL:200000000LL);d->connection="closing";d->broadcast(d->hosting?"session.end":"peer.leave",{});}return snapshot();
    }
    if(op=="peer.approve"){
        if(!d->hosting)return reject("ホストだけが参加を承認できます");auto i=d->peers.find(p["peerId"].toString());if(i==d->peers.end())return reject("参加希望が見つかりません");bool accept=p["accept"].toBool(true);d->signalSend({{"type","host.join_decision"},{"guestPeerId",i->first},{"accept",accept}});if(accept){i->second->approved=true;d->makePeer(*i->second,true);}else d->peers.erase(i);++d->auth.revision;return snapshot();
    }
    if(op=="invite.rotate") {if(!d->hosting)return reject("ホストだけが招待を更新できます");d->token=secureRandomToken(24);d->inviteExpiry=QDateTime::currentMSecsSinceEpoch()+3600000;d->signalSend({{"type","host.rotate_invite"},{"inviteTokenHash",sha256Hex(d->token.toUtf8())},{"inviteExpiresAt",double(d->inviteExpiry)}});d->updateInvite();return snapshot();}
    if(op=="program.configure") {if(!d->hosting)return reject("配信出力はホストが設定します");bool ok;int device=p["programDevice"].toString().toInt(&ok);if(!ok)return reject("配信先デバイスを選択してください");d->program.close();d->programOpened=false;d->programDevice=device;d->openProgram();if(p.contains("gain"))d->program.setGain(float(p["gain"].toDouble()));return snapshot();}
    if(op=="program.record.start"||op=="program.record.stop") {if(!d->hosting)return reject("配信録音はホストが操作します");QString failure;bool ok=op.endsWith("start")?d->program.startRecording(p["path"].toString(),&failure):d->program.stopRecording(&failure);if(!ok)return reject(failure);return snapshot();}
    if(op=="recovery.resume"){
        if(!d->hosting||d->auth.phase!="recovery")return reject("ホストが復旧中に操作できます");
        d->recoveryResumeFrame=d->now()+24000;d->recoveryEpoch=std::max(d->auth.epoch,d->auth.committed?d->auth.committed->newEpoch:quint64(0))+1;
        QSaveFile record(QStandardPaths::writableLocation(QStandardPaths::CacheLocation)+"/junction/"+d->auth.sessionId+".recovery");
        const auto bytes=json({{"sessionId",d->auth.sessionId},{"epoch",u64(d->recoveryEpoch)},{"frame",u64(d->recoveryResumeFrame)},{"owner",d->auth.host}});
        if(!record.open(QIODevice::WriteOnly)||record.write(bytes)!=bytes.size()||!record.flush()||platform_file::sync(record.handle())!=0||!record.commit()){d->recoveryResumeFrame=0;return reject("復旧状態を保存できません");}
        setCaptureAnchor(d->lastCaptureSourceEnd.load(),d->now());d->scheduledEpoch.store(d->recoveryEpoch);d->scheduledFrame.store(d->recoveryResumeFrame);d->captureEnabled.store(true);d->tap.enable(false,true);
        auto it=d->programPending.lower_bound(d->recoveryResumeFrame);d->programPending.erase(it,d->programPending.end());
        d->broadcast("session.recovery",{{"stage","scheduled"},{"reason","ホストの手元の演奏へ切り替えます"},{"frame",u64(d->recoveryResumeFrame)},{"epoch",u64(d->recoveryEpoch)}});return snapshot();
    }
    if(op=="handoff.request") {auto target=p["targetPeerId"].toString(d->auth.local);if(d->hosting){auto peer=d->peers.find(target);if(target!=d->auth.local&&(peer==d->peers.end()||!peer->second->approved))return reject("承認済みの参加者を選択してください");auto failure=d->auth.prepare(target);if(!failure.isEmpty())return reject(failure);d->resetPreparation();d->broadcast("handoff.prepare",{{"targetPeerId",target},{"handoffId",d->auth.handoffId}});if(d->auth.owner==d->auth.local)d->startExport();}else{auto i=d->peers.find(d->auth.host);if(i==d->peers.end())return reject("ホストに接続していません");d->queue(*i->second,"handoff.request",{{"targetPeerId",target}});}return snapshot();}
    if(op=="handoff.cancel") {if(!d->hosting)return reject("ホストに取り消しを依頼してください");const auto handoffId=d->auth.handoffId;auto failure=d->auth.cancel();if(!failure.isEmpty())return reject(failure);d->broadcast("handoff.cancel",{{"handoffId",handoffId},{"reason","cancelled"}});return snapshot();}
    if(op=="handoff.accept"){
        if(!d->hosting){auto h=d->peers.find(d->auth.host);if(h==d->peers.end())return reject("ホストに接続していません");d->queue(*h->second,"handoff.ready",{{"requestFence",true},{"handoffId",d->auth.handoffId}});return snapshot();}
        if(d->auth.phase!="preparing"||!d->ready)return reject("引き継ぎの準備を待っています");
        auto frame=d->now()+4800;d->auth.fence(frame,d->controlSeq);d->fenceDeadline=monotonicNanos()+6000000000LL;d->finalCheckpoint=false;d->validationStart=0;d->broadcast("handoff.fence",{{"frame",u64(frame)},{"handoffId",d->auth.handoffId}});return snapshot();
    }
    return reject("対応していないセッション操作です");
}
}
