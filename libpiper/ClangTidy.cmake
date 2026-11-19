option(ENABLE_CLANG_TIDY "Enable clang-tidy" OFF)

if(ENABLE_CLANG_TIDY)
    find_program(CLANG_TIDY_EXE NAMES clang-tidy)
    if(CLANG_TIDY_EXE)
        set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
        message(STATUS "clang-tidy enabled = ${CLANG_TIDY_EXE}")
    else()
        message(WARNING "clang-tidy requested but not found")
    endif()
endif()

function(enable_clang_tidy target)
    if(ENABLE_CLANG_TIDY)
       message(STATUS "Enabling clang-tidy for ${target}")
       set_target_properties(${target} PROPERTIES
            CXX_CLANG_TIDY
            "${CLANG_TIDY_EXE};-p=${CMAKE_BINARY_DIR};-export-fixes=${CMAKE_BINARY_DIR}/${target}-fixes.yaml"
       )
    endif()
endfunction()
