#include "runtime.h"
#include "media_transport.h"
#include "program_output.h"
#include "asset_cache.h"
#include "validation.h"
#include "validation_capture.h"
#include "ice_servers.h"
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
#include <unistd.h>
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
#if defined(DJALY_JUNCTION_WITH_LIBDATACHANNEL)
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
    struct Peer {QString id,name,fp;bool approved=false,hello=false,producing=false,endingAck=false;std::unique_ptr<MediaTransport> transport;QQueue<QByteArray> pending;};
    std::map<QString,std::unique_ptr<Peer>> peers;
#if defined(DJALY_JUNCTION_WITH_LIBDATACHANNEL)
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
    explicit Impl(Runtime* owner,PlaybackBackend* b):q(owner),backend(b),cache(QStandardPaths::writableLocation(QStandardPaths::CacheLocation)+"/junction") {
        timer.setInterval(5);QObject::connect(&timer,&QTimer::timeout,q,[this]{tick();});timer.start();
    }
    quint64 now() const {return hosting?timeline.now():timeline.frameAt(clock.toHostNanos(monotonicNanos()));}
    template<class F> void post(F fn) {QMetaObject::invokeMethod(q,std::move(fn),Qt::QueuedConnection);}
    void fail(const QString& text) {if(qEnvironmentVariableIsSet("DJALY_JUNCTION_TRACE"))qWarning()<<"junction failure"<<hosting<<text;problem=text;reasons={text};ready=false;}
    void signalSend(QJsonObject m) {
#if defined(DJALY_JUNCTION_WITH_LIBDATACHANNEL)
        m["v"]=1;
        if(signal && signal->isOpen()) {try{signal->send(json(m).toStdString());}catch(const std::exception&){fail("接続サービスへ送信できません");}}
#else
        Q_UNUSED(m);
#endif
    }
    void queue(Peer& p,const QString& type,QJsonObject payload) {
        if(p.pending.size()>=128) {p.pending.clear();fail("制御通信が混雑しています");return;}
        p.pending.enqueue(json({{"version",1},{"sessionId",auth.sessionId},{"senderPeerId",auth.local},{"epoch",u64(auth.epoch)},{"messageId",secureRandomHex(12)},{"type",type},{"payload",payload}}));
    }
    void broadcast(const QString& type,const QJsonObject& payload) {for(auto& [id,p]:peers)if(p->approved&&p->transport)queue(*p,type,payload);}
    QJsonObject publicState() const {
        QJsonArray participants;
        if(!auth.local.isEmpty())participants.append(QJsonObject{{"peerId",auth.local},{"displayName",displayName},{"approved",true},{"isHost",hosting},{"isPerformer",auth.owner==auth.local},{"isNextUp",auth.next==auth.local},{"status",connection}});
        for(const auto& [id,p]:peers)participants.append(QJsonObject{{"peerId",id},{"displayName",p->name},{"approved",p->approved},{"isHost",id==auth.host},{"isPerformer",id==auth.owner},{"isNextUp",id==auth.next},{"status",p->hello?"connected":p->approved?"connecting":"pending"}});
        if(!hosting)for(const auto& value:participantRoster){const auto row=value.toObject();const auto id=row["peerId"].toString();if(!validOpaqueId(id)||id==auth.local||peers.count(id))continue;
            participants.append(QJsonObject{{"peerId",id},{"displayName",sanitizeDisplayName(row["displayName"].toString())},{"approved",row["approved"].toBool()},{"isHost",id==auth.host},{"isPerformer",id==auth.owner},{"isNextUp",id==auth.next},{"status",row["status"].toString()}});
        }
        QJsonArray why;for(const auto& r:reasons)why.append(r);
        return {{"active",!auth.sessionId.isEmpty()},{"sessionId",auth.sessionId},{"localPeerId",auth.local},{"hostPeerId",auth.host},{"performerPeerId",auth.owner},{"nextPeerId",auth.next},{"epoch",u64(auth.epoch)},{"revision",double(auth.revision)},{"sessionName",name},{"handoffState",auth.phase},{"handoffId",auth.handoffId},{"participants",participants},{"readiness",QJsonObject{{"ready",ready},{"reasons",why}}},{"connection",QJsonObject{{"state",connection},{"detail",problem}}},{"program",QJsonObject{{"state",programState},{"localMonitor",separateLocalMaster.load()?"direct":"program-delayed"},{"outputDevice",QString::number(programDevice)},{"recording",program.recording()},{"underruns",u64(program.underruns())},{"meter",double(program.peak())},{"rms",double(program.rms())},{"sampleRateHz",int(program.sampleRate())},{"deviceLatencySeconds",program.deviceLatencySeconds()}}},{"invite",hosting?invite:QString{}},{"privatePreview",backend->privatePreviewState()}};
    }
    void updateInvite() {
        if(!hosting || room.isEmpty())return;
        QUrl u("djaly-junction://join");QUrlQuery query;
        query.addQueryItem("version","1");query.addQueryItem("signaling",origin);query.addQueryItem("room",room);query.addQueryItem("token",token);query.addQueryItem("host",identity->fingerprint);query.addQueryItem("expiresAt",QString::number(inviteExpiry));u.setQuery(query);invite=u.toString(QUrl::FullyEncoded);
    }
    QString connect(bool host) {
        hosting=host;QString error;
#ifdef __APPLE__
        if(sleepLease==kIOPMNullAssertionID)IOPMAssertionCreateWithName(kIOPMAssertionTypePreventUserIdleSystemSleep,kIOPMAssertionLevelOn,CFSTR("Djaly Junction audio session"),&sleepLease);
#endif
        if(!identity)identity=MediaTransport::createIdentity(identityDir.path(),&error);if(!identity)return error;
#if defined(DJALY_JUNCTION_WITH_LIBDATACHANNEL)
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
    void makePeer(Peer& p,bool offerer) {
        if(!iceReady||p.transport)return;
        const auto id=p.id;QPointer<Runtime> safe=q;
        MediaTransport::Callbacks callbacks;
        callbacks.localDescription=[safe,id](bool bulk,QString sdp,QString type,QString){if(safe)QMetaObject::invokeMethod(safe,[safe,id,bulk,sdp,type]{if(safe)safe->d->signalSend({{"type","signal.relay"},{"toPeerId",id},{"payload",QJsonObject{{"kind","description"},{"bulk",bulk},{"sdp",sdp},{"descriptionType",type}}}});},Qt::QueuedConnection);};
        callbacks.localCandidate=[safe,id](bool bulk,QString candidate,QString mid){if(safe)QMetaObject::invokeMethod(safe,[safe,id,bulk,candidate,mid]{if(safe)safe->d->signalSend({{"type","signal.relay"},{"toPeerId",id},{"payload",QJsonObject{{"kind","candidate"},{"bulk",bulk},{"candidate",candidate},{"mid",mid}}}});},Qt::QueuedConnection);};
        callbacks.producerManifest=[safe,id](StreamManifest manifest){if(safe)QMetaObject::invokeMethod(safe,[safe,id,manifest]{if(!safe)return;auto p=safe->d->peers.find(id);if(p!=safe->d->peers.end())safe->d->queue(*p->second,"peer.hello",{{"fingerprint",fingerprint()},{"displayName",safe->d->displayName},{"stream",streamJson(manifest)}});},Qt::QueuedConnection);};
        callbacks.control=[safe,id](QByteArray bytes){if(safe)QMetaObject::invokeMethod(safe,[safe,id,bytes]{if(safe)safe->d->control(id,bytes);},Qt::QueuedConnection);};
        callbacks.validation=[safe,id](QByteArray bytes){if(safe)QMetaObject::invokeMethod(safe,[safe,id,bytes]{if(safe)safe->d->validationChunk(id,bytes);},Qt::QueuedConnection);};
        callbacks.bulk=[safe,id](QByteArray bytes){if(safe)QMetaObject::invokeMethod(safe,[safe,id,bytes]{if(safe)safe->d->bulk(id,bytes);},Qt::QueuedConnection);};
        callbacks.error=[safe](QString error){if(safe)QMetaObject::invokeMethod(safe,[safe,error]{if(safe)safe->d->fail(error);},Qt::QueuedConnection);};
        p.transport=std::make_unique<MediaTransport>(id,iceServers,std::move(callbacks),identity,qEnvironmentVariable("DJALY_JUNCTION_FORCE_RELAY")=="1");QString error;if(!p.transport->start(offerer,&error)){fail(error);return;}
        queue(p,"peer.hello",{{"fingerprint",fingerprint()},{"displayName",displayName}});
        if(hosting)queue(p,"session.snapshot",wireState());
    }
    QJsonObject wireState() const {auto s=publicState();s.remove("invite");s.remove("privatePreview");s.remove("program");s["timelineOriginNanos"]=QString::number(timeline.originNanos());s["timelineOriginFrame"]=u64(timeline.originFrame());s["programDelayFrames"]=int(delay);s["engineFingerprint"]=fingerprint();if(auth.committed)s["commit"]=auth.committed->toJson();return s;}
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
        const auto payload=envelope.payload;
        if(envelope.type==MessageType::SessionSnapshot && payload["engineFingerprint"]!=fingerprint()){fail("エンジンのバージョンが一致しません");return;}
        if(!p.hello && envelope.type!=MessageType::PeerHello && envelope.type!=MessageType::SessionSnapshot)return;
        if(envelope.type==MessageType::PeerHello){if(payload["fingerprint"]!=fingerprint()){p.hello=false;fail("エンジンのバージョンが一致しません");return;}const bool firstHello=!p.hello;p.hello=true;if(firstHello)queue(p,"peer.hello",{{"fingerprint",fingerprint()},{"displayName",displayName}});p.name=payload["displayName"].toString(p.name);connection="connected";
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
        if(kind!=assetKinds.end()&&(kind->second=="djaly-ddj-dsp-v1"||kind->second=="djaly-keylock-v1"||kind->second=="djaly-fx-v1"))return backend->validateDspAsset(path);
        SF_INFO info{};auto* f=sf_open(path.toUtf8().constData(),SFM_READ,&info);if(f)sf_close(f);return f!=nullptr;
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
                    if(o["format"]=="djaly-ddj-dsp-v1"||o["format"]=="djaly-keylock-v1"||o["format"]=="djaly-fx-v1"){
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
        std::function<void(QJsonValue)> walk=[&](QJsonValue v){if(v.isArray()){for(const auto& x:v.toArray())walk(x);return;}if(!v.isObject())return;auto o=v.toObject();auto hash=o["assetId"].toString();if(o["format"]=="djaly-ddj-dsp-v1"||o["format"]=="djaly-keylock-v1"||o["format"]=="djaly-fx-v1")assetKinds[hash]=o["format"].toString();if(!hash.isEmpty() && assets.find(hash)==assets.end()){auto path=cache.resolve(hash);if(path.isEmpty()){if(!requestedAssets.contains(hash)){requestedAssets.insert(hash);queue(source,"asset.request",{{"assetId",hash}});}}else assets[hash]=path;}for(auto it=o.begin();it!=o.end();++it)walk(it.value());};walk(preparedGraph);tryPrepare();
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
            for(const auto& v:backend->audioDevices()["devices"].toArray()){const auto device=v.toObject();if(device["id"].toString()==QStringLiteral("coreaudio:")+QString::number(programDevice)&&device["name"].toString()==localName)separateLocalMaster.store(false);}
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
            if(producer==auth.owner&&info.epoch==auth.epoch)ownerAudioAt=monotonicNanos();
            if(auth.committed&&producer==auth.committed->oldOwner&&info.epoch==auth.committed->oldEpoch){
                backupPending.insert_or_assign(info.mediaFrame,ProgramBlock{info,std::vector<float>(pcm.data(),pcm.data()+info.frameCount*2)});
                while(backupPending.size()>384)backupPending.erase(backupPending.begin());
            }
            const auto allowed=[&](quint64 f){if(auth.phase=="recovery"){if(recoveryResumeFrame&&f>=recoveryResumeFrame)return producer==auth.host&&info.epoch==recoveryEpoch;return f<recoveryUntil&&producer==backupOwner&&info.epoch==backupEpoch;}if(auth.committed)return f<auth.cutoverFrame?producer==auth.committed->oldOwner&&info.epoch==auth.committed->oldEpoch:producer==auth.committed->newOwner&&info.epoch==auth.committed->newEpoch;return producer==auth.owner&&info.epoch==auth.epoch;};
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
        if(qEnvironmentVariableIsSet("DJALY_JUNCTION_TRACE"))qWarning()<<"junction validation begin"<<hosting<<start<<captureEpoch.load()<<captureGeneration.load();
        validationStart=start;validationEnd=start+12000;validationId=secureRandomHex(16);validationPcm.clear();validationReceiving.clear();validationOutgoing.clear();validationAwaitingAck.clear();
        validationSent=auth.local!=auth.owner&&auth.local!=auth.next;
        if(validationSent){validationCapture.cancel();return;}
        QString failure;if(!validationCapture.begin(start,12000,captureEpoch.load(),captureGeneration.load(),&failure))fail(failure);
    }
    void finishValidation() {
        if(!validationStart||validationSent)return;
        auto window=validationCapture.take();if(!window)return;
        validationSent=true;auto wire=std::move(window->samples);
        if(qEnvironmentVariableIsSet("DJALY_JUNCTION_TRACE"))qWarning()<<"junction validation complete"<<hosting<<wire.size();
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
        if(!file.open(QIODevice::WriteOnly)||file.write(bytes)!=bytes.size()||!file.flush()||::fsync(file.handle())!=0||!file.commit())return "引き継ぎ状態を保存できません";
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
        if(qEnvironmentVariableIsSet("DJALY_JUNCTION_TRACE"))qWarning()<<"junction validation match"<<match.ready<<match.lagFrames<<match.correlation<<match.levelDb<<match.fractionalLagFrames;
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
        ++ticks;if(auth.sessionId.isEmpty())return;
#if defined(DJALY_JUNCTION_WITH_LIBDATACHANNEL)
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
#endif
        captureEnabled.store(false);tap.enable(false,false);audible.store(true);separateLocalMaster.store(true);
        peers.clear();program.close();programOpened=false;programState="stopped";
#if defined(DJALY_JUNCTION_WITH_LIBDATACHANNEL)
        if(signal){signal->resetCallbacks();signal->forceClose();signal.reset();}
#endif
        endingAt=0;endingHost=false;reconnectAt=0;reconnectAttempts=0;turnRefreshAt=0;iceReady=false;iceServers.clear();deferredSignals.clear();identity.reset();participantRoster={};auth=Authority{};timeline=MediaTimeline{};clock.reset();q->setCaptureAnchor(UINT64_MAX,0);captureEpoch.store(1);scheduledFrame.store(UINT64_MAX);scheduledEpoch.store(0);sourceAnchor.store(UINT64_MAX);connection="disconnected";problem.clear();reasons.clear();invite.clear();ready=false;prepared=false;preparedGraph={};outgoing.clear();programEnqueuedThrough=0;backupPending.clear();backupOwner.clear();recoveryResumeFrame=0;recoveryUntil=0;ownerAudioAt=0;assetWaiters.clear();requestedAssets.clear();programPending.clear();validationReceiving.clear();validationOutgoing.clear();validationStart=0;validationCapture.reset();finalCheckpoint=false;aligned=false;graph={};
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
void Runtime::applied(const QString& op,const QJsonObject& params){if(!active()||d->auth.local!=d->auth.owner||Authority::localOnly(op))return;++d->controlSeq;++d->auth.revision;if(d->auth.phase=="preparing"){d->ready=false;d->graphDirty=true;d->lastSharedChange=monotonicNanos();d->reasons={"演奏の変更に同期しています"};d->broadcast("graph.applied",{{"throughSeq",u64(d->controlSeq)}});}Q_UNUSED(params);}
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
    if(op=="create"||op=="join"){
        if(active())return reject("参加中のセッションを終了してから操作してください");
        if(!d->backend->available()||!MediaTransport::available())return reject("音声エンジンとWebRTCの準備が必要です");
        d->displayName=sanitizeDisplayName(p["displayName"].toString());if(d->displayName.isEmpty())return reject("表示名を入力してください");
        d->origin=p["signalingUrl"].toString();d->hosting=op=="create";
        if(!d->hosting){QUrl u(p["invite"].toString());QUrlQuery query(u);if(u.scheme()!="djaly-junction"||u.host()!="join"||query.queryItemValue("version")!="1")return reject("招待が無効です");d->origin=query.queryItemValue("signaling");d->room=query.queryItemValue("room");d->token=query.queryItemValue("token");bool ok;d->inviteExpiry=query.queryItemValue("expiresAt").toLongLong(&ok);if(!ok||d->inviteExpiry<=QDateTime::currentMSecsSinceEpoch()||!validOpaqueId(d->room)||d->token.size()<22||d->token.size()>128)return reject("招待が無効、または期限切れです");d->pendingInvite={{"host",query.queryItemValue("host")}};if(d->pendingInvite["host"].toString().size()!=64)return reject("ホストの識別情報が無効です");}
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
        if(!record.open(QIODevice::WriteOnly)||record.write(bytes)!=bytes.size()||!record.flush()||::fsync(record.handle())!=0||!record.commit()){d->recoveryResumeFrame=0;return reject("復旧状態を保存できません");}
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
