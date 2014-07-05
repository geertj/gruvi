#
# This file is part of Gruvi. Gruvi is free software available under the
# terms of the MIT license. See the file "LICENSE" that was provided
# together with this source file for the licensing terms.
#
# Copyright (c) 2012-2014 the Gruvi authors. See the file "AUTHORS" for a
# complete list.

from __future__ import absolute_import, print_function

import os
import signal
import six
from io import TextIOWrapper

import pyuv
import gruvi

from gruvi import fibers, compat
from gruvi.hub import get_hub, switchpoint
from gruvi.sync import Event
from gruvi.stream import StreamProtocol
from gruvi.endpoints import create_connection, Endpoint

__all__ = ['Process', 'PIPE', 'DEVNULL']

PIPE = -1
DEVNULL = -3

CREATE_PIPE = pyuv.UV_CREATE_PIPE | pyuv.UV_READABLE_PIPE | pyuv.UV_WRITABLE_PIPE


class Process(Endpoint):
    """A child process.

    This class allows you to start up a child process, communicate with it and
    control it. The API is modeled after the :class:`subprocess.Popen` class.
    """

    def __init__(self, encoding=None, textio_args={}, timeout=None):
        """
        The *encoding* argument specifies the encoding to use for output of the
        child. If it is not specified, then reading from the child will produce
        ``bytes`` objects.

        The *textio_args* argument can be used to pass keyword arguments to the
        :class:`io.TextIOWrapper` instances that are used to wrap the raw
        standard input and outputs in case *encoding* is provided. It can be
        used e.g. to change buffering and enable universal newlines.
        """
        super(Process, self).__init__(self._create_protocol, timeout)
        self._encoding = encoding
        self._textio_args = textio_args.copy()
        # Unless specified otherwise, a text stream should be write-through.
        self._emulate_write_through = False
        if encoding and 'line_buffering' not in textio_args \
                    and 'write_through' not in textio_args:
            if six.PY2:
                self._emulate_write_through = True
            else:
                textio_args['write_through'] = True
        self._process = None
        self._child_exited = Event()
        self._reinit()

    def _create_protocol(self):
        # Protocol for stdin/stdout/stderr
        return StreamProtocol(timeout=self._timeout)

    def _reinit(self):
        # Re-initialize for a new spawn()
        self._stdin = None
        self._stdout = None
        self._stderr = None
        self._exit_status = None
        self._term_signal = None
        self._child_exited.clear()

    @property
    def stdin(self):
        """The child's standard input, or None."""
        if self._stdin:
            return self._stdin[0]

    @property
    def stdout(self):
        """The child's standard output, or None."""
        if self._stdout:
            return self._stdout[0]

    @property
    def stderr(self):
        """The child's standard error, or None."""
        if self._stderr:
            return self._stderr[0]

    @property
    def returncode(self):
        """The child's exit status, or None if it has not exited yet.

        On Unix, if the child was terminated by a signal, return  ``-SIGNUM``.
        """
        if self._term_signal:
            return -self._term_signal
        return self._exit_status

    @property
    def pid(self):
        """The child's process ID, or None if there is no child."""
        if self._process is None:
            return
        return self._process.pid

    def _create_stdio(self, name, loop, handle, fd):
        # Create a pyuv.StdIO container
        if handle is None:
            stdio = pyuv.StdIO(fd=fd, flags=pyuv.UV_INHERIT_FD)
        elif handle == PIPE:
            stdio = pyuv.StdIO(stream=pyuv.Pipe(loop), flags=CREATE_PIPE)
        elif handle == DEVNULL:
            stdio = pyuv.StdIO(flags=pyuv.UV_IGNORE)
        elif isinstance(handle, int) and handle >= 0:
            stdio = pyuv.StdIO(fd=handle, flags=pyuv.UV_INHERIT_FD)
        elif hasattr(handle, 'fileno'):
            stdio = pyuv.StdIO(fd=handle.fileno(), flags=CREATE_PIPE)
        elif isinstance(handle, pyuv.Stream):
            stdio = pyuv.StdIO(stream=handle, flags=CREATE_PIPE)
        else:
            raise TypeError('{0}: must be PIPE, an fd, a Stream, or a file-like object'
                            ' (got {1!r})'.format(name, type(handle).__name__))
        return stdio

    def _get_stdio_handles(self, loop, stdin, stdout, stderr, extra_handles):
        # Return a list of StdIO containers that are passed to our child
        handles = []
        handles.append(self._create_stdio('stdin', loop, stdin, 0))
        handles.append(self._create_stdio('stdout', loop, stdout, 1))
        handles.append(self._create_stdio('stderr', loop, stderr, 2))
        if extra_handles:
            for ix, handle in enumerate(extra_handles):
                name = 'handles[{0}]'.format(ix)
                if handle is None or handle == PIPE:
                    raise TypeError('{0}: cannot be None or PIPE'.format(name))
                handles.append(self._create_stdio(name, loop, handle, None))
        return handles

    def _connect_stdio(self, stdio):
        # Connect a StdIO container to a StreamProtocol. Return the (possibly
        # wrapped) Stream
        transport, protocol = create_connection(self._protocol_factory, stdio.stream)
        if self._encoding:
            stream = TextIOWrapper(protocol.stream, self._encoding, **self._textio_args)
            if self._emulate_write_through:
                compat.make_textiowrapper_writethrough(stream)
        else:
            stream = protocol.stream
        return stream, transport, protocol

    def spawn(self, args, executable=None, stdin=None, stdout=None, stderr=None,
              shell=False, cwd=None, env=None, flags=0, extra_handles=None):
        """Spawn a new child process.

        The executable to spawn and its arguments are determined by *args*,
        *executable* and *shell*.

        When *shell* is set to ``False`` (the default), *args* is normally a
        sequence and it contains both the program to execute (at index 0), and
        its arguments.

        When *shell* is set to ``True``, then *args* is normally a string and
        it indicates the command to execute through the shell.

        The *executable* argument can be used to override the executable to
        execute. If *shell* is ``False``, it overrides ``args[0]``. This is
        sometimes used on Unix to implement "fat" executables that behave
        differently based on argv[0]. If *shell* is ``True``, it overrides the
        shell to use. The default shell is ``'/bin/sh'`` on Unix, and the value
        of $COMSPEC (or ``'cmd.exe'`` if it is unset) on Windows.

        The *stdin*, *stdout* and *stderr* arguments specify how to handle
        standard input, output, and error, respectively. If set to None, then
        the child will inherit our respective stdio handle. If set to the
        special constant ``PIPE`` then a pipe is created. The pipe will be
        connected to a :class:`gruvi.StreamProtocol` which you can use to read
        or write from it. The stream protocol instance is available under
        either :attr:`stdin`, :attr:`stdout` or :attr:`stderr`. All 3 stdio
        arguments can also be a file descriptor, a file-like object, or a pyuv
        ``Stream`` instance.

        The *extra_handles* specifies any extra handles to pass to the client.
        It must be a sequence where each element is either a file descriptor, a
        file-like objects, or a ``pyuv.Stream`` instance. The position in the
        sequence determines the file descriptor in the client. The first
        position corresponds to FD 3, the second to 4, etc. This places these
        file descriptors directly after the stdio handles.

        The *cwd* argument specifies the directory to change to before
        executing the child. If not provided, the current directory is used.

        The *env* argument specifies the environment to use when executing the
        child. If provided, it must be a dictionary. By default, the current
        environment is used.

        The *flags* argument can be used to specify optional libuv
        ``uv_process_flags``. The only relevant flags are
        ``pyuv.UV_PROCESS_DETACHED`` and ``pyuv.UV_PROCESS_WINDOWS_HIDE``. Both
        are Windows specific and are silently ignored on Unix.
        """
        self._reinit()
        hub = get_hub()
        if isinstance(args, str):
            args = [args]
            flags |= pyuv.UV_PROCESS_WINDOWS_VERBATIM_ARGUMENTS
        else:
            args = list(args)
        if shell:
            if hasattr(os, 'fork'):
                # Unix
                if executable is None:
                    executable = '/bin/sh'
                args = [executable, '-c'] + args
            else:
                # Windows
                if executable is None:
                    executable = os.environ.get('COMSPEC', 'cmd.exe')
                args = [executable, '/c'] + args
        if executable is None:
            executable = args[0]
        kwargs = {}
        if env is not None:
            kwargs['env'] = env
        if cwd is not None:
            kwargs['cwd'] = cwd
        kwargs['flags'] = flags
        stdio = self._get_stdio_handles(hub.loop, stdin, stdout, stderr, extra_handles)
        kwargs['stdio'] = stdio
        process = pyuv.Process(hub.loop)
        process.spawn(args, executable, exit_callback=self._on_child_exit, **kwargs)
        # Create stdin/stdout/stderr transports/protocols.
        if stdio[0].stream:
            self._stdin = self._connect_stdio(stdio[0])
        if stdio[1].stream:
            self._stdout = self._connect_stdio(stdio[1])
        if stdio[2].stream:
            self._stderr = self._connect_stdio(stdio[2])
        self._process = process

    def _on_child_exit(self, handle, exit_status, term_signal):
        # Callback used as the exit_callback with pyuv.Process
        self._exit_status = exit_status
        self._term_signal = term_signal
        self._process.close()
        self._process = None
        if self._stdin:
            self._stdin[1].close()
        if self._stdout:
            self._stdout[1].close()
        if self._stderr:
            self._stderr[1].close()
        self._child_exited.set()
        self.child_exited(exit_status, term_signal)

    def child_exited(self, exit_status, term_signal):
        """Callback that is called when the child has exited."""

    def send_signal(self, signum):
        """Send the signal *signum* to the child.

        On Windows, SIGTERM, SIGKILL and SIGINT are emulated using
        TerminateProcess(). This will cause the child to exit unconditionally
        with status 1. No other signals can be sent on Windows.
        """
        if not self._process:
            return
        self._process.kill(signum)

    def terminate(self):
        """Send a SIGTERM to the child."""
        self.send_signal(signal.SIGTERM)

    def kill(self):
        """Send a SIGKILL to the child."""
        # On Windows the signal module doesn't define SIGKILL
        sigkill = getattr(signal, 'SIGKILL', 9)
        self.send_signal(sigkill)

    @switchpoint
    def poll(self):
        """Check if the child has exited.

        This will run the event loop once to check if the child has exited.
        After that, return the value of the :attr:`returncode` attribute.
        """
        gruvi.sleep(0)
        return self.returncode

    @switchpoint
    def wait(self, timeout=-1):
        """Wait for the child to exit.

        Wait for at most *timeout* seconds, or indefinitely if *timeout* is
        None. Return the value of the :attr:`returncode` attribute.
        """
        if not self._process:
            return
        if timeout == -1:
            timeout = self._timeout
        self._child_exited.wait(timeout)
        return self.returncode

    @switchpoint
    def communicate(self, input=None, timeout=-1):
        """Communicate with the child and return its output.

        If *input* is provided, it is sent to the client. Concurrent with
        sending the input, the child's standard output and standard error are
        read, until the child exits.

        The return value is a tuple ``(stdout_data, stderr_data)`` containing
        the data read from standard output and standard error.
        """
        if timeout == -1:
            timeout = self._timeout
        output = [[], []]
        def writer(stream, data):
            offset = 0
            while offset < len(data):
                offset += stream.write(data[offset:])
            stream.close()
        def reader(stream, data):
            readfrom = (lambda s: s.read(4096)) if self._encoding else (lambda s: s.read1())
            while True:
                buf = readfrom(stream)
                if not buf:
                    break
                data.append(buf)
        if self.stdin:
            fibers.spawn(writer, self.stdin, input or b'')
        if self.stdout:
            fibers.spawn(reader, self.stdout, output[0])
        if self.stderr:
            fibers.spawn(reader, self.stderr, output[1])
        self.wait(timeout)
        empty = '' if self._encoding else b''
        stdout_data = empty.join(output[0])
        stderr_data = empty.join(output[1])
        return (stdout_data, stderr_data)
