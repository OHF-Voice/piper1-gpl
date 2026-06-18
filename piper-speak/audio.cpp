//we use pcaudiolib because it is espeak-ng's backing system
#include <cstddef>
#include <iostream>
#include <pcaudiolib/audio.h>
#include <cstdint>
#include <stdint.h>

static struct audio_object *my_audio = NULL;

constexpr uint32_t audio_rate = 22050;

void init_audio() {
    //create the audio device
    my_audio = create_audio_device_object(nullptr, "piper-speak", "text-to-speech");
    int error = audio_object_open(my_audio, AUDIO_OBJECT_FORMAT_S16LE, audio_rate, 1);
    if (error != 0) {
        std::cout << "failed to open device because "
            << audio_object_strerror(my_audio, error) << "\n";
        exit(1);
    }
}

void play_audio(const float * in_data, size_t num_samples, float volume) {
    //convert to signed 16bit intergers
    int16_t cast_data[num_samples];
    for (size_t i = 0; i < num_samples; ++i) {
        cast_data[i] = static_cast<int16_t>(in_data[i] * float{INT16_MAX});
    }
    //we convert to 16bit integers because that is what espeak-ng uses with pcaudiolib
    //so it is presumably widely supported
    //this code assumes we are on a little endian machine, but I believe all PC's
    //are currently little endian, so it is a fine assumption for now.
    //if it is ported to a IBM mainframe then perhaps we will need to change it 

    //actually play audio
    int error = audio_object_write(my_audio, cast_data, sizeof(cast_data));
    if (error != 0) {
        std::cout << "failed to play audio because "
            <<  audio_object_strerror(my_audio, error) << "\n";
        exit(1);
    }
}

void wait_for_audio_to_finish() {
    int error = audio_object_drain(my_audio);
    if (error != 0) {
        std::cout << "failed to wait for audio to play because "
            <<  audio_object_strerror(my_audio, error) << "\n";
        exit(1);
    }
}

void cleanup_audio() {
    audio_object_close(my_audio); 
    audio_object_destroy(my_audio); //frees my_audio 
}
