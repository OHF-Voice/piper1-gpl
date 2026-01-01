# Linux native GNU compiler toolchain file.
set(CMAKE_C_COMPILER_LAUNCHER "/usr/bin/ccache")
set(CMAKE_CXX_COMPILER_LAUNCHER "/usr/bin/ccache")
set(CMAKE_C_COMPILER "/usr/bin/x86_64-linux-gnu-gcc-13")
set(CMAKE_CXX_COMPILER "/usr/bin/x86_64-linux-gnu-g++-13")
if (EXISTS "/usr/bin/ccache")
	set(CMAKE_C_COMPILER_LAUNCHER "/usr/bin/ccache")
	set(CMAKE_CXX_COMPILER_LAUNCHER "/usr/bin/ccache")
endif ()
