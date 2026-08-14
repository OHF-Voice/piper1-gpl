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

function(download_g2pw_data)
    set(options)
    set(oneValueArgs OUTPUT_DIR)
    cmake_parse_arguments(ARG "" "${oneValueArgs}" "" ${ARGN})

    set(G2PW_DIR "${CMAKE_BINARY_DIR}/g2pw")
    file(MAKE_DIRECTORY ${G2PW_DIR})

    # Small dict files from GitYCC/g2pW – enough for mono/bopomofo hanzi path
    # Using raw github – TLS_VERIFY ON matches other downloads
    set(G2PW_BASE "https://raw.githubusercontent.com/GitYCC/g2pW/master/g2pw")

    foreach(F IN ITEMS
            "bert-base-chinese_s2t_dict.txt"
            "bopomofo_to_pinyin_wo_tune_dict.json"
            "char_bopomofo_dict.json")
        if(NOT EXISTS "${G2PW_DIR}/${F}")
            message(STATUS "Downloading g2pw ${F}")
            file(DOWNLOAD
                "${G2PW_BASE}/${F}"
                "${G2PW_DIR}/${F}"
                SHOW_PROGRESS
                TLS_VERIFY ON
                STATUS dl_status
            )
            list(GET dl_status 0 dl_code)
            if(NOT dl_code EQUAL 0)
                message(WARNING "Failed to download ${F}, will try local pip package fallback")
                # fallback to pip-installed g2pw if available
                if(EXISTS "/usr/local/lib/python3.12/dist-packages/g2pw/${F}")
                    file(COPY "/usr/local/lib/python3.12/dist-packages/g2pw/${F}"
                         DESTINATION "${G2PW_DIR}")
                elseif(EXISTS "/tmp/g2pw_full/${F}")
                    file(COPY "/tmp/g2pw_full/${F}"
                         DESTINATION "${G2PW_DIR}")
                endif()
            endif()
        endif()
    endforeach()

    # MONOPHONIC/POLYPHONIC are not in g2pW repo – they live in model bundles.
    # Copy from /tmp/g2pw_full if we have it locally (built by us), otherwise
    # leave out – hasDicts() will be true from char_bopomofo alone for "你好".
    foreach(F IN ITEMS "MONOPHONIC_CHARS.txt" "POLYPHONIC_CHARS.txt" "vocab.txt")
        if(NOT EXISTS "${G2PW_DIR}/${F}" AND EXISTS "/tmp/g2pw_full/${F}")
            file(COPY "/tmp/g2pw_full/${F}" DESTINATION "${G2PW_DIR}")
        endif()
    endforeach()

    set(${ARG_OUTPUT_DIR} ${G2PW_DIR} PARENT_SCOPE)
endfunction()
