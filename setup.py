#
# This file is part of gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2013 the gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import os
import sys

from setuptools import setup, Extension


version_info = {
    'name': 'gruvi',
    'version': '0.10.2.dev',
    'description': 'Synchronous evented IO with pyuv and fibers',
    'author': 'Geert Jansen',
    'author_email': 'geertj@gmail.com',
    'url': 'https://github.com/geertj/gruvi',
    'license': 'MIT',
    'classifiers': [
        'Development Status :: 4 - Beta',
        'License :: OSI Approved :: MIT License',
        'Operating System :: POSIX',
        'Operating System :: Microsoft :: Windows',
        'Operating System :: MacOS :: MacOS X',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3.3',
        'Programming Language :: Python :: 3.4'
    ]
}

topdir, _ = os.path.split(os.path.abspath(__file__))


def get_requirements():
    """Parse a requirements.txt file and return as a list."""
    lines = []
    with open(os.path.join(topdir, 'requirements.txt')) as fin:
        for line in fin:
            lines.append(line.rstrip())
    # Workaround readthedocs issue #1401. Automake is not available in the
    # build environment, which means pyuv cannot be compiled.
    if os.environ.get('READTHEDOCS'):
        lines = [line for line in lines if not line.startswith('pyuv')]
        lines.append('mock')  # conf.py will mock out pyuv
    return lines


def main():
    os.chdir(topdir)
    ext_modules = []
    # Note that on Windows it's more involved to compile _sslcompat because
    # there's no system provided OpenSSL and you need to match the version that
    # was used to compile your Python.
    if sys.version_info[:2] < (3, 5):
        ext_modules.append(Extension('_sslcompat', ['src/sslcompat.c'],
                                     libraries=['ssl', 'crypto']))
    setup(
        packages=['gruvi', 'gruvi.txdbus'],
        package_dir={'': 'lib'},
        setup_requires=['cffi >= 1.0.0'],
        install_requires=get_requirements(),
        cffi_modules=['src/build_http.py:ffi', 'src/build_jsonrpc.py:ffi'],
        ext_package='gruvi',
        ext_modules=ext_modules,
        **version_info
    )


if __name__ == '__main__':
    main()
