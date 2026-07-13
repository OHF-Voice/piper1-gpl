#include "wavfile.hpp"
#include "wav_headers.hpp"
#include <iostream>

void textToWavFile(piper_synthesizer *piper,
                   piper_synthesize_options *options,
                   const char *string,
                   std::ostream &stream) {
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