.. _installation:

************
Installation
************

Gruvi uses the setuptools, so installation is relatively straightforward. You
need Python version 2.6, 2.7, or 3.3+.

Some of Gruvi's dependencies contain C extensions. This means that you need to
have a C compiler, and also the Python development files. Once you've made sure
you have these, use the commands below to install the latest Gruvi into a
virtualenv::

  $ virtualenv --distribute gruvi-dev
  $ . gruvi-dev/bin/activate
  $ git clone https://github.com/geertj/gruvi
  $ cd gruvi
  $ pip install -r requirements.txt
  $ python setup.py install

Linux Specific Notes
********************

Most Linux versions will have a supported version of Python installed. One
small exception would be RHEL/CentOS 5 which by default comes with Python 2.4.

Make sure you have gcc installed, and also the Python development files. On
Debian/Ubuntu type systems::

  $ sudo apt-get install gcc python-dev python-virtualenv git libffi-dev

On Red Hat/Fedora type systems::

  $ sudo yum install gcc python-devel python-virtualenv git libffi-devel

After this follow the generic instructions above.

Mac OSX Specific Notes
**********************

Recent versions of OSX will have a supported Python version available. The
easiest way to install a C compiler is to install Xcode from the Mac App Store.
This is a free download. 

After you’ve installed Xcode, go to Xcode -> Preferences -> Components, and
install the “Command Line Tools” component as well.

After this, follow the generic instructions above.

Windows Specific Notes
**********************

Windows does not come with a built-in Python, so you have to install one from
python.org. For the C compiler, I'd recommend MinGW. Unfortunately because of
issue12641_, compilation of C extensions is currently broken for MinGW. If you
feel determined, you can see `these instructions`_ from another Python module
that explain how to unbreak this.

**Update**: It appears that Python 2.7.6 and 3.3.3 will fix this bug! At the
time of writing (11/2/2013), both versions have release candidates, but the
final versions have not yet been released.


.. _issue12641: http://bugs.python.org/issue12641
.. _these instructions: http://docs.testmill.cc/en/latest/appendices.html#windows-installation
