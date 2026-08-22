#ifndef PIPER_H_
#define PIPER_H_

#if defined(__has_include)
#if __has_include(<cuchar>)
#include <cuchar>
#endif
#if __has_include(<cstddef>)
#include <cstddef>
#else
#include <stdbool.h>
#endif
#endif

#if !defined(__cplusplus) && !defined(__char32_t_defined)
#include <stdint.h>
typedef uint32_t char32_t;
#define __char32_t_defined
#endif

#if !defined(__cplusplus)
#include <stddef.h>
#endif

#if defined(WIN32) && (defined(__GNUC__) || defined(_MSC_VER))
#if defined(BUILDING_LIBPIPER)
#define EXPORT_SYMBOL __declspec(dllexport)
#else
#define EXPORT_SYMBOL __declspec(dllimport)
#endif
#else
#define EXPORT_SYMBOL
#endif

#ifdef __cplusplus
extern "C"
{
#endif

#define PIPER_OK (0)
#define PIPER_DONE (1)
#define PIPER_ERR_GENERIC (-1)

  /**
   * \brief Text-to-speech synthesizer.
   */
  typedef struct piper_synthesizer piper_synthesizer;

  /**
   * \brief Chunk of synthesized audio samples.
   */
  typedef struct piper_audio_chunk
  {
    /**
     * \brief Raw samples returned from the voice model.
     */
    const float* samples;

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
     * \brief Phoneme codepoints that produced this audio chunk, aligned with
     * ids.
     *
     * Phonemes will look like [p1, p1, 0, p2, p2, 0, ...] where the same
     * phoneme codepoint is repeated for each id from that phoneme (usually just
     * one id plus pad).
     *
     * Groups of repeated codepoints are separated by a 0 so that alignments can
     * be attributed to the correct phoneme. This is accomplished by:
     *
     * 1. Read N (repeated) codepoints from phonemes until a 0 is reached (or
     * end)
     * 2. The next N phoneme ids correspond to that phoneme
     * 3. The next N alignments (sample counts) correspond to that phoneme
     * 4. Advance your iterators in the phoneme id and alignment arrays by N
     * 5. Repeat
     */
    const char32_t* phonemes;

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
    const int* phoneme_ids;

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
    const int* alignments;

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
  typedef struct piper_synthesize_options
  {
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
   * \brief Options for creating a synthesizer.
   *
   * This struct is versioned by struct_size. Set struct_size =
   * sizeof(piper_create_options) before passing to piper_create_with_options.
   * Future fields will be appended at the end and gated by struct_size.
   */
  typedef struct piper_create_options
  {
    /**
     * \brief Size of this struct in bytes, for versioning.
     */
    size_t struct_size;

    /**
     * \brief Path to ONNX voice model file.
     */
    const char* model_path;

    /**
     * \brief Path to JSON voice config file or NULL if it's model_path + .json
     */
    const char* config_path;

    /**
     * \brief Path to espeak-ng data directory, or NULL if not needed (text
     * phonemes).
     */
    const char* espeak_data_path;

    /**
     * \brief Path to g2pw / pinyin dictionary directory for pinyin, or NULL for
     * auto-discovery.
     *
     * Phase 1 (monophonic fallback) directory should contain
     * MONOPHONIC_CHARS.txt (118K) and/or char_bopomofo_dict.json and
     * bopomofo_to_pinyin_wo_tune_dict.json. g2pw.onnx and
     * POLYPHONIC_CHARS.txt are not required in Phase 1; they will be used in
     * Phase 2 for contextual polyphone disambiguation.
     *
     * Directory may be next to espeak data / data_dir, or be data_dir/g2pw or
     * data_dir itself.
     */
    const char* g2pw_model_dir;

    /**
     * \brief Optional root data directory that may contain espeak-ng-data/ and
     * g2pw/.
     *
     * If espeak_data_path or g2pw_model_dir is NULL, library will search inside
     * data_dir/espeak-ng-data and data_dir/g2pw / data_dir.
     */
    const char* data_dir;
  } piper_create_options;

  /**
   * \brief Initialize piper_create_options with defaults.
   *
   * Sets struct_size and nulls paths. Caller must fill model_path at least.
   */
  static inline void piper_init_create_options(piper_create_options* opts)
  {
    if (opts)
    {
      opts->struct_size = sizeof(piper_create_options);
      opts->model_path = NULL;
      opts->config_path = NULL;
      opts->espeak_data_path = NULL;
      opts->g2pw_model_dir = NULL;
      opts->data_dir = NULL;
    }
  }

  /**
   * \brief Create a Piper text-to-speech synthesizer from a voice model
   * (options version).
   *
   * \param options creation options, must have struct_size set.
   *
   * \return a Piper text-to-speech synthesizer for the voice model, or NULL on
   * failure.
   */
  EXPORT_SYMBOL
  piper_synthesizer* piper_create_with_options(
      const piper_create_options* options);

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
  piper_synthesizer* piper_create(const char* model_path,
                                  const char* config_path,
                                  const char* espeak_data_path);

  /**
   * \brief Free resources for Piper synthesizer.
   *
   * \param synth Piper synthesizer.
   */
  EXPORT_SYMBOL
  void piper_free(piper_synthesizer* synth);

  /**
   * \brief Get the default synthesis options for a Piper synthesizer.
   *
   * \param synth Piper synthesizer.
   *
   * \return synthesis options from voice config.
   */
  EXPORT_SYMBOL
  piper_synthesize_options piper_default_synthesize_options(
      piper_synthesizer* synth);

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
  int piper_synthesize_start(piper_synthesizer* synth, const char* text,
                             const piper_synthesize_options* options);

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
  int piper_synthesize_next(piper_synthesizer* synth, piper_audio_chunk* chunk);

  /**
   * \return piper version
   */
  EXPORT_SYMBOL
  char const* piper_version(void);

#ifdef __cplusplus
}
#endif

#endif  // PIPER_H_
