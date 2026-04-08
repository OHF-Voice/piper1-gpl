# Windows x86_64 MSVC toolchain file.
#[[
# Set the toolchain root (adjust if different from C:/msvc)
set(MSVC_ROOT "S:/applications/windows/Toolchain/msvc")
set(MSVC_VERSION "14.50.35717")
set(SDK_VERSION "10.0.26100.0")

set(MSVC_TOOL_DIR "${MSVC_ROOT}/VC/Tools/MSVC/${MSVC_VERSION}/bin/Hostx64/x64/")

set(CMAKE_C_COMPILER "${MSVC_TOOL_DIR}cl.exe")
set(CMAKE_CXX_COMPILER "${MSVC_TOOL_DIR}cl.exe")
set(CMAKE_RC_COMPILER "${MSVC_ROOT}/Windows Kits/10/bin/${SDK_VERSION}/x64/rc.exe")
set(CMAKE_AR "${MSVC_TOOL_DIR}lib.exe")
set(CMAKE_LINKER "${MSVC_TOOL_DIR}link.exe")
set(CMAKE_NM "${MSVC_TOOL_DIR}dumpbin.exe")
# Unlike MinGW cross-compiling, we usually want to allow finding programs on the system
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
]]

# Compiler Launchers (ccache works with MSVC, but ensure it is in your PATH)
#set(CMAKE_C_COMPILER_LAUNCHER "ccache.exe")
#set(CMAKE_CXX_COMPILER_LAUNCHER "ccache.exe")
