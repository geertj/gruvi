/*
 * This file is part of Gruvi. Gruvi is free software available under the
 * terms of the MIT license. See the file "LICENSE" that was provided
 * together with this source file for the licensing terms.
 *
 * Copyright (c) 2012-2017 the Gruvi authors. See the file "AUTHORS" for a
 * complete list.
 */

#include <Python.h>

/*
 * This module backports the async SSL support from Python 3.5 to earlier
 * versions. It supports Python 2.7, 3.3 and 3.4.
 * */

#if !(PY_MAJOR_VERSION == 2 && PY_MINOR_VERSION == 7) \
    && !(PY_MAJOR_VERSION == 3 && PY_MINOR_VERSION == 3) \
    && !(PY_MAJOR_VERSION == 3 && PY_MINOR_VERSION == 4)
#  error "This module is for Python 2.7, 3.3 and 3.4 only."
#endif

#include <string.h>
#include <openssl/ssl.h>


/* Some useful error handling macros. */

#define RETURN_ERROR(fmt, ...) \
    do { \
        if ((fmt) != NULL) PyErr_Format(SSLError, fmt, ## __VA_ARGS__); \
        goto error; \
    } while (0)

#define RETURN_NONE(dest) \
    do { Py_INCREF(Py_None); dest = Py_None; goto error; } while (0)


/* Useful Python 2/3 portability macros. Kudos to
 * http://python3porting.com/cextensions.html. */

#if PY_MAJOR_VERSION >= 3
#  define MOD_OK(val) (val)
#  define MOD_ERROR NULL
#  define MOD_INITFUNC(name) PyMODINIT_FUNC PyInit_ ## name(void)
#  define INIT_MODULE(mod, name, methods, doc) \
        do { \
            static struct PyModuleDef moduledef = { \
                PyModuleDef_HEAD_INIT, name, doc, -1, methods, }; \
            mod = PyModule_Create(&moduledef); \
        } while (0)
#  define BUF_FMT "y*"
#else
#  define MOD_OK(value)
#  define MOD_ERROR
#  define MOD_INITFUNC(name) void init ## name(void)
#  define INIT_MODULE(mod, name, methods, doc) \
        do { mod = Py_InitModule3(name, methods, doc); } while (0)
#  define BUF_FMT "s*"
#endif


/* Globals */

static PyObject *SSLError = NULL;

/* The MemoryBIO object has been copied and adapted from Python 3.5 */

typedef struct {
    PyObject_HEAD
    BIO *bio;
    int eof_written;
} PySSLMemoryBIO;

static PyTypeObject PySSLMemoryBIO_Type;


/* Define a structure that has the same layout as PySSLObject in the _ssl
 * module. This allows us to compile this module separately from the Python
 * source tree.
 *
 * Of course we need to be very careful here that things match.
 */

typedef struct
{
    PyObject_HEAD
    PyObject *Socket;
#if PY_MAJOR_VERSION == 2
    SSL_CTX *ctx;
#endif
    SSL *ssl;
} PySSLObject;


#if PY_MAJOR_VERSION == 2 && PY_MINOR_VERSION == 7 && PY_MICRO_VERSION < 9
#  define SSL_OBJ_NAME "ssl.SSLContext"
#else
#  define SSL_OBJ_NAME "_ssl._SSLSocket"
#endif

#define CHECK_SSL_OBJ(obj) \
    do { \
        if (strcmp(Py_TYPE(obj)->tp_name, SSL_OBJ_NAME)) \
            RETURN_ERROR("expecting a " SSL_OBJ_NAME " instance"); \
    } while (0)


/* MemoryBIO type */

static PyObject *
memory_bio_new(PyTypeObject *type, PyObject *args, PyObject *kwds)
{
    BIO *bio = NULL;
    PySSLMemoryBIO *self = NULL;

    if (!PyArg_ParseTuple(args, ":MemoryBIO"))
        RETURN_ERROR(NULL);

    bio = BIO_new(BIO_s_mem());
    if (bio == NULL)
        RETURN_ERROR("failed to allocate BIO");

    /* Since our BIO is non-blocking an empty read() does not indicate EOF,
     * just that no data is currently available. The SSL routines should retry
     * the read, which we can achieve by calling BIO_set_retry_read(). */
    BIO_set_retry_read(bio);
    BIO_set_mem_eof_return(bio, -1);

    self = (PySSLMemoryBIO *) type->tp_alloc(type, 0);
    if (self == NULL)
        RETURN_ERROR(NULL);

    self->bio = bio; bio = NULL;
    self->eof_written = 0;

error:
    if (bio != NULL) BIO_free(bio);
    return (PyObject *) self;
}


static void
memory_bio_dealloc(PySSLMemoryBIO *self)
{
    BIO_free(self->bio);
    Py_TYPE(self)->tp_free(self);
}


static PyObject *
memory_bio_get_pending(PySSLMemoryBIO *self, void *c)
{
    return PyLong_FromLong(BIO_ctrl_pending(self->bio));
}


static PyObject *
memory_bio_get_eof(PySSLMemoryBIO *self, void *c)
{
    return PyBool_FromLong((BIO_ctrl_pending(self->bio) == 0) && self->eof_written);
}


static PyObject *
memory_bio_read(PySSLMemoryBIO *self, PyObject *args)
{
    int len = -1, avail, nbytes;
    PyObject *Pret = NULL;

    if (!PyArg_ParseTuple(args, "|i:read", &len))
        RETURN_ERROR(NULL);

    avail = BIO_ctrl_pending(self->bio);
    if ((len < 0) || (len > avail))
        len = avail;

    Pret = PyBytes_FromStringAndSize(NULL, len);
    if (Pret == NULL)
        RETURN_ERROR(NULL);

    if (len > 0) {
        nbytes = BIO_read(self->bio, PyBytes_AS_STRING(Pret), len);
        /* There should never be any short reads but check anyway. */
        if ((nbytes < len) && (_PyBytes_Resize(&Pret, len) < 0)) {
            Py_DECREF(Pret); Pret = NULL;
            RETURN_ERROR(NULL);
        }
    }

error:
    return Pret;
}


static PyObject *
memory_bio_write(PySSLMemoryBIO *self, PyObject *args)
{
    PyObject *Pret = NULL;
    Py_buffer buf;
    int nbytes;

    buf.buf = NULL;
    if (!PyArg_ParseTuple(args, BUF_FMT ":write", &buf))
        RETURN_ERROR(NULL);

    if (buf.len > INT_MAX)
        RETURN_ERROR("string longer than %d bytes", INT_MAX);
    if (self->eof_written)
        RETURN_ERROR("cannot write() after write_eof()");

    nbytes = BIO_write(self->bio, buf.buf, buf.len);
    if (nbytes < 0)
        RETURN_ERROR("BIO_write() failed");

    Pret = PyLong_FromLong(nbytes);

error:
    if (buf.buf != NULL) PyBuffer_Release(&buf);
    return Pret;
}


static PyObject *
memory_bio_write_eof(PySSLMemoryBIO *self, PyObject *args)
{
    self->eof_written = 1;
    /* After an EOF is written, a zero return from read() should be a real EOF
     * i.e. it should not be retried. Clear the SHOULD_RETRY flag. */
    BIO_clear_retry_flags(self->bio);
    BIO_set_mem_eof_return(self->bio, 0);

    Py_RETURN_NONE;
}


static PyGetSetDef memory_bio_getsetlist[] =
{
    {"pending", (getter) memory_bio_get_pending, NULL, NULL},
    {"eof", (getter) memory_bio_get_eof, NULL, NULL},
    {NULL, NULL}
};


static PyMethodDef memory_bio_methods[] =
{
    {"read", (PyCFunction) memory_bio_read, METH_VARARGS, NULL},
    {"write", (PyCFunction) memory_bio_write, METH_VARARGS, NULL},
    {"write_eof", (PyCFunction) memory_bio_write_eof, METH_NOARGS, NULL},
    {NULL, NULL}
};


static PyTypeObject PySSLMemoryBIO_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    "_sslcompat.MemoryBIO",                    /*tp_name*/
    sizeof(PySSLMemoryBIO),                    /*tp_basicsize*/
    0,                                         /*tp_itemsize*/
    (destructor)memory_bio_dealloc,            /*tp_dealloc*/
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    Py_TPFLAGS_DEFAULT,                        /*tp_flags*/
    0, 0, 0, 0, 0, 0, 0,
    memory_bio_methods,                        /*tp_methods*/
    0,                                         /*tp_members*/
    memory_bio_getsetlist,                     /*tp_getset*/
    0, 0, 0, 0, 0, 0, 0,
    memory_bio_new,                            /*tp_new*/
};


