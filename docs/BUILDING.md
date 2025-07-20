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

This approach leverages modifications to `CMakeLists.txt` (part of this fork) to automate the handling of native dependencies, aiming for a seamless `pip install` experience.

1.  **Initial Prerequisites**: Before running `pip install`, ensure you have the fundamental build tools installed via `pkg`. These are essential for CMake and the overall build process:

    ```bash
    pkg update && pkg install build-essential cmake git
    ```
    *(Note: `ninja` is handled automatically by the CMake script itself.)*

2.  **Automated `espeak-ng` Build**: To avoid version and ABI incompatibilities with the system-provided `espeak-ng` package, the `CMakeLists.txt` now automatically clones and compiles `espeak-ng` from source during the build process. This ensures that Piper is built against the exact version of `espeak-ng` it requires. The `python-onnxruntime` package is still installed automatically via `pkg`.

3.  **Simple `pip install`**: Once the initial prerequisites are met, you can install Piper directly using `pip`:

    ```bash
    pip install piper-tts
    ```

    This command will trigger the compilation of Piper's native extensions. The `CMakeLists.txt` will handle the installation of `python-onnxruntime` and the compilation of `espeak-ng`, allowing you to go for coffee while it builds.

### Plan B: Manual Verification and Troubleshooting

If the automated build (Plan A) fails, it is almost always due to an issue with the underlying system dependencies or network connectivity. This plan will guide you through verifying the environment and diagnosing problems.

1.  **Check `pkg` Status and Network**: If the build fails during the automated `pkg install` step for `python-onnxruntime`, verify your network connection and ensure `pkg` is functioning correctly.

    ```bash
    ping -c 3 google.com # Check network connectivity
    pkg update           # Ensure pkg is up-to-date
    ```

2.  **Verify Package Installation**: If the build fails with a `FATAL_ERROR` indicating a missing library or header, manually verify the presence of the packages and their files:

    ```bash
    pkg list-installed python-onnxruntime # Check if package is listed as installed
    ls -l /data/data/com.termux/files/usr/lib/python*/site-packages/onnxruntime/capi/libonnxruntime.so* # Check onnxruntime library
    ```
    If any of these files are missing, try manually installing the respective package: `pkg install -y python-onnxruntime`.

3.  **`espeak-ng` Build Failure**: If the build fails during the compilation of the bundled `espeak-ng`, you may need to build it manually. It is recommended to clone it into the `third-party` directory:

    ```bash
    # Clone the repository into the third-party directory
    git clone https://github.com/espeak-ng/espeak-ng.git third-party/espeak-ng
    cd third-party/espeak-ng

    # Build and install
    ./autogen.sh
    ./configure --prefix=/data/data/com.termux/files/usr
    make
    make install
    ```

4.  **Clean the Build Environment**: After any manual intervention or failed build, it's crucial to clean the build cache to ensure a fresh start:

    ```bash
    pip uninstall piper-tts # If partially installed
    rm -rf _skbuild         # Remove the build cache directory from the project root
    ```

5.  **Re-run the Build with Verbose Output**: If problems persist, run the installation with verbose output to get more detailed compiler and linker messages:

    ```bash
    pip install . -v
    ```
    Examine the output carefully for specific errors.

6.  **Patching (Last Resort)**: If you encounter linking errors related to incorrect library versions (e.g., it's looking for `libonnxruntime.so.1` but you only have `libonnxruntime.so`), you may need to use `patchelf`. This is an advanced step and should only be attempted if the error messages specifically indicate a version mismatch.

    ```bash
    # Example: Make a binary look for libonnxruntime.so instead of a versioned file
    # (You would run this on the compiled piper library inside _skbuild)
    patchelf --replace-needed libonnxruntime.so.1 libonnxruntime.so /path/to/compiled/piper/library.so
    ```

### What This Means for the User (Overall):

This fork aims to provide a significantly smoother experience for Termux users building Piper. The primary goal (Plan A) is to automate the complex native dependency handling, transforming the installation into a "go for coffee" experience. Even if Plan A requires troubleshooting, Plan B provides clear manual steps to resolve common issues.

*   **Automated Dependency Management**: The `CMakeLists.txt` now proactively manages the installation of `espeak` and `python-onnxruntime`, reducing manual steps.
*   **Robust Checks**: The build includes checks for `espeak-ng` version compatibility, ensuring the correct API is available.
*   **Clear Error Messages**: If automated steps fail, the script provides specific `FATAL_ERROR` messages with guidance for manual resolution.
*   **Simplified Installation**: The overall goal is to transform the installation into a "go for coffee" experience. After installing the initial `pkg` prerequisites, a simple `pip install piper-tts` will manage the compilation and linking of all native components, allowing the user to focus on using Piper rather than troubleshooting build errors.
*   **Reduced Manual Intervention**: The need for manual extraction of `libonnxruntime.so` from `.aar` files or using `patchelf` for library path adjustments is significantly reduced (Plan A) or provided as clear fallback steps (Plan B).

This updated documentation reflects the desired state after the `CMakeLists.txt` modifications are integrated into the main project. It aims to provide a much smoother experience for Termux users.