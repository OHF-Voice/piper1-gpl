# Builds Python module for Piper using espeak-ng and cmake.
#
# This is called automatically by scikit-build from setup.py.
cmake_minimum_required(VERSION 3.26)
project(piper LANGUAGES C CXX)

# Get the required variable 'GIT_EXECUTABLE'.
find_package(Git REQUIRED)

option(BUILD_TESTING "Enable project tests" ON)
if(BUILD_TESTING)
    enable_testing()
endif()

include(ExternalProject)

if (NOT PIPER_BUILD_LIB_ONLY)
# scikit-build-core will forward Python_* variables
    find_package(Python COMPONENTS Development.Module Development.SABIModule REQUIRED)
#    include(CMakePrintHelpers)
#    cmake_print_variables(Python_VERSION Python_INCLUDE_DIRS Python_LIBRARIES)
endif ()


# Install location for espeak-ng
set(ESPEAKNG_BUILD_DIR ${CMAKE_BINARY_DIR}/espeak_ng)
set(ESPEAKNG_INSTALL_DIR ${CMAKE_BINARY_DIR}/espeak_ng-install)

if(WIN32 AND MSVC)
    # Special handling for Windows
    set(ESPEAKNG_STATIC_LIB ${ESPEAKNG_INSTALL_DIR}/lib/espeak-ng.lib)
    set(UCD_STATIC_LIB ${ESPEAKNG_BUILD_DIR}/src/espeak_ng_external-build/src/ucd-tools/ucd.lib)
else()
    set(ESPEAKNG_STATIC_LIB ${ESPEAKNG_INSTALL_DIR}/lib/libespeak-ng.a)
    set(UCD_STATIC_LIB ${ESPEAKNG_BUILD_DIR}/src/espeak_ng_external-build/src/ucd-tools/libucd.a)
endif()

# Windows does not have a patch command and the built-in patch command does not work on a non repo source tree.
if(CMAKE_HOST_WIN32)
	find_package(Git QUIET)
	if(Git_FOUND)
		get_filename_component(GIT_DIR "${GIT_EXECUTABLE}" DIRECTORY)
		get_filename_component(GIT_ROOT "${GIT_DIR}" DIRECTORY)
		# Just add it to the path but using HINTS is also an option.
		list(APPEND CMAKE_PROGRAM_PATH "${GIT_ROOT}/usr/bin")
	endif()
endif()

# Find the re'Patch_EXECUTABLE' variable.
find_package(Patch REQUIRED)
# Location of the patch file.
set(_PatchFile "${CMAKE_CURRENT_LIST_DIR}/libpiper/src/espeak.patch")
# Patch command for when the source is Git cloned.
#set(_PatchCommand "${GIT_EXECUTABLE}" "apply" "--check" "--reverse" "${_PatchFile}" "||" "${GIT_EXECUTABLE}" "apply" "${_PatchFile}")
# Patch command when the source is unzipped.
set(_PatchCommand "${Patch_EXECUTABLE}" "--reverse" "--strip=1" "--input=${_PatchFile}" "||" "${Patch_EXECUTABLE}" "--strip=1" "--input=${_PatchFile}")

