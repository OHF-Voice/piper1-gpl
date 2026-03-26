#pragma once
#include <filesystem>

#if WIN32
/**
 * Determines if the application is running from Wine.
 * @return True when running Wine.
 */
bool isWine();
#endif

/**
 * Determines if the application is running in Docker
 * @return True when running Wine.
 */
bool isDocker();

/**
 * Gets the path to a dynamic library containing the given function.
 * @param func A pointer to a function in the library.
 * @return Path to the library.
 */
std::filesystem::path getLibraryPath(void *func = nullptr);

/**
 * Gets the path to the current executable.
 * @return Executable path.
 */
std::filesystem::path getExecutablePath();

/**
 * Writes a 32-bit IEEE Float mono WAV header.
 * @param sample_rate Frequency in Hz (e.g., 22050)
 * @param number_of_samples Total count of audio samples
 * @param os Output stream to write the header into
 */
void writeWavHeader(int sample_rate,
                    uint32_t number_of_samples,
                    std::ostream &os);
