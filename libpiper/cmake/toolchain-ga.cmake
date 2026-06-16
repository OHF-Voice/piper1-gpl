# This triggers setting variable 'CMAKE_CROSSCOMPILING'.
set(CMAKE_SYSTEM_NAME "Linux")
set(CMAKE_SYSTEM_PROCESSOR "aarch64")
# Linux arm64/aarch64 cross-compiler toolchain file.
set(CMAKE_C_COMPILER_LAUNCHER "/usr/bin/ccache")
set(CMAKE_CXX_COMPILER_LAUNCHER "/usr/bin/ccache")
set(CMAKE_C_COMPILER "/usr/bin/aarch64-linux-gnu-gcc-13")
set(CMAKE_CXX_COMPILER "/usr/bin/aarch64-linux-gnu-g++-13")

