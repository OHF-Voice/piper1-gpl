#include "wav_headers.hpp"

namespace
{
    template <typename T>
    void writeNumber(T num, std::ostream &stream)
    {
        stream.write(reinterpret_cast<char *>(&num), sizeof(num));
    }
} // namespace

void writeWavStreamHeader(std::ostream &stream, int sample_rate)
{
    const std::size_t unspec_count = 0x7ffff000;

    // ChunkID
    stream.write("RIFF", 4);
    // ChunkSize = 36 + Subchunk2Size
    writeNumber<uint32_t>(unspec_count + 36, stream);
    // Format
    stream.write("WAVE", 4);

    // Subchunk1ID
    stream.write("fmt ", 4);
    // Subchunk1Size = 16 for PCM/IEEE_FLOAT
    writeNumber<uint32_t>(16, stream);
    // AudioFormat = 3 (IEEE float)
    writeNumber<uint16_t>(3, stream);
    // NumChannels = 1 (mono)
    writeNumber<uint16_t>(1, stream);
    // SampleRate
    writeNumber<uint32_t>(sample_rate, stream);
    // ByteRate = SampleRate * NumChannels * BitsPerSample/8
    writeNumber<uint32_t>(sample_rate * 4, stream);
    // BlockAlign = NumChannels * BitsPerSample/8
    writeNumber<uint16_t>(4, stream);
    // BitsPerSample = 32
    writeNumber<uint16_t>(32, stream);

    // Subchunk2ID
    stream.write("data", 4);
    // Subchunk2Size = NumSamples * NumChannels * BitsPerSample/8
    writeNumber<uint32_t>(unspec_count, stream);
}