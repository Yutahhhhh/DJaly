cmake_minimum_required(VERSION 3.20)
project(DjalyRubberBand LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 20)
set(sources
 src/RubberBandStretcher.cpp src/RubberBandLiveShifter.cpp
 src/faster/AudioCurveCalculator.cpp src/faster/CompoundAudioCurve.cpp src/faster/HighFrequencyAudioCurve.cpp src/faster/SilentAudioCurve.cpp src/faster/PercussiveAudioCurve.cpp src/faster/R2Stretcher.cpp src/faster/StretcherChannelData.cpp src/faster/StretcherProcess.cpp
 src/common/Allocators.cpp src/common/FFT.cpp src/common/Log.cpp src/common/Profiler.cpp src/common/Resampler.cpp src/common/StretchCalculator.cpp src/common/sysutils.cpp src/common/mathmisc.cpp src/common/Thread.cpp src/finer/R3Stretcher.cpp src/finer/R3LiveShifter.cpp)
list(TRANSFORM sources PREPEND "${RB_SOURCE}/")
add_library(rubberband STATIC ${sources} "${RB_ADAPTER}/rubberband_state.cpp")
target_compile_options(rubberband PRIVATE -include cstddef)
target_compile_definitions(rubberband PRIVATE HAVE_VDSP HAVE_LIBSAMPLERATE USE_PTHREADS MALLOC_IS_ALIGNED NO_THREAD_CHECKS NO_TIMING LACK_SINCOS)
target_include_directories(rubberband PRIVATE "${RB_SOURCE}" "${RB_SOURCE}/src" "${RB_SOURCE}/rubberband" "${RB_PRIVATE}" /opt/homebrew/include)
target_link_libraries(rubberband PUBLIC /opt/homebrew/lib/libsamplerate.dylib "-framework Accelerate")
