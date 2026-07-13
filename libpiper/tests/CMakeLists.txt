cmake_minimum_required(VERSION 3.26)

message(STATUS "Building piper tests")
include(FetchContent)
FetchContent_Declare(
    googletest
    GIT_REPOSITORY https://github.com/google/googletest.git
    GIT_TAG v1.17.0
)

# For Windows: Prevent overriding the parent project's compiler/linker settings
set(gtest_force_shared_crt ON CACHE BOOL "" FORCE)
FetchContent_MakeAvailable(googletest)

enable_testing()

include(DownloadModel.cmake)

download_piper_model(VOICE "en/en_US/lessac/medium/en_US-lessac-medium"
                     OUTPUT_DIR EN_MODEL_DIR)

add_executable(piper_test
   test_piper.cpp
   utils/piper_test_assets.h
   utils/piper_test_assets.cpp
   test_main_utils.cpp
   test_process.cpp
   test_wav_headers.cpp
   test_wavfile.cpp
)

target_compile_definitions(piper_test
    PRIVATE "ESPEAK_DATA_PATH=\"${CMAKE_BINARY_DIR}/espeak_ng-install/share/espeak-ng-data\""
    PRIVATE "EN_TEST_MODEL_DIR=\"${EN_MODEL_DIR}\""
)

target_link_libraries(piper_test
    PRIVATE piper
    PRIVATE GTest::gtest_main
    PRIVATE main_utils
)

target_link_directories(piper_test PUBLIC
    ${ONNXRUNTIME_DIR}/lib
)

if(WIN32)
    add_custom_command(TARGET piper_test POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "$<TARGET_FILE:piper>"
        "$<TARGET_FILE_DIR:piper_test>"
    )
    add_custom_command(TARGET piper_test POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "${ONNXRUNTIME_DIR}/lib/onnxruntime.dll"
        "$<TARGET_FILE_DIR:piper_test>"
    )
endif()

include(GoogleTest)
get_target_property(PIPER_BINARY_DIR piper BINARY_DIR)

gtest_discover_tests(piper_test
    DISCOVERY_MODE PRE_TEST
    PROPERTIES ENVIRONMENT "PATH=${PIPER_BINARY_DIR}/$<CONFIG>;${ONNXRUNTIME_DIR}/lib;$ENV{PATH}"
)
