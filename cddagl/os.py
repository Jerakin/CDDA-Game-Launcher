import os

if os.name == 'nt':
    from cddagl.win32 import *
elif os.name == 'posix':
    from cddagl.posix import *


