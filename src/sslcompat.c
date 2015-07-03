/*
 * This file is part of Gruvi. Gruvi is free software available under the
 * terms of the MIT license. See the file "LICENSE" that was provided
 * together with this source file for the licensing terms.
 *
 * Copyright (c) 2012-2014 the Gruvi authors. See the file "AUTHORS" for a
 * complete list.
 */

#include <Python.h>

/* This module backports some useful SSL features on from later 3.x releases.
 * This module is only needed on Python 2.7, 3.3 and 3.4. From Python 3.5
 * onwards all functionality that we require is present.
 *
 * The following backports are available:
 *
 * - Functions for getting and enabling features on SSL protocol instances
 *   (e.g. tls_unique_cb(), load_dh_params(), set_tlsext_host_name())
 * - Memory BIO support (the MemoryBIO type, and the set_bio() function).
 *
 * The table below indicates which backports are needed for which Python
 * versions.

 * --------------   --------------  ------  ------  ------  ------
 * Python version   2.7.x (x <= 8)  2.7.9   3.3     3.4     3.5
 * --------------   --------------  ------  ------  ------  ------
 * SSL Features     Y               -       -       -       -
 * Memory BIO       Y               Y       Y       Y       -
 * --------------   --------------  ------  ------  ------  ------
 * */

#if PY_MAJOR_VERSION == 2 && PY_MINOR_VERSION < 7 \
    || PY_MAJOR_VERSION == 3 && PY_MINOR_VERSION < 3
#  error "This module is for Python 2.7 and 3.3+ only."
#endif

#include <stdio.h>
#include <string.h>

#include <openssl/ssl.h>
#include <openssl/ssl3.h>
#include <openssl/err.h>
#include <openssl/dh.h>
#include <openssl/pem.h>
#include <openssl/objects.h>
#include <openssl/crypto.h>
#include <openssl/bio.h>


/* Some useful error handling macros. */

