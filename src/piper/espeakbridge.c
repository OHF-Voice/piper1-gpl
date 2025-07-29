// Partially written by ChatGPT 2025-Jul-09

#define Py_LIMITED_API 0x03090000
#include <Python.h>
#include <espeak-ng/speak_lib.h>
#include <espeak-ng/espeak_ng.h>

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

static PyObject *py_initialize(PyObject *self, PyObject *args) {
    const char *data_dir;
    if (!PyArg_ParseTuple(args, "s", &data_dir)) {
        return NULL;
    }

    if (espeak_Initialize(AUDIO_OUTPUT_SYNCHRONOUS, 0, data_dir, 0) < 0) {
        PyErr_SetString(PyExc_RuntimeError, "Failed to initialize espeak-ng");
        return NULL;
    }

    Py_RETURN_NONE;
}

static PyObject *py_set_voice(PyObject *self, PyObject *args) {
    const char *voice;
    if (!PyArg_ParseTuple(args, "s", &voice)) {
        return NULL;
    }

    if (espeak_SetVoiceByName(voice) != ENS_OK) {
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
