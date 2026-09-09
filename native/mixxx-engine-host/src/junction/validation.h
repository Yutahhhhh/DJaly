#pragma once
#include <vector>
#include <cmath>
#include <algorithm>
#include <array>
namespace junction {
struct AudioMatch {bool ready=false;int lagFrames=0;double correlation=0,levelDb=0,errorRms=0,fractionalLagFrames=0;};
// Comparison only uses PCM before the agreed ownership frame H. Silence has
// an absolute-error gate instead of an undefined correlation coefficient.
inline AudioMatch compareAudio(const std::vector<float>& a,const std::vector<float>& b,int maxLag=256) {
    AudioMatch result;if(a.size()<4096||a.size()!=b.size()||a.size()%2||maxLag<0||maxLag>512||int(a.size()/2)<=2*(maxLag+32))return result;
    const int frames=int(a.size()/2),guard=maxLag+32;
    double best=-2;int bestLag=0;double bestA=0,bestB=0,bestError=0;
    struct Score{int lag;double correlation,a,b,error;};std::vector<Score> scores;scores.reserve(size_t(maxLag*2+1));
    for(int lag=-maxLag;lag<=maxLag;++lag){double aa=0,bb=0,ab=0,err=0;
        for(int i=guard;i<frames-guard;++i)for(int c=0;c<2;++c){const double x=a[i*2+c],y=b[(i+lag)*2+c];if(!std::isfinite(x)||!std::isfinite(y))return result;aa+=x*x;bb+=y*y;ab+=x*y;err+=(x-y)*(x-y);}
        const double corr=aa<1e-16&&bb<1e-16?1:ab/std::sqrt(std::max(1e-30,aa*bb));
        scores.push_back({lag,corr,aa,bb,err});
        if(corr>best+1e-12||(std::abs(corr-best)<1e-12&&std::abs(lag)<std::abs(bestLag))){best=corr;bestLag=lag;bestA=aa;bestB=bb;bestError=err;}
    }
    // Periodic audio has several valid correlation peaks. Select the closest
    // local peak that meets the same readiness correlation threshold; a tiny
    // fractional-sample SRC difference must not select a distant whole cycle.
    for(size_t i=1;i+1<scores.size();++i){const auto& score=scores[i];
        if(score.correlation>=.999&&score.correlation>=scores[i-1].correlation&&score.correlation>=scores[i+1].correlation&&std::abs(score.lag)<std::abs(bestLag)){
            bestLag=score.lag;best=score.correlation;bestA=score.a;bestB=score.b;bestError=score.error;
        }
    }
    double fractionalLag=bestLag;
    // At 44.1 -> 48 kHz the two capture grids can differ by less than one
    // sample. Measure that residual with band-limited interpolation instead
    // of mistaking broadband phase error for a different DSP state. The
    // correlation, level and one-sample readiness limits remain unchanged.
    if(best>.5&&best<.9995&&std::abs(bestLag)<maxLag){
        const auto scoreFraction=[&](double fraction,int stride){
            std::array<double,32> kernel{};double sum=0;
            const auto sinc=[](double x){return std::abs(x)<1e-12?1.0:std::sin(3.141592653589793*x)/(3.141592653589793*x);};
            for(int k=-15;k<=16;k++){const double x=k-fraction;kernel[k+15]=sinc(x)*sinc(x/16);sum+=kernel[k+15];}
            for(auto& value:kernel)value/=sum;
            double aa=0,bb=0,ab=0,error=0;
            for(int i=guard;i<frames-guard;i+=stride)for(int channel=0;channel<2;channel++){
                const double x=a[i*2+channel];double y=0;for(int k=-15;k<=16;k++)y+=kernel[k+15]*b[(i+bestLag+k)*2+channel];
                aa+=x*x;bb+=y*y;ab+=x*y;error+=(x-y)*(x-y);
            }
            return Score{bestLag,ab/std::sqrt(std::max(1e-30,aa*bb)),aa,bb,error};
        };
        double fraction=0,coarseBest=scoreFraction(0,4).correlation;
        for(int step=-8;step<=8;step++){
            const double trial=step/16.0;const auto score=scoreFraction(trial,4);
            if(score.correlation>coarseBest){coarseBest=score.correlation;fraction=trial;}
        }
        const double center=fraction;
        for(int step=-4;step<=4;step++){
            const double trial=center+step/128.0;const auto score=scoreFraction(trial,4);
            if(score.correlation>coarseBest){coarseBest=score.correlation;fraction=trial;}
        }
        const auto refined=scoreFraction(fraction,1);
        if(refined.correlation>best){fractionalLag=bestLag+fraction;best=refined.correlation;bestA=refined.a;bestB=refined.b;bestError=refined.error;}
    }
    result.fractionalLagFrames=fractionalLag;
    result.lagFrames=bestLag;result.correlation=best;result.levelDb=10*std::log10(std::max(1e-20,bestB)/std::max(1e-20,bestA));result.errorRms=std::sqrt(bestError/double((frames-2*guard)*2));
    const bool silence=std::max(bestA,bestB)/double((frames-2*guard)*2)<1e-10;
    result.ready=std::abs(fractionalLag)<=1 && (silence?result.errorRms<1e-5:best>=0.999&&std::abs(result.levelDb)<=0.25);
    return result;
}
}
