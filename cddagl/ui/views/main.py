import logging
import os

from PyQt5.QtWidgets import QWidget, QVBoxLayout

from cddagl.ui.views.game_dir_group_box import GameDirGroupBoxWin, GameDirGroupBoxOSX
from cddagl.ui.views.update_group_box import UpdateGroupBoxWin, UpdateGroupBoxOSX

logger = logging.getLogger('cddagl')


class MainTab(QWidget):
    def __init__(self):
        super(MainTab, self).__init__()

        if os.name == "nt":
            self.game_dir_group_box = GameDirGroupBoxWin()
        elif os.name == "posix":
            self.game_dir_group_box = GameDirGroupBoxOSX()

        if os.name == "nt":
            self.update_group_box = UpdateGroupBoxWin()
        elif os.name == "posix":
            self.update_group_box = UpdateGroupBoxOSX()

        layout = QVBoxLayout()
        layout.addWidget(self.game_dir_group_box)
        layout.addWidget(self.update_group_box)
        self.setLayout(layout)

    def set_text(self):
        self.game_dir_group_box.set_text()
        self.update_group_box.set_text()

    def get_main_window(self):
        return self.parentWidget().parentWidget().parentWidget()

    def get_settings_tab(self):
        return self.parentWidget().parentWidget().settings_tab

    def get_soundpacks_tab(self):
        return self.parentWidget().parentWidget().soundpacks_tab

    def get_mods_tab(self):
        return self.parentWidget().parentWidget().mods_tab

    def get_backups_tab(self):
        return self.parentWidget().parentWidget().backups_tab

    def disable_tab(self):
        self.game_dir_group_box.disable_controls()
        self.update_group_box.disable_controls(True)

    def enable_tab(self):
        self.game_dir_group_box.enable_controls()
        self.update_group_box.enable_controls()