#define RETURN_ERROR(fmt, ...) \
    do { \
        if ((fmt) != NULL) PyErr_Format(SSLError, fmt, ## __VA_ARGS__); \
        goto error; \
    } while (0)

#define RETURN_OPENSSL_ERROR \
    RETURN_ERROR("%s", ERR_error_string(ERR_get_error(), NULL))

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


/* OpenSSL compatibility */

#ifdef SSL_CTRL_SET_TLSEXT_HOSTNAME
#  define HAVE_SNI 1
#else
#  define HAVE_SNI 0
#endif

#define MAX_CB_LEN 64

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


/* sslcompat methods below */

static PyObject *
sslcompat_compression(PyObject *self, PyObject *args)
{
    PyObject *Pret = NULL;
    PySSLObject *sslob;
    const COMP_METHOD *method;
    const char *shortname;

    if (!PyArg_ParseTuple(args, "O:compression", &sslob))
        RETURN_ERROR(NULL);

    CHECK_SSL_OBJ(sslob);

    method = SSL_get_current_compression(sslob->ssl);
    if (method == NULL || method->type == NID_undef)
        RETURN_NONE(Pret);

    if (!(shortname = OBJ_nid2sn(method->type)))
        RETURN_OPENSSL_ERROR;

    Pret = PyBytes_FromString(shortname);

error:
    return Pret;
}


static PyObject *
sslcompat_get_options(PyObject *self, PyObject *args)
{
    PyObject *Pret = NULL;
    PySSLObject *sslob;
    SSL_CTX *ctx;
    long opts;

    if (!PyArg_ParseTuple(args, "O:get_options", &sslob))
        RETURN_ERROR(NULL);

    CHECK_SSL_OBJ(sslob);
    ctx = SSL_get_SSL_CTX(sslob->ssl);

    opts = SSL_CTX_get_options(ctx);
    Pret = PyLong_FromLong(opts);

error:
    return Pret;
}


static PyObject *
sslcompat_set_options(PyObject *self, PyObject *args)
{
    PyObject *Pret = NULL;
    PySSLObject *sslob;
    SSL_CTX *ctx;
    long opts, current, add, remove;

    if (!PyArg_ParseTuple(args, "Ol:set_options", &sslob, &opts))
        RETURN_ERROR(NULL);

    CHECK_SSL_OBJ(sslob);
    ctx = SSL_get_SSL_CTX(sslob->ssl);

    current = SSL_CTX_get_options(ctx);
    remove = current & ~opts;
    if (remove)
#ifdef SSL_CTRL_CLEAR_OPTIONS
        SSL_CTX_clear_options(ctx, remove);
#else
        RETURN_ERROR("this version of OpenSSL cannot remove options");
#endif
    add = ~current & opts;
    if (add)
        SSL_CTX_set_options(ctx, add);

    opts = SSL_CTX_get_options(ctx);
    Pret = PyLong_FromLong(opts);

error:
    return Pret;
}


static PyObject *
sslcompat_load_dh_params(PyObject *self, PyObject *args)
{
    char *path;
    PyObject *Pret = NULL;
    PySSLObject *sslob;
    DH *dh = NULL;
    FILE *fpem = NULL;

    if (!PyArg_ParseTuple(args, "Os:load_dh_params", &sslob, &path))
        RETURN_ERROR(NULL);

    CHECK_SSL_OBJ(sslob);

    if (!(fpem = fopen(path, "rb")))
        RETURN_ERROR("Could not open file %s", path);
    if (!(dh = PEM_read_DHparams(fpem, NULL, NULL, NULL)))
        RETURN_OPENSSL_ERROR;
    if (!SSL_set_tmp_dh(sslob->ssl, dh))
        RETURN_OPENSSL_ERROR;

    RETURN_NONE(Pret);

error:
    if (dh) DH_free(dh);
    if (fpem) fclose(fpem);
    return Pret;
}


static PyObject *
sslcompat_set_accept_state(PyObject *self, PyObject *args)
{
    PyObject *Pret = NULL;
    PySSLObject *sslob;

    if (!PyArg_ParseTuple(args, "O:set_accept_state", &sslob))
        RETURN_ERROR(NULL);

    CHECK_SSL_OBJ(sslob);

    SSL_set_accept_state(sslob->ssl);

    RETURN_NONE(Pret);

error:
    return Pret;
}


static PyObject *
sslcompat_tls_unique_cb(PyObject *self, PyObject *args)
{
    PyObject *Pret = NULL;
    PySSLObject *sslob;
    char buf[MAX_CB_LEN];
    int len;

    if (!PyArg_ParseTuple(args, "O:get_channel_binding", &sslob))
        RETURN_ERROR(NULL);

    CHECK_SSL_OBJ(sslob);

    if (SSL_session_reused(sslob->ssl) ^ !sslob->ssl->server)
        len = SSL_get_finished(sslob->ssl, buf, MAX_CB_LEN);
    else
        len = SSL_get_peer_finished(sslob->ssl, buf, MAX_CB_LEN);

    if (len == 0)
        RETURN_NONE(Pret);

    Pret = PyBytes_FromStringAndSize(buf, len);

error:
    return Pret;
}


static PyObject *
sslcompat_set_tlsext_host_name(PyObject *self, PyObject *args)
{
    PyObject *Pret = NULL;
    PySSLObject *sslob;
    char *hostname;

    if (!PyArg_ParseTuple(args, "Os:set_tlsext_host_name", &sslob, &hostname))
        RETURN_ERROR(NULL);

    CHECK_SSL_OBJ(sslob);

#if HAVE_SNI
    if (!SSL_set_tlsext_host_name(sslob->ssl, hostname))
        RETURN_OPENSSL_ERROR;

    RETURN_NONE(Pret);
#else
    RETURN_ERROR("SNI is not supported by your OpenSSL");
#endif

error:
    return Pret;
}


static PyObject *
sslcompat_set_bio(PyObject *self, PyObject *args)
{
    PyObject *Pret = NULL;
    PySSLObject *sslob;
    PySSLMemoryBIO *inbio, *outbio;

    /* The mode of operation of this function is to replace the BIO on the SSL
     * structure that the PySSLSocket is managing, without any knowledge or
     * cooperation from PySSLSocket itself.
     *
     * For this to work it is important that the socket is in non-blocking
     * mode. Otherwise _ssl will attempt to select on it which would be
     * meaningless.
     * */

    if (!PyArg_ParseTuple(args, "OO!O!:set_bio", &sslob, &PySSLMemoryBIO_Type,
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
    {"compression", (PyCFunction) sslcompat_compression, METH_VARARGS},
    {"get_options", (PyCFunction) sslcompat_get_options, METH_VARARGS},
    {"set_options", (PyCFunction) sslcompat_set_options, METH_VARARGS},
    {"load_dh_params", (PyCFunction) sslcompat_load_dh_params, METH_VARARGS},
    {"set_accept_state", (PyCFunction) sslcompat_set_accept_state, METH_VARARGS},
    {"tls_unique_cb", (PyCFunction) sslcompat_tls_unique_cb, METH_VARARGS},
    {"set_tlsext_host_name", (PyCFunction) sslcompat_set_tlsext_host_name, METH_VARARGS},
    {"set_bio", (PyCFunction) sslcompat_set_bio, METH_VARARGS},
    {NULL, NULL}
};


/* Main module */

PyDoc_STRVAR(sslcompat_doc, "Backports of upstream ssl methods");

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

    /* SSL_OP_DONT_INSERT_EMPTY_FRAGMENTS disables a workaround against the
     * BEAST attack on SSL and TLS < 1.1. The Python _ssl module removes it
     * from OP_ALL (enabling the workaround) and for consistency and security
     * we follow that lead. */
    if (PyModule_AddIntConstant(Pmodule, "OP_ALL",
                    SSL_OP_ALL & ~SSL_OP_DONT_INSERT_EMPTY_FRAGMENTS) < 0)
        return MOD_ERROR;
    if (PyModule_AddIntConstant(Pmodule, "OP_NO_SSLv2", SSL_OP_NO_SSLv2) < 0)
        return MOD_ERROR;
    if (PyModule_AddIntConstant(Pmodule, "OP_NO_SSLv3", SSL_OP_NO_SSLv3) < 0)
        return MOD_ERROR;
    if (PyModule_AddIntConstant(Pmodule, "OP_NO_TLSv1", SSL_OP_NO_TLSv1) < 0)
        return MOD_ERROR;
#ifdef SSL_OP_NO_TLSv1_1
    if (PyModule_AddIntConstant(Pmodule, "OP_NO_TLSv1_1", SSL_OP_NO_TLSv1_1) < 0)
        return MOD_ERROR;
#endif
#ifdef SSL_OP_NO_TLSv1_2
    if (PyModule_AddIntConstant(Pmodule, "OP_NO_TLSv1_2", SSL_OP_NO_TLSv1_2) < 0)
        return MOD_ERROR;
#endif
    if (PyModule_AddIntConstant(Pmodule, "OP_CIPHER_SERVER_PREFERENCE",
                    SSL_OP_CIPHER_SERVER_PREFERENCE) < 0)
        return MOD_ERROR;
    if (PyModule_AddIntConstant(Pmodule, "OP_SINGLE_DH_USE", SSL_OP_SINGLE_DH_USE) < 0)
        return MOD_ERROR;
#ifdef SSL_OP_NO_COMPRESSION
    if (PyModule_AddIntConstant(Pmodule, "OP_NO_COMPRESSION", SSL_OP_NO_COMPRESSION) < 0)
        return MOD_ERROR;
#endif
    if (PyModule_AddIntConstant(Pmodule, "HAS_SNI", HAVE_SNI) < 0)
        return MOD_ERROR;
    PyModule_AddIntConstant(Pmodule, "HAS_TLS_UNIQUE", 1);

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
