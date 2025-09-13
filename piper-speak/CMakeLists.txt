#build piper-speak binary
cmake_minimum_required(VERSION 3.26)
project(piper-speak LANGUAGES CXX)

set(LIBPIPER_DIR ${CMAKE_BINARY_DIR}/../../libpiper/install)

### set the dependencies as described in ROOT/libpiper/README.md
set(PIPER_HEADER ${LIBPIPER_DIR}/include)
#libpiper is inside the root of LIBPIPER_DIR already
#so no need for seperate variable
set(ONNX_LIB_DIR ${LIBPIPER_DIR}/lib)
set(ESPEAK_NG_DATA=${LIBPIPER_DIR}/espeak-ng-data/)

#We also need the path to the voices: the .onnx and the .onnx.json
set(VOICES_DIR ${CMAKE_BINARY_DIR}/../download/voices)

### With the variables set, we now hook them up to CMAKE

#piper.h header
include_directories(${PIPER_HEADER})

#link libpiper
find_library(LIBPIPER
	NAMES piper
	PATHS ${LIBPIPER_DIR}
	NO_DEFAULT_PATH
)

if(NOT LIBPIPER)
	message(FATAL_ERROR "Could not find libpiper in ${LIBPIPER_DIR}")
endif()

#link onnxruntime
find_library(ONNXRUNTIME
	NAMES onnxruntime
	PATHS ${ONNX_LIB_DIR}
	NO_DEFAULT_PATH
)

if(NOT ONNXRUNTIME)
	message(FATAL_ERROR "Could not find onnxruntime in ${ONNX_LIB_DIR}")
endif()

#tell the code where ESPEAK_NG_DATA is located
add_definitions(-DBUILD_ENV_ESPEAK_NG_DATA=\"${ESPEAK_EN_DATA}\")

#tell the code where the voices are located
add_definitions(-DBUILD_ENV_VOICES_PATH=\"${VOICES_DIR}\")


### we are done for the most part with the README steps

add_executable(${PROJECT_NAME} piper-speak.cpp)
target_link_libraries(${PROJECT_NAME} PRIVATE ${LIBPIPER})
target_link_libraries(${PROJECT_NAME} PRIVATE ${ONNXRUNTIME})

#we use c++17 to get the std::filesystem header
set_target_properties(${PROJECT_NAME} PROPERTIES CXX_STANDARD 17)

### We still need to download a voice to use
file(MAKE_DIRECTORY download/voices)
message(NOTICE "Currently you must manually download a .onnx file and the corresponding .json file and place them in download/voices")
set(VOICES_URL "https://huggingface.co/rhasspy/piper-voices/tree/main")
message(STATUS "look ${VOICES_URL} for voices")
