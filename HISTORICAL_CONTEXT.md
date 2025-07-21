# Historical Context for Piper TTS Build and Packaging on Termux


Some are oudated, as architecture decisions have changed. 

This document contains historical details about the process of building and packaging the Piper TTS project for Termux, including troubleshooting steps and lessons learned from various build attempts. While some issues have been resolved, these insights remain valuable. They mostly concern the .deb package method. Here we are using Python only.

## The Problem: ABI Incompatibility and `nlohmann::json` Versions

The initial issue was a `nlohmann::json` parsing error and a `libc++abi` error, indicating an Application Binary Interface (ABI) mismatch between `libpiper.so` and `libc++_shared.so`. This typically occurs after a system upgrade where `libc++_shared.so` is updated to an incompatible version, causing previously compiled binaries to crash.

During troubleshooting, it was discovered that the project contained two versions of the `nlohmann::json` header file: `libpiper/include/json.hpp` (version 3.12.0) and `libpiper/include/json.hpp.1.bad` (version 3.11.2). The original error message explicitly referenced `nlohmann::json_abi_v3_11_2`, indicating that `libpiper.so` was compiled against version 3.11.2 of `nlohmann::json`. The presence of the newer 3.12.0 version, and the `.1.bad` backup, suggests that during previous build attempts or dependency updates, the `nlohmann::json` header was either updated or replaced, leading to a mix of versions.

The root cause of the JSON parsing problem was the ABI incompatibility between the `libpiper.so` (compiled with `nlohmann::json` 3.11.2) and the system's updated `libc++_shared.so`. Even though `nlohmann::json` is a header-only library, its internal structures and how it interacts with the C++ standard library can change between versions, leading to these ABI issues when the compiled binary (libpiper.so) expects an older ABI than what the runtime library provides.

## How it Should Be Done (The Corrected Process - Historical Reference)

This section outlines the streamlined process for building and packaging Piper TTS for Termux, assuming a fresh clone of the Piper repository. **Note: This process reflects the state at the time of documentation and may have been superseded by current project practices.**

#### 1. Install System Build Dependencies

First, ensure you have the necessary build tools installed in your Termux environment.

```bash
pkg install -y build-essential cmake ninja
```

#### 2. Build and Install `espeak-ng` Separately

The Piper project's `CMakeLists.txt` attempts to manage `espeak-ng` as an `ExternalProject`, which proved problematic. It is more robust to build and install `espeak-ng` directly into your Termux system.

```bash
# Clone the espeak-ng repository (if you haven't already)
git clone https://github.com/espeak-ng/espeak-ng.git

# Navigate into the espeak-ng directory
cd espeak-ng

# Checkout the specific commit used by Piper (check Piper's CMakeLists.txt for the exact commit)
git checkout 212928b394a96e8fd2096616bfd54e17845c48f6

# Create a build directory and configure espeak-ng with the Termux installation prefix
mkdir -p build && cd build
cmake -G Ninja .. -DCMAKE_INSTALL_PREFIX=/data/data/com.termux/files/usr

# Build and install espeak-ng
ninja install
```

#### 3. Modify Piper's `CMakeLists.txt`

To prevent Piper from attempting to build `espeak-ng` as an external project (which caused numerous issues), modify its `CMakeLists.txt` to link against the system-installed `espeak-ng`.

**Original `CMakeLists.txt` (relevant parts):**

