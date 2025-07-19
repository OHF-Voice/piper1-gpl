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

1.  **Install Termux System Packages**: Before running `pip install`, ensure you have the necessary build tools and the `espeak` library installed via `pkg`:

    ```bash
    pkg update && pkg install git cmake build-essential ninja espeak
    ```

2.  **Automated ONNX Runtime Library Handling**: The modified `CMakeLists.txt` will now automatically download the required `onnxruntime-android-X.Y.Z.aar` from the official Maven repository, extract `libonnxruntime.so` (specifically for `arm64-v8a` architecture), and link against it during the `pip install` process. This eliminates the need for manual intervention for ONNX Runtime.

3.  **Simple `pip install`**: Once the system packages are in place, you can install Piper directly using `pip`:

    ```bash
    pip install piper-tts
    ```

    This command will trigger the compilation of Piper's native extensions, which will now correctly link against your Termux system's libraries, allowing you to go for coffee while it builds.

### Plan B: Manual Troubleshooting / Fallback

If Plan A does not work as expected, or if you encounter specific linking errors, you may need to perform some manual steps.

1.  **Install Termux System Packages**: (Same as Plan A)

    ```bash
    pkg update && pkg install git cmake build-essential ninja espeak
    ```

2.  **Manually Handle ONNX Runtime Library**: The `libonnxruntime.so` is a crucial dependency for Piper's C++ extensions. If the automated download/extraction fails, you will need to do this manually:

    *   **Download ONNX Runtime AAR**: Obtain the `onnxruntime-android-X.Y.Z.aar` file from the ONNX Runtime Maven Repository (e.g., `https://repo1.maven.org/maven2/com/microsoft/onnxruntime/onnxruntime-android/`). The version (X.Y.Z) should be compatible with the `onnxruntime` Python package version specified in `setup.py`.
    *   **Extract `libonnxruntime.so`**: Unzip the `.aar` file and locate `libonnxruntime.so` within the `jni/arm64-v8a/` directory (for aarch64 Termux devices).
    *   **Place `libonnxruntime.so`**: Copy the extracted `libonnxruntime.so` to Termux's system library path, typically `/data/data/com.termux/files/usr/lib/`.

3.  **Re-attempt `pip install`**: After manually placing `libonnxruntime.so`, try `pip install piper-tts` again.

4.  **Patching (Last Resort)**: If you encounter linking errors related to versioned shared libraries (e.g., `libonnxruntime.so.1`), you might need to use `patchelf` to adjust the library dependencies. This is an advanced step and should only be attempted if other methods fail.

    ```bash
    # Example (adjust paths and library names as needed)
    patchelf --replace-needed libonnxruntime.so.1 libonnxruntime.so /path/to/libpiper.so
    ```

### What This Means for the User (Overall):

This fork aims to provide a significantly smoother experience for Termux users building Piper. The primary goal (Plan A) is to automate the complex native dependency handling, transforming the installation into a "go for coffee" experience. Even if Plan A requires troubleshooting, Plan B provides clear manual steps to resolve common issues.

*   **Automated `espeak-ng` Integration**: The build system will now intelligently detect and link against your system-installed `espeak-ng` (ensuring you have run `pkg install espeak`). This eliminates the need for complex `ExternalProject` builds and ensures ABI compatibility with your Termux environment.
*   **Automated ONNX Runtime Handling (Plan A)**: The `CMakeLists.txt` will automatically download, extract, and correctly link against the necessary `libonnxruntime.so` shared library. The user will **not** need to manually download or place `.aar` files for Plan A to work.
*   **ABI Compatibility Resolved**: By ensuring all native C++ components (like `espeakbridge.so` and `piper_phonemize_cpp`) are built and linked against the system's `libc++` and other core libraries, the notorious ABI compatibility issues (such as the `nlohmann::json` parsing errors) are inherently addressed.
*   **Simplified Installation**: The overall goal is to transform the installation into a "go for coffee" experience. After installing the initial `pkg` prerequisites, a simple `pip install piper-tts` will manage the compilation and linking of all native components, allowing the user to focus on using Piper rather than troubleshooting build errors.
*   **Reduced Manual Intervention**: The need for manual extraction of `libonnxruntime.so` from `.aar` files or using `patchelf` for library path adjustments is significantly reduced (Plan A) or provided as clear fallback steps (Plan B).

This updated documentation reflects the desired state after the `CMakeLists.txt` modifications are integrated into the main project. It aims to provide a much smoother experience for Termux users.