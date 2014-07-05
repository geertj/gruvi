************
Front Matter
************

.. currentmodule:: gruvi

Package Namespace
=================

The API of Gruvi is exposed through the ``gruvi`` package. The individual
pieces that make up the API are actually defined in submodules, but those are
pulled into the package scope by the package's ``__init__.py``.

The symbol names in the gruvi package are designed to be unique and descriptive
within the scope of Gruvi, but are not globally unique. Therefore you should
use Gruvi as follows::

  # Import the package
  import gruvi
  gruvi.sleep(1)

  # Or.. import individual symbols
  from gruvi import Process
  proc = Process()

But never like this::

  # Don't use this. It won't work because __all__ is set to []
  from gruvi import *

Gruvi includes a few important protocol implementations that are provided under
its "batteries includes" philosophy. These are exposed as submodules under the
Gruvi namespace. For example::

  from gruvi.http import HttpClient
  client = HttpClient()

External protocols for Gruvi are recommended to install themselves into the
``gruvi.ext`` namespace package.

Exceptions
==========

Errors are reported through exceptions. The following base exceptions are
defined:

.. autoexception:: gruvi.Error

.. autoexception:: gruvi.Timeout

.. autoexception:: gruvi.Cancelled

More exceptions are defined by subsystems and they are documented with their
respective subsystem.

Functions that are a direct mapping of a pyuv function can also raise a pyuv
exception. Gruvi does not try to capture these and transform them into a Gruvi
exception, so in these cases you might want to capture the pyuv exception
separately. The relevant pyuv base exception is:

.. exception:: pyuv.error.UVError
    :noindex:

    Base exception for all pyuv errors.

Timeouts
========

Many parts of the Gruvi API use timeouts. Timeouts follow the Python convention
that they are expressed in seconds, and can be either passed as an integer or a
floating point argument. The granularity of timeouts in Gruvi is approximately
1 millisecond due to the fact that the libuv API represents timeouts as an
integer number of milliseconds.

In addition the above, there are two other values for timeout arguments:

* ``None`` means "no timeout".
* ``-1`` means a *default* timeout. This arguments is accepted for methods
  of objects where the constructor allows you to set a default timeout.

When a timeout occurs in a function or method, a :exc:`Timeout` exception is
raised.

Version Information
===================

The setup metadata used during the build process is captured and exposed as:

.. attribute:: gruvi.version_info

    A dictionary with version information from ``setup.py``.
