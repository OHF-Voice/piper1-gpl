🛠️ How to Build libpiper.so and a Native piper CLI Binary in Termux (Android)

This guide walks you through compiling libpiper.so and a native command-line frontend (piper) inside Termux on Android.


---

📦 Prerequisites

Install necessary build tools:

pkg update && pkg install git cmake build-essential termux-api sox patchelf


---

📁 Step 1: Clone the Repository

mkdir -p piper-tts && cd piper-tts
git clone https://github.com/OHF-Voice/piper1-gpl.git
cd piper1-gpl/libpiper


---

⚙️ Step 2: Configure and Build libpiper.so

cmake -Bbuild -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=$PWD/install
cmake --build build
cmake --install build

Then:

mv ./install/libpiper.so ./install/lib/


---

🔍 Step 3: Check Which ONNX Runtime is Needed

Before downloading any .aar, inspect the shared object dependency:

Now inspect which symbols are needed:

readelf -Ws ./install/lib/libpiper.so | grep OrtGetApiBase

If you see OrtGetApiBase or similar symbols, it means you need a compatible version of ONNX Runtime.
ex 1.14 1.15.1
now is 1.22.0

---

🌐 Step 4: Download ONNX Runtime

1. Go to the ONNXRuntime Maven Repo.
[https://repo1.maven.org/maven2/com/microsoft/onnxruntime/onnxruntime-android/](url)

2. Choose a version that matches the symbols needed by libpiper.so (e.g., 1.15.1, 1.14.1).
we need 1.22.0 

3. Download the corresponding .aar file.



Extract it:

unzip onnxruntime-android-1.22.0.aar
and extract libonnxruntime.so from
jni/arm64-v8a/libonnxruntime.so 
then:
Remove unneeded onnxruntime.so and ...
at ./install/lib/
then:
copy libonnxruntime.so to ./install/lib/


---

🩹 Step 5: Patch libpiper.so (if needed):

readelf -d ./install/lib/libpiper.so | grep onnx

This will show whether it's looking for libonnxruntime.so or a versioned one like libonnxruntime.so.1.
If libpiper.so is linked to a versioned .so like libonnxruntime.so.1, patch it:

patchelf --replace-needed libonnxruntime.so.1 libonnxruntime.so install/lib/libpiper.so


---

👷 Step 6: Compile CLI App (piper.cpp)

Use the following simple CLI wrapper for libpiper:

here is piper.cpp: 
```c++
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <cstring>
#include <cstdlib>

#include <piper.h>

int main(int argc, char *argv[]) {
    std::string model_name;
    std::string output_file = "output.raw";
    bool output_to_stdout = false;
    std::string input_text;

    // مسیر espeak از متغیر محیطی
    const char* espeak_path = std::getenv("ESPEAK_DATA_PATH");
    if (!espeak_path) {
        std::cerr << "خطا: متغیر محیطی ESPEAK_DATA_PATH تنظیم نشده.\n";
        return 1;
    }

    // پردازش آرگومان‌ها
    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "-m" && i + 1 < argc) {
            model_name = argv[++i];
        } else if (arg == "-f" && i + 1 < argc) {
            output_file = argv[++i];
        } else if (arg == "--output-raw") {
            output_to_stdout = true;
        } else if (arg == "--" && i + 1 < argc) {
            input_text = argv[++i];
        }
    }

    // اگر input_text خالی بود، از stdin بخوان
    if (input_text.empty()) {
        std::ostringstream ss;
        std::string line;
        while (std::getline(std::cin, line)) {
            ss << line << "\n";
        }
        input_text = ss.str();
    }

    // مسیر مدل‌ها
    std::string model_dir;
    const char* model_path_env = std::getenv("PIPER_VOICE_PATH");
    if (model_path_env) {
        model_dir = std::string(model_path_env) + "/";
    } else {
        model_dir = "./";
    }

    std::string onnx_path = model_dir + model_name + ".onnx";
    std::string json_path = model_dir + model_name + ".onnx.json";

    // ساخت سینتسایزر
    piper_synthesizer *synth = piper_create(onnx_path.c_str(), json_path.c_str(), espeak_path);
    if (!synth) {
        std::cerr << "خطا: بارگذاری مدل یا espeak-ng-data شکست خورد.\n";
        return 1;
    }

    // تنظیمات سینت
    piper_synthesize_options options = piper_default_synthesize_options(synth);

    // خروجی
    std::ostream* out = nullptr;
    std::ofstream file_stream;
    if (output_to_stdout) {
        out = &std::cout;
        std::cout.sync_with_stdio(false); // سریع‌تر
    } else {
        file_stream.open(output_file, std::ios::binary);
        if (!file_stream) {
            std::cerr << "خطا: باز کردن فایل خروجی شکست خورد.\n";
            piper_free(synth);
            return 1;
        }
        out = &file_stream;
    }

    // شروع تبدیل متن به صدا
    piper_synthesize_start(synth, input_text.c_str(), &options);

    piper_audio_chunk chunk;
    while (piper_synthesize_next(synth, &chunk) != PIPER_DONE) {
        out->write(reinterpret_cast<const char *>(chunk.samples),
                   chunk.num_samples * sizeof(float));
    }

    piper_free(synth);
    return 0;
}
``` 

Compile:

g++ piper.cpp -I./install/include -L./install/lib -lpiper -o piper


---

🧪 Step 7: Run TTS

Put your .onnx and .onnx.json models in a folder like install/, and run:

echo "$(termux-clipboard-get)" | \
LD_LIBRARY_PATH=./install/lib \
ESPEAK_DATA_PATH=install/espeak-ng-data \
PIPER_VOICE_PATH=./install \
./piper -m fa_IR-gyro-medium --output-raw - | \
play -q -r 22050 -c 1 -e float -b 32 -t raw -


---

🌿 Environment Variables

Variable	Description

ESPEAK_DATA_PATH	Path to espeak-ng-data folder optional
If not specified, it looks for the folder in the execution directory
PIPER_VOICE_PATH	Folder where .onnx and .onnx.json voice models are stored.
LD_LIBRARY_PATH	Must include the folder with libpiper.so and libonnxruntime.so.



---

Let me know if you'd like a script version or Makefile to automate this setup.


---
Piper TTS CLI deb package for termux
1- apt install espeak
2- download deb package

apt install -f ./xxx.deb
for use see : piper -h  or piper -help


Usage:
  piper [OPTIONS] [-- TEXT]
  echo "TEXT" | piper [OPTIONS]

Description:
  piper-tts-cli is a lightweight text-to-speech (TTS) command-line interface
  for Termux using Piper and eSpeak-ng.

Options:
  -m, --model MODEL_NAME
        Name of the ONNX voice model to use (without .onnx extension).
        This option is required.

  -f, --file OUTPUT_FILE
        Write synthesized audio to the given file (RAW format).
        Default: 'output.raw' if this option is used without a file name.

  --output-raw -
        Write audio output to standard output (stdout).
        This allows piping to audio players like 'play' or 'aplay'.

  -- TEXT
        Input text to synthesize. If not provided, text will be read from stdin.

Environment Variables:
  ESPEAK_DATA_PATH
        Optional. Path to the eSpeak-ng data directory.
        If eSpeak-ng is installed system-wide, this can be omitted.
        Otherwise, set this to the path where 'espeak-ng-data/' is located.

  PIPER_VOICE_PATH
        Optional. Path to the directory containing ONNX voice models.
        If not set, the current working directory will be used.

Examples:
  1. Read text from clipboard and play output:
     echo "$(termux-clipboard-get)" | \
     ESPEAK_DATA_PATH=./espeak-ng-data \
     PIPER_VOICE_PATH=./voice \
     piper -m fa_IR-gyro-medium --output-raw - | \
     play -q -r 22050 -c 1 -e float -b 32 -t raw -

  2. Write audio to a file:
     piper -m fa_IR-gyro-medium -f output.raw -- "سلام دنیا"

  3. Use default output file (output.raw) with stdin:
     echo "Hello world" | ./piper -m en_US-mlm -f

Notes:
  - Output is always in 32-bit float RAW format at 22050Hz, mono.
  - When using --output-raw -, the output can be piped directly to 'play' or other audio tools.
  - This CLI is designed for use within Termux and supports local model/data directories.

Release Version:
  piper-tts-cli-1.0
 
