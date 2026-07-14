cmake_minimum_required(VERSION 3.26)

add_executable(piper_exe main.cpp)

add_library(main_utils
  utils/wavfile.cpp
  utils/main_utils.cpp
  utils/process.cpp
  utils/wav_headers.cpp)

target_include_directories(
  main_utils
  PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}
  PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/utils)

target_sources(
  main_utils
  PUBLIC FILE_SET HEADERS
         BASE_DIRS ${CMAKE_CURRENT_SOURCE_DIR}
         FILES utils/wavfile.hpp utils/main_utils.hpp utils/process.hpp
               utils/wav_headers.hpp)

target_link_libraries(main_utils PRIVATE piper)

target_link_libraries(piper_exe PRIVATE piper main_utils)

install(
  TARGETS piper_exe
  RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
)