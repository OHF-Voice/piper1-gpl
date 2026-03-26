# Windows x86_64 MinGW toolchain file.
#[[
set(CMAKE_C_COMPILER_LAUNCHER "ccache.exe")
set(CMAKE_CXX_COMPILER_LAUNCHER "ccache.exe")
# Use mingw 64-bit compilers on Windows.
# Commented out now to have CMake find each of them.
set(CMAKE_C_COMPILER "x86_64-w64-mingw32-gcc.exe")
set(CMAKE_CXX_COMPILER "x86_64-w64-mingw32-g++.exe")
set(CMAKE_RC_COMPILER "windres.exe")
set(CMAKE_AR "x86_64-w64-mingw32-gcc-ar.exe")
set(CMAKE_RANLIB "x86_64-w64-mingw32-gcc-ranlib.exe")
set(CMAKE_NM "x86_64-w64-mingw32-gcc-nm.exe")
set(CMAKE_LINKER "ld.exe")
## Adjust the default behavior of the find commands:
## search headers and libraries in the target environment
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
## Search programs in the host environment
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
]]
