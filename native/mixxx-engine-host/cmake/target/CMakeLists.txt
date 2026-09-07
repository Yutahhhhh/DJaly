if(NOT TARGET mixxx-lib)
  message(FATAL_ERROR "DJaly host requires the pinned upstream mixxx-lib target")
endif()
set(DJALY_ROOT "${CMAKE_CURRENT_LIST_DIR}/../..")
add_executable(djaly-mixxx-engine-host
  "${DJALY_ROOT}/src/main.cpp"
  "${DJALY_ROOT}/src/host.cpp"
  "${DJALY_ROOT}/src/mixxx_backend.cpp")
set_target_properties(djaly-mixxx-engine-host PROPERTIES CXX_STANDARD 20 CXX_STANDARD_REQUIRED ON)
target_compile_definitions(djaly-mixxx-engine-host PRIVATE DJALY_WITH_MIXXX=1)
target_include_directories(djaly-mixxx-engine-host PRIVATE "${CMAKE_SOURCE_DIR}/src" "${CMAKE_BINARY_DIR}/src")
target_link_libraries(djaly-mixxx-engine-host PRIVATE mixxx-lib mixxx-gitinfostore)