```cmake
include(ExternalProject)

# Install location for espeak-ng
set(ESPEAKNG_BUILD_DIR ${CMAKE_BINARY_DIR}/espeak_ng)
set(ESPEAKNG_INSTALL_DIR ${CMAKE_BINARY_DIR}/espeak_ng-install)

if(WIN32)
    # Special handling for Windows
    set(ESPEAKNG_STATIC_LIB ${ESPEAKNG_INSTALL_DIR}/lib/espeak-ng.lib)
    set(UCD_STATIC_LIB ${ESPEAKNG_BUILD_DIR}/src/espeak_ng_external-build/src/ucd-tools/ucd.lib)
else()
    set(ESPEAKNG_STATIC_LIB ${ESPEAKNG_INSTALL_DIR}/lib/libespeak-ng.a)
    set(UCD_STATIC_LIB ${ESPEAKNG_BUILD_DIR}/src/espeak_ng_external-build/src/ucd-tools/libucd.a)
endif()

ExternalProject_Add(espeak_ng_external
    GIT_REPOSITORY https://github.com/espeak-ng/espeak-ng.git
    GIT_TAG 212928b394a96e8fd2096616bfd54e17845c48f6  # 2025-Mar-22
    PREFIX ${ESPEAKNG_BUILD_DIR}
    CMAKE_ARGS
        -DCMAKE_INSTALL_PREFIX=${ESPEAKNG_INSTALL_DIR}
        -DBUILD_SHARED_LIBS:BOOL=OFF
        -DCMAKE_POSITION_INDEPENDENT_CODE:BOOL=ON
        -DUSE_ASYNC:BOOL=OFF
        -DUSE_MBROLA:BOOL=OFF
        -DUSE_LIBSONIC:BOOL=OFF
        -DUSE_LIBPCAUDIO:BOOL=OFF
        -DUSE_KLATT:BOOL=OFF
        -DUSE_SPEECHPLAYER:BOOL=OFF
        -DEXTRA_cmn:BOOL=ON
        -DEXTRA_ru:BOOL=ON
        # Need to explicitly add ucd include directory for CI
        "-DCMAKE_C_FLAGS=-D_FILE_OFFSET_BITS=64 -I${ESPEAKNG_BUILD_DIR}/src/espeak_ng_external/src/ucd-tools/src/include"
    BUILD_BYPRODUCTS
        ${ESPEAKNG_STATIC_LIB}
        ${UCD_STATIC_LIB}
    UPDATE_DISCONNECTED TRUE
)

include_directories(
    ${ESPEAKNG_INSTALL_DIR}/include
)

# espeak bridge
add_library(espeakbridge MODULE
    src/piper/espeakbridge.c
)

add_dependencies(espeakbridge espeak_ng_external)
target_link_libraries(espeakbridge
    ${ESPEAKNG_STATIC_LIB}
    ${UCD_STATIC_LIB}
    Python::SABIModule
)
target_include_directories(espeakbridge PRIVATE
    ${ESPEAKNG_INSTALL_DIR}/include
)

# Copy espeak-ng-data
set(DATA_SRC ${CMAKE_BINARY_DIR}/espeak_ng-install/share/espeak-ng-data)
set(DATA_DST ${CMAKE_CURRENT_SOURCE_DIR}/src/piper/espeak-ng-data)

add_custom_target(copy_espeak_ng_data ALL
    COMMAND ${CMAKE_COMMAND} -E copy_directory ${DATA_SRC} ${DATA_DST}
    DEPENDS espeak_ng_external
    COMMENT "Copying espeak-ng-data after espeak-ng external project builds"
)
```

**Modified `CMakeLists.txt` (relevant parts):**

Remove the `ExternalProject` include, the `ESPEAKNG_BUILD_DIR` and `ESPEAKNG_INSTALL_DIR` variables, and the entire `ExternalProject_Add` block.

Modify the `espeakbridge` target to link directly to `espeak-ng` and include the system header path:

```cmake
# espeak bridge
add_library(espeakbridge MODULE
    src/piper/espeakbridge.c
)

target_link_libraries(espeakbridge
    espeak-ng
    Python::SABIModule
)
target_include_directories(espeakbridge PRIVATE
    /data/data/com.termux/files/usr/include
)
```

Also, remove the `add_dependencies(espeakbridge espeak_ng_external)` line and the entire `copy_espeak_ng_data` custom target, as `espeak-ng-data` will be provided by the system installation.

#### 4. Build Piper

After modifying `CMakeLists.txt`, clean Piper's build cache and build the Python extension:

```bash
rm -rf _skbuild
python3 setup.py build_ext --inplace -v
```

#### 5. You can create Debian Package

Use the `create_deb.sh` script in to package the compiled Piper Python module into a `.deb` file. Not needed here, as all pure Python

**`create_deb.sh` content:**

