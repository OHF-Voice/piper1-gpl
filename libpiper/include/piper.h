#ifndef PIPER_H_
#define PIPER_H_

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <uchar.h>

#if defined(_MSC_VER)
#if defined(BUILDING_LIBPIPER)
#define EXPORT_SYMBOL __declspec( dllexport )
#else
#define EXPORT_SYMBOL __declspec( dllimport )
#endif
#else
#define EXPORT_SYMBOL
#endif

#ifdef __cplusplus
extern "C" {
#endif

#define PIPER_OK 0
#define PIPER_DONE 1
#define PIPER_ERR_GENERIC -1

/**
 * \brief Text-to-speech synthesizer.
 */
typedef struct piper_synthesizer piper_synthesizer;

/**
 * \brief Chunk of synthesized audio samples.
 */
typedef struct piper_audio_chunk {
  /**
   * \brief Raw samples returned from the voice model.
   */
  const float *samples;

  /**
   * \brief Number of samples in the audio chunk.
   */
  size_t num_samples;

  /**
   * \brief Sample rate in Hertz.
   */
  int sample_rate;

  /**
   * \brief True if this is the last audio chunk.
   */
  bool is_last;

  /**
   * \brief Phoneme codepoints that produced this audio chunk, aligned with ids.
   *
   * Phonemes will look like [p1, p1, 0, p2, p2, 0, ...] where the same phoneme
   * codepoint is repeated for each id from that phoneme (usually just one id
   * plus pad).
   *
   * Groups of repeated codepoints are separated by a 0 so that alignments can
   * be attributed to the correct phoneme. This is accomplished by:
   *
   * 1. Read N (repeated) codepoints from phonemes until a 0 is reached (or end)
   * 2. The next N phoneme ids correspond to that phoneme
   * 3. The next N alignments (sample counts) correspond to that phoneme
   * 4. Advance your iterators in the phoneme id and alignment arrays by N
   * 5. Repeat
   */
  const char32_t *phonemes;

  /**
   * \brief Number of codepoints in phonemes.
   */
  size_t num_phonemes;

  /**
   * \brief Phoneme ids that produced this audio chunk.
   *
   * Ids will look like [1, 0, id1, 0, id2, 0, ..., 2] where:
   * 0 = pad
   * 1 = beginning of sentence
   * 2 = end of sentence
   */
  const int *phoneme_ids;

  /**
   * \brief Number of ids in phoneme_ids.
   */
  size_t num_phoneme_ids;

  /**
   * \brief Audio sample count for each phoneme id.
   *
   * This includes the meta ids:
   * 0 = pad
   * 1 = beginning of sentence
   * 2 = end of sentence
   *
   * Use the phonemes array to align these sample counts with actual phonemes.
   */
  const int *alignments;

  /**
   * \brief Number of alignments.
   *
   * This should be the same as num_phoneme_ids.
   */
  size_t num_alignments;
} piper_audio_chunk;

/**
 * \brief Options for synthesis.
 *
 * \sa \ref piper_default_synthesize_options
 */
typedef struct piper_synthesize_options {
  /**
   * \brief Id of speaker to use (multi-speaker models only).
   *
   * Id 0 is the first speaker.
   */
  int speaker_id;

  /**
   * \brief How fast the text is spoken.
   *
   * A length scale of 0.5 means to speak twice as fast.
   * A length scale of 2.0 means to speak twice as slow.
   * The default is 1.0.
   */
  float length_scale;

  /**
   * \brief Controls how much noise is added during synthesis.
   *
   * The best value depends on the voice.
   * For single speaker models, a value of 0.667 is usually good.
   * For multi-speaker models, a value of 0.333 is usually good.
   */
  float noise_scale;

  /**
   * \brief Controls how much phonemes vary in length during synthesis.
   *
   * The best value depends on the voice.
   * For single speaker models, a value of 0.8 is usually good.
   * For multi-speaker models, a value of 0.333 is usually good.
   */
  float noise_w_scale;
} piper_synthesize_options;

/**
 * \brief Create a Piper text-to-speech synthesizer from a voice model.
 *
 * \param model_path path to ONNX voice model file.
 *
 * \param config_path path to JSON voice config file or NULL if it's the
 * model_path + .json.
 *
 * \param espeak_data_path path to the espeak-ng data
 * directory.
 *
 * \return a Piper text-to-speech synthesizer for the voice model.
 */
EXPORT_SYMBOL
piper_synthesizer *piper_create(const char *model_path, const char *config_path,
                                const char *espeak_data_path);

/**
 * \brief Free resources for Piper synthesizer.
 *
 * \param synth Piper synthesizer.
 */
EXPORT_SYMBOL
void piper_free(piper_synthesizer *synth);

/**
 * \brief Get the default synthesis options for a Piper synthesizer.
 *
 * \param synth Piper synthesizer.
 *
 * \return synthesis options from voice config.
 */
EXPORT_SYMBOL
piper_synthesize_options
piper_default_synthesize_options(piper_synthesizer *synth);

/**
 * \brief Start text-to-speech synthesis.
 *
 * \param synth Piper synthesizer.
 *
 * \param text text to synthesize into audio.
 *
 * \param options synthesis options or NULL for defaults.
 *
 * \sa \ref piper_synthesize_next
 *
 * \return PIPER_OK or error code.
 */
EXPORT_SYMBOL
int piper_synthesize_start(piper_synthesizer *synth, const char *text,
                           const piper_synthesize_options *options);

/**
 * \brief Synthesize next chunk of audio.
 *
 * \param synth Piper synthesizer.
 *
 * \param chunk audio chunk to fill.
 *
 * piper_synthesize_start must be called before this function.
 * Each call to piper_synthesize_next will fill the audio chunk, invalidating
 * the memory of the previous chunk.
 * The final audio chunk will have is_last = true.
 * A return value of PIPER_DONE indicates that synthesis is complete.
 *
 * \sa \ref piper_synthesize_start
 *
 * \return PIPER_DONE when complete, otherwise PIPER_OK or error code.
 */
EXPORT_SYMBOL
int piper_synthesize_next(piper_synthesizer *synth, piper_audio_chunk *chunk);

#ifdef __cplusplus
}
#endif

#endif // PIPER_H_
