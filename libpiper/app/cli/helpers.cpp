#include <iostream>

#include "json.hpp"
#if WIN32
#if __MINGW32__
#include <windows.h>
#else
#include <Windows.h>
#endif
#else
#include <dlfcn.h>
#include <linux/limits.h>
#include <unistd.h>
#endif

#ifdef _MSC_VER
#define PACKED_STRUCT(name) __pragma(pack(push, 1)) struct name
#define PACKED_STRUCT_END __pragma(pack(pop))
#elif defined(__GNUC__) || defined(__clang__)
#define PACKED_STRUCT(name) struct __attribute__((packed)) name
#define PACKED_STRUCT_END
#else
#define PACKED_STRUCT(name) struct name
#define PACKED_STRUCT_END
#endif

#if WIN32
bool isWine() {
    const auto handle = ::GetModuleHandleA("ntdll.dll");
    if (handle) {
        const auto address = ::GetProcAddress(handle, "wine_get_version");
        return address ? true : false;
    }
    return false;
}

#endif

bool isDocker() {
#if WIN32
    return std::filesystem::exists(std::filesystem::path("Z:") / ".dockerenv");
#else
    return std::filesystem::exists(std::filesystem::path("/") / ".dockerenv");
#endif
}

std::filesystem::path getLibraryPath(void *func = nullptr) {
    if (!func)
        func = reinterpret_cast<void *>(getLibraryPath);
#if WIN32
    HMODULE handle = nullptr;
    // Get the handle for the module containing this function address
    if (func &&
        ::GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                                 GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                             static_cast<LPCSTR>(func),
                             &handle)) {
        std::string rv(MAX_PATH, '\0');
        rv.resize(::GetModuleFileNameA(handle, rv.data(), rv.capacity()));
        return rv;
    }
    return {};
#else
    Dl_info dl_info;
    // Pass the address of any function in the target library
    if (func && ::dladdr(func, &dl_info) && dl_info.dli_fname)
        return dl_info.dli_fname;
    return {};
#endif
}

std::filesystem::path getExecutablePath() {
#if WIN32
    std::string rv(MAX_PATH, '\0');
    rv.resize(::GetModuleFileNameA(nullptr, rv.data(), rv.capacity()));
    return rv;
#else
    std::string rv(PATH_MAX, '\0');
    rv.resize(readlink("/proc/self/exe", rv.data(), rv.capacity()));
    return rv;
#endif
}

PACKED_STRUCT(Header) {
    // RIFF Chunk
    uint8_t RIFF[4] = {'R', 'I', 'F', 'F'};
    uint32_t chunkSize;
    uint8_t WAVE[4] = {'W', 'A', 'V', 'E'};
    // fmt Chunk
    uint8_t fmt[4] = {'f', 'm', 't', ' '};
    // Changed from 16 to 18
    uint32_t fmtSize = 18;
    // IEEE Float
    uint16_t audioFormat = 3;
    uint16_t numChannels;
    uint32_t sampleRate;
    uint32_t bytesPerSec;
    uint16_t blockAlign;
    uint16_t bitsPerSample;
    // NEW: Extra 2 bytes required for non-PCM
    uint16_t extensionSize = 0;
    // data Chunk
    uint8_t data[4] = {'d', 'a', 't', 'a'};
    uint32_t dataSize;
}
PACKED_STRUCT_END;

void writeWavHeader(int sample_rate,
                    uint32_t number_of_samples,
                    std::ostream &os) {
    Header header;
    //
    const uint16_t channels = 1;
    // IEEE Float is 32-bit
    const uint16_t bits_per_sample = 32;
    //
    header.numChannels = channels;
    header.sampleRate = static_cast<uint32_t>(sample_rate);
    header.bitsPerSample = bits_per_sample;
    // Calculation: Channels * (BitsPerSample / 8)
    header.blockAlign = channels * (bits_per_sample / 8);
    // Calculation: SampleRate * BlockAlign
    header.bytesPerSec = header.sampleRate * header.blockAlign;
    // Calculation: NumberOfSamples * BlockAlign
    header.dataSize = number_of_samples * header.blockAlign;
    // Calculation: 36 + dataSize (Total size - 8 bytes for RIFF ID and Size)
    header.chunkSize = 36 + header.dataSize;
    //
    os.write(reinterpret_cast<const char *>(&header), sizeof(Header));
}
