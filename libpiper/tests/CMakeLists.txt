cmake_minimum_required(VERSION 3.26)

message(STATUS "Building piper tests")

find_package(GTest QUIET)

if(NOT GTest_FOUND)
    include(FetchContent)
    FetchContent_Declare(
        googletest
        GIT_REPOSITORY https://github.com/google/googletest.git
        GIT_TAG v1.17.0
    )

    # For Windows: Prevent overriding the parent project's compiler/linker settings
    set(gtest_force_shared_crt ON CACHE BOOL "" FORCE)
    FetchContent_MakeAvailable(googletest)
endif()

include(DownloadModel.cmake)

download_piper_model(VOICE "en/en_US/lessac/medium/en_US-lessac-medium"
                     OUTPUT_DIR EN_MODEL_DIR)

download_piper_model(VOICE "uk/uk_UA/ukrainian_tts/medium/uk_UA-ukrainian_tts-medium"
                     OUTPUT_DIR TEXT_MODEL_DIR)

download_piper_model(VOICE "zh/zh_CN/chaowen/medium/zh_CN-chaowen-medium"
                     OUTPUT_DIR ZH_MODEL_DIR)

download_g2pw_data(OUTPUT_DIR G2PW_MODEL_DIR)

# Split the English voice for the streaming tests. This needs Python with the
# onnx package; without it the streaming tests are skipped.
set(EN_STREAMING_MODEL_DIR "${CMAKE_BINARY_DIR}/models/en-streaming")
find_package(Python3 COMPONENTS Interpreter QUIET)
if(Python3_FOUND AND NOT EXISTS "${EN_STREAMING_MODEL_DIR}/model.decoder.onnx")
    execute_process(
        COMMAND ${Python3_EXECUTABLE} -c "import onnx"
        RESULT_VARIABLE PYTHON_ONNX_RESULT
        OUTPUT_QUIET ERROR_QUIET
    )
    if(PYTHON_ONNX_RESULT EQUAL 0)
        file(COPY "${EN_MODEL_DIR}/model.onnx" "${EN_MODEL_DIR}/model.onnx.json"
             DESTINATION "${EN_STREAMING_MODEL_DIR}")
        execute_process(
            COMMAND ${Python3_EXECUTABLE}
                    "${CMAKE_CURRENT_SOURCE_DIR}/../../src/piper/split_voice_for_streaming.py"
                    "${EN_STREAMING_MODEL_DIR}/model.onnx"
            RESULT_VARIABLE SPLIT_VOICE_RESULT
        )
        if(NOT SPLIT_VOICE_RESULT EQUAL 0)
            message(WARNING "Splitting the test voice failed; streaming tests will be skipped")
        endif()
    else()
        message(STATUS "Python onnx package not found; streaming tests will be skipped")
    endif()
endif()

add_executable(piper_test
   test_piper.cpp
   utils/piper_test_assets.h
   utils/piper_test_assets.cpp
   test_main_utils.cpp
   test_process.cpp
   test_wav_headers.cpp
   test_wavfile.cpp
   test_japanese.cpp
   test_streaming.cpp
)
enable_clang_tidy(piper_test)

# So tests can include the phonemizer headers (chinese_phonemizer.h,
# japanese_phonemizer.h) the same way test_piper.cpp already does.
target_include_directories(piper_test PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/../src)

target_compile_definitions(piper_test
    PRIVATE "ESPEAK_DATA_PATH=\"${CMAKE_BINARY_DIR}/espeak_ng-install/share/espeak-ng-data\""
    PRIVATE "EN_TEST_MODEL_DIR=\"${EN_MODEL_DIR}\""
    PRIVATE "TEXT_TEST_MODEL_DIR=\"${TEXT_MODEL_DIR}\""
    PRIVATE "ZH_TEST_MODEL_DIR=\"${ZH_MODEL_DIR}\""
    PRIVATE "EN_STREAMING_TEST_MODEL_DIR=\"${EN_STREAMING_MODEL_DIR}\""
    PRIVATE "G2PW_TEST_DATA_DIR=\"${G2PW_MODEL_DIR}\""
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
get_target_property(PIPER_EXE_BINARY_DIR piper_exe BINARY_DIR)

gtest_discover_tests(piper_test
    DISCOVERY_MODE PRE_TEST
    PROPERTIES ENVIRONMENT "PATH=${PIPER_EXE_BINARY_DIR}/$<CONFIG>;${PIPER_BINARY_DIR}/$<CONFIG>;${ONNXRUNTIME_DIR}/lib;$ENV{PATH}"
)
