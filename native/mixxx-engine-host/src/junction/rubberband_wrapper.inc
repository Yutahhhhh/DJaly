#include "rubberband_state.h"
namespace junction::rb {
bool Access::engine(RubberBand::RubberBandStretcher& engine,Cursor& cursor){
    if(!engine.m_d||!engine.m_d->m_r2||engine.m_d->m_r3)return false;
    return r2(*engine.m_d->m_r2,cursor);
}
}