/* This method is where the money it. It replaces the BIO on the SSL
 * structure that the PySSLSocket is managing, without any knowledge or
 * cooperation from PySSLSocket itself.
 *
 * For this to work it is important that the socket is in non-blocking
 * mode. Otherwise _ssl will attempt to select on it which would be
 * meaningless.
 * */

static PyObject *
sslcompat_replace_bio(PyObject *self, PyObject *args)
{
    PyObject *Pret = NULL;
    PySSLObject *sslob;
    PySSLMemoryBIO *inbio, *outbio;

    if (!PyArg_ParseTuple(args, "OO!O!:replace_bio", &sslob, &PySSLMemoryBIO_Type,
                          &inbio, &PySSLMemoryBIO_Type, &outbio))
        RETURN_ERROR(NULL);

    CHECK_SSL_OBJ(sslob);

    /* BIOs are reference counted and SSL_set_bio borrows our reference.
     * To prevent a double free in memory_bio_dealloc() we need to take an
     * extra reference here. */
    CRYPTO_add(&inbio->bio->references, 1, CRYPTO_LOCK_BIO);
    CRYPTO_add(&outbio->bio->references, 1, CRYPTO_LOCK_BIO);

    /* Now replace the socket BIO with the memory BIOs */
    SSL_set_bio(sslob->ssl, inbio->bio, outbio->bio);

    RETURN_NONE(Pret);

error:
    return Pret;
}


