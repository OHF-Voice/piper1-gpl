# Set the target name using the current directory name as a suffix.
get_filename_component(PROJECT_SUFFIX ${CMAKE_CURRENT_SOURCE_DIR} NAME)
set(APP_TARGET "${PROJECT_NAME}-${PROJECT_SUFFIX}")

add_executable("${APP_TARGET}")

target_sources("${APP_TARGET}" PRIVATE
	main.cpp
	helpers.cpp helpers.h
	CommandLine.cpp CommandLine.h
)

target_link_libraries("${APP_TARGET}" PRIVATE piper::static)

##!
# Downloads the model files in the models directory.
#
function(Sf_PiperDownloadModel _models_dir _language _region _dataset _quality)
	set(_BaseUrl "https://huggingface.co/rhasspy/piper-voices/resolve/main/${_language}/${_language}_${_region}/${_dataset}/${_quality}")
	set(_Model "${_language}_${_region}-${_dataset}-${_quality}")
	set(_File "${_models_dir}/${_Model}.onnx")
	if (NOT EXISTS "${_File}")
		file(DOWNLOAD "${_BaseUrl}/${_Model}.onnx" "${_File}" TIMEOUT 10 SHOW_PROGRESS)
	endif ()
	set(_File "${_models_dir}/${_Model}.onnx.json")
	if (NOT EXISTS "${_File}")
		file(DOWNLOAD "${_BaseUrl}/${_Model}.onnx.json" "${_File}" TIMEOUT 10 SHOW_PROGRESS)
	endif ()
endfunction()

if (BUILD_TESTING)
	# Check if running in Docker
	if (EXISTS "/.dockerenv")
		set(IN_DOCKER TRUE)
	else()
		set(IN_DOCKER FALSE)
	endif()

	Sf_PiperDownloadModel("${CMAKE_SOURCE_DIR}/bin/models" "en" "US" "hfc_female" "medium")
	Sf_PiperDownloadModel("${CMAKE_SOURCE_DIR}/bin/models" "en" "US" "hfc_male" "medium")
	#[[
	Sf_PiperDownloadModel("${CMAKE_SOURCE_DIR}/bin/models" "en" "GB" "cori" "high")
	Sf_PiperDownloadModel("${CMAKE_SOURCE_DIR}/bin/models" "en" "US" "lessac" "medium")
	Sf_PiperDownloadModel("${CMAKE_SOURCE_DIR}/bin/models" "en" "US" "ljspeech" "medium")
	Sf_PiperDownloadModel("${CMAKE_SOURCE_DIR}/bin/models" "nl" "NL" "pim" "medium")
	Sf_PiperDownloadModel("${CMAKE_SOURCE_DIR}/bin/models" "en" "GB" "vctk" "medium")
	]]
	if (WIN32)
		if (CMAKE_CROSSCOMPILING)
			# Check if wine is installed.
			find_program(_WineExe "wine")
			if (NOT _WineExe)
				message(NOTICE "Wine is not installed, skipping wine test.")
			else ()
				# Add the test using the target executable filename.
				add_test(NAME "win-${APP_TARGET}"
					COMMAND ${CMAKE_COMMAND} -E env wine "$<TARGET_FILE_NAME:${APP_TARGET}>"
					# Skipping playing when in a pipeline or docker.
					$<$<AND:$<NOT:$<BOOL:$ENV{CI}>>,$<NOT:$<BOOL:${IN_DOCKER}>>>:--play>
					--text "Success! When you here this text is looks like the for Windows cross-compiled 'Piper' library is working."
					WORKING_DIRECTORY "${CMAKE_RUNTIME_OUTPUT_DIRECTORY}"
				)
				# Use the double escape to prevent the string is considered to be a CMake list.
				string(REPLACE "\n" "\\\\;" _WinPath "${_WinPath}")
			endif ()
		else ()
			# Modify the resulting Windows PATH.
			list(APPEND _WinPath "${_WinPath}" "$ENV{PATH}")
			# Use the double escape to prevent the string is considered to be a CMake list.
			string(REPLACE ";" "\\\\;" _WinPath "${_WinPath}")
			if (MINGW)
				# Add the test using the target executable filename.
				add_test(NAME "win-${APP_TARGET}"
					COMMAND ${CMAKE_COMMAND} -E env "$<TARGET_FILE_NAME:${APP_TARGET}>"
					# Skipping playing when in a pipeline or docker.
					$<$<AND:$<NOT:$<BOOL:$ENV{CI}>>,$<NOT:$<BOOL:${IN_DOCKER}>>>:--play>
					--text "Success! When you here this text is looks like the for Minimalist Gnu for Windows compiled 'Piper' library is working."
					WORKING_DIRECTORY "${CMAKE_RUNTIME_OUTPUT_DIRECTORY}"
				)
			elseif (MSVC)
				# Add the test using the target executable filename.
				add_test(NAME "win-${APP_TARGET}"
					COMMAND ${CMAKE_COMMAND} -E env "$<TARGET_FILE_NAME:${APP_TARGET}>"
					# Skipping playing when in a pipeline or docker.
					$<$<AND:$<NOT:$<BOOL:$ENV{CI}>>,$<NOT:$<BOOL:${IN_DOCKER}>>>:--play>
					--text "Success! When you here this text is looks like the for  Windows with Microsoft Visual C++ compiled 'Piper' library is working."
					WORKING_DIRECTORY "${CMAKE_RUNTIME_OUTPUT_DIRECTORY}"
				)
			endif ()
		endif ()
	else ()
		# Add the test using the target executable filename.
		add_test(NAME "win-${APP_TARGET}"
			COMMAND "$<TARGET_FILE_NAME:${APP_TARGET}>"
			# Skipping playing when in a pipeline or docker.
			$<$<AND:$<NOT:$<BOOL:$ENV{CI}>>,$<NOT:$<BOOL:${IN_DOCKER}>>>:--play>
			--text "Success! When you here this text is looks like the for Linux compiled 'Piper' library is working."
			WORKING_DIRECTORY "${CMAKE_RUNTIME_OUTPUT_DIRECTORY}"
		)
	endif ()
endif ()