```bash
#!/bin/bash

PKGNAME="piper"
VERSION="1.0.0" # Or retrieve from project metadata
PREFIX="/data/data/com.termux/files/usr"

# Cleanup
rm -rf build
rm -f ${PKGNAME}*.deb
mkdir -p build

# ---- Package with espeak dependency ----

PKGDIR=build/$PKGNAME

mkdir -p $PKGDIR/DEBIAN
mkdir -p $PKGDIR$PREFIX/lib/python3.12/site-packages/ # Ensure Python site-packages directory exists

# Copy the Python module (which includes the compiled espeakbridge.so)
cp -r src/piper $PKGDIR$PREFIX/lib/python3.12/site-packages/

chmod 755 $PKGDIR/DEBIAN

cat > $PKGDIR/DEBIAN/control <<EOF
Package: $PKGNAME
Version: $VERSION
Section: sound
Priority: optional
Architecture: aarch64
Maintainer: Your Name <you@example.com>
Depends: python3, espeak
Conflicts: ${PKGNAME}-no-espeak
Description: Piper TTS CLI with espeak-ng data and shared libraries.
EOF

dpkg-deb --build $PKGDIR
mv $PKGDIR.deb $PKGNAME-$VERSION.deb

echo "Successfully created $PKGNAME-$VERSION.deb"
```

Make the script executable and run it:

```bash
chmod +x create_deb.sh
./create_deb.sh
```

#### 6. Install and Test

Install the generated `.deb` package:

```bash
dpkg -i piper-1.0.0.deb
```

Test Piper by generating audio to a file:

```bash
python3 -m piper --model ~/.cache/piper/en_US-lessac-medium.onnx --config ~/.cache/piper/en_US-lessac-medium.onnx.json --text "Hello, world! This is Piper speaking." --output_file output.wav
```

## What We Have Been Doing Wrong (Common Pitfalls - Historical Reference)

1.  **Underestimating `ExternalProject_Add` Complexity**: Relying on `ExternalProject_Add` for `espeak-ng` within Piper's `CMakeLists.txt` introduced significant complexity and fragility. It led to issues with file paths (`phsource/intonation`), network failures during cloning, and persistent CMake cache problems.
2.  **Ignoring CMake Cache**: Repeated build failures due to "CMake Error: The source ... does not match the source ... used to generate cache" indicated that simply re-running `setup.py build_ext` was insufficient. A full `rm -rf _skbuild` was necessary after significant `CMakeLists.txt` modifications.
3.  **Incorrect `ninja install` Usage**: Initially attempting `ninja install DESTDIR=/tmp/espeak-ng-install` was incorrect. The installation prefix (`CMAKE_INSTALL_PREFIX`) must be set during the `cmake` configuration step, not as an argument to `ninja install`.
4.  **Misunderstanding Python Packaging for `.deb`**: Assuming `piper` was a standalone executable or that `setup.py` would produce a `lib` directory for direct copying. The realization that `piper` is a Python module and its compiled components (`espeakbridge.so`) are placed within the Python `site-packages` directory was crucial for correct `.deb` packaging.
5.  **Lack of Explicit Directory Creation in Packaging Script**: The `cp -r` command in `create_deb.sh` failed when the target `site-packages` directory within the `.deb` staging area didn't exist. Explicit `mkdir -p` commands are essential for robust packaging.

## Other Lessons Learned (Historical Reference)

1.  **Prioritize System Packages for Dependencies**: For complex external libraries like `espeak-ng`, it's often more reliable to rely on the system's package manager (`apt` in Termux) to install them. This ensures they are correctly compiled for the target architecture and integrated with the system's library paths.
2.  **Thorough Build Cache Cleaning**: When encountering persistent build errors, especially with CMake, a complete cleanup of all build-related directories (e.g., `_skbuild`, `build` within external projects) is paramount to ensure a fresh start.
3.  **Verify Each Step**: After each significant change (e.g., modifying `CMakeLists.txt`, running a build command), verify the outcome (e.g., check for generated files, inspect error messages carefully).
4.  **Understand the Project's Build System**: Before attempting modifications, take time to understand how the project's build system (e.g., `scikit-build`, `CMake`, `setup.py`) works and how it handles dependencies.
5.  **Iterative Troubleshooting**: Break down complex build failures into smaller, manageable problems. Isolate components (e.g., build `espeak-ng` independently) to pinpoint the exact source of the issue.
6.  **Termux Specifics**: Remember Termux's unique environment, especially the `/data/data/com.termux/files/usr` prefix for installations.
7.  **The Value of Verbose Output**: Using `-v` with build commands (e.g., `python3 setup.py build_ext -v`) provides invaluable debugging information.
8.  **`dpkg-deb` for Packaging**: For distributing software on Debian-based systems like Termux, `dpkg-deb` is the tool to use. It requires careful preparation of the package's internal file structure and a correct `control` file.
