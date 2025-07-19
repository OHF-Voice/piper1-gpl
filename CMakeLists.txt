# Builds Python module for Piper using espeak-ng and cmake.
#
# This is called automatically by scikit-build from setup.py.
cmake_minimum_required(VERSION 3.26)
project(piper LANGUAGES C CXX)



# scikit-build-core will forward Python_* variables
find_package(Python COMPONENTS Development.Module Development.SABIModule REQUIRED)

# Install location for espeak-ng




# espeak bridge
add_library(espeakbridge MODULE
    src/piper/espeakbridge.c
)

target_link_libraries(espeakbridge
    espeak-ng
    Python::SABIModule
)
target_include_directories(espeakbridge PRIVATE
    /data/data/com.termux/files/usr/include
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


