#pragma once
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <functional>
#include <stdexcept>
#include <vector>
namespace waveform {
struct Bin {
    std::uint32_t count = 0;
    std::array<double,2> min{}, max{};
    std::array<std::array<double,2>,4> squares{};
    void merge(const Bin& b) {
        if (!b.count) return;
        for (unsigned c=0;c<2;++c) {
            min[c] = count ? std::min(min[c],b.min[c]) : b.min[c];
            max[c] = count ? std::max(max[c],b.max[c]) : b.max[c];
            for(unsigned f=0;f<4;++f) squares[f][c]+=b.squares[f][c];
        }
        count += b.count;
    }
};
struct Biquad {
    double b0,b1,b2,a1,a2,z1=0,z2=0;
    Biquad(double fs,double cutoff,bool high) {
        const double k=std::tan(3.14159265358979323846*cutoff/fs), q=std::sqrt(2.0);
        const double n=1/(1+q*k+k*k);
        b0=(high?1:k*k)*n; b1=(high?-2:2)*b0; b2=b0;
        a1=2*(k*k-1)*n; a2=(1-q*k+k*k)*n;
    }
    double process(double x) { const double y=b0*x+z1;z1=b1*x-a1*y+z2;z2=b2*x-a2*y;return y; }
};
/** Streaming double precision aggregates: no full-track PCM or pyramid in RAM. */
class Pyramid {
public:
    using Publish=std::function<void(unsigned,std::uint64_t,const std::vector<Bin>&)>;
    explicit Pyramid(double fs, Publish publish):publish_(std::move(publish)),
      filters_{{{Biquad(fs,250,false),Biquad(fs,250,true),Biquad(fs,2500,false),Biquad(fs,2500,true)},
                {Biquad(fs,250,false),Biquad(fs,250,true),Biquad(fs,2500,false),Biquad(fs,2500,true)}}}, bands_(fs>5000) {}
    void sample(double left,double right) {
        const double values[2]={left,right};
        for(unsigned c=0;c<2;++c) {
            const double x=values[c];
            if(!std::isfinite(x)) throw std::runtime_error("Non-finite decoded sample");
            base_.min[c]=base_.count?std::min(base_.min[c],x):x;
            base_.max[c]=base_.count?std::max(base_.max[c],x):x;
            base_.squares[0][c]+=x*x;
            if(bands_) {
                const double low=filters_[c][0].process(x), mid=filters_[c][2].process(filters_[c][1].process(x)), high=filters_[c][3].process(x);
                base_.squares[1][c]+=low*low; base_.squares[2][c]+=mid*mid; base_.squares[3][c]+=high*high;
            }
        }
        if(++base_.count==64) { append(0,base_);base_={}; }
    }
    void finish() {
        if(base_.count) {append(0,base_);base_={};}
        for(unsigned l=0;l<26;++l) {
            // Stop once a level contains a single bin covering the whole source.
            if(pending_[l].count && totals_[l]>1 && l<25) append(l+1,pending_[l]);
            pending_[l]={};
            flush(l);
        }
    }
    bool bands() const {return bands_;}
private:
    void append(unsigned l,const Bin& b) {
        ++totals_[l];tiles_[l].push_back(b);
        if(tiles_[l].size()==2048) flush(l);
        if(l==25)return;
        if(!pending_[l].count) pending_[l]=b;
        else {pending_[l].merge(b);append(l+1,pending_[l]);pending_[l]={};}
    }
    void flush(unsigned l) {
        if(tiles_[l].empty())return;
        publish_(l,indices_[l]++,tiles_[l]);tiles_[l].clear();
    }
    Publish publish_;
    std::array<std::array<Biquad,4>,2> filters_;
    bool bands_;
    Bin base_;
    std::array<Bin,26> pending_{};
    std::array<std::vector<Bin>,26> tiles_;
    std::array<std::uint64_t,26> indices_{},totals_{};
};
inline std::uint32_t crc32(const unsigned char* data, std::size_t size) {
    std::uint32_t crc=~0u;
    for(std::size_t i=0;i<size;++i){crc^=data[i];for(int bit=0;bit<8;++bit)crc=(crc>>1)^(0xedb88320u & (0u-(crc&1)));}
    return ~crc;
}
}
