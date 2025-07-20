cmake_minimum_required(VERSION 3.16)
project(piper)

if(ANDROID)
    # Termux/Android specific handling
    set(TERMUX_PREFIX "/data/data/com.termux/files/usr")
    set(PYTHON_SITE_PACKAGES "${TERMUX_PREFIX}/lib/python${Python_VERSION_MAJOR}.${Python_VERSION_MINOR}/site-packages")

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

    # Install python-onnxruntime
    try_install_pkg(python-onnxruntime)

    # Check for ONNX Runtime library and headers
    find_library(ONNX_RUNTIME_LIB onnxruntime PATHS
        ${PYTHON_SITE_PACKAGES}/onnxruntime/capi
        ${TERMUX_PREFIX}/lib
        NO_DEFAULT_PATH
    )
    find_path(ONNX_RUNTIME_INCLUDE_DIR onnxruntime_c_api.h PATHS
        ${TERMUX_PREFIX}/include
        NO_DEFAULT_PATH
    )
    if(NOT ONNX_RUNTIME_LIB OR NOT ONNX_RUNTIME_INCLUDE_DIR)
        message(FATAL_ERROR "ONNX Runtime library or headers not found after installation. Please verify the installation.")
    endif()
    message(STATUS "Found ONNX Runtime library: ${ONNX_RUNTIME_LIB}")
    message(STATUS "Found ONNX Runtime include dir: ${ONNX_RUNTIME_INCLUDE_DIR}")

    # --- Build espeak-ng from source ---
    include(ExternalProject)

    set(ESPEAK_NG_SRC_DIR "${CMAKE_CURRENT_SOURCE_DIR}/third-party/espeak-ng")
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
        CONFIGURE_COMMAND ./autogen.sh && ./configure --prefix=${ESPEAK_NG_INSTALL_DIR}
        BUILD_COMMAND make -j4
        INSTALL_COMMAND make install
        BYPRODUCTS ${ESPEAKNG_LIB}
    )

    add_subdirectory(libpiper)

    # Add dependency to ensure espeak-ng is built before our main target
    add_dependencies(piper espeak_ng_external)

    set(ESPEAKNG_STATIC_LIB ${ESPEAKNG_LIB})
    set(UCD_STATIC_LIB "") # Not needed for shared espeak-ng

    # Include directories for Termux
    include_directories(
        ${ESPEAKNG_INCLUDE_DIR}
        ${PYTHON_INCLUDE_DIRS}
        ${TERMUX_PREFIX}/include/python${Python_VERSION_MAJOR}.${Python_VERSION_MINOR}
    )
endif()