# Add the external 'espeak' project and apply the patch to use it as a static library only.
ExternalProject_Add(espeak_ng_external
		# Use of zip-file for commit hash. Is faster then Git and requires 150 MByte less storage space.
		URL https://github.com/espeak-ng/espeak-ng/archive/724808c5a83f9ef95fdd0db886ba7ba537ff224a.zip
    #GIT_REPOSITORY https://github.com/espeak-ng/espeak-ng.git
    #GIT_TAG 724808c5a83f9ef95fdd0db886ba7ba537ff224a # 2026-Apr-06
    PREFIX ${ESPEAKNG_BUILD_DIR}
    CMAKE_ARGS
        -DCMAKE_CROSSCOMPILING:BOOL=${CMAKE_CROSSCOMPILING}
        -DCMAKE_BUILD_TYPE=${CMAKE_BUILD_TYPE}
        # To allow this to work the minimum cmake version is also patched.
        # By linking the VCRT static libs it will prevent MSVC linker errors in dependent projects.
        #-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded$<$<CONFIG:Debug>:Debug>
        # Forward the current toolchain file.
        -DCMAKE_TOOLCHAIN_FILE=${CMAKE_TOOLCHAIN_FILE}
        -DCMAKE_SYSTEM_NAME=${CMAKE_SYSTEM_NAME}
        -DCMAKE_INSTALL_PREFIX=${ESPEAKNG_INSTALL_DIR}
        -DBUILD_SHARED_LIBS:BOOL=OFF
        # Do not compile intonation files when Piper used as a module in another project.
        -DCOMPILE_INTONATIONS:BOOL=${PROJECT_IS_TOP_LEVEL}
        # When not disabling tests when not the top level project, the build fails.
        -DENABLE_TESTS:BOOL=${PROJECT_IS_TOP_LEVEL}
        -DCMAKE_POSITION_INDEPENDENT_CODE:BOOL=ON
        -DUSE_ASYNC:BOOL=OFF
        -DUSE_MBROLA:BOOL=OFF
        -DUSE_LIBSONIC:BOOL=OFF
        -DUSE_LIBPCAUDIO:BOOL=OFF
        -DUSE_KLATT:BOOL=OFF
        -DUSE_SPEECHPLAYER:BOOL=OFF
        -DEXTRA_cmn:BOOL=ON
        -DEXTRA_ru:BOOL=ON
        # N_PATH_HOME sizes espeak-ng's data directory buffer. It defaults to
        # PATH_MAX on Linux but only 160 bytes elsewhere, and a longer path is
        # silently truncated and replaced by the build-time PATH_ESPEAK_DATA.
        #
        # Need to explicitly add ucd include directory for CI
        "-DCMAKE_C_FLAGS=-D_FILE_OFFSET_BITS=64 -I${ESPEAKNG_BUILD_DIR}/src/espeak_ng_external/src/ucd-tools/src/include"
        "-DCMAKE_CXX_FLAGS=-D_FILE_OFFSET_BITS=64 -I${ESPEAKNG_BUILD_DIR}/src/espeak_ng_external/src/ucd-tools/src/include"
    BUILD_BYPRODUCTS
        ${ESPEAKNG_STATIC_LIB}
        ${UCD_STATIC_LIB}
    UPDATE_DISCONNECTED TRUE
    # Headers are only importing or exporting functions but no consideration when only as a private static library.
    # Does not make cmake abort when the patch has already been performed by first checking it.
    # Patching with Git is only possible when it is a Git repository.
    PATCH_COMMAND ${_PatchCommand}
)

include_directories(
    ${ESPEAKNG_INSTALL_DIR}/include
)

if (NOT PIPER_BUILD_LIB_ONLY)

# espeak bridge
add_library(espeakbridge MODULE
    src/piper/espeakbridge.c
)

add_dependencies(espeakbridge espeak_ng_external)
target_link_libraries(espeakbridge
    ${ESPEAKNG_STATIC_LIB}
    ${UCD_STATIC_LIB}
    Python::SABIModule
)
target_include_directories(espeakbridge PRIVATE
    ${ESPEAKNG_INSTALL_DIR}/include
)

if(WIN32)
    # Fix dll thunk issue (__imp_SYMBOL not found)
    target_compile_definitions(espeakbridge PRIVATE LIBESPEAK_NG_EXPORT)

    # Fix .dll suffix
    set_target_properties(espeakbridge PROPERTIES
        PREFIX ""
        SUFFIX ".pyd"
    )
else()
    set_target_properties(espeakbridge PROPERTIES
        PREFIX ""
    )
endif()

install(TARGETS espeakbridge
    LIBRARY DESTINATION .
    RUNTIME DESTINATION .
)

endif()

# Projects using this repository as submodule need to deal with 'espeak-ng-data' directory themself.
if (PROJECT_IS_TOP_LEVEL)

    # Copy espeak-ng-data
    set(DATA_SRC ${CMAKE_BINARY_DIR}/espeak_ng-install/share/espeak-ng-data)
    set(DATA_DST ${CMAKE_CURRENT_SOURCE_DIR}/src/piper/espeak-ng-data)

    # The native compiled should have done the copy first.
    if (NOT CMAKE_CROSSCOMPILING)
    add_custom_target(copy_espeak_ng_data ALL
        COMMAND ${CMAKE_COMMAND} -E copy_directory "${DATA_SRC}" "${DATA_DST}"
        DEPENDS espeak_ng_external
        COMMENT "Copying espeak-ng-data after espeak-ng external project builds"
    )
    else ()
        if (NOT EXISTS "${DATA_DST}")
            message(FATAL_ERROR "Compile native first to create directory: ${DATA_DST}")
        else ()
            message(VERBOSE "Found required directory: ${DATA_DST}")
        endif ()
    endif ()

endif ()

message(STATUS "Compiling from ${CMAKE_HOST_SYSTEM_PROCESSOR} for ${CMAKE_SYSTEM_PROCESSOR}")

add_subdirectory(libpiper)
