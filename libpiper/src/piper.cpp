#define BUILDING_LIBPIPER
#include "piper.h"
#include "piper_impl.hpp"

#include <array>
#include <fstream>
#include <limits>

#if defined(WIN32)
#include <windows.h>
#ifdef min
#undef min
#endif
#ifdef max
#undef max
#endif
#endif

#if defined (_MSC_VER) // MSVC compile of espeak gives a STATIC library.
// tell espeak-ng/speak_lib.h to use unadorned entry points
#if defined (_WIN32)
#undef _WIN32
#endif
#if defined (_WIN64)
#undef _WIN64
#endif
#endif


#include <espeak-ng/speak_lib.h>

using json = nlohmann::json;

struct piper_synthesizer *piper_create(const char *model_path,
                                       const char *config_path,
                                       const char *espeak_data_path) {
    // onnx
    static Ort::Env ort_env{ ORT_LOGGING_LEVEL_WARNING, "piper" };

    if (!model_path) {
        return nullptr;
    }

    std::string config_path_str;
    if (!config_path) {
        std::string model_path_str(model_path);
        config_path_str = model_path_str + ".json";
    } else {
        config_path_str = config_path;
    }

    std::ifstream config_stream(config_path_str);
    auto config = json::parse(config_stream);

    if (espeak_Initialize(AUDIO_OUTPUT_SYNCHRONOUS, 0, espeak_data_path, 0) <
        0) {
        return nullptr;
    }

    piper_synthesizer *synth = new piper_synthesizer();

    // Load config options
    synth->espeak_voice = "en-us"; // default
    if (config.contains("espeak")) {
        auto &espeak_obj = config["espeak"];
        if (espeak_obj.contains("voice")) {
            synth->espeak_voice = espeak_obj["voice"].get<std::string>();
        }
    }

    if (config.contains("audio")) {
        auto &audio_obj = config["audio"];
        if (audio_obj.contains("sample_rate")) {
            // Sample rate of generated audio in hertz
            synth->sample_rate = audio_obj["sample_rate"].get<int>();
        }
    }

    // phoneme to [id] map
    // Maps phonemes to one or more phoneme ids (required).
    if (config.contains("phoneme_id_map")) {
        auto &phoneme_id_map_value = config["phoneme_id_map"];
        for (auto &from_phoneme_item : phoneme_id_map_value.items()) {
            std::string from_phoneme = from_phoneme_item.key();
            auto from_codepoint = get_codepoint(from_phoneme);
            if (!from_codepoint) {
                // No codepoint
                continue;
            }

            for (auto &to_id_value : from_phoneme_item.value()) {
                PhonemeId to_id = to_id_value.get<PhonemeId>();
                synth->phoneme_id_map[*from_codepoint].push_back(to_id);
            }
        }
    }

    synth->num_speakers = config["num_speakers"].get<SpeakerId>();

    if (config.contains("inference")) {
        // Overrides default inference settings
        auto inference_value = config["inference"];
        if (inference_value.contains("noise_scale")) {
            synth->synth_noise_scale =
                inference_value["noise_scale"].get<float>();
        }

        if (inference_value.contains("length_scale")) {
            synth->synth_length_scale =
                inference_value["length_scale"].get<float>();
        }

        if (inference_value.contains("noise_w")) {
            synth->synth_noise_w_scale =
                inference_value["noise_w"].get<float>();
        }
    }

    // Load onnx model
    synth->session_options.DisableCpuMemArena();
    synth->session_options.DisableMemPattern();
    synth->session_options.DisableProfiling();

    auto sz = ::MultiByteToWideChar(CP_ACP, 0, model_path, -1, 0,0);
    std::vector<wchar_t> model_path_wc(sz+1);
    ::MultiByteToWideChar(CP_ACP, 0, model_path, -1, &model_path_wc[0], sz);
    synth->session = std::make_unique<Ort::Session>(
        Ort::Session(ort_env, &model_path_wc[0], synth->session_options));

    return synth;
}

void piper_free(struct piper_synthesizer *synth) {
    espeak_Terminate();

    if (!synth) {
        return;
    }

    delete synth;
}

piper_synthesize_options
piper_default_synthesize_options(piper_synthesizer *synth) {
    piper_synthesize_options options;
    options.speaker_id = 0;
    options.length_scale = DEFAULT_LENGTH_SCALE;
    options.noise_scale = DEFAULT_NOISE_SCALE;
    options.noise_w_scale = DEFAULT_NOISE_W_SCALE;

    if (synth) {
        options.length_scale = synth->synth_length_scale;
        options.noise_scale = synth->synth_noise_scale;
        options.noise_w_scale = synth->synth_noise_w_scale;
    }

    return options;
}

