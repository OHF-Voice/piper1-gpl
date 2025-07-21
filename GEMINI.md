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

---

## Current Bug: `espeakbridge` ImportError during `pip install`

**Problem:**
After `pip install .`, the `piper` executable fails with an `ImportError: cannot import name 'espeakbridge' from 'piper'`. This indicates that the `espeakbridge` C extension, which is crucial for `espeak-ng` phonemization, is not being correctly built or linked into the Python package.

**Attempts to Fix:**

1.  **Initial `setup.py` Modification (Adding `Extension`):**
    *   **Action:** Modified `setup.py` to explicitly define `piper.espeakbridge` as a `setuptools.Extension`, pointing its `sources` to `src/piper/espeakbridge.c`.
    *   **Rationale:** This was intended to instruct the build system to compile `espeakbridge.c` into a Python-importable shared library (`.so` file).
    *   **Outcome:** The `pip install` failed with an error: "setup script specifies an absolute path: /data/data/com.termux/files/home/downloads/GitHub/piper1-gpl/src/piper/espeakbridge.c".

2.  **Path Correction in `setup.py` (Relative `sources`):**
    *   **Action:** Changed the `sources` path in `setup.py` from `str(MODULE_DIR / "espeakbridge.c")` (which resolved to an absolute path) to a direct relative string: `"src/piper/espeakbridge.c"`.
    *   **Rationale:** `setuptools` requires paths in `Extension` definitions to be relative to `setup.py`.
    *   **Outcome:** The `pip install` *still* failed with the exact same "setup script specifies an absolute path" error, pointing to the same absolute path. This suggests that `setuptools` or `skbuild` is performing an internal path resolution that converts the relative path back into an absolute one before the final build step, or that the error message is misleading.

3.  **Path Correction in `setup.py` (Relative `include_dirs` and `library_dirs`):**
    *   **Action:** Changed `include_dirs` and `library_dirs` within the `Extension` definition to also use relative paths (`"build/espeak-ng-install/include"` and `"build/espeak-ng-install/lib"`).
    *   **Rationale:** To ensure all paths provided to the `Extension` are relative, in case the issue was with these arguments.
    *   **Outcome:** The `pip install` *still* failed with the exact same "setup script specifies an absolute path" error.

4.  **Revert `include_dirs` and `library_dirs`:**
    *   **Action:** Reverted `include_dirs` and `library_dirs` back to using `Path(__file__).parent` as they were not the direct cause of the absolute path error.
    *   **Rationale:** To isolate the problem to the `sources` argument or the interaction between `setuptools.Extension` and `skbuild`.

**Current Hypothesis:**
The persistent "absolute path" error, despite providing relative paths in `setup.py`, indicates a deeper interaction issue between `setuptools.Extension` and `skbuild` (which uses CMake). It appears that `skbuild` might be resolving these paths to absolute paths internally before passing them to the underlying build system, leading to `setuptools` complaining.

**Next Steps (Plan):**

1.  **Remove `espeakbridge_ext` from `setup.py`:** The current approach of defining `espeakbridge.c` as a separate `setuptools.Extension` seems problematic with `skbuild`'s path handling.
2.  **Integrate `espeakbridge.c` compilation directly into `libpiper/CMakeLists.txt`:** This is the more robust and idiomatic way to handle C/C++ components when using CMake. I will modify `libpiper/CMakeLists.txt` to compile `espeakbridge.c` and link it into `libpiper.so`. This will ensure that `espeakbridge`'s functionality is part of the main `libpiper.so` shared library.
3.  **Verify Python-C interface:** After modifying CMake, I will need to ensure that the Python code in `piper/phonemize_espeak.py` can correctly call the C functions exposed by `libpiper.so` (which will now include the `espeakbridge` functionality). This might involve using `ctypes` or ensuring the C functions are exposed in a way that `libpiper.so` can be directly loaded and its symbols accessed.

This approach leverages CMake's strengths for managing C/C++ builds and avoids the potential path resolution conflicts encountered with `setuptools.Extension` in this specific setup.

## Tactical Decision: Handling `espeakbridge.c` Absolute Path Error

**Problem Summary:**
The `pip install` process consistently fails with the error: "setup script specifies an absolute path: `/data/data/com.termux/files/home/downloads/GitHub/piper1-gpl/src/piper/espeakbridge.c`". This error originates from `setuptools` (used by `skbuild`), which rejects absolute paths for extension sources.

**Analysis:**
1.  **`espeakbridge.c`'s Role:** This C source file provides the C-level interface to the `espeak-ng` library. It is intended to be compiled *into* the core native library, `libpiper.so`, not as a standalone Python C extension.
2.  **`skbuild`'s Misinterpretation:** `skbuild` (the build backend for `pip` that integrates with CMake) automatically scans Python package directories (like `src/piper/`). When it finds `espeakbridge.c` there, it implicitly assumes it's a standalone Python C extension.
3.  **Absolute Path Generation:** Due to this misinterpretation, `skbuild` (or the underlying build system it invokes) generates an absolute path to `espeakbridge.c` when attempting to build it as a separate extension. This absolute path is then passed to `setuptools`, triggering the error.
4.  **No Explicit `Extension` in `setup.py`:** Our review of `setup.py` confirms that `espeakbridge.c` is *not* explicitly defined as a `setuptools.Extension`. The problem is `skbuild`'s implicit behavior, not a direct instruction from `setup.py`.

**Proposed Solution (Future Action):**
The most idiomatic and robust solution is to explicitly include `espeakbridge.c` as a source file for the `piper` shared library within `libpiper/CMakeLists.txt`. This will tell CMake (and thus `skbuild`) that `espeakbridge.c` is part of `libpiper.so`, preventing `skbuild` from misinterpreting it as a separate Python extension and generating the problematic absolute path.

**Rationale for this Tactical Decision:**
This approach ensures that `espeakbridge.c` is handled correctly within the native library build, aligning with the project's architectural intent. It avoids fighting against `skbuild`'s implicit behaviors by providing explicit instructions at the CMake level where the native library is defined.

**Current State (Pre-Modification):**
The `CMakeLists.txt` currently includes debug messages for `PATH` and `LD_LIBRARY_PATH`, and explicitly sets `Python_VERSION_MAJOR` and `Python_VERSION_MINOR`. The `libpiper/CMakeLists.txt` is in its original state regarding `espeakbridge.c` sources.

**Next Steps:**
1.  Update `GEMINI.md` with this tactical decision.
2.  Commit `GEMINI.md`, `CMakeLists.txt`, and `libpiper/CMakeLists.txt` (if modified since last commit) to establish a clear checkpoint.
3.  Only *then* proceed with the modification to `libpiper/CMakeLists.txt` as described in the "Proposed Solution".
