#build piper-speak binary
cmake_minimum_required(VERSION 3.26)
project(piper-speak LANGUAGES CXX)

set(SOURCE_FILES piper-speak.cpp audio.cpp)

set(LIBPIPER_DIR ${CMAKE_BINARY_DIR}/../../libpiper/install)

### set the dependencies as described in ROOT/libpiper/README.md
set(PIPER_HEADER ${LIBPIPER_DIR}/include)
#libpiper is inside the root of LIBPIPER_DIR already
#so no need for seperate variable
set(ONNX_LIB_DIR ${LIBPIPER_DIR}/lib)
set(ESPEAK_NG_DATA=${LIBPIPER_DIR}/espeak-ng-data/)

#We also need the path to the voices: the .onnx and the .onnx.json
set(VOICES_DIR ${CMAKE_BINARY_DIR}/../download/voices)

### Actually find the libraries

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

# We depend on pcaudiolib for audio output
# since we already depend on espeak-ng and espeak-ng generally depends on pcaudiolib
# this shouldn't add additional dependences. 
# though currently we bundle espeak-ng while this looks for system pcaudiolib
find_library(PCAUDIO_LIB
	NAMES pcaudio
	)

find_path(PCAUDIO_INCLUDE
	NAMES pcaudiolib/audio.h
	)

### create the target and configure it
add_executable(${PROJECT_NAME} ${SOURCE_FILES})
target_include_directories(${PROJECT_NAME} PRIVATE ${PIPER_HEADER})
target_include_directories(${PROJECT_NAME} PRIVATE ${PCAUDIO_INCLUDE})
target_link_libraries(${PROJECT_NAME} PRIVATE ${LIBPIPER})
target_link_libraries(${PROJECT_NAME} PRIVATE ${ONNXRUNTIME})
target_link_libraries(${PROJECT_NAME} PRIVATE ${PCAUDIO_LIB})
target_compile_definitions(${PROJECT_NAME}
	#tell the code where ESPEAK_NG_DATA is located
	PRIVATE -DBUILD_ENV_ESPEAK_NG_DATA=\"${ESPEAK_EN_DATA}\"
	#tell the code where the voices are located
	PRIVATE -DBUILD_ENV_VOICES_PATH=\"${VOICES_DIR}\"
)
#we use c++17 to get the std::filesystem header
set_target_properties(${PROJECT_NAME} PROPERTIES CXX_STANDARD 17)

### We still need to download a voice to use
file(MAKE_DIRECTORY download/voices)
message(NOTICE "Currently you must manually download a .onnx file and the corresponding .json file and place them in download/voices")
set(VOICES_URL "https://huggingface.co/rhasspy/piper-voices/tree/main")
message(STATUS "look ${VOICES_URL} for voices")
