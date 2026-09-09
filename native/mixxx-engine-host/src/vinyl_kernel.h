#pragma once
#include <array>
#include <vector>
#include <cmath>
#include <algorithm>
namespace vinyl {
struct Bank {int taps;double rate;std::vector<float> coefficients;};
class Kernels {
public:
    static constexpr int phases=32;
    std::array<Bank,49> banks;
    Kernels(){
        constexpr double pi=3.14159265358979323846;
        for(unsigned b=0;b<banks.size();++b){
            auto& bank=banks[b];bank.rate=std::exp2(double(b)/8);bank.taps=2*int(std::ceil(64*bank.rate));
            bank.coefficients.resize((phases+1)*bank.taps);
            const double cutoff=.90/bank.rate;
            for(int phase=0;phase<=phases;phase++){
                double sum=0;
                for(int t=0;t<bank.taps;t++){
                    const double x=t-bank.taps/2+1-double(phase)/phases;
                    const double theta=2*pi*t/(bank.taps-1);
                    const double window=.35875-.48829*std::cos(theta)+.14128*std::cos(2*theta)-.01168*std::cos(3*theta);
                    const double c=window*(std::abs(x)<1e-12?cutoff:std::sin(pi*cutoff*x)/(pi*x));
                    bank.coefficients[phase*bank.taps+t]=float(c);sum+=c;
                }
                for(int t=0;t<bank.taps;t++)bank.coefficients[phase*bank.taps+t]/=float(sum);
            }
        }
    }
    const Bank& select(double rate)const {const auto index=std::clamp(int(std::ceil(8*std::log2(std::max(1.0,rate)))),0,48);return banks[index];}
};
inline const Kernels& kernels(){static const Kernels value;return value;}
}
