#ifndef WAV_HEADERS_HPP
#define WAV_HEADERS_HPP

#include <cstdint>
#include <ostream>

void writeWavStreamHeader(std::ostream &stream, int sample_rate);

#endif // WAV_HEADERS_HPP