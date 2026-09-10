#include "../sound_file.h"
#include "private_preview.h"
#include <sndfile.h>
#include <QFileInfo>
#include <array>
#include <atomic>
#include <thread>
#include <mutex>
#include <chrono>
#include <cmath>
#include <algorithm>
namespace junction {
struct PrivatePreview::Impl {
    static constexpr unsigned blockFrames=256, capacity=32;
    struct Block { std::array<float,blockFrames*2> pcm{}; unsigned count=0, generation=0; double sourceFrame=0, ratio=1; };
    std::array<Block,capacity> ring;
    std::atomic<unsigned> read{0},write{0},generation{1};
    std::atomic<bool> stopping{false},playing{false},ready{false};
    std::atomic<double> position{0},duration{0};
    std::atomic<unsigned> sourceRate{44100};
    std::atomic<float> gain{0.7f};
    mutable std::mutex mutex;
    QString path,error;
    double seekMs=0;
    unsigned offset=0; // callback-owned
    float blend=0;
    std::thread worker;
    Impl():worker([this]{run();}){}
    ~Impl(){stopping.store(true);worker.join();}
    void run(){
        SNDFILE* file=nullptr; SF_INFO info{}; unsigned seen=0; double cursor=0;
        std::array<float,16384> input{};
        while(!stopping.load()) {
            const unsigned gen=generation.load(std::memory_order_acquire);
            if(gen!=seen){
                QString next; double target;
                {std::lock_guard<std::mutex> lock(mutex);next=path;target=seekMs;}
                if(file)sf_close(file);file=nullptr; info={};
                if(!next.isEmpty())file=openSoundFile(next,SFM_READ,&info);
                if(file && (info.channels<1||info.channels>8||info.samplerate<8000||info.samplerate>192000)){sf_close(file);file=nullptr;}
                {std::lock_guard<std::mutex> lock(mutex);if(gen==generation.load())error=file?QString():next.isEmpty()?QString():QStringLiteral("Private preview decoder could not open this file");}
                if(gen==generation.load()){
                    sourceRate.store(file?info.samplerate:44100);duration.store(file?1000.0*info.frames/info.samplerate:0);
                    ready.store(file!=nullptr);position.store(target);
                }
                cursor=file?std::clamp(target*info.samplerate/1000.0,0.0,double(info.frames)):0;
                seen=gen;
            }
            const auto w=write.load(std::memory_order_relaxed);
            if(!file||!playing.load()||w-read.load(std::memory_order_acquire)>=capacity){std::this_thread::sleep_for(std::chrono::milliseconds(2));continue;}
            if(cursor>=info.frames){std::this_thread::sleep_for(std::chrono::milliseconds(2));continue;}
            const double ratio=double(info.samplerate)/44100.0;
            const auto first=sf_count_t(std::floor(cursor));
            const auto count=std::min<sf_count_t>(sf_count_t(std::ceil(blockFrames*ratio))+2,input.size()/info.channels);
            if(sf_seek(file,first,SEEK_SET)!=first){std::lock_guard<std::mutex> lock(mutex);error="Private preview seek failed";ready.store(false);playing.store(false);continue;}
            const auto got=sf_readf_float(file,input.data(),count);
            auto& block=ring[w%capacity];block.count=0;block.generation=gen;block.sourceFrame=cursor;block.ratio=ratio;
            for(unsigned i=0;i<blockFrames && cursor+i*ratio<info.frames;++i){
                const double local=cursor+i*ratio-first;const auto n=sf_count_t(local);if(n>=got)break;
                const double fraction=local-n;const auto next=std::min(n+1,got-1);
                for(int ch=0;ch<2;++ch){const int c=std::min(ch,info.channels-1);block.pcm[i*2+ch]=float(input[n*info.channels+c]*(1-fraction)+input[next*info.channels+c]*fraction);}
                ++block.count;
            }
            cursor+=block.count*ratio;
            if(block.count)write.store(w+1,std::memory_order_release);
            else {std::lock_guard<std::mutex> lock(mutex);error="Private preview read failed";ready.store(false);playing.store(false);}
        }
        if(file)sf_close(file);
    }
};
PrivatePreview::PrivatePreview():d(std::make_unique<Impl>()){}
PrivatePreview::~PrivatePreview()=default;
QString PrivatePreview::command(const QString& op,const QJsonObject& p){
    std::lock_guard<std::mutex> lock(d->mutex);
    if(op.endsWith(".load")){
        const auto path=p["path"].toString();if(!QFileInfo(path).isAbsolute()||!QFileInfo(path).isFile())return "Choose an existing local audio file";
        d->path=path;d->seekMs=0;d->error.clear();d->ready.store(false);d->playing.store(false);d->generation.fetch_add(1,std::memory_order_release);return {};
    }
    if(op.endsWith(".seek")){
        const auto value=p.contains("positionMs")?p["positionMs"]:p["ms"];
        if(!value.isDouble()||!std::isfinite(value.toDouble())||value.toDouble()<0||value.toDouble()>d->duration.load())return "Invalid private preview position";
        d->seekMs=value.toDouble();d->generation.fetch_add(1,std::memory_order_release);return {};
    }
    if(op.endsWith(".play")){if(!d->ready.load())return "Private preview is not ready";d->playing.store(p.value("enabled").toBool(true));return {};}
    if(op.endsWith(".pause")||op.endsWith(".stop")){d->playing.store(false);return {};}
    if(op.endsWith(".gain")){const auto gain=p["gain"];if(!gain.isDouble()||!std::isfinite(gain.toDouble())||gain.toDouble()<0||gain.toDouble()>1)return "Expected private preview gain 0..1";d->gain.store(float(gain.toDouble()));return {};}
    if(op.endsWith(".unload")){d->path.clear();d->playing.store(false);d->ready.store(false);d->generation.fetch_add(1,std::memory_order_release);return {};}
    if(op.endsWith(".state"))return {};
    return "Unknown private preview operation";
}
QJsonObject PrivatePreview::state() const {
    std::lock_guard<std::mutex> lock(d->mutex);
    return {{"loaded",d->ready.load()},{"playing",d->playing.load()},{"positionMs",d->position.load()},{"durationMs",d->duration.load()},{"sourceSampleRateHz",int(d->sourceRate.load())},{"error",d->error}};
}
void PrivatePreview::mixPfl(float* stereo,unsigned frames) noexcept {
    if(!stereo)return;
    const auto gen=d->generation.load(std::memory_order_acquire);
    auto r=d->read.load(std::memory_order_relaxed);const auto end=d->write.load(std::memory_order_acquire);
    for(unsigned f=0;f<frames;++f){
        while(r!=end && (d->ring[r%Impl::capacity].generation!=gen||d->offset>=d->ring[r%Impl::capacity].count)){++r;d->offset=0;}
        const bool active=d->playing.load(std::memory_order_relaxed)&&r!=end;
        const float target=active?1.f:0.f;d->blend+=std::clamp(target-d->blend,-1.f/220,1.f/220);
        for(unsigned ch=0;ch<2;++ch){const float sample=active?d->ring[r%Impl::capacity].pcm[d->offset*2+ch]*d->gain.load(std::memory_order_relaxed):0.f;stereo[f*2+ch]=stereo[f*2+ch]*(1-d->blend)+sample*d->blend;}
        if(active){auto& b=d->ring[r%Impl::capacity];++d->offset;d->position.store((b.sourceFrame+d->offset*b.ratio)*1000.0/(b.ratio*44100.0),std::memory_order_relaxed);}
    }
    d->read.store(r,std::memory_order_release);
}
}
