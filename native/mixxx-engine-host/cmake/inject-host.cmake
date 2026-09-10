# Loaded by upstream via -DCMAKE_PROJECT_mixxx_INCLUDE=... . Defer until
# mixxx-lib exists, retaining upstream's source/binary directory assumptions.
if(NOT PLUMDECK_HOST_INJECTED)
  set(PLUMDECK_HOST_INJECTED TRUE)
  set(PLUMDECK_HOST_ROOT "${CMAKE_CURRENT_LIST_DIR}/..")
  cmake_language(DEFER CALL include "${PLUMDECK_HOST_ROOT}/cmake/target/CMakeLists.txt")
endif()
