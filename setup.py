#
# This file is part of gruvi. Gruvi is free software available under the terms
# of the MIT license. See the file "LICENSE" that was provided together with
# this source file for the licensing terms.
#
# Copyright (c) 2012 the gruvi authors. See the file "AUTHORS" for a complete
# list.

from setuptools import setup


version_info = {
    'name': 'gruvi',
    'version': '0.1',
    'description': 'Synchronous evented IO',
    'author': 'Geert Jansen',
    'author_email': 'geertj@gmail.com',
    'url': 'https://github.com/geertj/gruvi',
    'license': 'MIT',
    'classifiers': [
        'Development Status :: 3 - Alpha',
        'License :: OSI Approved :: MIT License',
        'Operating System :: POSIX',
        'Programming Language :: Python :: 2.6',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3'
    ]
}

 
setup(
    package_dir = { '': 'lib' },
    packages = [ 'gruvi', 'gruvi.test' ],
    requires = ['greenlet'],
    install_requires = ['setuptools'],
    test_suite = 'nose.collector',
    **version_info
)
