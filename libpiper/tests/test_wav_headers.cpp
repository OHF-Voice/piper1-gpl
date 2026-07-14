#include <gtest/gtest.h>
#include <cstdint>
#include <sstream>
#include <vector>

#include "utils/wav_headers.hpp"

namespace {
// Helper to write little-endian values to a vector for comparison
template <typename T>
void pushLittleEndian(std::vector<char> &vec, T val) {
  for (size_t i = 0; i < sizeof(T); ++i) {
    vec.push_back((val >> (i * 8)) & 0xFF);
  }
}
} // namespace

TEST(WavHeadersTest, WriteWavStreamHeader) {
  std::stringstream ss;
  const int sampleRate = 22050;

  writeWavStreamHeader(ss, sampleRate);

  std::string headerStr = ss.str();
  ASSERT_EQ(headerStr.length(), 44);

  std::vector<char> expectedHeader;
  expectedHeader.insert(expectedHeader.end(), {'R', 'I', 'F', 'F'});
  pushLittleEndian<uint32_t>(expectedHeader, 0x7ffff000 + 36);
  expectedHeader.insert(expectedHeader.end(), {'W', 'A', 'V', 'E'});
  expectedHeader.insert(expectedHeader.end(), {'f', 'm', 't', ' '});
  pushLittleEndian<uint32_t>(expectedHeader, 16);
  pushLittleEndian<uint16_t>(expectedHeader, 3);    // IEEE float
  pushLittleEndian<uint16_t>(expectedHeader, 1);    // mono
  pushLittleEndian<uint32_t>(expectedHeader, sampleRate);
  pushLittleEndian<uint32_t>(expectedHeader, sampleRate * 4); // ByteRate
  pushLittleEndian<uint16_t>(expectedHeader, 4);    // BlockAlign
  pushLittleEndian<uint16_t>(expectedHeader, 32);   // BitsPerSample
  expectedHeader.insert(expectedHeader.end(), {'d', 'a', 't', 'a'});
  pushLittleEndian<uint32_t>(expectedHeader, 0x7ffff000);

  EXPECT_EQ(std::vector<char>(headerStr.begin(), headerStr.end()), expectedHeader);
}