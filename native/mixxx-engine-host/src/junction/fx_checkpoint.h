#pragma once
#include "ddj_checkpoint.h"
#include <functional>
#include <memory>
class EffectSlot;
namespace junction::fx {
inline constexpr auto format="plumdeck-fx-v1";
inline constexpr auto fingerprint="mixxx-3ebac449-fx-state2";
inline constexpr unsigned maxStateBytes=4*1024*1024;
struct Route {
    QString input,output;
    unsigned enable=0,chainEnable=0;float chainMix=0;
    std::vector<uint8_t> bytes;unsigned size=0;
};
struct Slot {
    QString group,processor;
    bool chainEnabled=false;int mixMode=0;unsigned flags=0;float mix=0;
    std::vector<Route> routes;
};
using Snapshot=std::vector<Slot>;
bool supported(const QString& processor);
Slot prepare(EffectSlot&,const std::function<QString(int)>&);
bool capture(EffectSlot&,Slot&);
bool restore(EffectSlot&,const Slot&,const std::function<int(const QString&)>&);
bool validateRoute(const QString&,const Route&);
inline bool write(const QString& path,const Snapshot& states){
    if(states.empty()||states.size()>9)return false;
    QSaveFile file(path);if(!file.open(QIODevice::WriteOnly))return false;QDataStream out(&file);out.setByteOrder(QDataStream::LittleEndian);
    out.writeRawData("DJFX0001",8);ddj::text(out,fingerprint);out<<quint32(states.size());
    for(const auto& slot:states){
        if(!supported(slot.processor)||slot.routes.empty()||slot.routes.size()>8)return false;
        ddj::text(out,slot.group);ddj::text(out,slot.processor);out<<quint8(slot.chainEnabled)<<qint32(slot.mixMode)<<quint32(slot.flags)<<slot.mix<<quint32(slot.routes.size());
        for(const auto& route:slot.routes){
            if(!route.size||route.size>route.bytes.size()||route.size>maxStateBytes)return false;
            ddj::text(out,route.input);ddj::text(out,route.output);out<<quint32(route.enable)<<quint32(route.chainEnable)<<route.chainMix<<quint32(route.size);
            out.writeRawData(reinterpret_cast<const char*>(route.bytes.data()),route.size);
        }
    }
    return out.status()==QDataStream::Ok&&file.size()<=64*1024*1024&&file.commit();
}
inline bool read(const QString& path,Snapshot* result){
    QFile file(path);if(!file.open(QIODevice::ReadOnly)||file.size()<32||file.size()>64*1024*1024)return false;
    QDataStream in(&file);in.setByteOrder(QDataStream::LittleEndian);char magic[8];QString identity;quint32 count=0;
    if(in.readRawData(magic,8)!=8||QByteArray(magic,8)!="DJFX0001"||!ddj::text(in,&identity)||identity!=fingerprint)return false;
    in>>count;if(!count||count>9)return false;Snapshot states;
    for(unsigned n=0;n<count;n++){
        Slot slot;quint8 enabled=0;qint32 mode=0;quint32 routes=0,flags=0;
        if(!ddj::text(in,&slot.group)||!ddj::text(in,&slot.processor)||!supported(slot.processor))return false;
        for(const auto& old:states)if(old.group==slot.group)return false;
        in>>enabled>>mode>>flags>>slot.mix>>routes;if(enabled>1||flags>1||mode<0||mode>1||!ddj::finite(slot.mix)||slot.mix<0||slot.mix>1||!routes||routes>8)return false;
        slot.chainEnabled=enabled;slot.mixMode=mode;slot.flags=flags;
        for(unsigned i=0;i<routes;i++){
            Route route;quint32 enable=0,chain=0,size=0;
            if(!ddj::text(in,&route.input)||!ddj::text(in,&route.output))return false;
            for(const auto& old:slot.routes)if(old.input==route.input&&old.output==route.output)return false;
            in>>enable>>chain>>route.chainMix>>size;if(enable>3||chain>3||!ddj::finite(route.chainMix)||route.chainMix<0||route.chainMix>1||!size||size>maxStateBytes||size>file.bytesAvailable())return false;
            route.enable=enable;route.chainEnable=chain;route.size=size;route.bytes.resize(size);
            if(in.readRawData(reinterpret_cast<char*>(route.bytes.data()),size)!=int(size)||!validateRoute(slot.processor,route))return false;
            slot.routes.push_back(std::move(route));
        }
        states.push_back(std::move(slot));
    }
    if(in.status()!=QDataStream::Ok||!file.atEnd())return false;if(result)*result=std::move(states);return true;
}
}
