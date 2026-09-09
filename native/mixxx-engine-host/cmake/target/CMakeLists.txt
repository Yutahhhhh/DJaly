if(NOT TARGET mixxx-lib)
  message(FATAL_ERROR "DJaly host requires the pinned upstream mixxx-lib target")
endif()
set(DJALY_ROOT "${CMAKE_CURRENT_LIST_DIR}/../..")
# Extend the pinned built-in registry in the build tree; keep upstream clean.
set(DJALY_REGISTRY_SOURCE "${CMAKE_SOURCE_DIR}/src/effects/backends/builtin/builtinbackend.cpp")
file(READ "${DJALY_REGISTRY_SOURCE}" DJALY_REGISTRY)
set(DJALY_REGISTRATIONS "")
foreach(DJALY_EFFECT RANGE 0 7)
  string(APPEND DJALY_REGISTRATIONS "    registerEffect<DdjTimedProcessor<DdjBeatProcessor<${DJALY_EFFECT}>>>();\n")
endforeach()
foreach(DJALY_EFFECT Echo Reverb Tremolo Flanger Phaser PitchShift)
  string(APPEND DJALY_REGISTRATIONS "    registerEffect<DdjTimedProcessor<${DJALY_EFFECT}Effect>>();\n")
endforeach()
string(REPLACE "BuiltInBackend::BuiltInBackend() {" "BuiltInBackend::BuiltInBackend() {\n${DJALY_REGISTRATIONS}" DJALY_REGISTRY "${DJALY_REGISTRY}")
file(WRITE "${CMAKE_CURRENT_BINARY_DIR}/djaly_builtinbackend.cpp" "#include \"${DJALY_ROOT}/src/ddj_beat_processors.h\"\n${DJALY_REGISTRY}")
get_target_property(DJALY_MIXXX_SOURCES mixxx-lib SOURCES)
list(FILTER DJALY_MIXXX_SOURCES EXCLUDE REGEX "effects/backends/builtin/builtinbackend\\.cpp$")
set_property(TARGET mixxx-lib PROPERTY SOURCES "${DJALY_MIXXX_SOURCES}")
target_sources(mixxx-lib PRIVATE "${CMAKE_CURRENT_BINARY_DIR}/djaly_builtinbackend.cpp")
add_executable(djaly-mixxx-engine-host
  "${DJALY_ROOT}/src/main.cpp"
  "${DJALY_ROOT}/src/host.cpp"
  "${DJALY_ROOT}/src/mixxx_backend.cpp")
set_target_properties(djaly-mixxx-engine-host PROPERTIES CXX_STANDARD 20 CXX_STANDARD_REQUIRED ON)
target_compile_definitions(djaly-mixxx-engine-host PRIVATE DJALY_WITH_MIXXX=1)
target_include_directories(djaly-mixxx-engine-host PRIVATE "${CMAKE_SOURCE_DIR}/src" "${CMAKE_BINARY_DIR}/src")
target_link_libraries(djaly-mixxx-engine-host PRIVATE mixxx-lib mixxx-gitinfostore)

# Reproducible hook in the generated SoundManager translation unit; pinned
# checkout stays clean. The callback captures the final master exactly once.
set(DJALY_SOUND_SOURCE "${CMAKE_SOURCE_DIR}/src/soundio/soundmanager.cpp")
file(READ "${DJALY_SOUND_SOURCE}" DJALY_SOUND)
set(DJALY_SOUND_NEEDLE "m_pEngineMixer->process(iFramesPerBuffer * 2);")
string(FIND "${DJALY_SOUND}" "${DJALY_SOUND_NEEDLE}" DJALY_SOUND_MATCH)
if(DJALY_SOUND_MATCH EQUAL -1)
  message(FATAL_ERROR "Pinned SoundManager audio hook no longer matches")
