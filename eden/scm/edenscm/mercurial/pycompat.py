# Portions Copyright (c) Facebook, Inc. and its affiliates.
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2.

# pycompat.py - portability shim for python 3
#
# Copyright Matt Mackall <mpm@selenic.com> and others
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

"""Mercurial portability shim for python 3.

This contains aliases to hide python version-specific details from the core.
"""

from __future__ import absolute_import

import abc
import errno
import getopt
import os
import shlex
import sys


ispypy = r"__pypy__" in sys.builtin_module_names

if sys.version_info[0] < 3:
    import cookielib

    import cPickle as pickle

    import httplib

    import Queue as _queue

    import SocketServer as socketserver
else:
    import http.cookiejar as cookielib  # noqa: F401
    import http.client as httplib  # noqa: F401
    import pickle  # noqa: F401
    import queue as _queue
    import socketserver  # noqa: F401

empty = _queue.Empty
queue = _queue

basestring = tuple({type(""), type(b""), type(u"")})


def identity(a):
    return a


if sys.version_info[0] >= 3:
    import builtins
    import functools
    import io
    import struct

    oslinesep = os.linesep
    osname = os.name
    ospathsep = os.pathsep
    ossep = os.sep
    osaltsep = os.altsep
    getcwd = os.getcwd
    sysplatform = sys.platform
    sysexecutable = sys.executable

    stringio = io.BytesIO
    maplist = lambda *args: list(map(*args))
    ziplist = lambda *args: list(zip(*args))
    rawinput = input
    range = range

    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    stderr = sys.stderr.buffer

    sysargv = sys.argv

    bytechr = chr
    bytestr = str

    def raisewithtb(exc, tb):
        """Raise exception with the given traceback"""
        raise exc.with_traceback(tb)

    def getdoc(obj):
        """Get docstring as bytes; may be None so gettext() won't confuse it
        with _('')"""
        if isinstance(obj, str):
            return obj
        doc = getattr(obj, u"__doc__", None)
        return doc

    unicode = str
    shlexsplit = shlex.split

    def encodeutf8(s):
        # type: (str) -> bytes
        return s.encode("utf-8")

    def decodeutf8(s, errors="strict"):
        # type: (bytes, str) -> str
        return s.decode("utf-8", errors=errors)

    def iteritems(s):
        return s.items()

    def iterkeys(s):
        return s.keys()

    def itervalues(s):
        return s.values()

    def ensurestr(s):
        # type: Union[str, bytes] -> str
        if isinstance(s, bytes):
            s = s.decode("utf-8")
        return s

    from .pycompat3 import ABC


else:
    import cStringIO

    bytechr = chr
    bytestr = str
    range = xrange  # noqa: F821
    unicode = unicode

    # this can't be parsed on Python 3
    exec("def raisewithtb(exc, tb):\n" "    raise exc, None, tb\n")

    def getdoc(obj):
        if isinstance(obj, str):
            return obj
        return getattr(obj, "__doc__", None)

    def _getoptbwrapper(orig, args, shortlist, namelist):
        return orig(args, shortlist, namelist)

    oslinesep = os.linesep
    osname = os.name
    ospathsep = os.pathsep
    ossep = os.sep
    osaltsep = os.altsep
    stdin = sys.stdin
    stdout = sys.stdout
    stderr = sys.stderr
    if getattr(sys, "argv", None) is not None:
        sysargv = sys.argv
    sysplatform = sys.platform
    getcwd = os.getcwd
    sysexecutable = sys.executable
    shlexsplit = shlex.split
    stringio = cStringIO.StringIO
    maplist = map
    ziplist = zip
    rawinput = raw_input  # noqa

    def encodeutf8(s):
        # type: (bytes) -> bytes
        assert isinstance(s, bytes)
        return s

    def decodeutf8(s, errors="strict"):
        # type: (bytes, str) -> bytes
        assert isinstance(s, bytes)
        return s

    def iteritems(s):
        return s.iteritems()

    def iterkeys(s):
        return s.iterkeys()

    def itervalues(s):
        return s.itervalues()

    def ensurestr(s):
        # type: Union[str, unicode] -> str
        if isinstance(s, unicode):
            s = s.encode("utf-8")
        return s

    class ABC(object):
        __metaclass__ = abc.ABCMeta


isjython = sysplatform.startswith("java")

isdarwin = sysplatform == "darwin"
islinux = sysplatform.startswith("linux")
isposix = osname == "posix"
iswindows = osname == "nt"


def getoptb(args, shortlist, namelist):
    return _getoptbwrapper(getopt.getopt, args, shortlist, namelist)


def gnugetoptb(args, shortlist, namelist):
    return _getoptbwrapper(getopt.gnu_getopt, args, shortlist, namelist)


def getcwdsafe():
    """Returns the current working dir, or None if it has been deleted"""
    try:
        return getcwd()
    except OSError as err:
        if err.errno == errno.ENOENT:
            return None
        raise
