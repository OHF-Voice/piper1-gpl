#include "wavfile.hpp"
#include "wav_headers.hpp"
#include <iostream>

void textToWavFile(piper::RunConfig &runConfig, piper_synthesizer *piper, piper_synthesize_options *options, const char *string, std::ostream &stream) {
    std::unique_ptr<piper_synthesize_options> default_options;
    if (!options) {
        default_options = std::make_unique<piper_synthesize_options>(
            piper_default_synthesize_options(piper));
        options = default_options.get();
    }

    // Speaker ID
    if (runConfig.speakerId) {
        options->speaker_id = runConfig.speakerId.value();
    }

    // Scales
    if (runConfig.noiseScale) {
        options->noise_scale = runConfig.noiseScale.value();
    }

    if (runConfig.lengthScale) {
        options->length_scale = runConfig.lengthScale.value();
    }

    if (runConfig.noiseW) {
        options->noise_w_scale = runConfig.noiseW.value();
    }

    piper_synthesize_start(piper,
                           string,
                           options /* NULL for defaults */);
    piper_audio_chunk chunk;
    bool isHeaderWritten = false;
    do {
        piper_synthesize_next(piper, &chunk);
        if (chunk.num_samples > 0) {
            if (!isHeaderWritten) {
                writeWavStreamHeader(stream, chunk.sample_rate);
                isHeaderWritten = true;
            }
            stream.write(reinterpret_cast<const char *>(chunk.samples),
                       chunk.num_samples * sizeof(float));
        }
    } while (!chunk.is_last);
}