cmake_minimum_required(VERSION 3.16)
project(piper LANGUAGES C CXX)

# Common elements for all platforms
find_package(Python COMPONENTS Development.Module Development.SABIModule REQUIRED)

# espeak bridge library definition (properties will be set conditionally)
add_library(espeakbridge MODULE src/piper/espeakbridge.c)

if(WIN32)
    message(STATUS "Building for Windows")

    include(ExternalProject)

    # Install location for espeak-ng
    set(ESPEAKNG_BUILD_DIR ${CMAKE_BINARY_DIR}/espeak_ng)
    set(ESPEAKNG_INSTALL_DIR ${CMAKE_BINARY_DIR}/espeak_ng-install)

    set(ESPEAKNG_STATIC_LIB ${ESPEAKNG_INSTALL_DIR}/lib/espeak-ng.lib)
    set(UCD_STATIC_LIB ${ESPEAKNG_BUILD_DIR}/src/espeak_ng_external-build/src/ucd-tools/ucd.lib)

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

    add_dependencies(espeakbridge espeak_ng_external)
    target_link_libraries(espeakbridge
        ${ESPEAKNG_STATIC_LIB}
        ${UCD_STATIC_LIB}
        Python::SABIModule
    )
    target_include_directories(espeakbridge PRIVATE
        ${ESPEAKNG_INSTALL_DIR}/include
    )

    # Fix dll thunk issue (__imp_SYMBOL not found)
    target_compile_definitions(espeakbridge PRIVATE LIBESPEAK_NG_EXPORT)

    # Fix .dll suffix
    set_target_properties(espeakbridge PROPERTIES
        PREFIX ""
        SUFFIX ".pyd"
    )

elseif(ANDROID)
    message(STATUS "Building for Android (Termux)")

    # Termux/Android specific handling
    set(PREFIX "/data/data/com.termux/files/usr")
    set(Python_VERSION_MAJOR 3)
    set(Python_VERSION_MINOR 12)
    set(PYTHON_SITE_PACKAGES "${PREFIX}/lib/python${Python_VERSION_MAJOR}.${Python_VERSION_MINOR}/site-packages")
    message(STATUS "DEBUG: Environment PATH: $ENV{PATH}")
    message(STATUS "DEBUG: Environment LD_LIBRARY_PATH: $ENV{LD_LIBRARY_PATH}")

    # Helper function to install Termux packages
    function(try_install_pkg PKG_NAME)
        find_program(PKG_EXECUTABLE NAMES pkg)
        if(NOT PKG_EXECUTABLE)
            message(FATAL_ERROR "Termux 'pkg' command not found. Please ensure Termux is properly set up and try manually installing '${PKG_NAME}' with 'pkg install ${PKG_NAME}'.")
        endif()

        message(STATUS "Installing ${PKG_NAME} via pkg...")
        execute_process(
            COMMAND ${PKG_EXECUTABLE} install -y ${PKG_NAME}
            RESULT_VARIABLE PKG_INSTALL_RESULT
            OUTPUT_VARIABLE PKG_INSTALL_OUTPUT
            ERROR_VARIABLE PKG_INSTALL_ERROR
        )
        if(NOT PKG_INSTALL_RESULT EQUAL 0)
            message(WARNING "Failed to install ${PKG_NAME}: ${PKG_INSTALL_ERROR}\n${PKG_INSTALL_OUTPUT}")
            message(FATAL_ERROR "Please manually install '${PKG_NAME}' using 'pkg install ${PKG_NAME}' and ensure network connectivity.")
        endif()
        message(STATUS "${PKG_NAME} installed successfully.")
    endfunction()

    set(TERMUX_PACKAGES espeak python-onnxruntime autoconf automake)
    foreach(PKG IN LISTS TERMUX_PACKAGES)
        try_install_pkg(${PKG})
    endforeach()

    # Check for ONNX Runtime library and headers
    message(STATUS "DEBUG: Searching for ONNX Runtime library in:")
    message(STATUS "DEBUG:   ${PYTHON_SITE_PACKAGES}/onnxruntime/capi")
    message(STATUS "DEBUG:   ${PREFIX}/lib")
    find_library(ONNX_RUNTIME_LIB onnxruntime PATHS
        ${PYTHON_SITE_PACKAGES}/onnxruntime/capi
        ${PREFIX}/lib
    )
    message(STATUS "DEBUG: Searching for ONNX Runtime include dir in:")
    message(STATUS "DEBUG:   ${PREFIX}/include")
    find_path(ONNX_RUNTIME_INCLUDE_DIR onnxruntime_c_api.h PATHS
        ${PREFIX}/include
    )
    message(STATUS "DEBUG: ONNX_RUNTIME_LIB = ${ONNX_RUNTIME_LIB}")
    message(STATUS "DEBUG: ONNX_RUNTIME_INCLUDE_DIR = ${ONNX_RUNTIME_INCLUDE_DIR}")
    if(NOT ONNX_RUNTIME_LIB OR NOT ONNX_RUNTIME_INCLUDE_DIR)
        message(FATAL_ERROR "ONNX Runtime library or headers not found after installation. Please verify the installation.")
    endif()

    # --- Build espeak-ng from source ---
    include(ExternalProject)

    set(ESPEAK_NG_SRC_DIR "${CMAKE_CURRENT_SOURCE_DIR}/third_party/espeak-ng")
    set(ESPEAK_NG_INSTALL_DIR "${CMAKE_BINARY_DIR}/espeak-ng-install")
    set(ESPEAKNG_LIB "${ESPEAK_NG_INSTALL_DIR}/lib/libespeak-ng.so")
    set(ESPEAKNG_INCLUDE_DIR "${ESPEAK_NG_INSTALL_DIR}/include")

    if(NOT EXISTS "${ESPEAK_NG_SRC_DIR}/.git")
        message(STATUS "Cloning espeak-ng repository...")
        execute_process(
            COMMAND git clone https://github.com/espeak-ng/espeak-ng.git ${ESPEAK_NG_SRC_DIR}
            RESULT_VARIABLE GIT_CLONE_RESULT
        )
        if(NOT GIT_CLONE_RESULT EQUAL 0)
            message(FATAL_ERROR "Failed to clone espeak-ng repository.")
        endif()
    endif()

    ExternalProject_Add(espeak_ng_external
        SOURCE_DIR ${ESPEAK_NG_SRC_DIR}
        CONFIGURE_COMMAND sh -c "cd ${ESPEAK_NG_SRC_DIR} && ./autogen.sh && ./configure --prefix=${ESPEAK_NG_INSTALL_DIR}"
        BUILD_COMMAND make -j4
        INSTALL_COMMAND make install
        BYPRODUCTS ${ESPEAKNG_LIB} ${ESPEAK_NG_INSTALL_DIR}/share/espeak-ng-data
        BUILD_IN_SOURCE 1
        # Ensure Termux binaries are in PATH for autogen.sh and its sub-processes
        ENV PATH "${PREFIX}/bin:$ENV{PATH}"
    )

    add_dependencies(espeakbridge espeak_ng_external)
    target_link_libraries(espeakbridge
        ${ESPEAKNG_LIB}
        ${ONNX_RUNTIME_LIB}
    )
    target_include_directories(espeakbridge PRIVATE
        ${ESPEAKNG_INCLUDE_DIR}
        ${ONNX_RUNTIME_INCLUDE_DIR}
        ${PYTHON_INCLUDE_DIRS}
        ${PREFIX}/include/python${Python_VERSION_MAJOR}.${Python_VERSION_MINOR}
        ${PREFIX}/include
    )

    # Set properties for espeakbridge (shared library)
    set_target_properties(espeakbridge PROPERTIES
        PREFIX ""
    )

    # libpiper is handled by its own CMakeLists.txt
    add_subdirectory(libpiper)

    # Add dependency to ensure espeak-ng is built before our main target
    add_dependencies(piper espeak_ng_external)

    install(TARGETS espeakbridge
        LIBRARY DESTINATION .
        RUNTIME DESTINATION .
    )

    # Copy espeak-ng-data
    set(DATA_SRC ${CMAKE_BINARY_DIR}/espeak-ng-install/share/espeak-ng-data)
    set(DATA_DST ${CMAKE_CURRENT_SOURCE_DIR}/src/piper/espeak-ng-data)

    add_custom_target(copy_espeak_ng_data ALL
        COMMAND ${CMAKE_COMMAND} -E copy_directory ${DATA_SRC} ${DATA_DST}
        DEPENDS espeak_ng_external
        COMMENT "Copying espeak-ng-data after espeak-ng external project builds"
    )

