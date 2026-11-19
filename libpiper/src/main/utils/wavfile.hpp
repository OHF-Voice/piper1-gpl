#ifndef WAVFILE_H_
#define WAVFILE_H_

#include "piper.h"
#include <ostream>

void textToWavFile(piper_synthesizer *piper, piper_synthesize_options *options,
                   const char *string, std::ostream &stream);

#endif // WAVFILE_H_
