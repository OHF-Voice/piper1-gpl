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

    # Download model.onnx if it does not exist
    if(NOT EXISTS "${MODEL_PATH}")
        message(STATUS "Downloading ${MODEL_URL}")
        file(DOWNLOAD
            ${MODEL_URL}
            ${MODEL_PATH}
            SHOW_PROGRESS
            TLS_VERIFY ON
        )
    else()
        message(STATUS "Model already exists at ${MODEL_PATH}, skipping download.")
    endif()

    # Download model.onnx.json if it does not exist
    if(NOT EXISTS "${MODEL_CONFIG_PATH}")
        message(STATUS "Downloading ${MODEL_CONFIG_URL}")
        file(DOWNLOAD
            ${MODEL_CONFIG_URL}
            ${MODEL_CONFIG_PATH}
            SHOW_PROGRESS
            TLS_VERIFY ON
        )
    else()
        message(STATUS "Model config already exists at ${MODEL_CONFIG_PATH}, skipping download.")
    endif()

    set(${ARG_OUTPUT_DIR} ${MODEL_DIR} PARENT_SCOPE)
endfunction()