elseif(UNIX) # Covers Linux and macOS
    message(STATUS "Building for generic Unix (Linux/macOS)")

    include(ExternalProject)

    # Install location for espeak-ng
    set(ESPEAKNG_BUILD_DIR ${CMAKE_BINARY_DIR}/espeak_ng)
    set(ESPEAKNG_INSTALL_DIR ${CMAKE_BINARY_DIR}/espeak_ng-install)

    set(ESPEAKNG_STATIC_LIB ${ESPEAKNG_INSTALL_DIR}/lib/libespeak-ng.a)
    set(UCD_STATIC_LIB ${ESPEAKNG_BUILD_DIR}/src/espeak_ng_external-build/src/ucd-tools/libucd.a)

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

    add_dependencies(espeakbridge espeak_ng_external)
    target_link_libraries(espeakbridge
        ${ESPEAKNG_STATIC_LIB}
        ${UCD_STATIC_LIB}
        Python::SABIModule
    )
    target_include_directories(espeakbridge PRIVATE
        ${ESPEAKNG_INSTALL_DIR}/include
    )

    install(TARGETS espeakbridge
        LIBRARY DESTINATION .
        RUNTIME DESTINATION .
    )

    # Copy espeak-ng-data
    set(DATA_SRC ${CMAKE_BINARY_DIR}/espeak_ng-install/share/espeak-ng-data)
    set(DATA_DST ${CMAKE_CURRENT_SOURCE_DIR}/src/piper/espeak-ng-data)

    add_custom_target(copy_espeak_ng_data ALL
        COMMAND ${CMAKE_COMMAND} -E copy_directory ${DATA_SRC} ${DATA_DST}
        DEPENDS espeak_ng_external
        COMMENT "Copying espeak-ng-data after espeak-ng external project builds"
    )

else()
    message(FATAL_ERROR "Unsupported platform")
endif()