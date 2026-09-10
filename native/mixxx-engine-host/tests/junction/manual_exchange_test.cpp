#include "harness.h"
#include "junction/manual_exchange.h"
#include "junction/media_transport.h"
#include <QTemporaryDir>
#include <QDateTime>
using namespace junction;
namespace {
ExchangePacket invitation(const MediaTransport::Identity& identity){
 ExchangePacket p;p.sessionId="session0123456789";p.inviteId="invite01234567890";p.hostPeerId="host012345678901";p.peerId="guest01234567890";p.hostFingerprint=identity.fingerprint;p.hostName="ホスト";p.sessionName="夜のDJ";p.generation=1;p.attempt=1;p.expiresAt=QDateTime::currentMSecsSinceEpoch()+60000;
 QString fp;for(int i=0;i<p.hostFingerprint.size();i+=2){if(i)fp+=':';fp+=p.hostFingerprint.mid(i,2);}
 for(auto& d:p.description)d={"offer","v=0\r\na=fingerprint:sha-256 "+fp+"\r\na=candidate:1 1 UDP 2122260223 127.0.0.1 4567 typ host\r\na=end-of-candidates\r\n"};
 p.certificatePem=readCertificatePem(identity.certificatePath);p.signature=signExchangePayload(identity.keyPath,p.canonicalPayload());return p;
}
}
JTEST("manual-exchange","bounded signed dual-link packet validates identity and detects modification"){
 QTemporaryDir directory;QString error;auto identity=MediaTransport::createIdentity(directory.path(),&error);CHECK(identity);auto p=invitation(*identity);auto text=encodeExchangePacket(p,&error);CHECK(!text.isEmpty());auto read=decodeExchangePacket(text,QDateTime::currentMSecsSinceEpoch(),&error);CHECK(read);CHECK(verifyExchangeSignature(*read,identity->fingerprint,&error));read->hostName="modified";CHECK(!verifyExchangeSignature(*read,identity->fingerprint,&error));CHECK(!verifyExchangeSignature(p,QString(64,'a'),&error));
}
JTEST("manual-exchange","expiry version truncation missing bulk and wrong DTLS identity fail closed"){
 QTemporaryDir directory;auto identity=MediaTransport::createIdentity(directory.path());CHECK(identity);auto p=invitation(*identity);QString error,code;
 auto text=encodeExchangePacket(p);CHECK(!decodeExchangePacket(text.left(text.size()/2),QDateTime::currentMSecsSinceEpoch()));CHECK(!decodeExchangePacket(QString(kMaxExchangeTextBytes+1,'x'),QDateTime::currentMSecsSinceEpoch()));
 CHECK(!decodeExchangePacket(text.replace("JUNCTION-1.","JUNCTION-2."),QDateTime::currentMSecsSinceEpoch(),&error,&code));CHECK_EQ(code,QString("unsupported_version"));
 p.expiresAt=QDateTime::currentMSecsSinceEpoch()-1;CHECK(!decodeExchangePacket(encodeExchangePacket(p),QDateTime::currentMSecsSinceEpoch(),&error,&code));CHECK_EQ(code,QString("expired"));p.expiresAt+=60000;
 p.description[1]={};CHECK(!decodeExchangePacket(encodeExchangePacket(p),QDateTime::currentMSecsSinceEpoch()));p.description[1]=p.description[0];p.hostFingerprint=QString(64,'b');CHECK(!decodeExchangePacket(encodeExchangePacket(p),QDateTime::currentMSecsSinceEpoch()));
}
JTEST("manual-exchange","signed cancellation is pinned to original host"){
 QTemporaryDir directory;auto identity=MediaTransport::createIdentity(directory.path());CHECK(identity);auto p=invitation(*identity);p.kind=ExchangeKind::Notice;p.description[0]={};p.description[1]={};p.noticeReason="cancelled";p.noticeText="取り消しました";p.signature=signExchangePayload(identity->keyPath,p.canonicalPayload());auto read=decodeExchangePacket(encodeExchangePacket(p),QDateTime::currentMSecsSinceEpoch());CHECK(read);CHECK(verifyExchangeSignature(*read,identity->fingerprint));read->inviteId="different0123456";CHECK(!verifyExchangeSignature(*read,identity->fingerprint));
}
