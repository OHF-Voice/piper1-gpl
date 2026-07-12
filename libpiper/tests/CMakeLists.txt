cmake_minimum_required(VERSION 3.26)
project(piper_test)

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

set(EN_MODEL_DIR "${CMAKE_BINARY_DIR}/en")
set(MODEL_PATH "${EN_MODEL_DIR}/model.onnx")
set(MODEL_CONFIG_PATH "${MODEL_PATH}.json")

set(MODEL_BASE_URL "https://huggingface.co/rhasspy/piper-voices/resolve/main")
set(MODEL_URL "${MODEL_BASE_URL}/en/en_US/lessac/medium/en_US-lessac-medium.onnx")
set(MODEL_CONFIG_URL "${MODEL_URL}.json")

file(DOWNLOAD
    ${MODEL_URL}
    ${MODEL_PATH}
    SHOW_PROGRESS
)
file(DOWNLOAD
    ${MODEL_CONFIG_URL}
    ${MODEL_CONFIG_PATH}
    SHOW_PROGRESS
)

add_executable(piper_test
   test_piper.cpp
   utils/piper_test_assets.h
   utils/piper_test_assets.cpp
)

target_compile_definitions(piper_test
    PRIVATE "ESPEAK_DATA_PATH=\"${CMAKE_BINARY_DIR}/espeak_ng-install/share/espeak-ng-data\""
    PRIVATE "EN_TEST_MODEL_DIR=\"${EN_MODEL_DIR}\""
)

target_link_libraries(piper_test
    PRIVATE piper
    PRIVATE GTest::gtest_main
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