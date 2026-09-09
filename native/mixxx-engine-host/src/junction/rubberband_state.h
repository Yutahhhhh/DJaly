#pragma once
#include <vector>
#include <array>
#include <cstdint>
#include <cstring>
#include <type_traits>
#include <bit>
#include <limits>
namespace RubberBand { class RubberBandStretcher;class R2Stretcher;class Resampler;template<class T>class RingBuffer;template<class T>class MovingMedian; }
namespace junction::rb {
constexpr size_t capacity=4*1024*1024;
struct State {std::vector<uint8_t> bytes;size_t size=0;State():bytes(capacity){};};
class Cursor {
public:
    uint8_t* data;size_t size,pos=0;bool reading,ok=true;
    Cursor(uint8_t* bytes,size_t length,bool read):data(bytes),size(length),reading(read){}
    void require(bool condition){ok=ok&&condition;}
    template<class T>void number(T& value){
        if(!ok||pos+sizeof(T)>size){ok=false;return;}
        if constexpr(std::is_same_v<T,bool>){if(reading){if(data[pos]>1)ok=false;value=data[pos]!=0;}else data[pos]=value;pos++;}
        else{
            static_assert(std::is_arithmetic_v<T>||std::is_enum_v<T>);
            using U=std::conditional_t<sizeof(T)==8,uint64_t,std::conditional_t<sizeof(T)==4,uint32_t,std::conditional_t<sizeof(T)==2,uint16_t,uint8_t>>>;
            U bits=0;if(!reading)std::memcpy(&bits,&value,sizeof(T));
            for(size_t i=0;i<sizeof(T);i++){if(reading)bits|=U(data[pos+i])<<(8*i);else data[pos+i]=uint8_t(bits>>(8*i));}pos+=sizeof(T);
            if(reading)std::memcpy(&value,&bits,sizeof(T));
            if constexpr(std::is_floating_point_v<T>){constexpr U mask=sizeof(T)==8?U(0x7ff0000000000000ULL):U(0x7f800000U);if((bits&mask)==mask)ok=false;}
        }
    }
    template<class... T>void operator()(T&... values){(number(values),...);}
    template<class T>void equal(T expected){T wire=expected;number(wire);require(wire==expected);}
    template<class T>void array(T* values,size_t count){
        if(!ok)return;
        if(count>capacity/sizeof(T)||!values||count*sizeof(T)>size-pos){require(count==0);return;}
        if constexpr(std::endian::native==std::endian::little&&std::is_arithmetic_v<T>&&!std::is_same_v<T,bool>){
            if(reading)std::memcpy(values,data+pos,count*sizeof(T));else std::memcpy(data+pos,values,count*sizeof(T));pos+=count*sizeof(T);
            if constexpr(std::is_floating_point_v<T>){using U=std::conditional_t<sizeof(T)==8,uint64_t,uint32_t>;constexpr U mask=sizeof(T)==8?U(0x7ff0000000000000ULL):U(0x7f800000U);for(size_t i=0;i<count;i++){volatile U bits=std::bit_cast<U>(values[i]);if((bits&mask)==mask){ok=false;return;}}}
        }else for(size_t i=0;i<count&&ok;i++)number(values[i]);
    }
};
class Access {
public:
    static bool engine(RubberBand::RubberBandStretcher&,Cursor&);
    static bool r2(RubberBand::R2Stretcher&,Cursor&);
    static bool resampler(RubberBand::Resampler&,Cursor&);
    static bool sinc(void*,Cursor&);
    template<class T>static void ring(RubberBand::RingBuffer<T>&,Cursor&);
    template<class T>static void median(RubberBand::MovingMedian<T>&,Cursor&);
};
bool capture(RubberBand::RubberBandStretcher&,State&);
bool restore(RubberBand::RubberBandStretcher&,const State&);
bool validate(const State&);
}
