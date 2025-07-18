#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <cstring>
#include <cstdlib>

#include <piper.h>

// تابع برای نمایش پیام راهنما
void print_usage() {
    // جداکننده رشته خام از " به HELP تغییر کرده تا با محتوای متن تداخل نداشته باشد
    std::cout << R"HELP(
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

Version:
  piper-tts-cli 1.0

Report bugs to: https://github.com/gyroing
)HELP";
}


int main(int argc, char *argv[]) {
    std::string model_name;
    std::string output_file = "output.raw";
    bool output_to_stdout = false;
    std::string input_text;

    // مسیر espeak از متغیر محیطی یا مسیر پیش‌فرض ترموکس
   const char* espeak_path = std::getenv("ESPEAK_DATA_PATH");
   if (!espeak_path) {
      espeak_path = "/data/data/com.termux/files/usr/share/espeak-ng-data";
   }

    // پردازش آرگومان‌ها
    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "-h" || arg == "--help") {
            print_usage();
            return 0;
        } else if (arg == "-m" && i + 1 < argc) {
            model_name = argv[++i];
        } else if (arg == "-f" && i + 1 < argc) {
            output_file = argv[++i];
        } else if (arg == "--output-raw") {
            output_to_stdout = true;
        } else if (arg == "--" && i + 1 < argc) {
            input_text = argv[++i];
            break; // End of options
        }
    }

    // بررسی اینکه آیا نام مدل مشخص شده است
    if (model_name.empty()) {
        std::cerr << "Error: Model name is required.\n";
        std::cerr << "Use -m MODEL_NAME to specify the model.\n";
        std::cerr << "Use --help for more information.\n";
        return 1;
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

