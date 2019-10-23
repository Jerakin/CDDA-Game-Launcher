import logging
import os
import re
import traceback
from io import StringIO

import cddagl
from cddagl.i18n import proxy_gettext as _

version = cddagl.__version__
logger = logging.getLogger('cddagl')


def log_exception(extype, value, tb):
    tb_io = StringIO()
    traceback.print_tb(tb, file=tb_io)

    logger.critical(_('Global error:\nLauncher version: {version}\nType: '
                      '{extype}\nValue: {value}\nTraceback:\n{traceback}').format(
        version=cddagl.__version__, extype=str(extype), value=str(value),
        traceback=tb_io.getvalue()))

def ensure_slash(path):
    """Return path making sure it has a trailing slash at the end."""
    return os.path.join(path, '')

def unique(seq):
    """Return unique entries in a unordered sequence while original order."""
    seen = set()
    for x in seq:
        if x not in seen:
            seen.add(x)
            yield x

def clean_qt_path(path):
    return os.path.realpath(path)

def safe_filename(filename):
    keepcharacters = (' ', '.', '_', '-')
    return ''.join(c for c in filename if c.isalnum() or c in keepcharacters
        ).strip()

def tryint(s):
    try:
        return int(s)
    except:
        return s

def alphanum_key(s):
    """ Turn a string into a list of string and number chunks.
        "z23a" -> ["z", 23, "a"]
    """
    return arstrip([tryint(c) for c in re.split('([0-9]+)', s)])

def arstrip(value):
    while len(value) > 1 and value[-1:] == ['']:
        value = value[:-1]
    return value

def is_64_windows():
    return 'PROGRAMFILES(X86)' in os.environ

def bitness():
    if is_64_windows():
        return _('64-bit')
    else:
        return _('32-bit')

def sizeof_fmt(num, suffix=None):
    if suffix is None:
        suffix = _('B')
    for unit in ['', _('Ki'), _('Mi'), _('Gi'), _('Ti'), _('Pi'), _('Ei'),
        _('Zi')]:
        if abs(num) < 1024.0:
            return "%3.1f %s%s" % (num, unit, suffix)
        num /= 1024.0
    return "%.1f %s%s" % (num, _('Yi'), suffix)


