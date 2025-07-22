## Project Context and Current Task

This `GEMINI.md` file provides essential context for working with the `piper1-gpl` project, especially within a Termux (Android) environment.

**Current Task:**
We are currently working on wrapping up this project to prepare for a Pull Request (PR). The primary goal is to ensure that the end-user can simply run `pip install piper-tts` (or `pip install .` from the project root) to install the package. We are actively hunting and fixing any bugs that prevent this streamlined installation, particularly those related to Termux-specific build challenges that the original project had.

## Repository Relationships (July 19, 2025)

This section clarifies the relationships between the various Git repositories encountered during this session to prevent future confusion.

### 1. Current Working Directory Repository (`/data/data/com.termux/files/home/downloads/GitHub/piper1-gpl`)
    *   **Local Path:** `/data/data/com.termux/files/home/downloads/GitHub/piper1-gpl`

*   **Your Fork (`origin` remote):** `https://github.com/Manamama/piper1-gpl`
    *   This is the user's personal fork of the `piper1-gpl` project. Local changes are pushed to this remote.
*   **Original/Upstream (`upstream` remote):** `https://github.com/OHF-Voice/piper1-gpl`
    *   This is the repository from which the user's `Manamama/piper1-gpl` fork was created. Updates are pulled from here to synchronize the user's fork with the original project.

### 2. Separate temp `piper-tts-for-termux` Repository
    *   **Local Path:** `/data/data/com.termux/files/home/downloads/GitHub/piper1-gpl/piper-tts-for-termux`

*   **Its Origin:** `https://github.com/gyroing/piper-tts-for-termux`
    *   This is a distinct Git repository. Its primary online location is `gyroing/piper-tts-for-termux`.
*   **Its Fork Remote:** This repository also contains a remote named `fork` pointing to `https://github.com/Manamama/piper1-gpl.git`. This suggests an interaction or consumption of the user's `piper1-gpl` fork by this `piper-tts-for-termux` project.

## Termux (Android) Build Status and Improvements

This section summarizes the current state of building Piper TTS on Termux, highlighting the successful compilation and the automated improvements implemented.

The project now compiles successfully on Termux. The following key improvements have been made to streamline the build process:

*   **Hybrid `espeak-ng` Strategy**: The build system employs a two-stage strategy for maximum reliability. It first ensures the system's `espeak-ng` package is installed via `pkg` to satisfy any underlying dependencies. It then proceeds to clone and compile a fresh version of `espeak-ng` from source. This guarantees that the project links against a known, consistent version of the library, eliminating potential ABI conflicts and ensuring a self-contained, robust build.
*   **Automated ONNX Runtime Handling**: The `CMakeLists.txt` now automatically detects and links against the system-installed `libonnxruntime.so` provided by the `python-onnxruntime` Termux package. This eliminates the need for manual downloading, extraction, or linking against pre-compiled `.aar` files, ensuring better ABI compatibility and a more streamlined build process.
*   **ABI Compatibility Resolved**: By ensuring all native C++ components (like `espeakbridge.so` and `piper_phonemize_cpp`) are built and linked against the system's `libc++` and other core libraries, the notorious ABI compatibility issues (such as the `nlohmann::json` parsing errors) are inherently addressed.
*   **Simplified Installation**: The overall goal is to transform the installation into a "go for coffee" experience. After installing the initial `pkg` prerequisites, a simple `pip install piper-tts` will manage the compilation and linking of all native components, allowing the user to focus on using Piper rather than troubleshooting build errors.
*   **Reduced Manual Intervention**: The need for manual extraction of `libonnxruntime.so` from `.aar` files or using `patchelf` for library path adjustments is significantly reduced or provided as clear fallback steps.

## Core Operational Principle: The Strategic Sanity Check

Before executing any file modification or complex command, I must pause and perform a "Strategic Sanity Check." This involves asking:

1.  **What is the overall strategic goal?** (e.g., "To create a reliable build," "To fix a specific bug," "To refactor for clarity.")
2.  **Does my planned action directly and logically serve this goal?**
3.  **Does this action conflict with any "Lessons Learned" or historical failures documented in my memory files?**

If my planned action fails this check—if it is a tactical solution that undermines the strategic goal or repeats a past mistake—I must stop, report the conflict to the user, and propose a better course of action. I will not be a "bulldog" focused only on the immediate task if it compromises the larger objective.

**Termux Environment and Shebangs:** Its crucial to understand that Termux operates on top of the Android OS. When a scripts shebang (e.g., `#!/bin/sh`) is invoked, it typically resolves to the *native Android system shell* (`/bin/sh`), not the Termux shell, unless specific Termux virtualization commands are employed. This native shell is often minimal and may not be suitable for complex build scripts. To ensure scripts are run by the full-featured Termux shell, explicitly invoke them with `/data/data/com.termux/files/usr/bin/bash -c "..."` or ensure the `PATH` is correctly set for the sub-process. If unsure about the nature of a binary or script, use `file <path>` or `ldd <path>` to inspect it.

