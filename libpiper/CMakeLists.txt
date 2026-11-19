# Builds libpiper
cmake_minimum_required(VERSION 3.26)
project(piper LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(MSVC)
    # Keep source and narrow string literals in UTF-8 on every Windows code page.
    add_compile_options(/utf-8)
endif()

include(ExternalProject)

# Install location for espeak-ng
set(ESPEAKNG_BUILD_DIR ${CMAKE_BINARY_DIR}/espeak_ng)
set(ESPEAKNG_INSTALL_DIR ${CMAKE_BINARY_DIR}/espeak_ng-install)

# ucd-tools is built (not installed) by espeak-ng, so we reference its static
# library directly from the build tree. Multi-config generators (e.g. Visual
# Studio) place the output in a per-config subdirectory whose name is only
# known at build time, so resolve it with a $<CONFIG> generator expression.
# Single-config generators (Unix Makefiles, Ninja) write directly into the
# build directory with no subdirectory.
get_property(IS_MULTI_CONFIG GLOBAL PROPERTY GENERATOR_IS_MULTI_CONFIG)
if(IS_MULTI_CONFIG)
    set(UCD_CONFIG_SUBDIR "$<CONFIG>/")
else()
    set(UCD_CONFIG_SUBDIR "")
endif()

set(UCD_TOOLS_DIR ${ESPEAKNG_BUILD_DIR}/src/espeak_ng_external-build/src/ucd-tools)

if(CMAKE_CXX_COMPILER_ID STREQUAL "MSVC")
    # MSVC emits .lib files (espeak-ng is re-exported from piper.dll)
    set(ESPEAKNG_STATIC_LIB ${ESPEAKNG_INSTALL_DIR}/lib/espeak-ng.lib)
    set(UCD_STATIC_LIB ${UCD_TOOLS_DIR}/${UCD_CONFIG_SUBDIR}ucd.lib)
else()
    set(ESPEAKNG_STATIC_LIB ${ESPEAKNG_INSTALL_DIR}/lib/libespeak-ng.a)
    set(UCD_STATIC_LIB ${UCD_TOOLS_DIR}/${UCD_CONFIG_SUBDIR}libucd.a)
endif()

# espeak-ng's compat shims (unistd.h, endian.h, getopt.h) test
# `#if __has_include_next(...)`, which MSVC 14.52 (Visual Studio 2026) rejects
# with C7780 because MSVC has no __has_include_next. Backport of espeak-ng
# 021e465, which defines it as 0 when the compiler lacks it. Drop this once the
# pinned commit includes that fix.
set(ESPEAKNG_PATCH_SCRIPT ${CMAKE_CURRENT_BINARY_DIR}/espeak_ng_patch.cmake)
file(WRITE ${ESPEAKNG_PATCH_SCRIPT} [=[
foreach(header unistd endian getopt)
    set(path "${ESPEAKNG_SOURCE_DIR}/src/include/compat/${header}.h")
    file(READ "${path}" content)
    string(FIND "${content}" "#ifndef __has_include_next" guarded)
    if(guarded EQUAL -1)
        set(anchor "#if __has_include_next(<${header}.h>)")
        string(FIND "${content}" "${anchor}" anchor_pos)
        if(anchor_pos EQUAL -1)
            message(FATAL_ERROR "${path}: '${anchor}' not found")
        endif()
        string(REPLACE "${anchor}" "#ifndef __has_include_next // MSVC has no __has_include_next\n#define __has_include_next(header) 0\n#endif\n\n${anchor}" content "${content}")
        file(WRITE "${path}" "${content}")
    endif()
endforeach()
]=])

ExternalProject_Add(espeak_ng_external
    GIT_REPOSITORY https://github.com/espeak-ng/espeak-ng.git
    GIT_TAG 212928b394a96e8fd2096616bfd54e17845c48f6  # 2025-Mar-22
    PREFIX ${ESPEAKNG_BUILD_DIR}
    PATCH_COMMAND ${CMAKE_COMMAND} -DESPEAKNG_SOURCE_DIR=<SOURCE_DIR> -P ${ESPEAKNG_PATCH_SCRIPT}
    CMAKE_ARGS
        -DCMAKE_INSTALL_PREFIX=${ESPEAKNG_INSTALL_DIR}
        -DCMAKE_BUILD_TYPE=${CMAKE_BUILD_TYPE}
        -DBUILD_SHARED_LIBS:BOOL=OFF
        -DCMAKE_POSITION_INDEPENDENT_CODE:BOOL=ON
        -DUSE_ASYNC:BOOL=OFF
        -DUSE_MBROLA:BOOL=OFF
        -DUSE_LIBSONIC:BOOL=OFF
        -DUSE_LIBPCAUDIO:BOOL=OFF
        -DUSE_KLATT:BOOL=OFF
        -DUSE_SPEECHPLAYER:BOOL=OFF
        -DEXTRA_cmn:BOOL=ON
        -DEXTRA_ru:BOOL=ON
        # Need to explicitly add ucd include directory for CI
        "-DCMAKE_C_FLAGS=-D_FILE_OFFSET_BITS=64 -I${ESPEAKNG_BUILD_DIR}/src/espeak_ng_external/src/ucd-tools/src/include"
        "-DCMAKE_CXX_FLAGS=-D_FILE_OFFSET_BITS=64 -I${ESPEAKNG_BUILD_DIR}/src/espeak_ng_external/src/ucd-tools/src/include"
    BUILD_BYPRODUCTS
        ${ESPEAKNG_STATIC_LIB}
        ${UCD_STATIC_LIB}
    UPDATE_DISCONNECTED TRUE
)

include_directories(
    ${ESPEAKNG_INSTALL_DIR}/include
)

# ---- open_jtalk (Japanese frontend: text -> full-context labels) ---
#
# Built from tsukumijima/open_jtalk, the same fork pyopenjtalk-plus vendors
# (this is what the ja_JA voice was trained with). Only the frontend sources
# are compiled - no hts_engine waveform code. The fork already ships a CMake
# build at src/CMakeLists.txt producing a single `openjtalk` static library
# from jpcommon, mecab, mecab2njd, njd, njd2jpcommon, njd_set_* and text2mecab.
#
# Notes:
# - The fork declares cmake_minimum_required(VERSION 3.5), so CMake >= 4 needs
#   -DCMAKE_POLICY_VERSION_MINIMUM=3.5.
# - Its configure_file() writes mecab/src/config.h into the *source* tree, so
#   multi-ABI builds (e.g. Android) must build ABIs serially, not in parallel.
set(OPENJTALK_BUILD_DIR ${CMAKE_BINARY_DIR}/open_jtalk)
set(OPENJTALK_SRC_DIR ${OPENJTALK_BUILD_DIR}/src/openjtalk_external/src)
set(OPENJTALK_LIB_DIR
    ${OPENJTALK_BUILD_DIR}/src/openjtalk_external-build)

# Multi-config generators (e.g. Visual Studio) place the library in a
# per-config subdirectory whose name is only known at build time, so
# resolve it with a $<CONFIG> generator expression - the same pattern
# used for the ucd library above. Single-config generators (Unix
# Makefiles, Ninja) write directly into the build directory.
if(IS_MULTI_CONFIG)
    set(OPENJTALK_CONFIG_SUBDIR "$<CONFIG>/")
else()
    set(OPENJTALK_CONFIG_SUBDIR "")
endif()

if(MSVC)
    set(OPENJTALK_STATIC_LIB
        ${OPENJTALK_LIB_DIR}/${OPENJTALK_CONFIG_SUBDIR}openjtalk.lib)
else()
    set(OPENJTALK_STATIC_LIB
        ${OPENJTALK_LIB_DIR}/${OPENJTALK_CONFIG_SUBDIR}libopenjtalk.a)
endif()

ExternalProject_Add(openjtalk_external
    GIT_REPOSITORY https://github.com/tsukumijima/open_jtalk.git
    # master as of 2026-09-12; re-pin deliberately on update
    GIT_TAG 4a1ef70897689d2ee6b8f9be35454a3a4b15b289
    PREFIX ${OPENJTALK_BUILD_DIR}
    SOURCE_SUBDIR src
    CMAKE_ARGS
        -DCMAKE_INSTALL_PREFIX=${OPENJTALK_BUILD_DIR}/install
        -DCMAKE_BUILD_TYPE=${CMAKE_BUILD_TYPE}
        -DBUILD_SHARED_LIBS:BOOL=OFF
        -DCMAKE_POSITION_INDEPENDENT_CODE:BOOL=ON
        -DCMAKE_POLICY_VERSION_MINIMUM=3.5
    BUILD_BYPRODUCTS
        ${OPENJTALK_STATIC_LIB}
    UPDATE_DISCONNECTED TRUE
    # open_jtalk defines no install rules: headers come from the
    # source tree and the library from the build tree, so there is
    # nothing to install. The default install step must be skipped
    # explicitly - on Windows it runs MSBuild on an INSTALL project
    # that a project without install rules never generates (MSB1009).
    INSTALL_COMMAND ""
)

set(OPENJTALK_INCLUDE_DIRS
    ${OPENJTALK_SRC_DIR}/jpcommon
    ${OPENJTALK_SRC_DIR}/mecab/src
    ${OPENJTALK_SRC_DIR}/mecab2njd
    ${OPENJTALK_SRC_DIR}/njd
    ${OPENJTALK_SRC_DIR}/njd2jpcommon
    ${OPENJTALK_SRC_DIR}/njd_set_accent_phrase
    ${OPENJTALK_SRC_DIR}/njd_set_accent_type
    ${OPENJTALK_SRC_DIR}/njd_set_digit
    ${OPENJTALK_SRC_DIR}/njd_set_long_vowel
    ${OPENJTALK_SRC_DIR}/njd_set_pronunciation
    ${OPENJTALK_SRC_DIR}/njd_set_unvoiced_vowel
    ${OPENJTALK_SRC_DIR}/text2mecab
)

# ---- onnxruntime ---

find_package(onnxruntime QUIET)

# Download url to path unless it is already there. Fails on an HTTP error
# instead of saving the error page, and checks sha256 (when not empty) for a
# fresh download and for one left from an earlier configure.
function(piper_download url path sha256)
    if(EXISTS "${path}")
        if(NOT sha256)
            return()
        endif()

        file(SHA256 "${path}" existing_sha256)
        string(TOLOWER "${sha256}" expected_sha256)
        if(existing_sha256 STREQUAL expected_sha256)
            return()
        endif()

        message(STATUS "${path} does not match its SHA256; downloading it again")
        file(REMOVE "${path}")
    endif()

    set(hash_args "")
    if(sha256)
        set(hash_args EXPECTED_HASH "SHA256=${sha256}")
    endif()

    message(STATUS "Downloading ${url}")
    file(DOWNLOAD "${url}" "${path}.part" STATUS download_status TLS_VERIFY ON ${hash_args})
    list(GET download_status 0 download_code)
    if(NOT download_code EQUAL 0)
        list(GET download_status 1 download_message)
        file(REMOVE "${path}.part")
        message(FATAL_ERROR "Failed to download ${url}: ${download_message}")
    endif()

    file(RENAME "${path}.part" "${path}")
endfunction()

# Without a system onnxruntime or -DONNXRUNTIME_DIR, download a prebuilt one
# into <root>/lib/onnxruntime-<platform>-<version>/, with include/ and lib/
# laid out like Microsoft's release archives.
if(NOT TARGET onnxruntime::onnxruntime AND NOT DEFINED ONNXRUNTIME_DIR)
    if(NOT DEFINED ONNXRUNTIME_VERSION)
        set(ONNXRUNTIME_VERSION "1.22.0")
    endif()

    # ONNXRUNTIME_PREFIX names the directory, ONNXRUNTIME_RID is the platform
    # in the NuGet package
    if(WIN32)
        # Windows x86-64
        set(ONNXRUNTIME_PREFIX "onnxruntime-win-x64-${ONNXRUNTIME_VERSION}")
        set(ONNXRUNTIME_RID "win-x64")
        set(ONNXRUNTIME_EXT "zip")
    elseif (APPLE)
        if(CMAKE_SYSTEM_PROCESSOR STREQUAL x86_64)
            # MacOS x86-64
            set(ONNXRUNTIME_PREFIX "onnxruntime-osx-x86_64-${ONNXRUNTIME_VERSION}")
            set(ONNXRUNTIME_RID "osx-x64")
        elseif(CMAKE_SYSTEM_PROCESSOR STREQUAL arm64)
            # MacOS Apple Silicon
            set(ONNXRUNTIME_PREFIX "onnxruntime-osx-arm64-${ONNXRUNTIME_VERSION}")
            set(ONNXRUNTIME_RID "osx-arm64")
        else()
            message(FATAL_ERROR "Unsupported architecture for onnxruntime")
        endif()

        set(ONNXRUNTIME_EXT "tgz")
    else()
        if(CMAKE_SYSTEM_PROCESSOR STREQUAL x86_64)
            # Linux x86-64
            set(ONNXRUNTIME_PREFIX "onnxruntime-linux-x64-${ONNXRUNTIME_VERSION}")
            set(ONNXRUNTIME_RID "linux-x64")
        elseif(CMAKE_SYSTEM_PROCESSOR STREQUAL aarch64)
            # Linux ARM 64-bit
            set(ONNXRUNTIME_PREFIX "onnxruntime-linux-aarch64-${ONNXRUNTIME_VERSION}")
            set(ONNXRUNTIME_RID "linux-arm64")
        elseif(CMAKE_SYSTEM_PROCESSOR STREQUAL armv7l)
            # Linux ARM 32-bit: not in the NuGet package
            set(ONNXRUNTIME_PREFIX "onnxruntime-linux-arm32-${ONNXRUNTIME_VERSION}")
            if(NOT DEFINED ONNXRUNTIME_URL)
                set(ONNXRUNTIME_URL "https://github.com/synesthesiam/prebuilt-apps/releases/download/v1.0/onnxruntime-linux-arm32-${ONNXRUNTIME_VERSION}.tgz")
            endif()
        else()
            message(FATAL_ERROR "Unsupported architecture for onnxruntime")
        endif()

        set(ONNXRUNTIME_EXT "tgz")
    endif()

    if(NOT DEFINED ONNXRUNTIME_SHA256)
        if(NOT DEFINED ONNXRUNTIME_URL AND ONNXRUNTIME_VERSION STREQUAL "1.22.0")
            # Microsoft.ML.OnnxRuntime.1.22.0.nupkg, which matches the SHA512 in
            # the nuget.org catalog. Set ONNXRUNTIME_SHA256 for another version.
            set(ONNXRUNTIME_SHA256 "d571e63a2329baacb713f441e65ad75284de354db6e1ac435fe4bebbb417986a")
        else()
            set(ONNXRUNTIME_SHA256 "")
        endif()
    endif()

    set(ONNXRUNTIME_DIR "${CMAKE_CURRENT_LIST_DIR}/lib/${ONNXRUNTIME_PREFIX}")
    set(ONNXRUNTIME_DOWNLOAD_DIR "${CMAKE_CURRENT_LIST_DIR}/download")

    if(NOT EXISTS "${ONNXRUNTIME_DIR}")
        if(DEFINED ONNXRUNTIME_URL)
            # A .zip or .tgz laid out like Microsoft's release archives, which
            # extracts to a directory like lib/onnxruntime-linux-x64-1.22.0/
            set(ONNXRUNTIME_FILENAME "${ONNXRUNTIME_PREFIX}.${ONNXRUNTIME_EXT}")
            piper_download("${ONNXRUNTIME_URL}" "${ONNXRUNTIME_DOWNLOAD_DIR}/${ONNXRUNTIME_FILENAME}" "${ONNXRUNTIME_SHA256}")
            file(ARCHIVE_EXTRACT INPUT "${ONNXRUNTIME_DOWNLOAD_DIR}/${ONNXRUNTIME_FILENAME}" DESTINATION "${CMAKE_CURRENT_LIST_DIR}/lib")
        else()
            # Microsoft's NuGet package: one archive for every platform, with
            # the headers in build/native/include and the libraries in
            # runtimes/<rid>/native
            set(ONNXRUNTIME_FILENAME "microsoft.ml.onnxruntime.${ONNXRUNTIME_VERSION}.nupkg")
            set(ONNXRUNTIME_NUGET_URL "https://api.nuget.org/v3-flatcontainer/microsoft.ml.onnxruntime/${ONNXRUNTIME_VERSION}/${ONNXRUNTIME_FILENAME}")
            if(NOT ONNXRUNTIME_SHA256)
                message(WARNING "No SHA256 for onnxruntime ${ONNXRUNTIME_VERSION}; set ONNXRUNTIME_SHA256 to verify the download")
            endif()
            piper_download("${ONNXRUNTIME_NUGET_URL}" "${ONNXRUNTIME_DOWNLOAD_DIR}/${ONNXRUNTIME_FILENAME}" "${ONNXRUNTIME_SHA256}")

            set(nuget_dir "${ONNXRUNTIME_DOWNLOAD_DIR}/nuget-${ONNXRUNTIME_VERSION}")
            set(native_dir "${nuget_dir}/runtimes/${ONNXRUNTIME_RID}/native")
            set(staging_dir "${ONNXRUNTIME_DIR}.part")
            file(REMOVE_RECURSE "${nuget_dir}" "${staging_dir}")
            file(ARCHIVE_EXTRACT INPUT "${ONNXRUNTIME_DOWNLOAD_DIR}/${ONNXRUNTIME_FILENAME}" DESTINATION "${nuget_dir}"
                PATTERNS "build/native/include/*" "runtimes/${ONNXRUNTIME_RID}/native/*" "LICENSE" "ThirdPartyNotices.txt")

            file(MAKE_DIRECTORY "${staging_dir}/lib")
            file(COPY "${nuget_dir}/build/native/include/" DESTINATION "${staging_dir}/include")
            file(COPY "${nuget_dir}/LICENSE" "${nuget_dir}/ThirdPartyNotices.txt" DESTINATION "${staging_dir}")

            # Give the library the file names of the release archives, which
            # its embedded name (install name or soname) refers to
            if(WIN32)
                file(COPY "${native_dir}/" DESTINATION "${staging_dir}/lib")
            elseif(APPLE)
                # Install name: @rpath/libonnxruntime.<version>.dylib
                file(COPY_FILE "${native_dir}/libonnxruntime.dylib" "${staging_dir}/lib/libonnxruntime.${ONNXRUNTIME_VERSION}.dylib")
                file(CREATE_LINK "libonnxruntime.${ONNXRUNTIME_VERSION}.dylib" "${staging_dir}/lib/libonnxruntime.dylib" SYMBOLIC)
            else()
                # Soname: libonnxruntime.so.<major>
                string(REGEX MATCH "^[0-9]+" onnxruntime_major "${ONNXRUNTIME_VERSION}")
                file(COPY_FILE "${native_dir}/libonnxruntime.so" "${staging_dir}/lib/libonnxruntime.so.${ONNXRUNTIME_VERSION}")
                file(CREATE_LINK "libonnxruntime.so.${ONNXRUNTIME_VERSION}" "${staging_dir}/lib/libonnxruntime.so.${onnxruntime_major}" SYMBOLIC)
                file(CREATE_LINK "libonnxruntime.so.${onnxruntime_major}" "${staging_dir}/lib/libonnxruntime.so" SYMBOLIC)
                file(COPY "${native_dir}/libonnxruntime_providers_shared.so" DESTINATION "${staging_dir}/lib")
            endif()

            file(RENAME "${staging_dir}" "${ONNXRUNTIME_DIR}")
            file(REMOVE_RECURSE "${nuget_dir}")
        endif()
    endif()
endif()

if(DEFINED ONNXRUNTIME_DIR)
    find_library(ONNXRUNTIME_LIB NAMES onnxruntime PATHS ${ONNXRUNTIME_DIR}/lib REQUIRED)
    add_library(onnxruntime::onnxruntime UNKNOWN IMPORTED)
    set_target_properties(onnxruntime::onnxruntime PROPERTIES
        IMPORTED_LOCATION ${ONNXRUNTIME_LIB}
        INTERFACE_INCLUDE_DIRECTORIES ${ONNXRUNTIME_DIR}/include
    )
endif()

# ---- linting ----
include(ClangTidy.cmake)
# ---- libpiper ---

add_library(piper SHARED
    ${CMAKE_CURRENT_SOURCE_DIR}/src/piper.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/src/chinese_phonemizer.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/src/japanese_phonemizer.cpp
)
enable_clang_tidy(piper)

add_dependencies(piper espeak_ng_external openjtalk_external)
target_include_directories(piper PUBLIC
    ${ESPEAKNG_INSTALL_DIR}/include
    ${OPENJTALK_INCLUDE_DIRS}
    ${CMAKE_CURRENT_SOURCE_DIR}/include
)
target_link_libraries(piper
    ${ESPEAKNG_STATIC_LIB}
    ${UCD_STATIC_LIB}
    ${OPENJTALK_STATIC_LIB}
    onnxruntime::onnxruntime
)

# ---- piper exe ---
add_subdirectory(src/main)

# ---- version
file(READ ${CMAKE_SOURCE_DIR}/../setup.py SETUP_PY_CONTENTS)
string(REGEX MATCH "version=\"([0-9]+\\.[0-9]+\\.[0-9]+)\"" _ ${SETUP_PY_CONTENTS})
set(PIPER_VERSION ${CMAKE_MATCH_1})

if(PIPER_VERSION)
  message(STATUS "Parsed Piper Version: ${PIPER_VERSION}")
  target_compile_definitions(piper PRIVATE PIPER_VERSION="${PIPER_VERSION}")
else()
  message(WARNING "Could not parse version from setup.py")
endif()

# Windows DLL export for Chinese phonemizer symbols (fixes LNK2019)
target_compile_definitions(piper PRIVATE BUILDING_LIBPIPER)


# ---- install ---

include(GNUInstallDirs)

if(WIN32)
    install(TARGETS piper
        RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
        ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
    )
else()
    install(TARGETS piper
        DESTINATION ${CMAKE_INSTALL_LIBDIR}
    )
endif()

install(
    FILES ${CMAKE_CURRENT_SOURCE_DIR}/include/piper.h
    DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}
)

