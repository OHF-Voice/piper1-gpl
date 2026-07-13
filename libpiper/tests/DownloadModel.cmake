function(download_piper_model)
    set(options)
    set(oneValueArgs VOICE OUTPUT_DIR)
    set(multiValueArgs)

    cmake_parse_arguments(ARG "${options}" "${oneValueArgs}" "${multiValueArgs}" ${ARGN})

    if(NOT ARG_VOICE OR NOT ARG_OUTPUT_DIR)
        message(FATAL_ERROR "download_piper_model requires VOICE and OUTPUT_DIR arguments.")
    endif()

    string(REPLACE "/" "-" VOICE_DIR_NAME ${ARG_VOICE})
    set(MODEL_DIR "${CMAKE_BINARY_DIR}/models/${VOICE_DIR_NAME}")
    set(MODEL_PATH "${MODEL_DIR}/model.onnx")
    set(MODEL_CONFIG_PATH "${MODEL_PATH}.json")

    set(MODEL_BASE_URL "https://huggingface.co/rhasspy/piper-voices/resolve/main")
    set(MODEL_URL "${MODEL_BASE_URL}/${ARG_VOICE}.onnx")
    set(MODEL_CONFIG_URL "${MODEL_URL}.json")

    message(STATUS "Downloading ${MODEL_URL}")
    file(DOWNLOAD
        ${MODEL_URL}
        ${MODEL_PATH}
        SHOW_PROGRESS
        TLS_VERIFY ON
    )
    message(STATUS "Downloaded ${MODEL_URL}")
    message(STATUS "Downloading ${MODEL_CONFIG_URL}")
    file(DOWNLOAD
        ${MODEL_CONFIG_URL}
        ${MODEL_CONFIG_PATH}
        SHOW_PROGRESS
        TLS_VERIFY ON
    )
    message(STATUS "Downloaded ${MODEL_CONFIG_URL}")

    set(${ARG_OUTPUT_DIR} ${MODEL_DIR} PARENT_SCOPE)
endfunction()