int piper_synthesize_start(struct piper_synthesizer *synth, const char *text,
                           const piper_synthesize_options *options) {
    if (!synth) {
        return PIPER_ERR_GENERIC;
    }

    if (espeak_SetVoiceByName(synth->espeak_voice.c_str()) != EE_OK) {
        return PIPER_ERR_GENERIC;
    }

    // Clear state
    while (!synth->phoneme_id_queue.empty()) {
        synth->phoneme_id_queue.pop();
    }
    synth->chunk_samples.clear();

    std::unique_ptr<piper_synthesize_options> default_options;
    if (!options) {
        default_options = std::make_unique<piper_synthesize_options>(
            piper_default_synthesize_options(synth));
        options = default_options.get();
    }

    synth->length_scale = options->length_scale;
    synth->noise_scale = options->noise_scale;
    synth->noise_w_scale = options->noise_w_scale;
    synth->speaker_id = options->speaker_id;

    // phonemize
    std::vector<std::string> sentence_phonemes{""};
    std::size_t current_idx = 0;
    const void *text_ptr = text;
    while (text_ptr != nullptr) {
        int terminator = 0;
        std::string terminator_str = "";

        const char *phonemes = espeak_TextToPhonemesWithTerminator(
            &text_ptr, espeakCHARS_AUTO, espeakPHONEMES_IPA, &terminator);

        if (phonemes) {
            sentence_phonemes[current_idx] += phonemes;
        }

        // Categorize terminator
        terminator &= 0x000FFFFF;

        if (terminator == CLAUSE_PERIOD) {
            terminator_str = ".";
        } else if (terminator == CLAUSE_QUESTION) {
            terminator_str = "?";
        } else if (terminator == CLAUSE_EXCLAMATION) {
            terminator_str = "!";
        } else if (terminator == CLAUSE_COMMA) {
            terminator_str = ", ";
        } else if (terminator == CLAUSE_COLON) {
            terminator_str = ": ";
        } else if (terminator == CLAUSE_SEMICOLON) {
            terminator_str = "; ";
        }

        sentence_phonemes[current_idx] += terminator_str;

        if ((terminator & CLAUSE_TYPE_SENTENCE) == CLAUSE_TYPE_SENTENCE) {
            sentence_phonemes.push_back("");
            current_idx = sentence_phonemes.size() - 1;
        }
    }

    // phonemes to ids
    std::vector<Phoneme> sentence_codepoints;
    std::vector<PhonemeId> sentence_ids;
    for (auto &phonemes_str : sentence_phonemes) {
        if (phonemes_str.empty()) {
            continue;
        }

        sentence_codepoints.push_back(PHONEME_BOS);
        sentence_ids.push_back(ID_BOS);

        sentence_codepoints.push_back(PHONEME_BOS);
        sentence_ids.push_back(ID_PAD);

        sentence_codepoints.push_back(PHONEME_SEPARATOR);

        auto phonemes_norm = una::norm::to_nfd_utf8(phonemes_str);
        auto phonemes_range = una::ranges::utf8_view{phonemes_norm};
        auto phonemes_iter = phonemes_range.begin();
        auto phonemes_end = phonemes_range.end();

        // Filter out (lang) switch (flags).
        // These surround words from languages other than the current voice.
        bool in_lang_flag = false;
        while (phonemes_iter != phonemes_end) {
            auto phoneme = *phonemes_iter;

            if (in_lang_flag) {
                if (phoneme == U')') {
                    // End of (lang) switch
                    in_lang_flag = false;
                }
            } else if (phoneme == U'(') {
                // Start of (lang) switch
                in_lang_flag = true;
            } else {
                // Look up ids
                auto ids_for_phoneme = synth->phoneme_id_map.find(phoneme);
                if (ids_for_phoneme != synth->phoneme_id_map.end()) {
                    for (auto id : ids_for_phoneme->second) {
                        sentence_codepoints.push_back(phoneme);
                        sentence_ids.push_back(id);

                        sentence_codepoints.push_back(phoneme);
                        sentence_ids.push_back(ID_PAD);

                        sentence_codepoints.push_back(PHONEME_SEPARATOR);
                    }
                }
            }

            phonemes_iter++;
        }

        sentence_codepoints.push_back(PHONEME_EOS);
        sentence_ids.push_back(ID_EOS);
        sentence_codepoints.push_back(PHONEME_SEPARATOR);

        synth->phoneme_id_queue.emplace(
            std::move(std::make_pair(sentence_codepoints, sentence_ids)));
        sentence_ids.clear();
    }

    return PIPER_OK;
}

