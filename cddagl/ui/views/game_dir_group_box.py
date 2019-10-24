import hashlib
import html
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from os import scandir


import arrow
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QStringListModel, QThread

from PyQt5.QtWidgets import (
    QApplication, QWidget, QGridLayout, QGroupBox, QLabel, QLineEdit,
    QPushButton, QFileDialog, QToolButton, QProgressBar,
    QComboBox, QMessageBox, QStyle, QHBoxLayout, QSizePolicy
)

from cddagl.system import CDDASystemError

import cddagl.constants as cons
from cddagl.constants import get_cddagl_path, get_cdda_uld_path
from cddagl.functions import sizeof_fmt, clean_qt_path, ensure_slash

from cddagl.i18n import proxy_ngettext as ngettext, proxy_gettext as _
from cddagl.sql.functions import (
    get_config_value, set_config_value, new_version, get_build_from_sha256,
    new_build, config_true
)
from cddagl.system import (
    activate_window, process_id_from_path, wait_for_pid, get_save_directory
)

logger = logging.getLogger('cddagl')


class GameDirGroupBox(QGroupBox):
    def __init__(self):
        super(GameDirGroupBox, self).__init__()

        self.shown = False
        self.exe_path = None
        self.restored_previous = False
        self.current_build = None

        self.exe_reading_timer = None
        self.update_saves_timer = None
        self.saves_size = 0

        self.dir_combo_inserting = False

        self.game_process = None
        self.game_process_id = None
        self.game_started = False

        layout = QGridLayout()

        dir_label = QLabel()
        layout.addWidget(dir_label, 0, 0, Qt.AlignRight)
        self.dir_label = dir_label

        self.layout_dir = QHBoxLayout()
        layout.addLayout(self.layout_dir, 0, 1)

        self.dir_combo = QComboBox()
        self.layout_dir.addWidget(self.dir_combo)
        self.dir_combo.setEditable(True)
        self.dir_combo.setInsertPolicy(QComboBox.InsertAtTop)
        self.dir_combo.currentIndexChanged.connect(self.dc_index_changed)
        self.dir_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        game_directories = json.loads(get_config_value('game_directories', '[]'))
        self.dir_combo_model = QStringListModel(game_directories, self)
        self.dir_combo.setModel(self.dir_combo_model)

        dir_change_button = QToolButton()
        self.layout_dir.addWidget(dir_change_button)
        dir_change_button.setText('...')
        dir_change_button.clicked.connect(self.set_game_directory)
        self.dir_change_button = dir_change_button

        self.dir_state_icon = QLabel()
        self.layout_dir.addWidget(self.dir_state_icon)
        self.dir_state_icon.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Minimum)
        self.dir_state_icon.hide()

        version_label = QLabel()
        layout.addWidget(version_label, 1, 0, Qt.AlignRight)
        self.version_label = version_label

        version_value_label = QLineEdit()
        version_value_label.setReadOnly(True)
        layout.addWidget(version_value_label, 1, 1)
        self.version_value_label = version_value_label

        build_label = QLabel()
        layout.addWidget(build_label, 2, 0, Qt.AlignRight)
        self.build_label = build_label

        build_value_label = QLineEdit()
        build_value_label.setReadOnly(True)
        build_value_label.setText(_('Unknown'))
        layout.addWidget(build_value_label, 2, 1)
        self.build_value_label = build_value_label

        saves_label = QLabel()
        layout.addWidget(saves_label, 3, 0, Qt.AlignRight)
        self.saves_label = saves_label

        saves_value_edit = QLineEdit()
        saves_value_edit.setReadOnly(True)
        saves_value_edit.setText(_('Unknown'))
        layout.addWidget(saves_value_edit, 3, 1)
        self.saves_value_edit = saves_value_edit

        saves_warning_label = QLabel()
        icon = QApplication.style().standardIcon(QStyle.SP_MessageBoxWarning)
        saves_warning_label.setPixmap(icon.pixmap(16, 16))
        saves_warning_label.hide()
        layout.addWidget(saves_warning_label, 3, 2)
        self.saves_warning_label = saves_warning_label

        buttons_container = QWidget()
        buttons_layout = QGridLayout()
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_container.setLayout(buttons_layout)

        launch_game_button = QPushButton()
        launch_game_button.setEnabled(False)
        launch_game_button.setStyleSheet("font-size: 20px;")
        launch_game_button.clicked.connect(self.launch_game)
        buttons_layout.addWidget(launch_game_button, 0, 0, 1, 3)
        self.launch_game_button = launch_game_button

        restore_button = QPushButton()
        restore_button.setEnabled(False)
        restore_button.clicked.connect(self.restore_previous)
        buttons_layout.addWidget(restore_button, 0, 3, 1, 1)
        self.restore_button = restore_button

        layout.addWidget(buttons_container, 4, 0, 1, 3)
        self.buttons_container = buttons_container
        self.buttons_layout = buttons_layout

        self.setLayout(layout)
        self.set_text()

    def set_text(self):
        self.dir_label.setText(_('Directory:'))
        self.version_label.setText(_('Version:'))
        self.build_label.setText(_('Build:'))
        self.saves_label.setText(_('Saves:'))
        self.saves_warning_label.setToolTip(
            _('Your save directory might be large '
            'enough to cause significant delays during the update process.\n'
            'You might want to enable the "Do not copy or move the save '
            'directory" option in the settings tab.'))
        self.launch_game_button.setText(_('Launch game'))
        self.restore_button.setText(_('Restore previous version'))
        self.setTitle(_('Game'))

    def set_dir_state_icon(self, state):
        style = QApplication.style()
        if state == 'critical':
            icon = style.standardIcon(QStyle.SP_MessageBoxCritical).pixmap(16, 16)
        elif state == 'warning':
            icon = style.standardIcon(QStyle.SP_MessageBoxWarning).pixmap(16, 16)
        elif state == 'ok':
            icon = style.standardIcon(QStyle.SP_DialogApplyButton).pixmap(16, 16)
        elif state == 'hide':
            self.dir_state_icon.hide()
            return

        self.dir_state_icon.setPixmap(icon)
        self.dir_state_icon.show()

    def showEvent(self, event):
        if not self.shown:
            self.shown = True

            self.last_game_directory = None

            if (getattr(sys, 'frozen', False)
                    and config_true(get_config_value('use_launcher_dir', 'False'))):
                game_directory = get_cdda_uld_path()

                self.dir_combo.setEnabled(False)
                self.dir_change_button.setEnabled(False)

                self.set_dir_combo_value(game_directory)
            else:
                game_directory = get_config_value('game_directory')
                if game_directory is None:
                    cddagl_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
                    default_dir = os.path.join(cddagl_path, 'cdda')
                    game_directory = default_dir

                self.set_dir_combo_value(game_directory)

            self.game_directory_changed()

        self.shown = True

    def set_dir_combo_value(self, value):
        dir_model = self.dir_combo.model()

        index_list = dir_model.match(dir_model.index(0, 0), Qt.DisplayRole,
            value, 1, Qt.MatchFixedString)
        if len(index_list) > 0:
            self.dir_combo.setCurrentIndex(index_list[0].row())
        else:
            self.dir_combo_inserting = True
            self.dir_combo.insertItem(0, value)
            self.dir_combo_inserting = False

            self.dir_combo.setCurrentIndex(0)

    def disable_controls(self):
        self.dir_combo.setEnabled(False)
        self.dir_change_button.setEnabled(False)

        self.launch_game_button.setEnabled(False)
        self.restore_button.setEnabled(False)

    def enable_controls(self):
        self.dir_combo.setEnabled(True)
        self.dir_change_button.setEnabled(True)

        self.launch_game_button.setEnabled(
            self.exe_path is not None and os.path.isfile(self.exe_path))

        directory = self.dir_combo.currentText()
        previous_version_dir = os.path.join(directory, 'previous_version')
        self.restore_button.setEnabled(os.path.isdir(previous_version_dir))

    def restore_previous(self):
        raise NotImplementedError

    def focus_game(self):
        raise NotImplementedError

    def launch_game(self):
        if self.game_started:
            return self.focus_game()

        if config_true(get_config_value('backup_on_launch', 'False')):
            main_tab = self.get_main_tab()
            backups_tab = main_tab.get_backups_tab()

            backups_tab.prune_auto_backups()

            name = '{auto}_{name}'.format(auto=_('auto'),
                                          name=_('before_launch'))

            backups_tab.after_backup = self.launch_game_process
            backups_tab.backup_saves(name)
        else:
            self.launch_game_process()

    def launch_game_process(self):
        if self.exe_path is None or not os.path.isfile(self.exe_path):
            main_window = self.get_main_window()
            status_bar = main_window.statusBar()

            status_bar.showMessage(_('Game executable not found'))

            self.launch_game_button.setEnabled(False)
            return

        self.get_main_window().setWindowState(Qt.WindowMinimized)
        exe_dir = os.path.dirname(self.exe_path)

        params = get_config_value('command.params', '').strip()
        if params != '':
            params = ' ' + params

        cmd = '{exe_path}{params}'.format(exe_path=self.executable, params=params)

        try:
            # game_process = subprocess.Popen(cmd, cwd=exe_dir, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
            game_process = subprocess.Popen(cmd, cwd=exe_dir)
        except OSError as e:
            main_window = self.get_main_window()
            status_bar = main_window.statusBar()

            status_bar.showMessage(_('Could not launch the game executable'))

            error_msgbox = QMessageBox()
            error_msgbox.setWindowTitle(_('Cannot launch game'))

            text = _('''
<p>The launcher failed to start the game executable in <strong>{filename}</strong> .</p>
<p>It received the following error from the operating system: {error}</p>
<p>Poor antivirus products are known to detect the game binary as a threat and
block its execution. A simple workaround is to add the game binary in your
antivirus whitelist or select the action to trust this binary when detected.</p>
''').format(
                filename=html.escape(e.filename or _('[unknown]')),
                error=html.escape(e.strerror))

            error_msgbox.setText(text)
            error_msgbox.addButton(_('OK'), QMessageBox.YesRole)
            error_msgbox.setIcon(QMessageBox.Critical)

            error_msgbox.exec()
            return

        self.game_process = game_process
        self.game_started = True

        if not config_true(get_config_value('keep_launcher_open', 'False')):
            self.get_main_window().close()
        else:
            main_window = self.get_main_window()
            status_bar = main_window.statusBar()

            status_bar.showMessage(_('Game process is running'))

            main_tab = self.get_main_tab()
            update_group_box = main_tab.update_group_box

            self.disable_controls()
            update_group_box.disable_controls(True)

            soundpacks_tab = main_tab.get_soundpacks_tab()
            mods_tab = main_tab.get_mods_tab()
            settings_tab = main_tab.get_settings_tab()
            backups_tab = main_tab.get_backups_tab()

            soundpacks_tab.disable_tab()
            mods_tab.disable_tab()
            settings_tab.disable_tab()
            backups_tab.disable_tab()

            self.launch_game_button.setText(_('Show current game'))
            self.launch_game_button.setEnabled(True)

            class ProcessWaitThread(QThread):
                ended = pyqtSignal()

                def __init__(self, process):
                    super(ProcessWaitThread, self).__init__()

                    self.process = process

                def __del__(self):
                    self.wait()

                def run(self):
                    self.process.wait()
                    self.ended.emit()

            def process_ended():
                self.game_ended()

            process_wait_thread = ProcessWaitThread(self.game_process)
            process_wait_thread.ended.connect(process_ended)
            process_wait_thread.start()

            self.process_wait_thread = process_wait_thread

    def game_ended(self):
        raise NotImplementedError

    def find_executable(self, directory):
        raise NotImplementedError

    def update_version(self):
        raise NotImplementedError

    def check_running_process(self, exe_path):
        # TODO: Verify that this works on OSX
        pid = process_id_from_path(exe_path)

        if pid is not None:
            self.game_started = True
            self.game_process_id = pid

            main_window = self.get_main_window()
            status_bar = main_window.statusBar()

            if status_bar.busy == 0:
                status_bar.showMessage(_('Game process is running'))

            main_tab = self.get_main_tab()
            update_group_box = main_tab.update_group_box

            self.disable_controls()
            update_group_box.disable_controls(True)

            soundpacks_tab = main_tab.get_soundpacks_tab()
            mods_tab = main_tab.get_mods_tab()
            settings_tab = main_tab.get_settings_tab()
            backups_tab = main_tab.get_backups_tab()

            soundpacks_tab.disable_tab()
            mods_tab.disable_tab()
            settings_tab.disable_tab()
            backups_tab.disable_tab()

            self.launch_game_button.setText(_('Show current game'))
            self.launch_game_button.setEnabled(True)

            class ProcessWaitThread(QThread):
                ended = pyqtSignal()

                def __init__(self, pid):
                    super(ProcessWaitThread, self).__init__()

                    self.pid = pid

                def __del__(self):
                    self.wait()

                def run(self):
                    wait_for_pid(self.pid)
                    self.ended.emit()

            def process_ended():
                self.process_wait_thread = None

                self.game_process_id = None
                self.game_started = False

                status_bar.showMessage(_('Game process has ended'))

                self.enable_controls()
                update_group_box.enable_controls()

                soundpacks_tab.enable_tab()
                mods_tab.enable_tab()
                settings_tab.enable_tab()
                backups_tab.enable_tab()

                self.launch_game_button.setText(_('Launch game'))

                self.get_main_window().setWindowState(Qt.WindowActive)

                self.update_saves()

                if config_true(get_config_value('backup_on_end', 'False')):
                    backups_tab.prune_auto_backups()

                    name = '{auto}_{name}'.format(auto=_('auto'),
                                                  name=_('after_end'))

                    backups_tab.backup_saves(name)

            process_wait_thread = ProcessWaitThread(self.game_process_id)
            process_wait_thread.ended.connect(process_ended)
            process_wait_thread.start()

            self.process_wait_thread = process_wait_thread

    def add_game_dir(self):
        new_game_dir = self.dir_combo.currentText()

        game_dirs = json.loads(get_config_value('game_directories', '[]'))

        try:
            index = game_dirs.index(new_game_dir)
            if index > 0:
                del game_dirs[index]
                game_dirs.insert(0, new_game_dir)
        except ValueError:
            game_dirs.insert(0, new_game_dir)

        if len(game_dirs) > cons.MAX_GAME_DIRECTORIES:
            del game_dirs[cons.MAX_GAME_DIRECTORIES:]

        set_config_value('game_directories', json.dumps(game_dirs))

    def update_saves(self):
        # TODO: OSX Does not find the saves properly
        # TODO: We should maybe not backup the saves in the same way on OS/WIN

        self.game_dir = self.dir_combo.currentText()

        if (self.update_saves_timer is not None and self.update_saves_timer.isActive()):
            self.update_saves_timer.stop()
            self.saves_value_edit.setText(_('Unknown'))

        save_dir = get_save_directory(self.game_dir)
        if not os.path.isdir(save_dir):
            self.saves_value_edit.setText(
                '{world_count} {worlds} - {character_count} {characters}'
                    .format(
                    world_count=0,
                    character_count=0,
                    worlds=ngettext('World', 'Worlds', 0),
                    characters=ngettext('Character', 'Characters', 0)
                )
            )
            return

        timer = QTimer(self)
        self.update_saves_timer = timer

        self.saves_size = 0
        self.saves_worlds = 0
        self.saves_characters = 0
        self.world_dirs = set()

        self.saves_scan = scandir(save_dir)
        self.next_scans = []
        self.save_dir = save_dir

        def timeout():
            try:
                entry = next(self.saves_scan)
                if entry.is_dir():
                    self.next_scans.append(entry.path)
                elif entry.is_file():
                    self.saves_size += entry.stat().st_size

                    if entry.name.endswith('.sav'):
                        world_dir = os.path.dirname(entry.path)
                        if self.save_dir == os.path.dirname(world_dir):
                            self.saves_characters += 1

                    if entry.name in cons.WORLD_FILES:
                        world_dir = os.path.dirname(entry.path)
                        if (world_dir not in self.world_dirs
                                and self.save_dir == os.path.dirname(world_dir)):
                            self.world_dirs.add(world_dir)
                            self.saves_worlds += 1

                worlds_text = ngettext('World', 'Worlds', self.saves_worlds)
                characters_text = ngettext('Character', 'Characters', self.saves_characters)
                self.saves_value_edit.setText(
                    '{world_count} {worlds} - {character_count} {characters} ({size})'
                        .format(
                        world_count=self.saves_worlds,
                        character_count=self.saves_characters,
                        size=sizeof_fmt(self.saves_size),
                        worlds=worlds_text,
                        characters=characters_text
                    )
                )
            except StopIteration:
                if len(self.next_scans) > 0:
                    self.saves_scan = scandir(self.next_scans.pop())
                else:
                    # End of the tree
                    self.update_saves_timer.stop()
                    self.update_saves_timer = None

                    # no more path to scan but still 0 chars/worlds
                    if self.saves_worlds == 0 and self.saves_characters == 0:
                        self.saves_value_edit.setText(
                            '{world_count} {worlds} - {character_count} {characters}'
                                .format(
                                world_count=0,
                                character_count=0,
                                worlds=ngettext('World', 'Worlds', 0),
                                characters=ngettext('Character', 'Characters', 0)
                            )
                        )

                    # Warning about saves size
                    if (self.saves_size > cons.SAVES_WARNING_SIZE and
                            not config_true(get_config_value('prevent_save_move', 'False'))):
                        self.saves_warning_label.show()
                    else:
                        self.saves_warning_label.hide()

        timer.timeout.connect(timeout)
        timer.start(0)

    def analyse_new_build(self, build):
        raise NotImplementedError

    def get_main_tab(self):
        return self.parentWidget()

    def get_main_window(self):
        return self.get_main_tab().get_main_window()

    def update_soundpacks(self):
        main_window = self.get_main_window()
        central_widget = main_window.central_widget
        soundpacks_tab = central_widget.soundpacks_tab

        directory = self.dir_combo.currentText()
        soundpacks_tab.game_dir_changed(directory)

    def update_mods(self):
        main_window = self.get_main_window()
        central_widget = main_window.central_widget
        mods_tab = central_widget.mods_tab

        directory = self.dir_combo.currentText()
        mods_tab.game_dir_changed(directory)

    def update_backups(self):
        main_window = self.get_main_window()
        central_widget = main_window.central_widget
        backups_tab = central_widget.backups_tab

        directory = self.dir_combo.currentText()
        backups_tab.game_dir_changed(directory)

    def clear_soundpacks(self):
        main_window = self.get_main_window()
        central_widget = main_window.central_widget
        soundpacks_tab = central_widget.soundpacks_tab

        soundpacks_tab.clear_soundpacks()

    def clear_mods(self):
        main_window = self.get_main_window()
        central_widget = main_window.central_widget
        mods_tab = central_widget.mods_tab

        mods_tab.clear_mods()

    def clear_backups(self):
        main_window = self.get_main_window()
        central_widget = main_window.central_widget
        backups_tab = central_widget.backups_tab

        backups_tab.clear_backups()

    def set_game_directory(self):
        options = QFileDialog.DontResolveSymlinks | QFileDialog.ShowDirsOnly
        directory = QFileDialog.getExistingDirectory(self,
                _('Game directory'), self.dir_combo.currentText(),
                options=options)
        if directory:
            self.set_dir_combo_value(clean_qt_path(directory))

    def dc_index_changed(self, index):
        if self.shown and not self.dir_combo_inserting:
            self.game_directory_changed()

    def game_directory_changed(self):
        logger.info("Game Directory Changed")
        # Todo: OSX - Find game version
        directory = self.dir_combo.currentText()

        main_window = self.get_main_window()
        status_bar = main_window.statusBar()
        status_bar.clearMessage()
        self.set_dir_state_icon('hide')

        self.exe_path = None

        main_tab = self.get_main_tab()
        update_group_box = main_tab.update_group_box

        dir_state = None
        if ensure_slash(get_cddagl_path()).startswith(ensure_slash(directory)):
            dir_state = 'critical'
            self.set_dir_state_icon(dir_state)
            self.version_value_label.setText(
                _('Unknown version - Reason:') + ' ' +
                _('CDDA Game Launcher files cannot be inside Game directory!')
            )
        elif os.path.isfile(directory):
            dir_state = 'critical'
            self.set_dir_state_icon(dir_state)
            self.version_value_label.setText(
                _('Unknown version - Reason:') + ' ' +
                _('Game directory was set to a file!')
            )
        elif not os.path.isdir(directory):
            dir_state = 'warning'
            self.set_dir_state_icon(dir_state)
            self.version_value_label.setText(
                _('Unknown version - Reason:') + ' ' +
                _("Game directory doesn't exist, Game is not installed here.")
            )
        else:
            # Check for previous version
            previous_version_dir = os.path.join(directory, 'previous_version')
            self.restore_button.setEnabled(os.path.isdir(previous_version_dir))
            logging.info("Checking for previous version")

            # Finding the executable depending on OS
            self.find_executable(directory)

            if self.version_type is None:
                dir_state = 'warning'
                self.set_dir_state_icon(dir_state)
                self.version_value_label.setText(
                    _('Unknown version - Reason:') + ' ' +
                    _("Game is not installed in this directory.")
                )
            else:
                dir_state = "ok"
                if self.last_game_directory != directory:
                    self.version_value_label.setText(_('Analyzing...'))
                    self.build_value_label.setText(_('Analyzing...'))
                    self.saves_value_edit.setText(_('Analyzing...'))
                    self.update_version()
                    self.update_saves()
                    self.update_soundpacks()
                    self.update_mods()
                    self.update_backups()

            if self.exe_path is None:
                self.launch_game_button.setEnabled(False)
                update_group_box.update_button.setText(_('Install game'))
                update_group_box.update_button.setEnabled(dir_state != 'critical')

                self.restored_previous = False

                self.current_build = None
                self.build_value_label.setText(_('Unknown'))
                self.saves_value_edit.setText(_('Unknown'))
                self.clear_soundpacks()
                self.clear_mods()
                self.clear_backups()
            else:

                self.launch_game_button.setEnabled(True)
                update_group_box.update_button.setText(_('Update game'))
                update_group_box.update_button.setEnabled(dir_state == 'ok')

                self.check_running_process(self.exe_path)

            self.last_game_directory = directory
            if not (getattr(sys, 'frozen', False)
                    and config_true(get_config_value('use_launcher_dir', 'False'))):
                set_config_value('game_directory', directory)

    @property
    def app_locale(self):
        return QApplication.instance().app_locale

    @property
    def executable(self):
        return '"{}"'.format(self.exe_path)


