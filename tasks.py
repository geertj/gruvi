#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

from invoke import run, task


@task
def clean(ctx):
    run('find . -name __pycache__ | xargs rm -rf || :', echo=True)
    run('find . -name \*.so | xargs rm -f', echo=True)
    run('find . -name \*.pyc | xargs rm -f', echo=True)
    run('find . -name \*.egg-info | xargs rm -rf', echo=True)
    run('rm -rf build dist', echo=True)
    run('rm -rf docs/_build/*', echo=True)


@task(clean)
def develop(ctx):
    run('python setup.py build', echo=True)
    if develop:
        run('python setup.py develop', echo=True)


@task
def checksdist(ctx):
    from setup import version_info
    run('git ls-files | sort > files.git')
    run('rm -rf lib/*.egg-info')
    run('python setup.py sdist >/dev/null 2>&1')
    run('tar tfz dist/{name}-{version}.tar.gz'
       ' | sed -e \'s/^{name}-{version}\///\' -e \'/\/$/d\' -e \'/^$/d\''
       ' | sort > files.sdist'.format(**version_info))
    run('diff -u files.git files.sdist || true')
    run('rm files.git; rm files.sdist')


@task
def buildwheels(ctx):
    run('tox -e py27 -- python setup.py bdist_wheel')
    run('tox -e py35 -- python setup.py bdist_wheel')
    run('tox -e py36 -- python setup.py bdist_wheel')
