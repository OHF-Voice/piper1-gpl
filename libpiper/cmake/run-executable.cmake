#[[
Execute this file using
	cmake --preset gnu-debug -DSF_EXECUTABLE=123.bin -P cmake/lib/run-executable.cmake
]]

cmake_minimum_required(VERSION 3.29)

if (SF_VERBOSE)
	message(STATUS "SF_COMPILER: ${SF_COMPILER}")
	message(STATUS "SF_EXEC_DIR_SUFFIX: $ENV{SF_EXEC_DIR_SUFFIX}")
	message(STATUS "SF_EXECUTABLE_DIR: $ENV{SF_EXECUTABLE_DIR}")
	message(STATUS "SF_LIBRARY_DIR: $ENV{SF_LIBRARY_DIR}")
	message(STATUS "CMAKE_BINARY_DIR: ${CMAKE_BINARY_DIR}")
	message(STATUS "CMAKE_RUNTIME_OUTPUT_DIRECTORY: ${CMAKE_RUNTIME_OUTPUT_DIRECTORY}")
	message(STATUS "CMAKE_LIBRARY_OUTPUT_DIRECTORY: ${CMAKE_LIBRARY_OUTPUT_DIRECTORY}")
endif ()

function(Sf_ArgDecode _VarRef)
	set(_work_str "${${_VarRef}}")
	# Common encoded characters to decode
	# %3B is semicolon (;), %20 is space ( ), %2F is slash (/)
	set(hex_codes "%3B" "%20" "%25")
	set(chars "\;" " " "%")
	list(LENGTH hex_codes len)
	math(EXPR max "${len} - 1")
	foreach (i RANGE ${max})
		list(GET hex_codes ${i} hex)
		list(GET chars ${i} char)
		string(REPLACE "${hex}" "${char}" _work_str "${_work_str}")
	endforeach ()
	set(${_VarRef} "${_work_str}" PARENT_SCOPE)
endfunction()

function(Sf_GetOptionalArgument _VarOut _Index _Argn)
	list(LENGTH _Argn _Length)
	if (_Index LESS _Length)
		list(GET _Argn ${_Index} _Value)
		set(${_VarOut} "${_Value}" PARENT_SCOPE)
	endif ()
endfunction()

function(Sf_ListPath _Path)
	Sf_GetOptionalArgument(_Prefix 0 "${ARGN}")
	# Check if the variable is a Linux path one.
	string(FIND "${_Path}" ";" _idx)
	# Check if this is a Linux path.
	if (_idx EQUAL -1)
		string(REPLACE ":" ";" _Path "${_Path}")
	endif ()
	set(_Counter 0)
	foreach (_Dir IN LISTS _Path)
		message(STATUS "${_Prefix}${_Var}[${_Counter}]: ${_Dir}")
		math(EXPR _Counter "${_Counter} + 1")
	endforeach ()
endfunction()

function(Sf_PrintDependencies _File)
	# Check if in Wine since Wine prints the ldd information already.
	if (NOT DEFINED ENV{WINE_HOST_HOME})
		if ("${CMAKE_HOST_SYSTEM_NAME}" STREQUAL "Windows")
			# Git on Windows contains an ldd tool.
			find_program(_GitExe git REQUIRED)
			get_filename_component(_Dir "${_GitExe}" DIRECTORY)
			# Use Git's executable directory to find the 'ldd' tool.
			find_program(_LddExe ldd PATHS "${_Dir}\\..\\usr\\bin\\")
			if (_LddExe)
				execute_process(
					COMMAND ${_LddExe} ${_File}
					WORKING_DIRECTORY "${CMAKE_RUNTIME_OUTPUT_DIRECTORY}"
					COMMAND_ERROR_IS_FATAL ANY
					COMMAND_ECHO STDOUT
				)
			endif ()
		endif ()
	endif ()
endfunction()

if (NOT DEFINED SF_EXECUTABLE OR SF_EXECUTABLE STREQUAL "")
	if (NOT SF_EXECUTABLE STREQUAL "")
		message(STATUS "SF_EXECUTABLE: ${SF_EXECUTABLE}")
	else ()
		# Show the environment when not selected.
		message(STATUS "SF_EXECUTABLE: Not selected...")
		return()
	endif ()
endif ()

set(_ExeFile "${SF_EXECUTABLE}")
# Keep the cmake list with ';' intact.
Sf_ArgDecode(_ExeFile)
if (SF_VERBOSE)
	message(STATUS "SF_EXECUTABLE: ${_ExeFile}")
	set(SF_CMD_ECHO "STDOUT")
else ()
	set(SF_CMD_ECHO "NONE")
endif ()

# Show some related environment variables.
if ("${CMAKE_HOST_SYSTEM_NAME}" STREQUAL "Linux" AND (SF_COMPILER STREQUAL "gw"))
	if (SF_VERBOSE)
		Sf_ListPath("$ENV{PATH}" "PATH")
		Sf_ListPath("$ENV{WINEPATH}" "WINEPATH")
	endif ()
	find_program(_WineExe wine REQUIRED)
	# Execute the file.
	execute_process(
		COMMAND ${_WineExe} ${_ExeFile}
		WORKING_DIRECTORY "${CMAKE_RUNTIME_OUTPUT_DIRECTORY}"
		COMMAND_ECHO ${SF_CMD_ECHO}
		ECHO_ERROR_VARIABLE
		ECHO_OUTPUT_VARIABLE
		# Any error is fatal.
		COMMAND_ERROR_IS_FATAL ANY
	)
elseif ("${CMAKE_HOST_SYSTEM_NAME}" STREQUAL "Windows" AND (SF_COMPILER STREQUAL "mingw" OR SF_COMPILER STREQUAL "msvc"))
	if (SF_VERBOSE)
		Sf_ListPath("$ENV{PATH}" "PATH")
	endif ()
	# Execute the file.
	execute_process(
		# Without cmd /c the GUI app will not appear.
		COMMAND cmd /c ${_ExeFile}
		WORKING_DIRECTORY "${CMAKE_RUNTIME_OUTPUT_DIRECTORY}"
		COMMAND_ECHO ${SF_CMD_ECHO}
		ECHO_ERROR_VARIABLE
		ECHO_OUTPUT_VARIABLE
		RESULT_VARIABLE _ExitCode
	)
	if (NOT _ExitCode EQUAL 0)
		message("${_ExitCode}")
		Sf_PrintDependencies("${_ExeFile}")
	endif ()
else ()
	if (SF_VERBOSE)
		Sf_ListPath("$ENV{LD_LIBRARY_PATH}" "LD_LIBRARY_PATH")
	endif ()
	# Execute the file.
	execute_process(
		COMMAND ${_ExeFile}
		WORKING_DIRECTORY "${CMAKE_RUNTIME_OUTPUT_DIRECTORY}"
		COMMAND_ECHO ${SF_CMD_ECHO}
		ECHO_ERROR_VARIABLE
		ECHO_OUTPUT_VARIABLE
		# Any error is fatal.
		COMMAND_ERROR_IS_FATAL ANY
	)
endif ()

