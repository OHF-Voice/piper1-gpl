# 🛠️ Building Manually

We use [scikit-build-core](https://github.com/scikit-build/scikit-build-core) along with [cmake](https://cmake.org/) to build a Python module that directly embeds [espeak-ng][].

You will need the following system packages installed (`apt-get`):

* `build-essential`
* `cmake`
* `ninja-build`

To create a dev environment:

``` sh
git clone https://github.com/OHF-voice/piper1-gpl.git
cd piper1-gpl
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .[dev]
```

Next, run `script/dev_build` or manually build the extension:

``` sh
python3 setup.py build_ext --inplace
```

Now you should be able to use `script/run` or manually run Piper:

``` sh
python3 -m piper --help
```

You can manually build wheels with:

``` sh
python3 -m build
```

## Design Decisions

[espeak-ng][] is used via a small Python bridge in `espeakbridge.c` which uses Python's [limited API][limited-api]. This allows the use of Python's [stable ABI][stable-abi], which means Piper wheels only need to be built once for each platform (Linux, Mac, Windows) instead of for each platform **and** Python version.

We build upstream [espeak-ng][] since they added the `espeak_TextToPhonemesWithTerminator` that Piper depends on. This function gets phonemes for text as well as the "terminator" that ends each text clause, such as a comma or period. Piper requires this terminator because punctuation is passed on to the voice model as "phonemes" so they can influence synthesis. For example, a voice trained with statements (ends with "."), questions (ends with "?"), and exclamations (ends with "!") may pronounce sentences ending in each punctuation mark differently. Commas, colons, and semicolons are also useful for proper pauses in synthesized audio.

<!-- Links -->
[espeak-ng]: https://github.com/espeak-ng/espeak-ng
[limited-api]: https://docs.python.org/3/c-api/stable.html#limited-c-api
[stable-abi]: https://docs.python.org/3/c-api/stable.html#stable-abi

---

## 📱 Termux (Android) Specifics

Building Piper on Termux (Android) involves specific considerations due to its unique environment. This section outlines the recommended approach (Plan A) for a streamlined `pip install` experience, and a manual troubleshooting guide (Plan B) if automated steps encounter issues.

### Plan A: Automated Build (Recommended)

This approach leverages modifications to `CMakeLists.txt` to automate the handling of native dependencies, aiming for a seamless `pip install` experience. The build process is as follows:

1.  **Initial Prerequisites**: Before running `pip install`, ensure you have the fundamental build tools installed via `pkg`. These are essential for CMake and the overall build process:

    ```bash
    pkg update && pkg install build-essential cmake git ninja-build
    ```

2.  **Run Installation**: With the prerequisites in place, simply run the standard pip installation command from the project root:

    ```bash
    pip install .
    ```

3.  **Automated Dependency Management (What Happens Next)**: When you run the install command, the `CMakeLists.txt` script takes over and performs several automated steps:
    *   **Installs System Packages**: It uses the Termux `pkg` command to automatically install `espeak`, `python-onnxruntime`, `autoconf`, and `automake`. These are required for the subsequent build steps.
    *   **Verifies ONNX Runtime**: It checks that the `onnxruntime` library (from the `python-onnxruntime` package) is correctly installed and located.
    *   **Clones and Builds `espeak-ng`**: To avoid version and ABI incompatibilities with the system-provided `espeak-ng` package, the `CMakeLists.txt` now automatically clones and compiles `espeak-ng` from source during the build process. This ensures that Piper is built against the exact version of `espeak-ng` it requires. This local build is used exclusively by Piper, avoiding any potential conflicts with the system version.
    *   **Handles Data Installation (The "Hack")**: A small but critical modification was made to the build process. The required `espeak-ng-data` directory is now copied into its final package location *before* the main `piper` library is compiled. This is done using a `PRE_BUILD` custom command in CMake. This architectural choice is a workaround for a complex timing issue where the standard `install` command would fail because the data from the external `espeak-ng` project wasn't available at the right moment. This ensures the data is ready when the final package is assembled.
    *   **Builds Piper**: Finally, it compiles the Piper library itself, linking it against the locally built `espeak-ng` and the system's `onnxruntime`.

This entire process is designed to be automatic. Once you start the `pip install` command, you can step away while it completes.

### Plan B: Manual Verification and Troubleshooting

If the automated build (Plan A) fails, this guide will help you diagnose the problem. The issue is almost always related to system dependencies, network connectivity, or a stale build cache.

1.  **Clean the Build Environment**: Before anything else, if a build has failed, you must start with a clean slate. This is the most common fix.

    ```bash
    # If piper-tts was partially installed, remove it
    pip uninstall piper-tts

    # CRITICAL: Remove the build cache directory from the project root
    rm -rf _skbuild
    ```

2.  **Verify Prerequisites and Network**: Ensure the core packages are installed and that you have network access, which is required for the `git clone` step.

    ```bash
    # Install/verify core build tools
    pkg install -y build-essential cmake git ninja-build autoconf automake

    # Check network connectivity
    ping -c 3 google.com
    ```

3.  **Re-run with Verbose Output**: The most important step for debugging is to get detailed logs.

    ```bash
    pip install . -v
    ```
    Examine the output carefully. The error will be near the end.

4.  **Interpreting Common Errors**:
    *   **`Failed to clone espeak-ng repository`**: This indicates a network problem or that `git` is not installed correctly. Check your connection.
    *   **`sh: 1: ./autogen.sh: not found`**: This was an error we fixed. If you see it, ensure your `CMakeLists.txt` is up-to-date with the version in this repository.
    *   **`make: *** No targets specified and no makefile found`**: This was another error we fixed. It means the `espeak-ng` build is happening in the wrong directory. Ensure your `CMakeLists.txt` contains the `BUILD_IN_SOURCE 1` directive for the external project.
    *   **`file INSTALL cannot find ... espeak-ng-data`**: This was the final timing error we fixed. It means the `espeak-ng-data` directory wasn't copied correctly. Ensure your `libpiper/CMakeLists.txt` uses the `add_custom_command` logic.
    *   **Errors inside `espeak-ng` compilation**: If the error occurs during the `make` step for `espeak_ng_external` (you'll see C++ compiler errors), the problem is likely with the build environment itself. You can inspect the detailed logs created by the external project build:
        ```bash
        # Find the log files after a failed build
        ls -l _skbuild/linux-aarch64-3.12/cmake-build/espeak_ng_external-prefix/src/
        ```
        Look at the `espeak_ng_external-configure-out.log` and `espeak_ng_external-build-out.log` files for specific compiler errors.



### What This Means for the User (Overall):

This fork aims to provide a significantly smoother experience for Termux users building Piper. The primary goal (Plan A) is to automate the complex native dependency handling, transforming the installation into a "go for coffee" experience. Even if Plan A requires troubleshooting, Plan B provides clear manual steps to resolve common issues.

*   **Automated Dependency Management**: The `CMakeLists.txt` now proactively manages the installation of `espeak` and `python-onnxruntime`, reducing manual steps.
*   **Robust Checks**: The build includes checks for `espeak-ng` version compatibility, ensuring the correct API is available.
*   **Clear Error Messages**: If automated steps fail, the script provides specific `FATAL_ERROR` messages with guidance for manual resolution.
*   **Simplified Installation**: The overall goal is to transform the installation into a "go for coffee" experience. After installing the initial `pkg` prerequisites, a simple `pip install piper-tts` will manage the compilation and linking of all native components, allowing the user to focus on using Piper rather than troubleshooting build errors.
*   **Reduced Manual Intervention**: The need for manual extraction of `libonnxruntime.so` from `.aar` files or using `patchelf` for library path adjustments is significantly reduced (Plan A) or provided as clear fallback steps (Plan B).

This updated documentation reflects the desired state after the `CMakeLists.txt` modifications are integrated into the main project. It aims to provide a much smoother experience for Termux users.