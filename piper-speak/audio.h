#include <cstddef>
void init_audio();
void play_audio(const float * in_data, size_t num_samples, float volume = 1.0);
void cleanup_audio();
void wait_for_audio_to_finish();
