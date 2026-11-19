// Partially written by ChatGPT 2025-Jul-09

#define Py_LIMITED_API 0x03090000
#include <Python.h>
#include <espeak-ng/speak_lib.h>
#include <stdlib.h>
#include <string.h>

#define CLAUSE_INTONATION_FULL_STOP 0x00000000
#define CLAUSE_INTONATION_COMMA 0x00001000
#define CLAUSE_INTONATION_QUESTION 0x00002000
#define CLAUSE_INTONATION_EXCLAMATION 0x00003000

#define CLAUSE_TYPE_CLAUSE 0x00040000
#define CLAUSE_TYPE_SENTENCE 0x00080000

#define CLAUSE_PERIOD (40 | CLAUSE_INTONATION_FULL_STOP | CLAUSE_TYPE_SENTENCE)
#define CLAUSE_COMMA (20 | CLAUSE_INTONATION_COMMA | CLAUSE_TYPE_CLAUSE)
#define CLAUSE_QUESTION (40 | CLAUSE_INTONATION_QUESTION | CLAUSE_TYPE_SENTENCE)
#define CLAUSE_EXCLAMATION                                                     \
    (45 | CLAUSE_INTONATION_EXCLAMATION | CLAUSE_TYPE_SENTENCE)
#define CLAUSE_COLON (30 | CLAUSE_INTONATION_FULL_STOP | CLAUSE_TYPE_CLAUSE)
#define CLAUSE_SEMICOLON (30 | CLAUSE_INTONATION_COMMA | CLAUSE_TYPE_CLAUSE)

// Data directory espeak-ng was initialized with, or NULL before the first
// initialize(). Guarded by the GIL, which every call here holds.
static char *initialized_data_dir = NULL;

static PyObject *py_initialize(PyObject *self, PyObject *args) {
    const char *data_dir;
    if (!PyArg_ParseTuple(args, "s", &data_dir)) {
        return NULL;
    }

    // espeak_Initialize must not run twice. A second call frees and reloads
    // the phoneme tables while the current voice still points into the old
    // ones, so the next get_phonemes() reads freed memory. Every
    // EspeakPhonemizer() calls this, so initialize once per data directory,
    // and tear the old state down before switching to another.
    if (initialized_data_dir != NULL) {
        if (strcmp(initialized_data_dir, data_dir) == 0) {
            Py_RETURN_NONE;
        }

        espeak_Terminate();
        free(initialized_data_dir);
        initialized_data_dir = NULL;
    }

    size_t data_dir_size = strlen(data_dir) + 1;
    char *data_dir_copy = malloc(data_dir_size);
    if (data_dir_copy == NULL) {
        return PyErr_NoMemory();
    }
    memcpy(data_dir_copy, data_dir, data_dir_size);

    if (espeak_Initialize(AUDIO_OUTPUT_SYNCHRONOUS, 0, data_dir, 0) < 0) {
        free(data_dir_copy);
        PyErr_SetString(PyExc_RuntimeError, "Failed to initialize espeak-ng");
        return NULL;
    }

    initialized_data_dir = data_dir_copy;
    Py_RETURN_NONE;
}

static PyObject *py_set_voice(PyObject *self, PyObject *args) {
    const char *voice;
    if (!PyArg_ParseTuple(args, "s", &voice)) {
        return NULL;
    }

    if (espeak_SetVoiceByName(voice) != EE_OK) {
        PyErr_Format(PyExc_RuntimeError, "Failed to set voice: %s", voice);
        return NULL;
    }

    Py_RETURN_NONE;
}

static PyObject *py_get_phonemes(PyObject *self, PyObject *args) {
    const char *text;
    if (!PyArg_ParseTuple(args, "s", &text)) {
        return NULL;
    }

    PyObject *phonemes_and_terminators = PyList_New(0);

    while (text != NULL) {
        int terminator = 0;
        char *terminator_str = "";

        const char *phonemes = espeak_TextToPhonemesWithTerminator(
            (const void **)&text, espeakCHARS_AUTO, espeakPHONEMES_IPA,
            &terminator);

        // Categorize terminator
        terminator &= 0x000FFFFF;

        if (terminator == CLAUSE_PERIOD) {
            terminator_str = ".";
        } else if (terminator == CLAUSE_QUESTION) {
            terminator_str = "?";
        } else if (terminator == CLAUSE_EXCLAMATION) {
            terminator_str = "!";
        } else if (terminator == CLAUSE_COMMA) {
            terminator_str = ",";
        } else if (terminator == CLAUSE_COLON) {
            terminator_str = ":";
        } else if (terminator == CLAUSE_SEMICOLON) {
            terminator_str = ";";
        }

        PyList_Append(phonemes_and_terminators,
                      Py_BuildValue("(ssO)", phonemes, terminator_str,
                                    (terminator & CLAUSE_TYPE_SENTENCE) ==
                                            CLAUSE_TYPE_SENTENCE
                                        ? Py_True
                                        : Py_False));
    }

    return phonemes_and_terminators;
}

static PyMethodDef methods[] = {
    {"initialize", py_initialize, METH_VARARGS, "Initialize espeak-ng"},
    {"set_voice", py_set_voice, METH_VARARGS, "Set voice by name"},
    {"get_phonemes", py_get_phonemes, METH_VARARGS, "Get phonemes from text"},
    {NULL, NULL, 0, NULL}};

static struct PyModuleDef module = {PyModuleDef_HEAD_INIT, "espeakbridge", NULL,
                                    -1, methods};

PyMODINIT_FUNC PyInit_espeakbridge(void) { return PyModule_Create(&module); }
