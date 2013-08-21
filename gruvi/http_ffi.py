#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import os.path
from cffi import FFI

__all__ = []


ffi = FFI()
ffi.cdef("""
    typedef struct http_parser http_parser;
    typedef struct http_parser_settings http_parser_settings;

    typedef int (*http_data_cb) (http_parser*, const char *at, size_t length);
    typedef int (*http_cb) (http_parser*);

    enum http_parser_type { HTTP_REQUEST, HTTP_RESPONSE, HTTP_BOTH, ... };
    enum http_parser_url_fields { UF_SCHEMA, UF_HOST, UF_PORT, UF_PATH,
                                  UF_QUERY, UF_FRAGMENT, UF_USERINFO, ... };

    struct http_parser {
      unsigned short http_major;
      unsigned short http_minor;
      unsigned short status_code;
      unsigned char method;
      void *data;
      ...;
    };

    struct http_parser_settings {
      http_cb      on_message_begin;
      http_data_cb on_url;
      http_cb      on_status_complete;
      http_data_cb on_header_field;
      http_data_cb on_header_value;
      http_cb      on_headers_complete;
      http_data_cb on_body;
      http_cb      on_message_complete;
      ...;
    };

    struct http_parser_url {
      uint16_t field_set;
      uint16_t port;
      struct { uint16_t off; uint16_t len; } field_data[];
      ...;
    };

    void http_parser_init(http_parser *parser, enum http_parser_type type);
    size_t http_parser_execute(http_parser *parser,
                               const http_parser_settings *settings,
                               const char *data,
                               size_t len);

    int http_should_keep_alive(const http_parser *parser);
    const char *http_method_str(enum http_method m);

    const char *http_errno_name(enum http_errno err);
    const char *http_errno_description(enum http_errno err);

    int http_parser_parse_url(const char *buf, size_t buflen,
                              int is_connect,
                              struct http_parser_url *u);
    void http_parser_pause(http_parser *parser, int paused);
    int http_body_is_final(const http_parser *parser);

    /* Extra functions to extract bitfields not supported by cffi */
    unsigned char http_message_type(http_parser *parser);
    unsigned char http_errno(http_parser *parser);
    unsigned char http_is_upgrade(http_parser *parser);

""")


parent, _ = os.path.split(os.path.abspath(__file__))
topdir, _ = os.path.split(parent)

lib = ffi.verify("""
    #include <stdlib.h>
    #include "src/http_parser.h"
    #include "src/http_parser.c"

    unsigned char http_message_type(http_parser *p) { return p->type; }
    unsigned char http_errno(http_parser *p) { return p->http_errno; }
    unsigned char http_is_upgrade(http_parser *p) { return p->upgrade; }

    """, modulename='http_cffi', include_dirs=[topdir])