if(DEFINED ONNXRUNTIME_DIR)
    if(WIN32)
        install(
            DIRECTORY ${ONNXRUNTIME_DIR}/lib/
            DESTINATION ${CMAKE_INSTALL_BINDIR}
            FILES_MATCHING PATTERN "*.dll"
            PATTERN "cmake" EXCLUDE
            PATTERN "pkgconfig" EXCLUDE
        )
        install(
            DIRECTORY ${ONNXRUNTIME_DIR}/lib/
            DESTINATION ${CMAKE_INSTALL_LIBDIR}
            PATTERN "*.dll" EXCLUDE
            PATTERN "cmake" EXCLUDE
            PATTERN "pkgconfig" EXCLUDE
        )
    else()
        install(
            DIRECTORY ${ONNXRUNTIME_DIR}/lib/
            DESTINATION ${CMAKE_INSTALL_LIBDIR}
            PATTERN "cmake" EXCLUDE
            PATTERN "pkgconfig" EXCLUDE
        )
    endif()
endif()

# Copy espeak-ng-data
set(ESPEAKNG_DATA_SRC ${CMAKE_BINARY_DIR}/espeak_ng-install/share/espeak-ng-data)

install(
    DIRECTORY ${ESPEAKNG_DATA_SRC}
    DESTINATION ${CMAKE_INSTALL_DATAROOTDIR}
)

