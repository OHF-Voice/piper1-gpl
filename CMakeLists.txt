# Builds Python module for Piper using espeak-ng and cmake.
#
# This is called automatically by scikit-build from setup.py.
cmake_minimum_required(VERSION 3.26)
project(piper LANGUAGES C CXX)

find_package(Python COMPONENTS Interpreter Development REQUIRED)

if(ANDROID)
    # Termux/Android specific handling for ONNX Runtime and espeak-ng
    set(ONNX_RUNTIME_VERSION "1.22.0") # Match the version from README.md
    set(ONNX_RUNTIME_AAR_URL "https://repo1.maven.org/maven2/com/microsoft/onnxruntime/onnxruntime-android/${ONNX_RUNTIME_VERSION}/onnxruntime-android-${ONNX_RUNTIME_VERSION}.aar")
    set(ONNX_RUNTIME_DOWNLOAD_DIR ${CMAKE_BINARY_DIR}/onnxruntime_download)
    set(ONNX_RUNTIME_EXTRACT_DIR ${CMAKE_BINARY_DIR}/onnxruntime_extracted)
    set(ONNX_RUNTIME_LIB_PATH ${ONNX_RUNTIME_EXTRACT_DIR}/jni/arm64-v8a/libonnxruntime.so)

    # Create download and extract directories
    file(MAKE_DIRECTORY ${ONNX_RUNTIME_DOWNLOAD_DIR})
    file(MAKE_DIRECTORY ${ONNX_RUNTIME_EXTRACT_DIR})

    # Download ONNX Runtime AAR
    file(DOWNLOAD ${ONNX_RUNTIME_AAR_URL} ${ONNX_RUNTIME_DOWNLOAD_DIR}/onnxruntime-android-${ONNX_RUNTIME_VERSION}.aar
         STATUS download_status
         LOG download_log)

    if(NOT download_status EQUAL 0)
        message(FATAL_ERROR "Failed to download ONNX Runtime AAR: ${download_log}")
    endif()

    # Extract libonnxruntime.so
    execute_process(COMMAND unzip ${ONNX_RUNTIME_DOWNLOAD_DIR}/onnxruntime-android-${ONNX_RUNTIME_VERSION}.aar -d ${ONNX_RUNTIME_EXTRACT_DIR}
                    RESULT_VARIABLE unzip_result
                    OUTPUT_VARIABLE unzip_output
                    ERROR_VARIABLE unzip_error)

    if(NOT unzip_result EQUAL 0)
        message(FATAL_ERROR "Failed to extract ONNX Runtime AAR: ${unzip_error}")
    endif()

    # Set espeak-ng and ONNX Runtime libraries for Android
    # For Termux, we assume espeak-ng is system-installed via pkg
    find_library(ESPEAKNG_LIB espeak-ng PATHS /data/data/com.termux/files/usr/lib NO_DEFAULT_PATH)
    if(NOT ESPEAKNG_LIB)
        message(FATAL_ERROR "espeak-ng library not found. Please install it via 'pkg install espeak'.")
    endif()

    set(ESPEAKNG_STATIC_LIB ${ESPEAKNG_LIB})
    set(UCD_STATIC_LIB "") # Not needed for system espeak-ng
    set(ONNX_RUNTIME_LIB ${ONNX_RUNTIME_LIB_PATH})

    # Add ONNX Runtime include directory (assuming it's within the extracted AAR)
    include_directories(${ONNX_RUNTIME_EXTRACT_DIR}/jni/arm64-v8a/include)

    # Add Termux system include directory for espeak-ng headers
    include_directories(/data/data/com.termux/files/usr/include)

else()
    # Original espeak-ng ExternalProject_Add for non-Android platforms
    include(ExternalProject)

    # Install location for espeak-ng
    set(ESPEAKNG_BUILD_DIR ${CMAKE_BINARY_DIR}/espeak_ng)
    set(ESPEAKNG_INSTALL_DIR ${CMAKE_BINARY_DIR}/espeak_ng-install)

    if(WIN32)
        # Special handling for Windows
        set(ESPEAKNG_STATIC_LIB ${ESPEAKNG_INSTALL_DIR}/lib/espeak-ng.lib)
        set(UCD_STATIC_LIB ${ESPEAKNG_BUILD_DIR}/src/espeak_ng_external-build/src/ucd-tools/ucd.lib)
    else()
        set(ESPEAKNG_STATIC_LIB ${ESPEAKNG_INSTALL_DIR}/lib/libespeak-ng.a)
        set(UCD_STATIC_LIB ${ESPEAKNG_BUILD_DIR}/src/espeak_ng_external-build/src/ucd-tools/libucd.a)
    endif()

    ExternalProject_Add(espeak_ng_external
        GIT_REPOSITORY https://github.com/espeak-ng/espeak-ng.git
        GIT_TAG 212928b394a96e8fd2096616bfd54e17845c48f6  # 2025-Mar-22
        PREFIX ${ESPEAKNG_BUILD_DIR}
        CMAKE_ARGS
            -DCMAKE_INSTALL_PREFIX=${ESPEAKNG_INSTALL_DIR}
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
        BUILD_BYPRODUCTS
            ${ESPEAKNG_STATIC_LIB}
            ${UCD_STATIC_LIB}
        UPDATE_DISCONNECTED TRUE
    )

    include_directories(
        ${ESPEAKNG_INSTALL_DIR}/include
    )
endif()

# espeak bridge
add_library(espeakbridge MODULE
    src/piper/espeakbridge.c
)

if(ANDROID)
    target_link_libraries(espeakbridge
        ${ESPEAKNG_LIB}
        ${ONNX_RUNTIME_LIB}
        ${PYTHON_LIBRARIES}
    )
    target_include_directories(espeakbridge PRIVATE
        ${PYTHON_INCLUDE_DIRS}
        /data/data/com.termux/files/usr/include/python3.12/
    )
else()
    add_dependencies(espeakbridge espeak_ng_external)
    target_link_libraries(espeakbridge
        ${ESPEAKNG_STATIC_LIB}
        ${UCD_STATIC_LIB}
        ${PYTHON_LIBRARIES}
    )
    target_include_directories(espeakbridge PRIVATE
        ${PYTHON_INCLUDE_DIRS}
    )
endif()

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