endif()
string(REPLACE "${DJALY_SOUND_NEEDLE}" "if (junction::beforeAudio(iFramesPerBuffer)) m_pEngineMixer->process(iFramesPerBuffer * 2);
    junction::afterAudio(const_cast<float*>(m_pEngineMixer->getMainBuffer()), const_cast<float*>(m_pEngineMixer->getHeadphoneBuffer()), iFramesPerBuffer);" DJALY_SOUND "${DJALY_SOUND}")
set(DJALY_INPUT_NEEDLE "const SINT iFramesPerBuffer) {\n   for (QList<AudioInputBuffer>::ConstIterator")
string(FIND "${DJALY_SOUND}" "${DJALY_INPUT_NEEDLE}" DJALY_INPUT_MATCH)
if(DJALY_INPUT_MATCH EQUAL -1)
  message(FATAL_ERROR "Pinned SoundManager input ownership hook no longer matches")
endif()
string(REPLACE "${DJALY_INPUT_NEEDLE}" "const SINT iFramesPerBuffer) {\n   junction::InputGuard inputGuard;\n   if (!inputGuard) return;\n   for (QList<AudioInputBuffer>::ConstIterator" DJALY_SOUND "${DJALY_SOUND}")
file(WRITE "${CMAKE_CURRENT_BINARY_DIR}/djaly_soundmanager.cpp" "#include \"${DJALY_ROOT}/src/junction/audio_bridge.h\"\n${DJALY_SOUND}")
get_target_property(DJALY_MIXXX_SOURCES mixxx-lib SOURCES)
list(FILTER DJALY_MIXXX_SOURCES EXCLUDE REGEX "soundio/soundmanager\\.cpp$")
set_property(TARGET mixxx-lib PROPERTY SOURCES "${DJALY_MIXXX_SOURCES}")
target_sources(mixxx-lib PRIVATE "${CMAKE_CURRENT_BINARY_DIR}/djaly_soundmanager.cpp")
include("${DJALY_ROOT}/cmake/junction.cmake")
target_link_libraries(djaly-mixxx-engine-host PRIVATE djaly-junction-core)

target_sources(djaly-mixxx-engine-host PRIVATE "${DJALY_ROOT}/src/junction/private_preview.cpp")

target_include_directories(mixxx-lib PRIVATE "${CMAKE_SOURCE_DIR}/src/soundio")

file(READ "${CMAKE_SOURCE_DIR}/src/engine/enginemixer.cpp" DJALY_MIXER)
string(FIND "${DJALY_MIXER}" "const CSAMPLE* EngineMixer::buffer(const AudioOutput& output) const {" DJALY_SINK_MATCH)
if(DJALY_SINK_MATCH EQUAL -1)
  message(FATAL_ERROR "Pinned EngineMixer device sink hook no longer matches")
endif()
string(REPLACE "const CSAMPLE* EngineMixer::buffer(const AudioOutput& output) const {" "const CSAMPLE* EngineMixer::buffer(const AudioOutput& output) const {
    if (output.getType() == AudioPathType::Main || output.getType() == AudioPathType::Headphones) {
        if (const auto* idle = junction::idleOutput(output.getType() == AudioPathType::Headphones)) return idle;
    }" DJALY_MIXER "${DJALY_MIXER}")
set(DJALY_CLOCK_NEEDLE "m_sampleRate = mixxx::audio::SampleRate::fromDouble(m_pSampleRate->get());")
string(FIND "${DJALY_MIXER}" "${DJALY_CLOCK_NEEDLE}" DJALY_CLOCK_MATCH)
if(DJALY_CLOCK_MATCH EQUAL -1)
  message(FATAL_ERROR "Pinned mixer clock hook no longer matches")
endif()
string(REPLACE "${DJALY_CLOCK_NEEDLE}" "${DJALY_CLOCK_NEEDLE}
    deckclock::beginAudio(iBufferSize / 2, m_sampleRate.value()); deckclock::CallbackScope djalyCallbackScope;" DJALY_MIXER "${DJALY_MIXER}")
file(WRITE "${CMAKE_CURRENT_BINARY_DIR}/djaly_enginemixer.cpp" "#include \"${DJALY_ROOT}/src/junction/audio_bridge.h\"\n#include \"${DJALY_ROOT}/src/deck_telemetry.h\"\n${DJALY_MIXER}")
get_target_property(DJALY_MIXXX_SOURCES mixxx-lib SOURCES)
list(FILTER DJALY_MIXXX_SOURCES EXCLUDE REGEX "engine/enginemixer\\.cpp$")
set_property(TARGET mixxx-lib PROPERTY SOURCES "${DJALY_MIXXX_SOURCES}")
target_sources(mixxx-lib PRIVATE "${CMAKE_CURRENT_BINARY_DIR}/djaly_enginemixer.cpp")

file(READ "${CMAKE_SOURCE_DIR}/src/engine/enginebuffer.cpp" DJALY_BUFFER)
foreach(DJALY_NEEDLE "m_playPos = position;" "m_pReadAheadManager->getFilePlaypositionFromLog(m_playPos, framesRead);")
  string(FIND "${DJALY_BUFFER}" "${DJALY_NEEDLE}" DJALY_MATCH)
  if(DJALY_MATCH EQUAL -1)
    message(FATAL_ERROR "Pinned EngineBuffer boundary hook no longer matches")
  endif()
endforeach()
string(REPLACE "m_playPos = position;" "deckclock::boundary(1);
    m_playPos = position;" DJALY_BUFFER "${DJALY_BUFFER}")
string(REPLACE "// Adjust filepos_play by the amount we processed." "// Adjust filepos_play by the amount we processed.
            const auto expectedPosition = m_playPos + framesRead;" DJALY_BUFFER "${DJALY_BUFFER}")
string(REPLACE "m_pReadAheadManager->getFilePlaypositionFromLog(m_playPos, framesRead);" "m_pReadAheadManager->getFilePlaypositionFromLog(m_playPos, framesRead);
            if (m_playPos != expectedPosition) deckclock::boundary(2);" DJALY_BUFFER "${DJALY_BUFFER}")
set(DJALY_SCALER_NEEDLE "m_pScaleLinear = new EngineBufferScaleLinear(m_pReadAheadManager);")
string(FIND "${DJALY_BUFFER}" "${DJALY_SCALER_NEEDLE}" DJALY_SCALER_MATCH)
if(DJALY_SCALER_MATCH EQUAL -1)
  message(FATAL_ERROR "Pinned vinyl scaler hook no longer matches")
endif()
string(REPLACE "${DJALY_SCALER_NEEDLE}" "m_pScaleLinear = qEnvironmentVariable(\"DJALY_VINYL_SCALER\") != \"linear\" ? static_cast<EngineBufferScaleLinear*>(new DjalyVinylScaler(m_pReadAheadManager)) : new EngineBufferScaleLinear(m_pReadAheadManager);" DJALY_BUFFER "${DJALY_BUFFER}")
file(WRITE "${CMAKE_CURRENT_BINARY_DIR}/djaly_enginebuffer.cpp" "#include \"${DJALY_ROOT}/src/deck_telemetry.h\"\n#include \"${DJALY_ROOT}/src/djaly_vinyl_scaler.h\"\n${DJALY_BUFFER}")
get_target_property(DJALY_MIXXX_SOURCES mixxx-lib SOURCES)
list(FILTER DJALY_MIXXX_SOURCES EXCLUDE REGEX "engine/enginebuffer\\.cpp$")
set_property(TARGET mixxx-lib PROPERTY SOURCES "${DJALY_MIXXX_SOURCES}")
target_sources(mixxx-lib PRIVATE "${CMAKE_CURRENT_BINARY_DIR}/djaly_enginebuffer.cpp")

target_include_directories(mixxx-lib PRIVATE "${CMAKE_SOURCE_DIR}/src/engine")

file(READ "${CMAKE_SOURCE_DIR}/src/engine/cachingreader/cachingreaderworker.cpp" DJALY_READER)
set(DJALY_READER_NEEDLE "m_pAudioSource = SoundSourceProxy(pTrack).openAudioSource(config);")
string(FIND "${DJALY_READER}" "${DJALY_READER_NEEDLE}" DJALY_READER_MATCH)
if(DJALY_READER_MATCH EQUAL -1)
  message(FATAL_ERROR "Pinned decoder binding hook no longer matches")
endif()
string(REPLACE "${DJALY_READER_NEEDLE}" "SoundSourceProxy djalyProxy(pTrack);
    m_pAudioSource = djalyProxy.openAudioSource(config);
    waveform::bindSource(pTrack->getLocation(), djalyProxy, m_pAudioSource);" DJALY_READER "${DJALY_READER}")
file(WRITE "${CMAKE_CURRENT_BINARY_DIR}/djaly_cachingreaderworker.cpp" "#include \"${DJALY_ROOT}/src/waveform/source_binding.h\"\n${DJALY_READER}")
get_target_property(DJALY_MIXXX_SOURCES mixxx-lib SOURCES)
list(FILTER DJALY_MIXXX_SOURCES EXCLUDE REGEX "engine/cachingreader/cachingreaderworker\\.cpp$")
set_property(TARGET mixxx-lib PROPERTY SOURCES "${DJALY_MIXXX_SOURCES}")
target_sources(mixxx-lib PRIVATE "${CMAKE_CURRENT_BINARY_DIR}/djaly_cachingreaderworker.cpp")
target_include_directories(mixxx-lib PRIVATE "${CMAKE_SOURCE_DIR}/src/engine/cachingreader")
target_sources(djaly-mixxx-engine-host PRIVATE "${DJALY_ROOT}/src/waveform/manager.cpp")

target_link_libraries(djaly-mixxx-engine-host PRIVATE Qt6::Network)

target_sources(mixxx-lib PRIVATE "${DJALY_ROOT}/src/djaly_vinyl_scaler.cpp")

# Observe actual PortAudio underflow/overflow reports without logging in RT.
file(READ "${CMAKE_SOURCE_DIR}/src/soundio/sounddeviceportaudio.cpp" DJALY_PORTAUDIO)
string(FIND "${DJALY_PORTAUDIO}" "m_pSoundManager->underflowHappened(" DJALY_XRUN_MATCH)
if(DJALY_XRUN_MATCH EQUAL -1)
  message(FATAL_ERROR "Pinned PortAudio xrun hook no longer matches")
endif()
string(REPLACE "m_pSoundManager->underflowHappened(" "deckclock::xruns.fetch_add(1, std::memory_order_relaxed), m_pSoundManager->underflowHappened(" DJALY_PORTAUDIO "${DJALY_PORTAUDIO}")
file(WRITE "${CMAKE_CURRENT_BINARY_DIR}/djaly_sounddeviceportaudio.cpp" "#include \"${DJALY_ROOT}/src/deck_telemetry.h\"\n${DJALY_PORTAUDIO}")
get_target_property(DJALY_MIXXX_SOURCES mixxx-lib SOURCES)
list(FILTER DJALY_MIXXX_SOURCES EXCLUDE REGEX "soundio/sounddeviceportaudio\\.cpp$")
set_property(TARGET mixxx-lib PROPERTY SOURCES "${DJALY_MIXXX_SOURCES}")
target_sources(mixxx-lib PRIVATE "${CMAKE_CURRENT_BINARY_DIR}/djaly_sounddeviceportaudio.cpp")

include("${DJALY_ROOT}/cmake/keylock-checkpoint.cmake")
