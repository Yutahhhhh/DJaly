# Loaded by upstream via -DCMAKE_PROJECT_mixxx_INCLUDE=... . Defer until
# mixxx-lib exists, retaining upstream's source/binary directory assumptions.
if(NOT DJALY_HOST_INJECTED)
  set(DJALY_HOST_INJECTED TRUE)
  set(DJALY_HOST_ROOT "${CMAKE_CURRENT_LIST_DIR}/..")
  cmake_language(DEFER CALL include "${DJALY_HOST_ROOT}/cmake/target/CMakeLists.txt")
endif()