static PyMethodDef sslcompat_methods[] =
{
    {"replace_bio", (PyCFunction) sslcompat_replace_bio, METH_VARARGS},
    {NULL, NULL}
};


/* Main module */

PyDoc_STRVAR(sslcompat_doc, "Backport of Python 3.5+ async ssl support");

MOD_INITFUNC(_sslcompat)
{
    PyObject *Pmodule, *Pdict, *Perrors, *Pstr;

    INIT_MODULE(Pmodule, "_sslcompat", sslcompat_methods, sslcompat_doc);

    if (!((Pdict = PyModule_GetDict(Pmodule))))
        return MOD_ERROR;
    if (!(SSLError = PyErr_NewException("_sslcompat.Error", NULL, NULL)))
        return MOD_ERROR;
    if (PyDict_SetItemString(Pdict, "Error", SSLError) < 0)
        return MOD_ERROR;

    if (PyType_Ready(&PySSLMemoryBIO_Type) < 0)
        return MOD_ERROR;
    if (PyDict_SetItemString(Pdict, "MemoryBIO", (PyObject *) &PySSLMemoryBIO_Type) < 0)
        return MOD_ERROR;

    /* Expose error codes that are needed (just 1 for now). */
    if (!(Perrors = PyDict_New()))
        return MOD_ERROR;
    if (!(Pstr = PyBytes_FromString("PROTOCOL_IS_SHUTDOWN")))
        return MOD_ERROR;
    if (PyDict_SetItem(Perrors, PyLong_FromLong(SSL_R_PROTOCOL_IS_SHUTDOWN), Pstr) < 0)
        return MOD_ERROR;
    if (PyDict_SetItemString(Pdict, "errorcode", Perrors) < 0)
        return MOD_ERROR;

    /* Don't initialize the SSL library here. The following is done by _ssl:
        SSL_load_error_strings();
        SSL_library_init();
     */

    return MOD_OK(Pmodule);
}