int piper_synthesize_next(struct piper_synthesizer *synth,
                          struct piper_audio_chunk *chunk) {
    if (!synth) {
        return PIPER_ERR_GENERIC;
    }

    if (!chunk) {
        return PIPER_ERR_GENERIC;
    }

    // Clear data from previous call
    synth->chunk_samples.clear();
    synth->chunk_phonemes.clear();
    synth->chunk_phoneme_ids.clear();
    synth->chunk_alignments.clear();

    chunk->sample_rate = synth->sample_rate;
    chunk->samples = nullptr;
    chunk->num_samples = 0;
    chunk->is_last = false;
    chunk->phoneme_ids = nullptr;
    chunk->num_phoneme_ids = 0;
    chunk->alignments = nullptr;
    chunk->num_alignments = 0;

    if (synth->phoneme_id_queue.empty()) {
        // Empty final chunk
        chunk->is_last = true;
        return PIPER_DONE;
    }

    // Process next list of phoneme ids
    auto [next_phonemes, next_ids] = std::move(synth->phoneme_id_queue.front());
    synth->phoneme_id_queue.pop();

    auto memoryInfo = Ort::MemoryInfo::CreateCpu(
        OrtAllocatorType::OrtArenaAllocator, OrtMemType::OrtMemTypeDefault);

    // Allocate
    std::vector<int64_t> phoneme_id_lengths{(int64_t)next_ids.size()};
    std::vector<float> scales{synth->noise_scale, synth->length_scale,
                              synth->noise_w_scale};

    std::vector<Ort::Value> input_tensors;
    std::vector<int64_t> phoneme_ids_shape{1, (int64_t)next_ids.size()};
    input_tensors.push_back(Ort::Value::CreateTensor<int64_t>(
        memoryInfo, next_ids.data(), next_ids.size(), phoneme_ids_shape.data(),
        phoneme_ids_shape.size()));

    std::vector<int64_t> phoneme_id_lengths_shape{
        (int64_t)phoneme_id_lengths.size()};
    input_tensors.push_back(Ort::Value::CreateTensor<int64_t>(
        memoryInfo, phoneme_id_lengths.data(), phoneme_id_lengths.size(),
        phoneme_id_lengths_shape.data(), phoneme_id_lengths_shape.size()));

    std::vector<int64_t> scales_shape{(int64_t)scales.size()};
    input_tensors.push_back(Ort::Value::CreateTensor<float>(
        memoryInfo, scales.data(), scales.size(), scales_shape.data(),
        scales_shape.size()));

    // Add speaker id.
    // NOTE: These must be kept outside the "if" below to avoid being
    // deallocated.
    std::vector<int64_t> speaker_id{(int64_t)synth->speaker_id};
    std::vector<int64_t> speaker_id_shape{(int64_t)speaker_id.size()};

    if (synth->num_speakers > 1) {
        input_tensors.push_back(Ort::Value::CreateTensor<int64_t>(
            memoryInfo, speaker_id.data(), speaker_id.size(),
            speaker_id_shape.data(), speaker_id_shape.size()));
    }

    // From export_onnx.py
    std::array<const char *, 4> input_names = {"input", "input_lengths",
                                               "scales", "sid"};

    // Get all output names
    std::vector<std::string> output_names_strs =
        synth->session->GetOutputNames();
    std::vector<const char *> output_names;
    for (const auto &name : output_names_strs) {
        output_names.push_back(name.c_str());
    }

    // Infer
    auto output_tensors = synth->session->Run(
        Ort::RunOptions{nullptr}, input_names.data(), input_tensors.data(),
        input_tensors.size(), output_names.data(), output_names.size());

    if ((output_tensors.size() < 1) || (!output_tensors.front().IsTensor())) {
        return PIPER_ERR_GENERIC;
    }

    auto audio_shape =
        output_tensors.front().GetTensorTypeAndShapeInfo().GetShape();
    chunk->num_samples = audio_shape[audio_shape.size() - 1];

    const float *audio_tensor_data =
        output_tensors.front().GetTensorData<float>();
    synth->chunk_samples.resize(chunk->num_samples);
    std::copy(audio_tensor_data, audio_tensor_data + chunk->num_samples,
              synth->chunk_samples.begin());
    chunk->samples = synth->chunk_samples.data();

    chunk->is_last = synth->phoneme_id_queue.empty();

    // Copy phonemes
    synth->chunk_phonemes = std::move(next_phonemes);
    chunk->phonemes = synth->chunk_phonemes.data();
    chunk->num_phonemes = synth->chunk_phonemes.size();

    // Copy phoneme ids
    for (auto phoneme_id : next_ids) {
        if (phoneme_id < std::numeric_limits<int>::min() ||
            phoneme_id > std::numeric_limits<int>::max()) {
            continue;
        }
        synth->chunk_phoneme_ids.push_back(static_cast<int>(phoneme_id));
    }

    chunk->phoneme_ids = synth->chunk_phoneme_ids.data();
    chunk->num_phoneme_ids = synth->chunk_phoneme_ids.size();

    // Check for alignments
    if (output_tensors.size() > 1) {
        auto alignments_shape =
            output_tensors[1].GetTensorTypeAndShapeInfo().GetShape();

        chunk->num_alignments = alignments_shape[alignments_shape.size() - 1];
        const float *alignments_tensor_data =
            output_tensors[1].GetTensorData<float>();

        synth->chunk_alignments.resize(chunk->num_alignments);
        for (std::size_t i = 0; i < chunk->num_alignments; i++) {
            synth->chunk_alignments[i] =
                (int)(alignments_tensor_data[i] * synth->hop_length);
        }

        chunk->alignments = synth->chunk_alignments.data();
    }

    // Clean up
    for (std::size_t i = 0; i < output_tensors.size(); i++) {
        Ort::detail::OrtRelease(output_tensors[i].release());
    }

    for (std::size_t i = 0; i < input_tensors.size(); i++) {
        Ort::detail::OrtRelease(input_tensors[i].release());
    }

    return PIPER_OK;
}