When testing the ready `piper` package do use the audio models which are located in `~/.cache/piper`. Do use piper's --help to learn how to

## Known Issues

### ImportError: espeakbridge

When attempting to run the `piper` command, an `ImportError` occurs, indicating that the `espeakbridge` module cannot be imported:

```
ImportError: cannot import name 'espeakbridge' from 'piper' (/data/data/com.termux/files/usr/lib/python3.12/site-packages/piper/__init__.py)
```

This suggests that the native `espeakbridge` component, crucial for phonemization, is is not being correctly built or installed during the `pip install .` process. This is the primary blocker for the `piper` package's functionality.

## Build Fixes and Progress

### espeakbridge ImportError Resolved (Manual Build)

The persistent `ImportError: cannot import name 'espeakbridge'` has been addressed. The root cause was the `espeakbridge.c` C extension not being properly compiled and integrated into the Python package.

**Solution:**

`setup.py` was modified to explicitly define `espeakbridge` as a `setuptools.Extension`. This involved:

*   Adding `import sys` and `from setuptools import Extension`.
*   Defining an `espeakbridge_extension` object, specifying `src/piper/espeakbridge.c` as its source.
*   Using `sys.prefix` to dynamically determine the `espeak-ng` include and library paths for portability (e.g., `Path(sys.prefix) / "include" / "espeak-ng"`).
*   Adding `espeakbridge_extension` to the `ext_modules` list in the `setup()` call.

**Verification (Manual Build):**

Running `python3 setup.py build_ext --inplace` successfully compiled `espeakbridge.c` into `espeakbridge.cpython-312.so` and placed it in the `src/piper` directory, resolving the compilation aspect of the `ImportError`.

**Next Steps:**

While the C extension now compiles, the `piper` package itself is not yet fully discoverable by the Python interpreter in a standard way (e.g., `python3 -m piper` still fails). This indicates that a proper installation (e.g., via `pip install .` or `pip install -e .`) is still required to make the package and its entry points accessible in the Python environment.


## Build Fixes and Progress

### espeakbridge ImportError Resolved (Final Solution)

The persistent `ImportError: cannot import name 'espeakbridge'` has been fully addressed, and the `piper` package now installs and functions correctly with `pip install .` (including build isolation).

**Root Cause:**

The primary issue was the `espeakbridge.c` C extension not being properly compiled and integrated into the Python package, specifically due to `setuptools` misinterpreting relative paths as absolute within `pip`'s isolated build environment.

**Solution:**

`setup.py` was modified to explicitly define `espeakbridge` as a `setuptools.Extension` with a robust relative path construction. This involved:

*   Adding `import os` and ensuring `import sys` and `from setuptools import Extension` are present.
*   Defining an `espeakbridge_extension` object.
*   Crucially, setting the `sources` argument for `espeakbridge_extension` to use `os.path.relpath(os.path.join(os.path.dirname(__file__), "src", "piper", "espeakbridge.c"))`. This ensures the path is always correctly interpreted as relative to `setup.py`, even in isolated build environments.
*   Using `sys.prefix` to dynamically determine the `espeak-ng` include and library paths for portability (e.g., `str(Path(sys.prefix) / "include" / "espeak-ng")`).
*   Adding `espeakbridge_extension` to the `ext_modules` list in the `setup()` call.

**Verification:**

Running `pip install . -v` now successfully builds and installs the `piper` package, including the `espeakbridge` C extension. The `piper` command is accessible in the PATH, and speech generation functions as expected.

## README.md Cleanup and Simplification

The `README.md` file has been significantly updated and simplified to reflect the successful build process and provide a clearer user experience. Key changes include:

*   **Introduction of a "Quick Start (Recommended Method)" section**: This new section highlights the streamlined `pip install .` process, making it the primary and easiest way for users to get started.
*   **Removal of obsolete manual build instructions**: All detailed, step-by-step guides for manual compilation, ONNX Runtime handling, and `patchelf` usage have been removed as they are no longer necessary with the automated build.
*   **Consolidation and update of usage examples**: The various usage examples have been combined into a single, comprehensive "Usage" section. All examples now correctly demonstrate how to use the installed Python package via `python3 -m piper`.
*   **Refined "Environment Variables" section**: This section has been updated to reflect the relevant environment variables for the Python API and CLI, removing outdated information.
*   **Removal of the Debian package section**: The section detailing the `piper-tts-cli` deb package has been removed as it is no longer the primary or recommended installation method.
*   **Retention of "Building from Source & Development"**: This section remains and now explicitly points to `docs/BUILDING.md` for advanced users who need detailed build information or wish to contribute to development.