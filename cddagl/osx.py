import os
import sys
import tempfile
import filecmp
import shutil
import locale
import psutil
import appdirs
import logging
from subprocess import Popen, PIPE, call
import plistlib
import tempfile
import send2trash

import posix_ipc
from posix_ipc import *

import cddagl.constants as cons

CDDASystemError = OSError
logger = logging.getLogger('cddagl')


class PathNotFoundException(Exception):
    pass


def get_downloads_directory():
    return os.path.join(os.path.expanduser("~"), 'Downloads')


def process_id_from_path(path):
    lower_path = path.lower()

    for proc in psutil.process_iter():
        try:
            if proc.name() == lower_path:
                return proc
        except psutil.Error:
            pass

    return None


def wait_for_pid(pid):
    raise NotImplementedError


# Find the process which is using the file handle
def find_process_with_file_handle(path):
    for proc in psutil.process_iter():
        for open_file in proc.open_files():
            if open_file.path == path:
                return {
                    'pid': proc.pid,
                    'image_file_name': open_file.path
                }

    return None


def get_ui_locale():
    try:
        return locale.getdefaultlocale()
    except ValueError:
        from os import environ
        if "LANG" not in environ:
            environ["LANG"] = "en_US.UTF-8"
            get_ui_locale()


def activate_window(pid):
    return True


def get_hwnds_for_pid(pid):
    raise NotImplementedError


class SingleInstance:
    def __init__(self):
        # cddagl_{64394E79-7931-49CB-B8CF-3F4ECAE16B6C}
        self.mutexname = 'cddagl_{64394E79-7931}'
        self.lasterror = 0
        self.mutex = 0
        try:
            self.mutex = posix_ipc.Semaphore(self.mutexname, O_CREAT)
        except ExistentialError:
            self.lasterror = 666

    def aleradyrunning(self):
        return (self.lasterror == 666)

    def close(self):
        # TODO: Investigate if this try statement is a bad idea
        if self.mutex:
            try:
                self.mutex.unlink()
            except posix_ipc.ExistentialError:
                pass
            self.mutex = None

    def __del__(self):
        self.close()


class SimpleNamedPipe:
    def __init__(self, name):
        self.name = name
        self.filename = os.path.join(tempfile.gettempdir(), name)
        self.pipe = None
        self.create_pipe()

    def create_pipe(self):
        filename = self.filename;
        try:
            os.mkfifo(filename)
        except OSError as e:
            pass

    def connect(self):
        self.pipe = os.open(self.filename, os.O_RDONLY)
        return True

    def read(self, size):
        return os.read(self.pipe, size)

    def close(self):
        if self.pipe:
            self.pipe.close()
            os.remove(self.filename)
            self.pipe = None

    def __del__(self):
        self.close()


def write_named_pipe(name, value):
    filename = os.path.join(tempfile.gettempdir(), name)
    os.mkfifo(filename)
    with os.open(filename, os.O_WRONLY) as f:
        f.write(value)


def delete_path(path):
    try:
        send2trash.send2trash(path)
        return True
    except send2trash.TrashPermissionError:
        return False


def move_path(srcpath, dstpath, show_progress=None):
    # TODO: Add progressbar
    is_file = os.path.isfile(srcpath)
    absolute_dst = os.path.join(dstpath, os.path.basename(srcpath))
    try:
        if is_file:
            logger.info("Moving a file")
            logger.info(srcpath)
            shutil.copy2(srcpath, dstpath)
            os.remove(srcpath)
        else:
            if os.path.exists(absolute_dst):
                logger.info("Cannot overwrite files - removing destination")
                logger.info(absolute_dst)
                shutil.rmtree(absolute_dst)
            if show_progress:
                shutil.copytree(srcpath,  absolute_dst, True, ignore=show_progress)
            else:
                shutil.copytree(srcpath, absolute_dst, True)

        return True
    except PermissionError as e:
        # TODO: This should return False if the folders are not equal
        # if not is_file:
        #     folder_equal = filecmp.cmp(srcpath, absolute_dst)
        #     if folder_equal or True:
        #         try:
        #             shutil.rmtree(srcpath)
        #         except OSError as e:
        #             logger.info("Could not remove file")
        #             logger.info(e)
        #             return True
        #         return True
        return True


def get_save_directory(_):
    return os.path.join(appdirs.AppDirs("Cataclysm").site_data_dir, "save")


def mount(dmg_path, use_shadow=False):
    """
    Attempts to mount the dmg at dmgpath
    and returns a list of mountpoints
    If use_shadow is true, mount image with shadow file
    """
    mount_points = []
    dmg_name = os.path.basename(dmg_path)
    cmd = ['/usr/bin/hdiutil', 'attach', dmg_path, '-mountRandom', tempfile.mkdtemp(prefix=cons.TEMP_PREFIX), '-plist',
           '-owners', 'on']

    if use_shadow:
        shadow_name = dmg_name + '.shadow'
        shadow_root = os.path.dirname(dmg_path)
        shadow_path = os.path.join(shadow_root, shadow_name)
        cmd.extend(['-shadow', shadow_path])
    else:
        shadow_path = None
    proc = Popen(cmd, bufsize=-1,
        stdout=PIPE, stderr=PIPE)
    (plist_str, err) = proc.communicate()

    if proc.returncode:
        logger.info("Error: {} while mounting {}".format(err, dmg_name))

    if plist_str:
        plist = plistlib.loads(plist_str)
        for entity in plist['system-entities']:
            if 'mount-point' in entity:
                mount_points.append(entity['mount-point'])

    return mount_points, shadow_path


def unmount(mount_point):
    """
    Unmounts the dmg at mountpoint
    """
    proc = Popen(['/usr/bin/hdiutil', 'detach', mount_point], bufsize=-1, stdout=PIPE, stderr=PIPE)
    (unused_output, err) = proc.communicate()
    if proc.returncode:
        logger.info("Polite unmount failed: {}".format(err))
        logger.info('Attempting to force unmount {}'.format(mount_point))
        # try forcing the unmount
        retcode = call(['/usr/bin/hdiutil', 'detach', mount_point,
                                '-force'])
        if retcode:
            logger.info('Failed to unmount {}'.format(mount_point))
