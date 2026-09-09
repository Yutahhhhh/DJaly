#include "rubberband_state.h"
namespace junction::rb {
bool Access::resampler(RubberBand::Resampler& resampler,Cursor& cursor){
    auto* state=dynamic_cast<RubberBand::Resamplers::D_SRC*>(resampler.d);if(!state)return false;
    cursor.equal(state->m_channels);cursor(state->m_prevRatio,state->m_ratioUnset,state->m_smoothRatios);
    cursor.require(state->m_prevRatio>0&&state->m_prevRatio<=256);
    return cursor.ok&&sinc(state->m_src,cursor);
}
}
