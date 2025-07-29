#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>
#include <cstring> // For strcmp

#include <piper.h>

// Conditionally include PulseAudio headers
#ifdef ENABLE_PULSEAUDIO
#include <pulse/simple.h>
#include <pulse/error.h>
#endif

// Function to display the help message
void print_usage() {
    std::cout << R"HELP(
Usage:
  piper [OPTIONS]
  piper [OPTIONS] -- "TEXT"
  echo "TEXT" | piper [OPTIONS]

Description:
  A lightweight TTS command-line interface for Termux using Piper and eSpeak-ng.
  It can write to a file, stdout, or play audio directly.

Options:
  -h, --help
        Show this help message.

  -m, --model MODEL_NAME
        (Required) Name of the ONNX voice model to use (e.g., 'en_US-lessac-medium').

  -f, --file [OUTPUT_FILE]
        Write synthesized audio to a file.
        Defaults to 'output.raw' if no filename is given.

  -i, --input INPUT_FILE
        Read text from the specified file instead of stdin or command line.

  -p, --play
        Play the synthesized audio directly. Requires PulseAudio.

  --output-raw -
        Write RAW audio to standard output (stdout) for piping.

  -- "TEXT"
        Input text to synthesize. Must be the last option.

Environment Variables:
  ESPEAK_DATA_PATH
        Path to the eSpeak-ng data directory.
        Default: '/data/data/com.termux/files/usr/share/espeak-ng-data'

  PIPER_VOICE_PATH
        Path to the directory containing ONNX voice models.
        Default: Current working directory.

Examples:
  1. Synthesize text and play it directly:
     piper -m fa_IR-gyro-medium -p -- "سلام دنیا"

  2. Read text from a file and save as 'audio.raw':
     piper -m en_US-lessac-medium -i text.txt -f audio.raw

  3. Pipe clipboard content for direct playback:
     termux-clipboard-get | piper -m en_US-lessac-medium -p

Notes:
  - Audio format is 32-bit float, 22050Hz, single channel (mono).
  - To compile with playback support, ensure libpulse is installed and use:
    g++ piper.cpp -o piper -lpiper -lpulse-simple -lpulse -DENABLE_PULSEAUDIO
  - Report bugs to: https://github.com/gyroing

Version:
  piper-tts-cli 2.0
)HELP";
}