if(WIN32)
    # The CLI looks next to its executable; retain the shared API data above.
    install(
        DIRECTORY ${ESPEAKNG_DATA_SRC}
        DESTINATION ${CMAKE_INSTALL_BINDIR}
    )
endif()

# ----------------
# Testing
# ----------------
option(PIPER_BUILD_TESTS "Build piper tests" OFF)

if(PIPER_BUILD_TESTS)
    enable_testing()
    add_subdirectory(tests)
endif()



# ---- clang format ---
find_program(CLANG_FORMAT clang-format)

set(CLANG_FORMAT_ARGS "-i" CACHE STRING "Arguments for clang-format")

if(CLANG_FORMAT)
    file(GLOB_RECURSE FORMAT_SOURCES
        "src/*.cpp"
        "src/*.h"
        "src/*.hpp"
        "tests/*.cpp"
        "tests/*.h"
        "tests/*.hpp"
        "include/piper.h"
        "include/piper_impl.hpp"
    )

    add_custom_target(format
        COMMAND ${CLANG_FORMAT} ${CLANG_FORMAT_ARGS} ${FORMAT_SOURCES}
        COMMENT "Formatting C/C++ files with clang-format"
    )
    message(STATUS "Added 'format' target to run clang-format.")
else()
    message(WARNING "clang-format not found. The 'format' target will not be available.")
endif()
