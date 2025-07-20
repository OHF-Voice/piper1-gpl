# Builds libpiper
cmake_minimum_required(VERSION 3.26)
project(piper LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)



# ---- onnxruntime ---

# Look for onnxruntime files in <root>/lib
if(NOT DEFINED ONNXRUNTIME_DIR)
    if(NOT DEFINED ONNXRUNTIME_VERSION)
        set(ONNXRUNTIME_VERSION "1.22.0")
    endif()

    if(WIN32)
        # Windows x86-64
        set(ONNXRUNTIME_PREFIX "onnxruntime-win-x64-${ONNXRUNTIME_VERSION}")
        set(ONNXRUNTIME_EXT "zip")
    elseif (APPLE)
        if(CMAKE_SYSTEM_PROCESSOR STREQUAL x86_64)
            # MacOS x86-64
            set(ONNXRUNTIME_PREFIX "onnxruntime-osx-x86_64-${ONNXRUNTIME_VERSION}")
        elseif(CMAKE_SYSTEM_PROCESSOR STREQUAL arm64)
            # MacOS Apple Silicon
            set(ONNXRUNTIME_PREFIX "onnxruntime-osx-arm64-${ONNXRUNTIME_VERSION}")
        else()
            message(FATAL_ERROR "Unsupported architecture for onnxruntime")
        endif()

        set(ONNXRUNTIME_EXT "tgz")
    else()
        if(CMAKE_SYSTEM_PROCESSOR STREQUAL x86_64)
            # Linux x86-64
            set(ONNXRUNTIME_PREFIX "onnxruntime-linux-x64-${ONNXRUNTIME_VERSION}")
        elseif(CMAKE_SYSTEM_PROCESSOR STREQUAL aarch64)
            # Linux ARM 64-bit
            set(ONNXRUNTIME_PREFIX "onnxruntime-linux-aarch64-${ONNXRUNTIME_VERSION}")
        elseif(CMAKE_SYSTEM_PROCESSOR STREQUAL armv7l)
            # Linux ARM 32-bit
            set(ONNXRUNTIME_PREFIX "onnxruntime-linux-arm32-${ONNXRUNTIME_VERSION}")
            set(ONNXRUNTIME_URL "https://github.com/synesthesiam/prebuilt-apps/releases/download/v1.0/onnxruntime-linux-arm32-${ONNXRUNTIME_VERSION}.tgz")
        else()
            message(FATAL_ERROR "Unsupported architecture for onnxruntime")
        endif()

        set(ONNXRUNTIME_EXT "tgz")
    endif()

    if(NOT DEFINED ONNXRUNTIME_URL)
        set(ONNXRUNTIME_URL "https://github.com/microsoft/onnxruntime/releases/download/v${ONNXRUNTIME_VERSION}/${ONNXRUNTIME_PREFIX}.${ONNXRUNTIME_EXT}")
    endif()

    set(ONNXRUNTIME_FILENAME "${ONNXRUNTIME_PREFIX}.${ONNXRUNTIME_EXT}")
    set(ONNXRUNTIME_DIR "${CMAKE_CURRENT_LIST_DIR}/lib/${ONNXRUNTIME_PREFIX}")

    if(NOT EXISTS "${ONNXRUNTIME_DIR}")
        if(NOT EXISTS "download/${ONNXRUNTIME_FILENAME}")
            # Download onnxruntime release
            message("Downloading ${ONNXRUNTIME_URL}")
            file(DOWNLOAD "${ONNXRUNTIME_URL}" "download/${ONNXRUNTIME_FILENAME}")
        endif()

        # Extract .zip or .tgz to a directory like lib/onnxruntime-linux-x64-1.22.0/
        file(ARCHIVE_EXTRACT INPUT "download/${ONNXRUNTIME_FILENAME}" DESTINATION "${CMAKE_CURRENT_LIST_DIR}/lib")
    endif()
endif()

# ---- libpiper ---

add_library(piper SHARED
    ${CMAKE_CURRENT_SOURCE_DIR}/src/piper.cpp
)

add_dependencies(piper espeak_ng_external)
target_include_directories(piper PUBLIC
    ${ESPEAKNG_INSTALL_DIR}/include
    ${ONNXRUNTIME_DIR}/include
    ${CMAKE_CURRENT_SOURCE_DIR}/include
)
target_link_directories(piper PUBLIC
    ${ONNXRUNTIME_DIR}/lib
)
target_link_libraries(piper
    ${ESPEAKNG_STATIC_LIB}
    ${UCD_STATIC_LIB}
    onnxruntime
)

# ---- install ---

include(GNUInstallDirs)

install(TARGETS piper
    DESTINATION ${CMAKE_INSTALL_PREFIX}
)

install(
    FILES ${CMAKE_CURRENT_SOURCE_DIR}/include/piper.h
    DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}
)

install(
    DIRECTORY ${ONNXRUNTIME_DIR}/lib/
    DESTINATION ${CMAKE_INSTALL_LIBDIR}
)

# Copy espeak-ng-data
set(ESPEAKNG_DATA_SRC ${CMAKE_BINARY_DIR}/espeak_ng-install/share/espeak-ng-data)
set(ESPEAKNG_DATA_DST ${CMAKE_INSTALL_PREFIX}/espeak-ng-data)

install(
    DIRECTORY ${ESPEAKNG_DATA_SRC}
    DESTINATION ${CMAKE_INSTALL_PREFIX}
)