int main(int argc, char *argv[]) {
    setvbuf(stdout, nullptr, _IONBF, 0);

    std::string model_name;
    std::string output_file;
    std::string input_file;
    std::string input_text;
    bool use_file_output = false;
    bool output_to_stdout = false;
    bool play_audio = false;

    // Process arguments
    for (int i = 1; i < argc; ++i) {
        if (strcmp(argv[i], "-h") == 0 || strcmp(argv[i], "--help") == 0) {
            print_usage();
            return 0;
        } else if (strcmp(argv[i], "-m") == 0 || strcmp(argv[i], "--model") == 0) {
            if (i + 1 < argc) model_name = argv[++i];
        } else if (strcmp(argv[i], "-i") == 0 || strcmp(argv[i], "--input") == 0) {
            if (i + 1 < argc) input_file = argv[++i];
        } else if (strcmp(argv[i], "-f") == 0 || strcmp(argv[i], "--file") == 0) {
            use_file_output = true;
            // Check if a filename is provided next, otherwise use default
            if (i + 1 < argc && argv[i + 1][0] != '-') {
                output_file = argv[++i];
            } else {
                output_file = "output.raw";
            }
        } else if (strcmp(argv[i], "--output-raw") == 0) {
            if (i + 1 < argc && strcmp(argv[i + 1], "-") == 0) {
                 output_to_stdout = true;
                 i++; // Consume the '-'
            }
        } else if (strcmp(argv[i], "-p") == 0 || strcmp(argv[i], "--play") == 0) {
            play_audio = true;
        } else if (strcmp(argv[i], "--") == 0) {
            if (i + 1 < argc) {
                // Collect all remaining arguments as input text
                std::ostringstream text_stream;
                for (int j = i + 1; j < argc; ++j) {
                    text_stream << argv[j] << (j < argc - 1 ? " " : "");
                }
                input_text = text_stream.str();
            }
            break; // End of options
        } else {
             // To handle the case where text is provided without '--'
             if(input_text.empty()) {
                std::ostringstream text_stream;
                for (int j = i; j < argc; ++j) {
                    text_stream << argv[j] << (j < argc - 1 ? " " : "");
                }
                input_text = text_stream.str();
                break;
            }
        }
    }


    if (model_name.empty()) {
        std::cerr << "Error: Model name is required. Use -m <MODEL_NAME>.\n";
        print_usage();
        return 1;
    }

#ifndef ENABLE_PULSEAUDIO
    if (play_audio) {
        std::cerr << "Error: Playback support is not enabled.\n";
        std::cerr << "Compile with -DENABLE_PULSEAUDIO and link against libpulse.\n";
        return 1;
    }
#endif

    // Determine input source
    if (!input_file.empty()) {
        std::ifstream file(input_file);
        if (!file) {
            std::cerr << "Error: Cannot open input file: " << input_file << "\n";
            return 1;
        }
        std::ostringstream ss;
        ss << file.rdbuf();
        input_text = ss.str();
    } else if (input_text.empty()) {
        // Read from stdin if no file or direct text is given
        std::ostringstream ss;
        std::string line;
        while (std::getline(std::cin, line)) {
            ss << line << "\n";
        }
        input_text = ss.str();
    }

    // Set up paths
    const char* espeak_path = std::getenv("ESPEAK_DATA_PATH");
    if (!espeak_path) espeak_path = "/data/data/com.termux/files/usr/share/espeak-ng-data";

    std::string model_dir = "./";
    const char* model_path_env = std::getenv("PIPER_VOICE_PATH");
    if (model_path_env) model_dir = std::string(model_path_env) + "/";

    std::string onnx_path = model_dir + model_name + ".onnx";
    std::string json_path = model_dir + model_name + ".onnx.json";

    // Initialize Piper
    piper_synthesizer *synth = piper_create(onnx_path.c_str(), json_path.c_str(), espeak_path);
    if (!synth) {
        std::cerr << "Error: Failed to load model or eSpeak-ng data.\n";
        return 1;
    }

    piper_synthesize_options options = piper_default_synthesize_options(synth);
    piper_synthesize_start(synth, input_text.c_str(), &options);

    // --- Output Handling ---
#ifdef ENABLE_PULSEAUDIO
    pa_simple *pa_stream = nullptr;
    if (play_audio) {
        static const pa_sample_spec ss = {
            .format = PA_SAMPLE_FLOAT32LE,
            .rate = 22050,
            .channels = 1
        };
        int error;
        pa_stream = pa_simple_new(NULL, "piper", PA_STREAM_PLAYBACK, NULL, "playback", &ss, NULL, NULL, &error);
        if (!pa_stream) {
            std::cerr << "Error: pa_simple_new() failed: " << pa_strerror(error) << "\n";
            piper_free(synth);
            return 1;
        }
    }
#endif

    std::ofstream file_stream;
    std::ostream* out_stream = nullptr;

    if (!play_audio) {
        if (output_to_stdout) {
            out_stream = &std::cout;
        } else if (use_file_output) {
            file_stream.open(output_file, std::ios::binary);
            if (!file_stream) {
                std::cerr << "Error: Failed to open output file: " << output_file << "\n";
                piper_free(synth);
                return 1;
            }
            out_stream = &file_stream;
        }
    }


    // Synthesis loop
    piper_audio_chunk chunk;
    while (piper_synthesize_next(synth, &chunk) != PIPER_DONE) {
        if (play_audio) {
#ifdef ENABLE_PULSEAUDIO
            int error;
            if (pa_simple_write(pa_stream, chunk.samples, chunk.num_samples * sizeof(float), &error) < 0) {
                std::cerr << "Error: pa_simple_write() failed: " << pa_strerror(error) << "\n";
                break;
            }
#endif
        } else if(out_stream) {
            out_stream->write(reinterpret_cast<const char *>(chunk.samples), chunk.num_samples * sizeof(float));
        }
    }

    // Cleanup
#ifdef ENABLE_PULSEAUDIO
    if (pa_stream) {
        int error;
        if (pa_simple_drain(pa_stream, &error) < 0) {
            std::cerr << "Error: pa_simple_drain() failed: " << pa_strerror(error) << "\n";
        }
        pa_simple_free(pa_stream);
    }
#endif

    piper_free(synth);
    return 0;
}

