# Windows x86_64 cross-compiler toolchain file.
# Setting variable CMAKE_SYSTEM_NAME also sets the flag CMAKE_CROSSCOMPILING.
set(CMAKE_SYSTEM_NAME "Windows")
set(CMAKE_C_COMPILER_LAUNCHER "/usr/bin/ccache")
set(CMAKE_CXX_COMPILER_LAUNCHER "/usr/bin/ccache")
# Use mingw 64-bit compilers.
set(CMAKE_C_COMPILER "x86_64-w64-mingw32-gcc-posix")
set(CMAKE_CXX_COMPILER "x86_64-w64-mingw32-c++-posix")
set(CMAKE_RC_COMPILER "x86_64-w64-mingw32-windres")
set(CMAKE_RANLIB "x86_64-w64-mingw32-ranlib")
set(CMAKE_FIND_ROOT_PATH "/usr/x86_64-w64-mingw32")
# Adjust the default behavior of the find commands:
# search headers and libraries in the target environment
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
# Search programs in the host environment
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
if (EXISTS "/usr/bin/ccache")
	set(CMAKE_C_COMPILER_LAUNCHER "/usr/bin/ccache")
	set(CMAKE_CXX_COMPILER_LAUNCHER "/usr/bin/ccache")
endif ()