class GameDirGroupBoxOSX(GameDirGroupBox):
    def __init__(self):
        super(GameDirGroupBoxOSX, self).__init__()

    def restore_previous(self):
        raise NotImplementedError

    def focus_game(self):
        raise NotImplementedError

    def game_ended(self):
        raise NotImplementedError

    def find_executable(self, directory):
        console_exe = os.path.join(directory, 'Cataclysm.app', "Contents", "Resources", "cataclysm")
        tiles_exe = os.path.join(directory, 'Cataclysm.app', "Contents", "Resources", "cataclysm-tiles")
        exe_path = None
        version_type = None
        if os.path.isfile(console_exe):
            version_type = _('console')
            exe_path = console_exe
        elif os.path.isfile(tiles_exe):
            version_type = _('tiles')
            exe_path = tiles_exe

        self.exe_path = exe_path
        self.version_type = version_type

    @property
    def executable(self):
        return os.path.join(os.path.dirname(self.exe_path), "..", "MacOS", "Cataclysm.sh")

    def update_version(self):

        main_window = self.get_main_window()
        status_bar = main_window.statusBar()

        if (self.exe_reading_timer is not None
                and self.exe_reading_timer.isActive()):
            self.exe_reading_timer.stop()

            status_bar = main_window.statusBar()
            status_bar.removeWidget(self.reading_label)
            status_bar.removeWidget(self.reading_progress_bar)

            status_bar.busy -= 1

        status_bar.clearMessage()
        status_bar.busy += 1

        reading_label = QLabel()
        reading_label.setText(_('Reading: {0}').format(self.exe_path))
        status_bar.addWidget(reading_label, 100)
        self.reading_label = reading_label

        progress_bar = QProgressBar()
        status_bar.addWidget(progress_bar)
        self.reading_progress_bar = progress_bar

        timer = QTimer(self)
        self.exe_reading_timer = timer

        exe_size = os.path.getsize(self.exe_path)

        progress_bar.setRange(0, exe_size)
        self.exe_total_read = 0

        self.exe_sha256 = hashlib.sha256()
        self.last_bytes = None
        self.game_version = ''
        self.opened_exe = open(self.exe_path, 'rb')

        def timeout():
            bytes = self.opened_exe.read(cons.READ_BUFFER_SIZE)
            if len(bytes) == 0:
                self.opened_exe.close()
                self.exe_reading_timer.stop()
                main_window = self.get_main_window()
                status_bar = main_window.statusBar()

                status_bar.removeWidget(self.reading_label)
                status_bar.removeWidget(self.reading_progress_bar)

                status_bar.busy -= 1
                if status_bar.busy == 0 and not self.game_started:
                    if self.restored_previous:
                        status_bar.showMessage(
                            _('Previous version restored'))
                    else:
                        status_bar.showMessage(_('Ready'))

                if status_bar.busy == 0 and self.game_started:
                    status_bar.showMessage(_('Game process is running'))

                sha256 = self.exe_sha256.hexdigest()

                stable_version = cons.STABLE_SHA256.get(sha256, None)
                is_stable = stable_version is not None

                if is_stable:
                    self.game_version = stable_version
                    logger.info("Game Version is stable")
                if self.game_version == '':
                    self.game_version = _('Unknown')
                    logger.info("Game Version is Unknown")
                else:
                    logger.info("Game Version is ?")
                    self.add_game_dir()

                self.version_value_label.setText(
                    '{version} ({type})'
                        .format(version=self.game_version, type=self.version_type)
                )

                new_version(self.game_version, sha256, is_stable)

                build = get_build_from_sha256(sha256)

                if build is not None:
                    build_date = arrow.get(build['released_on'], 'UTC')
                    human_delta = build_date.humanize(arrow.utcnow(), locale=self.app_locale)
                    self.build_value_label.setText(
                        '{build} ({time_delta})'
                            .format(build=build['build'], time_delta=human_delta)
                    )
                    self.current_build = build['build']

                    main_tab = self.get_main_tab()
                    update_group_box = main_tab.update_group_box

                    if (update_group_box.builds is not None
                            and len(update_group_box.builds) > 0
                            and status_bar.busy == 0
                            and not self.game_started):
                        last_build = update_group_box.builds[0]

                        message = status_bar.currentMessage()
                        if message != '':
                            message = message + ' - '

                        if last_build['number'] == self.current_build:
                            message = message + _('Your game is up to date')
                        else:
                            message = message + _('There is a new update available')
                        status_bar.showMessage(message)

                else:
                    self.build_value_label.setText(_('Unknown'))
                    self.current_build = None

            else:
                last_frame = bytes
                if self.last_bytes is not None:
                    last_frame = self.last_bytes + last_frame

                match = re.search(
                    b'(?P<version>[01]\\.[A-F](-\\d+-g[0-9a-f]+)?)\\x00',
                    last_frame)
                if match is not None:
                    game_version = match.group('version').decode('ascii')
                    if len(game_version) > len(self.game_version):
                        self.game_version = game_version

                self.exe_total_read += len(bytes)
                self.reading_progress_bar.setValue(self.exe_total_read)
                self.exe_sha256.update(bytes)
                self.last_bytes = bytes

        timer.timeout.connect(timeout)
        timer.start(0)

    def analyse_new_build(self, build):
        game_dir = self.dir_combo.currentText()

        self.previous_exe_path = self.exe_path
        self.exe_path = None

        self.find_executable(game_dir)

        if self.version_type is None:
            self.version_value_label.setText(_('Not a CDDA directory'))
            self.build_value_label.setText(_('Unknown'))
            self.current_build = None

            main_tab = self.get_main_tab()
            update_group_box = main_tab.update_group_box
            update_group_box.finish_updating()

            self.launch_game_button.setEnabled(False)

            main_window = self.get_main_window()
            status_bar = main_window.statusBar()
            status_bar.showMessage(_('No executable found in the downloaded '
                                     'archive. You might want to restore your previous version.'))

        else:
            if (self.exe_reading_timer is not None
                    and self.exe_reading_timer.isActive()):
                self.exe_reading_timer.stop()

                main_window = self.get_main_window()
                status_bar = main_window.statusBar()
                status_bar.removeWidget(self.reading_label)
                status_bar.removeWidget(self.reading_progress_bar)

                status_bar.busy -= 1

            self.build_number = build['number']
            self.build_date = build['date']

            main_window = self.get_main_window()

            status_bar = main_window.statusBar()
            status_bar.clearMessage()

            status_bar.busy += 1

            reading_label = QLabel()
            reading_label.setText(_('Reading: {0}').format(self.exe_path))
            status_bar.addWidget(reading_label, 100)
            self.reading_label = reading_label

            progress_bar = QProgressBar()
            status_bar.addWidget(progress_bar)
            self.reading_progress_bar = progress_bar

            timer = QTimer(self)
            self.exe_reading_timer = timer

            exe_size = os.path.getsize(self.exe_path)

            progress_bar.setRange(0, exe_size)
            self.exe_total_read = 0

            self.exe_sha256 = hashlib.sha256()
            self.last_bytes = None
            self.game_version = ''
            self.opened_exe = open(self.exe_path, 'rb')

            def timeout():
                bytes = self.opened_exe.read(cons.READ_BUFFER_SIZE)
                if len(bytes) == 0:
                    self.opened_exe.close()
                    self.exe_reading_timer.stop()
                    main_window = self.get_main_window()
                    status_bar = main_window.statusBar()

                    build_date = arrow.get(self.build_date, 'UTC')
                    human_delta = build_date.humanize(arrow.utcnow(), locale=self.app_locale)
                    self.build_value_label.setText(
                        '{build} ({time_delta})'
                            .format(build=self.build_number, time_delta=human_delta)
                    )
                    self.current_build = self.build_number

                    status_bar.removeWidget(self.reading_label)
                    status_bar.removeWidget(self.reading_progress_bar)

                    status_bar.busy -= 1

                    sha256 = self.exe_sha256.hexdigest()

                    stable_version = cons.STABLE_SHA256.get(sha256, None)
                    is_stable = stable_version is not None

                    if is_stable:
                        self.game_version = stable_version

                    if self.game_version == '':
                        self.game_version = _('Unknown')
                    self.version_value_label.setText(
                        '{version} ({type})'
                            .format(version=self.game_version, type=self.version_type)
                    )

                    new_build(self.game_version, sha256, is_stable, self.build_number,
                              self.build_date)

                    main_tab = self.get_main_tab()
                    update_group_box = main_tab.update_group_box

                    update_group_box.post_extraction()

                else:
                    last_frame = bytes
                    if self.last_bytes is not None:
                        last_frame = self.last_bytes + last_frame

                    match = re.search(
                        b'(?P<version>[01]\\.[A-F](-\\d+-g[0-9a-f]+)?)\\x00',
                        last_frame)
                    if match is not None:
                        game_version = match.group('version').decode('ascii')
                        if len(game_version) > len(self.game_version):
                            self.game_version = game_version

                    self.exe_total_read += len(bytes)
                    self.reading_progress_bar.setValue(self.exe_total_read)
                    self.exe_sha256.update(bytes)
                    self.last_bytes = bytes

            timer.timeout.connect(timeout)
            timer.start(0)


