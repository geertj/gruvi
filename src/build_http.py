#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2017 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import os.path
from cffi import FFI

parent, _ = os.path.split(os.path.abspath(__file__))
topdir, _ = os.path.split(parent)


ffi = FFI()

ffi.set_source('http_ffi', """
    #include <stdlib.h>
    #include "src/http_parser.h"
    #include "src/http_parser.c"

    unsigned char http_message_type(http_parser *p) { return p->type; }
    unsigned int http_status_code(http_parser *p) { return p->status_code; }
    unsigned int http_method(http_parser *p) { return p->method; }
    unsigned char http_errno(http_parser *p) { return p->http_errno; }
    unsigned char http_is_upgrade(http_parser *p) { return p->upgrade; }
""", include_dirs=[topdir])

ffi.cdef("""
    typedef struct http_parser http_parser;
    typedef struct http_parser_settings http_parser_settings;

    typedef int (*http_data_cb) (http_parser*, const char *at, size_t length);
    typedef int (*http_cb) (http_parser*);

    enum http_parser_type { HTTP_REQUEST, HTTP_RESPONSE, HTTP_BOTH, ... };

    struct http_parser {
      unsigned short http_major;
      unsigned short http_minor;
      void *data;
      ...;
    };

    struct http_parser_settings {
      http_cb      on_message_begin;
      http_data_cb on_url;
      http_data_cb on_status;
      http_data_cb on_header_field;
      http_data_cb on_header_value;
      http_cb      on_headers_complete;
      http_data_cb on_body;
      http_cb      on_message_complete;
      ...;
    };

    enum http_parser_url_fields { UF_SCHEMA, UF_HOST, UF_PORT, UF_PATH,
            UF_QUERY, UF_FRAGMENT, UF_USERINFO, UF_MAX };

    struct http_parser_url {
        uint16_t field_set;
        uint16_t port;

        struct {
            uint16_t off;
            uint16_t len;
        } field_data[UF_MAX];
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

    void http_parser_url_init(struct http_parser_url *u);
    int http_parser_parse_url(const char *buf, size_t buflen,
                              int is_connect, struct http_parser_url *u);

    /* Extra functions to extract bitfields not supported by cffi */
    unsigned char http_message_type(http_parser *parser);
    unsigned int http_status_code(http_parser *parser);
    unsigned int http_method(http_parser *parser);
    unsigned char http_errno(http_parser *parser);
    unsigned char http_is_upgrade(http_parser *parser);

""")


if __name__ == '__main__':
    ffi.compile()
