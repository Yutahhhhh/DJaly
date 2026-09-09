#pragma once
#include <QDataStream>
#include <QFile>
#include <QSaveFile>
#include <QString>
#include <QStringList>
#include <array>
#include <vector>
#include <memory>
#include <functional>
#include <algorithm>
#include <bit>
namespace junction::ddj {
inline constexpr auto fingerprint="mixxx-3ebac449-ddj-state1";
inline constexpr qint64 maxAssetBytes=16*1024*1024;
struct State {
    unsigned version=1;
    std::vector<float> ring;
    size_t write=0,captured=0,loopLength=0,loopStart=0,loopRead=0;
    double phase=0,delay=0,lastBeats=0;
    std::array<double,2> low{},feedback{};
    std::array<double,6> oscillators{};
};
struct Route {QString input,output;unsigned rate=0;State state;};
struct Snapshot {QString processor;std::vector<Route> routes;};
class Processor;
inline std::vector<Processor*>& processors(){static std::vector<Processor*> value;return value;}
// Registry lifecycle is main-thread only; capture/restore require exclusive
// stopped graph ownership, not merely a guessed quiet audio instant.
class Processor {
public:
    Processor(){processors().push_back(this);}
    virtual ~Processor(){auto& all=processors();all.erase(std::remove(all.begin(),all.end(),this),all.end());}
    virtual QString checkpointId() const=0;
    virtual Snapshot prepare(const std::function<QString(int)>&) const=0;
    virtual bool captureInto(Snapshot&) const=0;
    virtual bool restore(const Snapshot&,const std::function<int(const QString&)>&)=0;
};
inline Processor* latest(const QString& id){auto& all=processors();for(auto i=all.rbegin();i!=all.rend();++i)if((*i)->checkpointId()==id)return *i;return nullptr;}
inline void text(QDataStream& out,const QString& value){const auto bytes=value.toUtf8();out<<quint16(bytes.size());out.writeRawData(bytes.constData(),bytes.size());}
inline bool text(QDataStream& in,QString* value){quint16 size=0;in>>size;if(size>256)return false;char bytes[256];if(in.readRawData(bytes,size)!=size)return false;*value=QString::fromUtf8(bytes,size);return true;}
inline bool write(const QString& path,const Snapshot& snapshot){
    if(snapshot.routes.empty()||snapshot.routes.size()>8)return false;
    QSaveFile file(path);if(!file.open(QIODevice::WriteOnly))return false;
    QDataStream out(&file);out.setByteOrder(QDataStream::LittleEndian);out.setFloatingPointPrecision(QDataStream::DoublePrecision);
    out.writeRawData("DJDDJ001",8);out<<quint32(1);text(out,QString::fromLatin1(fingerprint));text(out,snapshot.processor);out<<quint32(snapshot.routes.size());
    for(const auto& route:snapshot.routes){text(out,route.input);text(out,route.output);out<<quint32(route.rate);const auto& s=route.state;
        out<<quint32(s.ring.size());for(float value:s.ring)out<<quint32(std::bit_cast<quint32>(value));
        out<<quint64(s.write)<<quint64(s.captured)<<quint64(s.loopLength)<<quint64(s.loopStart)<<quint64(s.loopRead)<<s.phase<<s.delay<<s.lastBeats;
        for(double v:s.low)out<<v;for(double v:s.feedback)out<<v;for(double v:s.oscillators)out<<v;
    }
    return out.status()==QDataStream::Ok&&file.size()<=maxAssetBytes&&file.commit();
}
inline bool finite(const float& v){volatile quint32 bits=std::bit_cast<quint32>(v);return (bits&0x7f800000U)!=0x7f800000U;}
inline bool finite(const double& v){volatile quint64 bits=std::bit_cast<quint64>(v);return (bits&0x7ff0000000000000ULL)!=0x7ff0000000000000ULL;}
inline bool read(const QString& path,Snapshot* result){
    QFile file(path);if(!file.open(QIODevice::ReadOnly)||file.size()<32||file.size()>maxAssetBytes)return false;
    QDataStream in(&file);in.setByteOrder(QDataStream::LittleEndian);in.setFloatingPointPrecision(QDataStream::DoublePrecision);
    char magic[8];quint32 version=0,count=0;QString identity,processor;
    if(in.readRawData(magic,8)!=8||QByteArray(magic,8)!="DJDDJ001")return false;
    in>>version;if(version!=1||!text(in,&identity)||identity!=QString::fromLatin1(fingerprint)||!text(in,&processor)||!processor.startsWith("org.djaly.effects."))return false;
    const QStringList allowed={"lowcutecho","mtdelay","spiral","enigmajet","sliproll","roll","mobiussaw","mobiustri","tremolo"};
    if(!allowed.contains(processor.mid(QStringLiteral("org.djaly.effects.").size())))return false;
    const bool tremolo=processor=="org.djaly.effects.tremolo";
    in>>count;if(!count||count>8)return false;Snapshot snapshot;snapshot.processor=processor;
    for(quint32 i=0;i<count;++i){Route route;quint32 rate=0,samples=0;if(!text(in,&route.input)||!text(in,&route.output)||!route.input.startsWith('[')||!route.output.startsWith('['))return false;in>>rate>>samples;
        // Mixxx preallocates effect routes at its 96 kHz maximum even when
        // the live callback runs at 44.1/48 kHz. This is allocation capacity.
        if((rate!=44100&&rate!=48000&&rate!=96000)||samples!=(tremolo?0:rate*8)||qint64(samples)*4>file.bytesAvailable())return false;route.rate=rate;auto& s=route.state;s.ring.resize(samples);
        for(auto& sample:s.ring){quint32 bits=0;in>>bits;sample=std::bit_cast<float>(bits);if(!finite(sample))return false;}
        quint64 write=0,captured=0,length=0,start=0,cursor=0;in>>write>>captured>>length>>start>>cursor>>s.phase>>s.delay>>s.lastBeats;
        const auto capacity=rate*4;if(write>=capacity||captured>capacity||length>capacity||start>=capacity||!finite(s.phase)||s.phase<0||s.phase>=1||!finite(s.delay)||s.delay<0||s.delay>capacity||!finite(s.lastBeats)||s.lastBeats<0||s.lastBeats>16)return false;
        s.write=write;s.captured=captured;s.loopLength=length;s.loopStart=start;s.loopRead=cursor;
        for(auto& v:s.low){in>>v;if(!finite(v))return false;}for(auto& v:s.feedback){in>>v;if(!finite(v))return false;}for(auto& v:s.oscillators){in>>v;if(!finite(v)||v<0||v>=1)return false;}
        if(tremolo&&(s.loopRead>UINT32_MAX||s.captured>1||s.loopLength>1||s.low[0]<0||s.low[0]>1))return false;
        for(const auto& previous:snapshot.routes)if(previous.input==route.input&&previous.output==route.output)return false;
        snapshot.routes.push_back(std::move(route));
    }
    if(in.status()!=QDataStream::Ok||!file.atEnd())return false;if(result)*result=std::move(snapshot);return true;
}
}
