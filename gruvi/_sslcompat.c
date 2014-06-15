/*
 * This file is part of Gruvi. Gruvi is free software available under the
 * terms of the MIT license. See the file "LICENSE" that was provided
 * together with this source file for the licensing terms.
 *
 * Copyright (c) 2012-2014 the Gruvi authors. See the file "AUTHORS" for a
 * complete list.
 */

#include <Python.h>

/* This module is only needed (and supported) on Python 2.6/2.7. */

#if PY_MAJOR_VERSION >= 3
#  error "This module is for Python 2.6/2.7 only."
#endif

#include <stdio.h>
#include <string.h>

#include <openssl/ssl.h>
#include <openssl/ssl3.h>
#include <openssl/err.h>
#include <openssl/dh.h>
#include <openssl/pem.h>
#include <openssl/objects.h>


/* Some useful error handling macros. */

#define RETURN_ERROR(fmt, ...) \
    do { \
        if ((fmt) != NULL) PyErr_Format(sslcompat_Error, fmt, ## __VA_ARGS__); \
        goto error; \
    } while (0)

#define RETURN_OPENSSL_ERROR \
    RETURN_ERROR("%s", ERR_error_string(ERR_get_error(), NULL))


/* Exception used by this module. */

static PyObject *sslcompat_Error = NULL;


/*
 * Define a structure that has the same layout as PySSLObject in the _ssl
 * module. This allows us to compile this module separately from the Python
 * source tree.
 *
 * The format of PySSLObject has been kept consistent in Python 2.6 and 2.7.
 * And since both are in deep freeze now, we should be fine.
 */

typedef struct
{
    PyObject_HEAD
    PyObject *Socket;
    SSL_CTX *ctx;
    SSL *ssl;
} PySSLObject;


/* sslcompat method below */

static PyObject *
sslcompat_set_ciphers(PyObject *self, PyObject *args)
{
    char *ciphers;
    PyObject *Pret = NULL;
    PySSLObject *sslob;

    if (!PyArg_ParseTuple(args, "Os:set_ciphers", &sslob, &ciphers))
        RETURN_ERROR(NULL);
    if (strcmp(sslob->ob_type->tp_name, "ssl.SSLContext"))
        RETURN_ERROR("expecting a SSLContext");

    if (!SSL_set_cipher_list(sslob->ssl, ciphers))
        RETURN_OPENSSL_ERROR;

    Py_INCREF(Py_None); Pret = Py_None;

error:
    return Pret;
}


static PyObject *
sslcompat_compression(PyObject *self, PyObject *args)
{
    PyObject *Pret = NULL;
    PySSLObject *sslob;
    const COMP_METHOD *method;
    const char *shortname;

    if (!PyArg_ParseTuple(args, "O:compression", &sslob))
        RETURN_ERROR(NULL);
    if (strcmp(sslob->ob_type->tp_name, "ssl.SSLContext"))
        RETURN_ERROR("expecting a SSLContext");

    method = SSL_get_current_compression(sslob->ssl);
    if (method == NULL || method->type == NID_undef) {
        Py_INCREF(Py_None); Pret = Py_None;
        RETURN_ERROR(NULL);
    }

    if (!(shortname = OBJ_nid2sn(method->type)))
        RETURN_OPENSSL_ERROR;

    return PyString_FromString(shortname);

error:
    return Pret;
}


static PyObject *
sslcompat_get_options(PyObject *self, PyObject *args)
{
    PyObject *Pret = NULL;
    PySSLObject *sslob;
    long opts;

    if (!PyArg_ParseTuple(args, "O:get_options", &sslob))
        RETURN_ERROR(NULL);
    if (strcmp(sslob->ob_type->tp_name, "ssl.SSLContext"))
        RETURN_ERROR("expecting a SSLContext");

    opts = SSL_CTX_get_options(sslob->ctx);

    Pret = PyLong_FromLong(opts);

error:
    return Pret;
}


static PyObject *
sslcompat_set_options(PyObject *self, PyObject *args)
{
    PyObject *Pret = NULL;
    PySSLObject *sslob;
    long opts, current, add, remove;

    if (!PyArg_ParseTuple(args, "Ol:set_options", &sslob, &opts))
        RETURN_ERROR(NULL);
    if (strcmp(sslob->ob_type->tp_name, "ssl.SSLContext"))
        RETURN_ERROR("expecting a SSLContext");

    current = SSL_CTX_get_options(sslob->ctx);
    remove = current & ~opts;
    if (remove)
#ifdef SSL_CTRL_CLEAR_OPTIONS
        SSL_CTX_clear_options(sslob->ctx, remove);
#else
        RETURN_ERROR("this version of OpenSSL cannot remove options");
#endif
    add = ~current & opts;
    if (add)
        SSL_CTX_set_options(sslob->ctx, add);

    opts = SSL_CTX_get_options(sslob->ctx);
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
    if (strcmp(sslob->ob_type->tp_name, "ssl.SSLContext"))
        RETURN_ERROR("expecting a SSLContext");

    if (!(fpem = fopen(path, "rb")))
        RETURN_ERROR("Could not open file %s", path);
    if (!(dh = PEM_read_DHparams(fpem, NULL, NULL, NULL)))
        RETURN_OPENSSL_ERROR;
    if (!SSL_set_tmp_dh(sslob->ssl, dh))
        RETURN_OPENSSL_ERROR;

    Py_INCREF(Py_None); Pret = Py_None;

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
    if (strcmp(sslob->ob_type->tp_name, "ssl.SSLContext"))
        RETURN_ERROR("expecting a SSLContext");

    SSL_set_accept_state(sslob->ssl);

    Py_INCREF(Py_None); Pret = Py_None;

error:
    return Pret;
}


static PyObject *
sslcompat_tls_unique_cb(PyObject *self, PyObject *args)
{
    PyObject *Pcb = NULL;
    PySSLObject *sslob;
    SSL3_STATE *s3;

    if (!PyArg_ParseTuple(args, "O:get_channel_binding", &sslob))
        RETURN_ERROR(NULL);
    if (strcmp(sslob->ob_type->tp_name, "ssl.SSLContext"))
        RETURN_ERROR("expecting a SSLContext");

    if (sslob->ssl->s3 == NULL)
        RETURN_ERROR("cannot get channel binding for SSLv2");

#if defined(__APPLE__) && __APPLE_CC__ < 6000 && defined(__LP64__)
    /* FUDGE... On Mac OSX, when compiling against the OpenSSL headers provided
     * in /usr/include/openssl, the compiler believes that the s3->tmp struct
     * is 8 bytes earlier than it really is.  No idea where this comes from....
     *
     * Might also be needed on 32-bit or PPC - NOT tested. 
     *
     * Update for OSX Mavericks: In Mavericks, gcc isn't gcc anymore but a
     * symlink to clang. Clang appears to compile things correctly.
     */
    s3 = (SSL3_STATE *) ((char *) sslob->ssl->s3 + 8);
#else
    s3 = sslob->ssl->s3;
#endif

    if (SSL_session_reused(sslob->ssl) ^ !sslob->ssl->server)
        Pcb = PyString_FromStringAndSize((char *) s3->tmp.finish_md,
                    s3->tmp.finish_md_len);
    else
        Pcb = PyString_FromStringAndSize((char *) s3->tmp.peer_finish_md,
                    s3->tmp.peer_finish_md_len);

error:
    return Pcb;
}


#ifdef SSL_CTRL_SET_TLSEXT_HOSTNAME
static PyObject *
sslcompat_set_tlsext_host_name(PyObject *self, PyObject *args)
{
    PyObject *Pret = NULL;
    PySSLObject *sslob;
    char *hostname;

    if (!PyArg_ParseTuple(args, "Os:set_tlsext_host_name", &sslob, &hostname))
        RETURN_ERROR(NULL);
    if (strcmp(sslob->ob_type->tp_name, "ssl.SSLContext"))
        RETURN_ERROR("expecting a SSLContext");

    if (!SSL_set_tlsext_host_name(sslob->ssl, hostname))
        RETURN_OPENSSL_ERROR;

    Py_INCREF(Py_None); Pret = Py_None;

error:
    return Pret;
}
#endif

static PyMethodDef sslcompat_methods[] =
{
    { "set_ciphers", (PyCFunction) sslcompat_set_ciphers, METH_VARARGS },
    { "compression", (PyCFunction) sslcompat_compression, METH_VARARGS },
    { "get_options", (PyCFunction) sslcompat_get_options, METH_VARARGS },
    { "set_options", (PyCFunction) sslcompat_set_options, METH_VARARGS },
    { "load_dh_params", (PyCFunction) sslcompat_load_dh_params, METH_VARARGS },
    { "set_accept_state", (PyCFunction) sslcompat_set_accept_state, METH_VARARGS },
    { "tls_unique_cb", (PyCFunction) sslcompat_tls_unique_cb, METH_VARARGS },
#ifdef SSL_CTRL_SET_TLSEXT_HOSTNAME
    { "set_tlsext_host_name", (PyCFunction) sslcompat_set_tlsext_host_name, METH_VARARGS },
#endif
    { NULL, NULL }
};

PyDoc_STRVAR(sslcompat_doc, "Backports of Py3K ssl methods");


void init_sslcompat(void)
{
    PyObject *Pmodule, *Pdict, *Perrors;

    if (!(Pmodule = Py_InitModule3("_sslcompat", sslcompat_methods, sslcompat_doc)))
        return;
    if (!((Pdict = PyModule_GetDict(Pmodule))))
        return;
    if (!(sslcompat_Error = PyErr_NewException("_sslcompat.Error", NULL, NULL)))
        return;
    if (PyDict_SetItemString(Pdict, "Error", sslcompat_Error) < 0)
        return;

    /* SSL_OP_DONT_INSERT_EMPTY_FRAGMENTS disables a workaround against the
     * BEAST attack on SSL and TLS < 1.1. The Python _ssl module removes it
     * from OP_ALL (enabling the workaround) and for consistency and security
     * we follow that lead. */
    if (PyModule_AddIntConstant(Pmodule, "OP_ALL",
                    SSL_OP_ALL & ~SSL_OP_DONT_INSERT_EMPTY_FRAGMENTS) < 0)
        return;
    if (PyModule_AddIntConstant(Pmodule, "OP_NO_SSLv2", SSL_OP_NO_SSLv2) < 0)
        return;
    if (PyModule_AddIntConstant(Pmodule, "OP_NO_SSLv3", SSL_OP_NO_SSLv3) < 0)
        return;
    if (PyModule_AddIntConstant(Pmodule, "OP_NO_TLSv1", SSL_OP_NO_TLSv1) < 0)
        return;
#ifdef SSL_OP_NO_TLSv1_1
    if (PyModule_AddIntConstant(Pmodule, "OP_NO_TLSv1_1", SSL_OP_NO_TLSv1_1) < 0)
        return;
#endif
#ifdef SSL_OP_NO_TLSv1_2
    if (PyModule_AddIntConstant(Pmodule, "OP_NO_TLSv1_2", SSL_OP_NO_TLSv1_2) < 0)
        return;
#endif
    if (PyModule_AddIntConstant(Pmodule, "OP_CIPHER_SERVER_PREFERENCE",
                    SSL_OP_CIPHER_SERVER_PREFERENCE) < 0)
        return;
    if (PyModule_AddIntConstant(Pmodule, "OP_SINGLE_DH_USE", SSL_OP_SINGLE_DH_USE) < 0)
        return;
#ifdef SSL_OP_NO_COMPRESSION
    if (PyModule_AddIntConstant(Pmodule, "OP_NO_COMPRESSION", SSL_OP_NO_COMPRESSION) < 0)
        return;
#endif

    /* Expose error codes that are needed (just 1 for now). */
    if (!(Perrors = PyDict_New()))
        return;
    if (PyDict_SetItem(Perrors, PyInt_FromLong(SSL_R_PROTOCOL_IS_SHUTDOWN),
                       PyString_FromString("PROTOCOL_IS_SHUTDOWN")) < 0)
        return;
    if (PyDict_SetItemString(Pdict, "errorcode", Perrors) < 0)
        return;

    /* Don't initialize the SSL library here. The following is done by _ssl:
        SSL_load_error_strings();
        SSL_library_init();
     */
}
