#pragma once
#include "backend.h"
#include "deck_telemetry.h"
#include <QLocalServer>
#include <QLocalSocket>
#include <QTemporaryDir>
#include <QJsonDocument>
#include <QTimer>
#include <QUuid>
#include <QtEndian>
#include <array>
#include <functional>

// Authenticated local MIDI ingress. All decoding and ControlObject operations
// run on the native actor; the audio callback only consumes ScratchDeck's ring.
class PerformanceInput final : public QObject {
public:
    using State=std::function<QJsonObject(int)>;
    PerformanceInput(PlaybackBackend* backend, State state, std::function<bool()> allowed, QObject* parent=nullptr)
      :QObject(parent),backend_(backend),state_(std::move(state)),allowed_(std::move(allowed)) {
        server_.setSocketOptions(QLocalServer::UserAccessOption);
#ifdef Q_OS_WIN
        server_.listen("plumdeck-midi-" + QUuid::createUuid().toString(QUuid::WithoutBraces));
#else
        server_.listen(directory_.filePath("input.sock"));
#endif
        connect(&server_,&QLocalServer::newConnection,this,[this]{
            auto* socket=server_.nextPendingConnection();
            if(socket_) {socket->abort();socket->deleteLater();return;}
            socket_=socket;socket_->setReadBufferSize(65536);authed_=false;input_.clear();sequence_=0;
            connect(socket_,&QLocalSocket::readyRead,this,[this]{read();});
            connect(socket_,&QLocalSocket::disconnected,this,[this,socket]{abort();if(socket_==socket)socket_=nullptr;socket->deleteLater();});
        });
        timer_.setInterval(4);connect(&timer_,&QTimer::timeout,this,[this]{tick();});timer_.start();
    }
    ~PerformanceInput() override {abort();if(socket_){socket_->disconnect(this);socket_->abort();}server_.close();}
    QJsonObject endpoint() const {return {{"schema",2},{"path",server_.fullServerName()},{"token",token_},{"active",authed_},{"sequence",double(sequence_)},{"touchingA",decks_[0].touching},{"generationA",double(decks_[0].generation)}};}
    void reset(){abort();token_=QUuid::createUuid().toString(QUuid::WithoutBraces);if(socket_)socket_->abort();}
private:
    struct Deck {quint64 generation=0;bool touching=false,vinyl=true,preview=false;int adjust=0;double loopStart=0,loopEnd=0,seekPosition=0,seekAt=0;double displacement=0,lastMotion=0,lastCapture=0,speed=0,releaseAt=0,cue=0,range=.16,bendUntil=0;};
    // 自分が握っていないデッキへ介入しない。ネイティブの解放はネイティブのsequenceを伴い、
    // 新しいポインタ操作のジェスチャーやUIが設定したpitchbendを巻き込まない。
    void abort(){for(int i=0;i<4;i++){auto& d=decks_[i];const bool owned=d.touching||d.releaseAt;
        if(owned&&sequence_)backend_->scratch(i,"abort",0,0,false,sequence_);
        if(d.preview)backend_->play(i,false);
        if(owned||d.bendUntil)backend_->pitchbend(i,0);
        d={};}held_.fill(false);msb_.fill(-1);running_=0;dataCount_=0;authed_=false;}
    void finish(int i){auto& d=decks_[i];if(d.touching||d.releaseAt)backend_->scratch(i,"end",d.displacement,deckclock::monotonicUs(),false,sequence_);d.touching=false;d.releaseAt=0;}
    void publish(){
        if(!socket_||!authed_)return;
        if(socket_->bytesToWrite()>16384){socket_->abort();return;}
        QJsonArray decks;for(int i=0;i<4;i++){const auto state=state_(i);decks.append(QJsonObject{{"generation",state["loadGeneration"]},{"cueMs",decks_[i].cue},{"range",decks_[i].range*100}});}
        socket_->write(QJsonDocument(QJsonObject{{"nativeUs",deckclock::monotonicUs()},{"decks",decks}}).toJson(QJsonDocument::Compact)+'\n');
    }
    void read(){
        if(!socket_)return;
        input_+=socket_->read(65536-input_.size());
        if(input_.size()>=65536){socket_->abort();return;}
        if(!authed_){
            const auto end=input_.indexOf('\n');if(end<0)return;
            const auto p=QJsonDocument::fromJson(input_.left(end)).object();input_.remove(0,end+1);
            if(p["token"]!=token_||!allowed_()){socket_->abort();return;}
            const auto sensitivity=p["sensitivity"].toDouble(.1);
            if(!std::isfinite(sensitivity)||sensitivity<=0||sensitivity>20){socket_->abort();return;}
            sensitivity_=sensitivity;
            const auto ranges=p["ranges"].toArray(),cues=p["cues"].toArray();
            for(int i=0;i<4;i++){decks_[i].range=i<ranges.size()?std::clamp(ranges[i].toDouble(16),6.0,75.0)/100:.16;decks_[i].cue=i<cues.size()?std::max(0.0,cues[i].toDouble()):0;}
            authed_=true;lastInput_=deckclock::monotonicUs();publish();
        }
        // Fixed 48-byte records: seq, native capture, four load generations,
        // packed three-byte MIDI. Source clock provenance stays in Rust.
        unsigned consumed=0;
        while(input_.size()>=48 && consumed++<64){
            const auto* b=reinterpret_cast<const uchar*>(input_.constData());
            const auto sequence=qFromLittleEndian<quint64>(b);
            const double captured=double(qFromLittleEndian<quint64>(b+8));
            const auto now=deckclock::monotonicUs();
            if(sequence<=sequence_||captured>now+10000||now-captured>500000||!allowed_()){socket_->abort();return;}
            sequence_=sequence;lastInput_=now;
            for(int i=0;i<4;i++)expected_[i]=qFromLittleEndian<quint32>(b+16+i*4);
            const unsigned length=b[32];if(length>3){socket_->abort();return;}
            for(unsigned i=0;i<length;i++)feed(b[33+i],captured);
            input_.remove(0,48);
        }
    }
    void feed(unsigned byte,double captured){
        if(byte>=0xf8)return;
        if(byte&0x80){running_=byte<0xf0?byte:0;dataCount_=0;return;}
        if(!running_)return;
        data_[dataCount_++]=byte;
        if(dataCount_==((running_&0xe0)==0xc0?1u:2u)){decode(running_,data_[0],data_[1],captured);dataCount_=0;}
    }
    void decode(unsigned status,unsigned key,unsigned value,double captured){
        const unsigned channel=status&15,type=status&0xf0;
        if(type==0x90||type==0x80){
            const bool pressed=type==0x90&&value>0;const unsigned id=channel*128+key;
            if(held_[id]==pressed)return;held_[id]=pressed;
            if(channel>=4)return;
            const int i=channel;auto& d=decks_[i];const auto state=state_(i);
            if(expected_[i]!=state["loadGeneration"].toDouble()||!state["track"].isObject())return;
            if(key==0x17&&pressed){d.vinyl=!d.vinyl;if(!d.vinyl)finish(i);return;}
            if(key==0x60&&pressed){const double ranges[]={.06,.10,.16,.75};for(int r=0;r<4;r++)if(std::abs(d.range-ranges[r])<.001){d.range=ranges[(r+1)%4];break;}return;}
            if((key==0x4c||((key==0x4d||key==0x50)&&held_[channel*128+0x3f]))&&pressed&&state["loopRegion"].toObject()["enabled"].toBool()){
                const int target=key==0x4c?1:2;d.adjust=d.adjust==target?0:target;finish(i);const auto loop=state["loopRegion"].toObject();d.loopStart=loop["startMs"].toDouble();d.loopEnd=loop["endMs"].toDouble();return;
            }
            if(key==0x36||key==0x67){
                if(d.adjust)return;
                if(pressed&&d.vinyl){if(d.releaseAt){d.releaseAt=0;d.touching=true;return;}finish(i);backend_->pitchbend(i,0);d.touching=true;d.displacement=0;d.lastCapture=captured;d.lastMotion=deckclock::monotonicUs();d.speed=0;backend_->scratch(i,"begin",0,captured,false,sequence_);}
                else if(d.speed<-.75&&deckclock::monotonicUs()-d.lastMotion<60000)d.releaseAt=deckclock::monotonicUs()+60000;
                else finish(i);return;
            }
            if((key==0x0b||key==0x47)&&pressed){if(d.preview){d.preview=false;return;}backend_->play(i,!backend_->playing(i));return;}
            if(key==0x48&&pressed){backend_->seek(i,0);return;}
            if(key==0x1a&&pressed){backend_->keylock(i,!state["keylock"].toBool());return;}
            if(key==0x0c){
                if(pressed){if(backend_->playing(i)){backend_->play(i,false);backend_->seek(i,d.cue);}
                    else if(std::abs(backend_->positionMs(i)-d.cue)>20)d.cue=backend_->positionMs(i);
                    else{d.preview=true;backend_->play(i,true);}}
                else if(d.preview){d.preview=false;backend_->play(i,false);backend_->seek(i,d.cue);}return;
            }
            return;
        }
        if(type!=0xb0)return;
        if(channel<4 && (key==0x22||key==0x23||key==0x21||key==0x1f||key==0x26||key==0x29)){
            const int i=channel;auto& d=decks_[i];const auto state=state_(i);
            if(expected_[i]!=state["loadGeneration"].toDouble()||!state["track"].isObject())return;
            const double count=int(value)-64;if(!count)return;
            if(d.adjust&&state["loopRegion"].isObject()){
                if(d.adjust==1)d.loopStart=std::clamp(d.loopStart+count*sensitivity_,0.0,d.loopEnd-1);else d.loopEnd=std::clamp(d.loopEnd+count*sensitivity_,d.loopStart+1,state["track"].toObject()["durationMs"].toDouble());
                backend_->loop(i,d.loopStart,d.loopEnd);backend_->loopEnable(i,true);return;
            }
            const bool search=key==0x26||key==0x29;
            if(key==0x23||search)finish(i);if(d.releaseAt&&count>0)finish(i);
            if(d.touching||d.releaseAt){
                const double next=std::clamp(d.displacement+count*sensitivity_,-60000.0,60000.0),interval=(captured-d.lastCapture)/1000;
                if(interval>0)d.speed=interval>120?0:(next-d.displacement)/interval;
                d.displacement=next;d.lastCapture=captured;d.lastMotion=deckclock::monotonicUs();
                if(d.releaseAt)d.releaseAt=d.lastMotion+60000;
                backend_->scratch(i,"move",next,captured,false,sequence_);
            }else if(search||!backend_->playing(i)){
                const double now=deckclock::monotonicUs(),origin=now-d.seekAt<200000?d.seekPosition:backend_->positionMs(i);
                d.seekPosition=std::clamp(origin+count*(search?100:sensitivity_),-60000.0,state["track"].toObject()["durationMs"].toDouble());d.seekAt=now;backend_->seek(i,d.seekPosition);
            }
            else{backend_->pitchbend(i,std::clamp(count*.002,-.75,.75));d.bendUntil=deckclock::monotonicUs()+120000;}
            return;
        }
        const unsigned base=key>=32?key-32:key;
        if(!((channel==6&&base==31)||(channel<4&&(base==0||base==5||base==4||base==7||base==11||base==15||base==19))))return;
        const unsigned id=channel*32+base;if(key<32){msb_[id]=value;return;}const int high=msb_[id];msb_[id]=-1;if(high<0)return;
        const double amount=(high*128+value)/16383.0;
        if(channel==6){backend_->crossfader(amount*2-1);return;}
        const int i=channel;if(expected_[i]!=state_(i)["loadGeneration"].toDouble())return;
        if(base==0||base==5){backend_->pitchbend(i,0);decks_[i].bendUntil=0;backend_->tempo(i,1+(amount-.5)*2*decks_[i].range);}
        else if(base==4)backend_->trim(i,amount*2);
        else if(base==19)backend_->gain(i,amount);
        else backend_->eq(i,base==7?"high":base==11?"mid":"low",amount<=.5?amount*2:1+(amount-.5)*6);
    }
    void tick(){
        if(!authed_)return;const double now=deckclock::monotonicUs();
        if(!allowed_()||now-lastInput_>1500000){socket_->abort();return;}
        for(int i=0;i<4;i++){auto& d=decks_[i];const auto generation=quint64(state_(i)["loadGeneration"].toDouble());
            if(generation!=d.generation){if(d.generation){const bool owned=d.touching||d.releaseAt;
                if(owned&&sequence_)backend_->scratch(i,"abort",0,0,false,sequence_);
                if(owned||d.bendUntil)backend_->pitchbend(i,0);
                const auto range=d.range;d={};d.range=range;}d.generation=generation;}
            if(d.releaseAt&&now>=d.releaseAt)finish(i);
            if(d.bendUntil&&now>=d.bendUntil){backend_->pitchbend(i,0);d.bendUntil=0;}
            if(d.touching&&!d.releaseAt&&now-d.lastMotion>200000&&now-lastHeartbeat_>200000)backend_->scratch(i,"move",d.displacement,now,true,sequence_);
        }
        if(now-lastHeartbeat_>200000)lastHeartbeat_=now;
        if(now-lastPublish_>20000){publish();lastPublish_=now;}
        if(input_.size()>=48)read();
    }
    PlaybackBackend* backend_;State state_;std::function<bool()> allowed_;
    QTemporaryDir directory_;QLocalServer server_;QLocalSocket* socket_=nullptr;QTimer timer_;
    QString token_=QUuid::createUuid().toString(QUuid::WithoutBraces);QByteArray input_;
    std::array<Deck,4> decks_{};std::array<quint32,4> expected_{};
    std::array<int,512> msb_=[] {std::array<int,512>a;a.fill(-1);return a;}();
    std::array<bool,2048> held_{};unsigned running_=0,dataCount_=0;std::array<unsigned,2> data_{};
    quint64 sequence_=0;bool authed_=false;double sensitivity_=.1,lastInput_=0,lastPublish_=0,lastHeartbeat_=0;
};
