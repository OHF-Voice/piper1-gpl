#ifndef WAVFILE_H_
#define WAVFILE_H_

#include "piper.h"
#include <fstream>

void textToWavFile(piper_synthesizer *piper, piper_synthesize_options options, const char *string, std::ostream &file);

#endif // WAVFILE_H_