class GameDirGroupBoxWin(GameDirGroupBox):
    def __init__(self):
        super(GameDirGroupBoxWin, self).__init__()

    def restore_previous(self):
        self.disable_controls()

        main_tab = self.get_main_tab()
        update_group_box = main_tab.update_group_box
        update_group_box.disable_controls(True)

        self.restored_previous = False

        try:
            game_dir = self.dir_combo.currentText()
            previous_version_dir = os.path.join(game_dir, 'previous_version')

            if os.path.isdir(previous_version_dir) and os.path.isdir(game_dir):

                with tempfile.TemporaryDirectory(prefix=cons.TEMP_PREFIX
                                                 ) as temp_move_dir:

                    excluded_entries = set(['previous_version'])
                    if config_true(get_config_value('prevent_save_move',
                                                    'False')):
                        excluded_entries.add('save')

                    # Prevent moving the launcher if it's in the game directory
                    if getattr(sys, 'frozen', False):
                        launcher_exe = os.path.abspath(sys.executable)
                        launcher_dir = os.path.dirname(launcher_exe)
                        if os.path.abspath(game_dir) == launcher_dir:
                            excluded_entries.add(os.path.basename(launcher_exe))

                    for entry in os.listdir(game_dir):
                        if entry not in excluded_entries:
                            entry_path = os.path.join(game_dir, entry)
                            shutil.move(entry_path, temp_move_dir)

                    excluded_entries = set()
                    if config_true(get_config_value('prevent_save_move', 'False')):
                        excluded_entries.add('save')
                    for entry in os.listdir(previous_version_dir):
                        if entry not in excluded_entries:
                            entry_path = os.path.join(previous_version_dir, entry)
                            shutil.move(entry_path, game_dir)

                    for entry in os.listdir(temp_move_dir):
                        entry_path = os.path.join(temp_move_dir, entry)
                        shutil.move(entry_path, previous_version_dir)

                self.restored_previous = True
        except OSError as e:
            main_window = self.get_main_window()
            status_bar = main_window.statusBar()

            status_bar.showMessage(str(e))

        self.last_game_directory = None
        self.enable_controls()
        update_group_box.enable_controls()
        self.game_directory_changed()

    def focus_game(self):
        if self.game_process is None and self.game_process_id is None:
            return

        if self.game_process is not None:
            pid = self.game_process.pid
        elif self.game_process_id is not None:
            pid = self.game_process_id

        try:
            activate_window(pid)
        except (OSError, CDDASystemError):
            # Can't activate window, we will assume that the game ended
            self.game_ended()

    def game_ended(self):
        if self.process_wait_thread is not None:
            self.process_wait_thread.quit()
            self.process_wait_thread = None

        self.game_process = None
        self.game_started = False

        main_window = self.get_main_window()
        status_bar = main_window.statusBar()

        status_bar.showMessage(_('Game process has ended'))

        main_tab = self.get_main_tab()
        update_group_box = main_tab.update_group_box

        soundpacks_tab = main_tab.get_soundpacks_tab()
        mods_tab = main_tab.get_mods_tab()
        settings_tab = main_tab.get_settings_tab()
        backups_tab = main_tab.get_backups_tab()

        self.enable_controls()
        update_group_box.enable_controls()

        soundpacks_tab.enable_tab()
        mods_tab.enable_tab()
        settings_tab.enable_tab()
        backups_tab.enable_tab()

        self.launch_game_button.setText(_('Launch game'))

        self.get_main_window().setWindowState(Qt.WindowActive)

        self.update_saves()

        if config_true(get_config_value('backup_on_end', 'False')):
            backups_tab.prune_auto_backups()

            name = '{auto}_{name}'.format(auto=_('auto'),
                                          name=_('after_end'))

            backups_tab.backup_saves(name)

    def update_version(self):
        main_window = self.get_main_window()
        status_bar = main_window.statusBar()

        if (self.exe_reading_timer is not None
                and self.exe_reading_timer.isActive()):
            self.exe_reading_timer.stop()

            status_bar = main_window.statusBar()
            status_bar.removeWidget(self.reading_label)
            status_bar.removeWidget(self.reading_progress_bar)

            status_bar.busy -= 1

        status_bar.clearMessage()
        status_bar.busy += 1

        reading_label = QLabel()
        reading_label.setText(_('Reading: {0}').format(self.exe_path))
        status_bar.addWidget(reading_label, 100)
        self.reading_label = reading_label

        progress_bar = QProgressBar()
        status_bar.addWidget(progress_bar)
        self.reading_progress_bar = progress_bar

        timer = QTimer(self)
        self.exe_reading_timer = timer

        exe_size = os.path.getsize(self.exe_path)

        progress_bar.setRange(0, exe_size)
        self.exe_total_read = 0

        self.exe_sha256 = hashlib.sha256()
        self.last_bytes = None
        self.game_version = ''
        self.opened_exe = open(self.exe_path, 'rb')

        def timeout():
            bytes = self.opened_exe.read(cons.READ_BUFFER_SIZE)
            if len(bytes) == 0:
                self.opened_exe.close()
                self.exe_reading_timer.stop()
                main_window = self.get_main_window()
                status_bar = main_window.statusBar()

                status_bar.removeWidget(self.reading_label)
                status_bar.removeWidget(self.reading_progress_bar)

                status_bar.busy -= 1
                if status_bar.busy == 0 and not self.game_started:
                    if self.restored_previous:
                        status_bar.showMessage(
                            _('Previous version restored'))
                    else:
                        status_bar.showMessage(_('Ready'))

                if status_bar.busy == 0 and self.game_started:
                    status_bar.showMessage(_('Game process is running'))

                sha256 = self.exe_sha256.hexdigest()

                stable_version = cons.STABLE_SHA256.get(sha256, None)
                is_stable = stable_version is not None

                if is_stable:
                    self.game_version = stable_version

                if self.game_version == '':
                    self.game_version = _('Unknown')
                else:
                    self.add_game_dir()

                self.version_value_label.setText(
                    '{version} ({type})'
                        .format(version=self.game_version, type=self.version_type)
                )

                new_version(self.game_version, sha256, is_stable)

                build = get_build_from_sha256(sha256)

                if build is not None:
                    build_date = arrow.get(build['released_on'], 'UTC')
                    human_delta = build_date.humanize(arrow.utcnow(), locale=self.app_locale)
                    self.build_value_label.setText(
                        '{build} ({time_delta})'
                            .format(build=build['build'], time_delta=human_delta)
                    )
                    self.current_build = build['build']

                    main_tab = self.get_main_tab()
                    update_group_box = main_tab.update_group_box

                    if (update_group_box.builds is not None
                            and len(update_group_box.builds) > 0
                            and status_bar.busy == 0
                            and not self.game_started):
                        last_build = update_group_box.builds[0]

                        message = status_bar.currentMessage()
                        if message != '':
                            message = message + ' - '

                        if last_build['number'] == self.current_build:
                            message = message + _('Your game is up to date')
                        else:
                            message = message + _('There is a new update available')
                        status_bar.showMessage(message)

                else:
                    self.build_value_label.setText(_('Unknown'))
                    self.current_build = None

            else:
                last_frame = bytes
                if self.last_bytes is not None:
                    last_frame = self.last_bytes + last_frame

                match = re.search(
                    b'(?P<version>[01]\\.[A-F](-\\d+-g[0-9a-f]+)?)\\x00',
                    last_frame)
                if match is not None:
                    game_version = match.group('version').decode('ascii')
                    if len(game_version) > len(self.game_version):
                        self.game_version = game_version

                self.exe_total_read += len(bytes)
                self.reading_progress_bar.setValue(self.exe_total_read)
                self.exe_sha256.update(bytes)
                self.last_bytes = bytes

        timer.timeout.connect(timeout)
        timer.start(0)

    def analyse_new_build(self, build):
        game_dir = self.dir_combo.currentText()

        self.previous_exe_path = self.exe_path
        self.exe_path = None

        console_exe = os.path.join(game_dir, 'cataclysm.exe')
        tiles_exe = os.path.join(game_dir, 'cataclysm-tiles.exe')

        exe_path = None
        version_type = None
        if os.path.isfile(console_exe):
            version_type = _('console')
            exe_path = console_exe
        elif os.path.isfile(tiles_exe):
            version_type = _('tiles')
            exe_path = tiles_exe

        if version_type is None:
            self.version_value_label.setText(_('Not a CDDA directory'))
            self.build_value_label.setText(_('Unknown'))
            self.current_build = None

            main_tab = self.get_main_tab()
            update_group_box = main_tab.update_group_box
            update_group_box.finish_updating()

            self.launch_game_button.setEnabled(False)

            main_window = self.get_main_window()
            status_bar = main_window.statusBar()
            status_bar.showMessage(_('No executable found in the downloaded '
                                     'archive. You might want to restore your previous version.'))

        else:
            if (self.exe_reading_timer is not None
                    and self.exe_reading_timer.isActive()):
                self.exe_reading_timer.stop()

                main_window = self.get_main_window()
                status_bar = main_window.statusBar()
                status_bar.removeWidget(self.reading_label)
                status_bar.removeWidget(self.reading_progress_bar)

                status_bar.busy -= 1

            self.exe_path = exe_path
            self.version_type = version_type
            self.build_number = build['number']
            self.build_date = build['date']

            main_window = self.get_main_window()

            status_bar = main_window.statusBar()
            status_bar.clearMessage()

            status_bar.busy += 1

            reading_label = QLabel()
            reading_label.setText(_('Reading: {0}').format(self.exe_path))
            status_bar.addWidget(reading_label, 100)
            self.reading_label = reading_label

            progress_bar = QProgressBar()
            status_bar.addWidget(progress_bar)
            self.reading_progress_bar = progress_bar

            timer = QTimer(self)
            self.exe_reading_timer = timer

            exe_size = os.path.getsize(self.exe_path)

            progress_bar.setRange(0, exe_size)
            self.exe_total_read = 0

            self.exe_sha256 = hashlib.sha256()
            self.last_bytes = None
            self.game_version = ''
            self.opened_exe = open(self.exe_path, 'rb')

            def timeout():
                bytes = self.opened_exe.read(cons.READ_BUFFER_SIZE)
                if len(bytes) == 0:
                    self.opened_exe.close()
                    self.exe_reading_timer.stop()
                    main_window = self.get_main_window()
                    status_bar = main_window.statusBar()

                    build_date = arrow.get(self.build_date, 'UTC')
                    human_delta = build_date.humanize(arrow.utcnow(), locale=self.app_locale)
                    self.build_value_label.setText(
                        '{build} ({time_delta})'
                            .format(build=self.build_number, time_delta=human_delta)
                    )
                    self.current_build = self.build_number

                    status_bar.removeWidget(self.reading_label)
                    status_bar.removeWidget(self.reading_progress_bar)

                    status_bar.busy -= 1

                    sha256 = self.exe_sha256.hexdigest()

                    stable_version = cons.STABLE_SHA256.get(sha256, None)
                    is_stable = stable_version is not None

                    if is_stable:
                        self.game_version = stable_version

                    if self.game_version == '':
                        self.game_version = _('Unknown')
                    self.version_value_label.setText(
                        '{version} ({type})'
                            .format(version=self.game_version, type=self.version_type)
                    )

                    new_build(self.game_version, sha256, is_stable, self.build_number,
                              self.build_date)

                    main_tab = self.get_main_tab()
                    update_group_box = main_tab.update_group_box

                    update_group_box.post_extraction()

                else:
                    last_frame = bytes
                    if self.last_bytes is not None:
                        last_frame = self.last_bytes + last_frame

                    match = re.search(
                        b'(?P<version>[01]\\.[A-F](-\\d+-g[0-9a-f]+)?)\\x00',
                        last_frame)
                    if match is not None:
                        game_version = match.group('version').decode('ascii')
                        if len(game_version) > len(self.game_version):
                            self.game_version = game_version

                    self.exe_total_read += len(bytes)
                    self.reading_progress_bar.setValue(self.exe_total_read)
                    self.exe_sha256.update(bytes)
                    self.last_bytes = bytes

            timer.timeout.connect(timeout)
            timer.start(0)

    def find_executable(self, directory):
        console_exe = os.path.join(directory, 'cataclysm.exe')
        tiles_exe = os.path.join(directory, 'cataclysm-tiles.exe')

        exe_path = None
        version_type = None
        if os.path.isfile(console_exe):
            version_type = _('console')
            exe_path = console_exe
        elif os.path.isfile(tiles_exe):
            version_type = _('tiles')
            exe_path = tiles_exe

        self.exe_path = exe_path
        self.version_type = version_type

