#pragma once
#include "soundtouch_state.h"
#include "rubberband_state.h"
#include "ddj_checkpoint.h"
#include <QFile>
#include <QSaveFile>
class EngineBuffer;
namespace junction::keylock {
inline constexpr auto format="djaly-keylock-v1";
inline constexpr auto fingerprint="mixxx-3ebac449-st241-rb400-state2";
struct State {
    unsigned deck=0,logSize=0;st::State processor;rb::State rubberband;
    bool usesRubberBand=false;int remainingPadding=0;
    double position=0,readerPosition=0,speed=0,actualSpeed=0,tempo=1,pitch=1,base=1,rate=1;
    double scaleBase=1,scaleTempo=1,scalePitch=1,effectiveRate=1;
    bool reverse=false,backwards=false;
    std::array<std::array<double,2>,2048> readLog{};
};
using Snapshot=std::vector<State>;
class Access;
bool active(EngineBuffer&);
bool capture(EngineBuffer&,State&);
bool restore(EngineBuffer&,const State&);
inline bool valid(const State& s){
    if(s.deck>=4||s.logSize>s.readLog.size()||(s.usesRubberBand?(!s.rubberband.size||s.rubberband.size>s.rubberband.bytes.size()):!st::valid(s.processor))||s.remainingPadding<0||s.remainingPadding>65536)return false;
    for(double value:{s.position,s.readerPosition,s.speed,s.actualSpeed,s.tempo,s.pitch,s.base,s.rate,s.scaleBase,s.scaleTempo,s.scalePitch,s.effectiveRate})if(!ddj::finite(value))return false;
    if(s.position < -5760000||s.position>1e12||s.readerPosition < -11520000||s.readerPosition>2e12||std::abs(s.speed)>100||std::abs(s.rate)>256||s.scaleBase<=0||s.scaleBase>8||s.scaleTempo<=0||s.scaleTempo>100||std::abs(s.scalePitch)>256||std::abs(s.effectiveRate)>256)return false;
    for(unsigned i=0;i<s.logSize;i++)for(double value:s.readLog[i])if(!ddj::finite(value)||value < -11520000||value>2e12)return false;
    return true;
}
inline bool write(const QString& path,const Snapshot& snapshot){
    if(snapshot.empty()||snapshot.size()>4)return false;
    QSaveFile file(path);if(!file.open(QIODevice::WriteOnly))return false;QDataStream out(&file);out.setByteOrder(QDataStream::LittleEndian);
    out.writeRawData("DJKEY001",8);ddj::text(out,QString::fromLatin1(fingerprint));out<<quint32(snapshot.size());
    for(const auto& s:snapshot){if(!valid(s))return false;out<<quint32(s.deck)<<s.position<<s.readerPosition<<s.speed<<s.actualSpeed<<s.tempo<<s.pitch<<s.base<<s.rate<<s.scaleBase<<s.scaleTempo<<s.scalePitch<<s.effectiveRate<<quint8(s.reverse)<<quint8(s.backwards)<<quint32(s.logSize);
        for(unsigned i=0;i<s.logSize;i++)out<<s.readLog[i][0]<<s.readLog[i][1];out<<quint8(s.usesRubberBand)<<qint32(s.remainingPadding);
        if(s.usesRubberBand){out<<quint32(s.rubberband.size);out.writeRawData(reinterpret_cast<const char*>(s.rubberband.bytes.data()),s.rubberband.size);}else st::write(out,s.processor);
    }
    return out.status()==QDataStream::Ok&&file.size()<=24*1024*1024&&file.commit();
}
inline bool read(const QString& path,Snapshot* result){
    QFile file(path);if(!file.open(QIODevice::ReadOnly)||file.size()<32||file.size()>24*1024*1024)return false;
    QDataStream in(&file);in.setByteOrder(QDataStream::LittleEndian);char magic[8];QString identity;quint32 count=0;
    if(in.readRawData(magic,8)!=8||QByteArray(magic,8)!="DJKEY001"||!ddj::text(in,&identity)||identity!=QString::fromLatin1(fingerprint))return false;
    in>>count;if(!count||count>4)return false;Snapshot snapshot;unsigned seen=0;
    for(unsigned n=0;n<count;n++){State s;quint32 deck=0,size=0;quint8 reverse=0,backwards=0;
        in>>deck>>s.position>>s.readerPosition>>s.speed>>s.actualSpeed>>s.tempo>>s.pitch>>s.base>>s.rate>>s.scaleBase>>s.scaleTempo>>s.scalePitch>>s.effectiveRate>>reverse>>backwards>>size;
        if(deck>=4||(seen&(1u<<deck))||reverse>1||backwards>1||size>s.readLog.size())return false;seen|=1u<<deck;s.deck=deck;s.logSize=size;s.reverse=reverse;s.backwards=backwards;
        for(unsigned i=0;i<size;i++)in>>s.readLog[i][0]>>s.readLog[i][1];quint8 rb=0;qint32 padding=0;in>>rb>>padding;if(rb>1)return false;s.usesRubberBand=rb;s.remainingPadding=padding;
        if(rb){quint32 length=0;in>>length;if(!length||length>s.rubberband.bytes.size())return false;s.rubberband.size=length;if(in.readRawData(reinterpret_cast<char*>(s.rubberband.bytes.data()),length)!=int(length))return false;}else if(!st::read(in,s.processor))return false;
        if(!valid(s)||(s.usesRubberBand&&!rb::validate(s.rubberband)))return false;snapshot.push_back(std::move(s));
    }
    if(in.status()!=QDataStream::Ok||!file.atEnd())return false;if(result)*result=std::move(snapshot);return true;
}
}
