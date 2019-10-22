import html
import logging
import os
import platform
import traceback
from io import StringIO
from urllib.parse import urlencode

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QGridLayout, QLabel, QLineEdit, QPushButton, QFileDialog, QToolButton,
    QDialog, QTextBrowser, QMessageBox, QHBoxLayout, QTextEdit
)

import cddagl.constants as cons
from cddagl import __version__ as version
from cddagl.constants import get_resource_path
from cddagl.functions import clean_qt_path, bitness
from cddagl.i18n import proxy_gettext as _
if os.name == 'nt':
    from cddagl.win32 import get_downloads_directory
elif os.name == 'posix':
    from cddagl.posix import get_downloads_directory
logger = logging.getLogger('cddagl')


class BrowserDownloadDialog(QDialog):
    def __init__(self, name, url, expected_filename):
        super(BrowserDownloadDialog, self).__init__()

        self.name = name
        self.url = url
        self.expected_filename = expected_filename
        self.downloaded_path = None

        layout = QGridLayout()

        info_label = QLabel()
        info_label.setText(_('This {name} cannot be directly downloaded by the '
            'launcher. You have to use your browser to download it.').format(
            name=name))
        layout.addWidget(info_label, 0, 0, 1, 2)
        self.info_label = info_label

        step1_label = QLabel()
        step1_label.setText(_('1. Open the URL in your browser.'))
        layout.addWidget(step1_label, 1, 0, 1, 2)
        self.step1_label = step1_label

        url_tb = QTextBrowser()
        url_tb.setText('<a href="{url}">{url}</a>'.format(url=html.escape(url)))
        url_tb.setReadOnly(True)
        url_tb.setOpenExternalLinks(True)
        url_tb.setMaximumHeight(23)
        url_tb.setLineWrapMode(QTextEdit.NoWrap)
        url_tb.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        layout.addWidget(url_tb, 2, 0, 1, 2)
        self.url_tb = url_tb

        step2_label = QLabel()
        step2_label.setText(_('2. Download the {name} on that page and wait '
            'for the download to complete.').format(name=name))
        layout.addWidget(step2_label, 3, 0, 1, 2)
        self.step2_label = step2_label

        step3_label = QLabel()
        step3_label.setText(_('3. Select the downloaded archive.'))
        layout.addWidget(step3_label, 4, 0, 1, 2)
        self.step3_label = step3_label

        path = get_downloads_directory()
        if expected_filename is not None:
            path = os.path.join(path, expected_filename)

        download_path_le = QLineEdit()
        download_path_le.setText(path)
        layout.addWidget(download_path_le, 5, 0)
        self.download_path_le = download_path_le

        download_path_button = QToolButton()
        download_path_button.setText('...')
        download_path_button.clicked.connect(self.set_download_path)
        layout.addWidget(download_path_button, 5, 1)
        self.download_path_button = download_path_button

        buttons_container = QWidget()
        buttons_layout = QHBoxLayout()
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_container.setLayout(buttons_layout)

        install_button = QPushButton()
        install_button.setText(_('Install this {name}').format(name=name))
        install_button.clicked.connect(self.install_clicked)
        buttons_layout.addWidget(install_button)
        self.install_button = install_button

        do_not_install_button = QPushButton()
        do_not_install_button.setText(_('Do not install'))
        do_not_install_button.clicked.connect(self.do_not_install_clicked)
        buttons_layout.addWidget(do_not_install_button)
        self.do_not_install_button = do_not_install_button

        layout.addWidget(buttons_container, 6, 0, 1, 2, Qt.AlignRight)
        self.buttons_container = buttons_container
        self.buttons_layout = buttons_layout

        self.setLayout(layout)

        self.setWindowTitle(_('Browser download'))

    def set_download_path(self):
        options = QFileDialog.DontResolveSymlinks
        selected_file, selected_filter = QFileDialog.getOpenFileName(self,
            _('Downloaded archive'), self.download_path_le.text(),
            _('Archive files {formats}').format(formats='(*.zip *.rar *.7z)'),
            options=options)
        if selected_file:
            self.download_path_le.setText(clean_qt_path(selected_file))

    def install_clicked(self):
        choosen_file = self.download_path_le.text()
        if not os.path.isfile(choosen_file):
            filenotfound_msgbox = QMessageBox()
            filenotfound_msgbox.setWindowTitle(_('File not found'))

            text = (_('{filepath} is not an existing file on your system. '
                'Make sure to download the archive with your browser. Make '
                'sure to select the downloaded archive afterwards.')).format(
                    filepath=choosen_file
                )

            filenotfound_msgbox.setText(text)
            filenotfound_msgbox.addButton(_('I will try again'),
                QMessageBox.AcceptRole)
            filenotfound_msgbox.setIcon(QMessageBox.Warning)
            filenotfound_msgbox.exec()

            return

        self.downloaded_path = choosen_file
        self.done(1)

    def do_not_install_clicked(self):
        self.done(0)


class AboutDialog(QDialog):
    def __init__(self, parent=0, f=0):
        super(AboutDialog, self).__init__(parent, f)

        layout = QGridLayout()

        text_content = QTextBrowser()
        text_content.setReadOnly(True)
        text_content.setOpenExternalLinks(True)

        text_content.setSearchPaths([get_resource_path()])
        layout.addWidget(text_content, 0, 0)
        self.text_content = text_content

        ok_button = QPushButton()
        ok_button.clicked.connect(self.done)
        layout.addWidget(ok_button, 1, 0, Qt.AlignRight)
        self.ok_button = ok_button

        layout.setRowStretch(0, 100)

        self.setMinimumSize(640, 450)

        self.setLayout(layout)
        self.set_text()

    def set_text(self):
        self.setWindowTitle(_('About CDDA Game Launcher'))
        self.ok_button.setText(_('OK'))
        m = _('<p>CDDA Game Launcher version {version}</p>').format(version=version)
        m += _('<p>Get the latest release'
               ' <a href="https://github.com/remyroy/CDDA-Game-Launcher/releases">on GitHub</a>.'
               '</p>')
        m += _('<p>Please report any issue'
               ' <a href="https://github.com/remyroy/CDDA-Game-Launcher/issues/new">on GitHub</a>.'
               '</p>')
        bitcoin_text = r'3N2BRM61bZLuFRHjSj2Lhtw6DrwPUGeTvV'
        bitcoin_link = r'bitcoin:3N2BRM61bZLuFRHjSj2Lhtw6DrwPUGeTvV'
        ether_link = r'https://etherscan.io/address/0xdb731476e913d75061a78105c3d1b5a7a03aa21b'
        ether_text = r'0xdb731476e913d75061a78105c3d1b5a7a03aa21b'
        m += _('<p>If you like the CDDA Game Launcher, you can buy me a beer by:</p>'
               '<p>donating bitcoins to <a href="{bitcoin_link}">{bitcoin_text}</a></p>'
               '<p><img src="btc-qr.png" /></p>'
               '<p>or by donating ethers to <a href="{ether_link}">{ether_text}</a></p>'
               '<p><img src="eth-qr.png" /></p>').format(bitcoin_text=bitcoin_text,
                                                         bitcoin_link=bitcoin_link,
                                                         ether_link=ether_link,
                                                         ether_text=ether_text)
        m += _('<p>Thanks to the following people for their efforts in'
               ' translating the CDDA Game Launcher</p>'
               '<ul>'
               '<li>Russian: Daniel from <a href="http://cataclysmdda.ru/">cataclysmdda.ru</a>'
               ' and Night_Pryanik'
               '</li>'
               '<li>Italian: Rettiliano Verace from'
               ' <a href="http://emigrantebestemmiante.blogspot.com">Emigrante Bestemmiante</a>'
               '</li>'
               '<li>French: Rémy Roy</li>'
               '<li>Spanish: KurzedMetal</li>'
               '</ul>')
        m += _('<p>Thanks to <a href="http://mattahan.deviantart.com/">Paul Davey aka Mattahan</a>'
               ' for the permission to use his artwork for the launcher icon.</p>')
        m += _('<p>This software is distributed under the MIT License. That means this is'
               ' 100&#37; free software, completely free to use, modify and/or distribute.'
               ' If you like more details check the following boring legal stuff...</p>')
        m += '<p>Copyright (c) 2015-2019 Rémy Roy</p>'
        m += ('<p>Permission is hereby granted, free of charge, to any person obtaining a copy'
              ' of this software and associated documentation files (the "Software"), to deal'
              ' in the Software without restriction, including without limitation the rights'
              ' to use, copy, modify, merge, publish, distribute, sublicense, and/or sell'
              ' copies of the Software, and to permit persons to whom the Software is'
              ' furnished to do so, subject to the following conditions:</p>'
              '<p>The above copyright notice and this permission notice shall be included in'
              ' all copies or substantial portions of the Software.</p>'
              '<p>THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR'
              ' IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,'
              ' FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE'
              ' AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER'
              ' LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,'
              ' OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE'
              ' SOFTWARE.</p>')
        self.text_content.setHtml(m)


class ExceptionWindow(QWidget):
    def __init__(self, app, extype, value, tb):
        super(ExceptionWindow, self).__init__()

        self.app = app

        layout = QGridLayout()

        information_label = QLabel()
        information_label.setText(_('The CDDA Game Launcher just crashed. An '
            'unhandled exception was raised. Here are the details.'))
        layout.addWidget(information_label, 0, 0)
        self.information_label = information_label

        tb_io = StringIO()
        traceback.print_tb(tb, file=tb_io)
        traceback_content = html.escape(tb_io.getvalue()).replace('\n', '<br>')

        text_content = QTextBrowser()
        text_content.setReadOnly(True)
        text_content.setOpenExternalLinks(True)
        text_content.setHtml(_('''
<p>CDDA Game Launcher version: {version}</p>
<p>OS: {os} ({bitness})</p>
<p>Type: {extype}</p>
<p>Value: {value}</p>
<p>Traceback:</p>
<code>{traceback}</code>
''').format(version=html.escape(version), extype=html.escape(str(extype)),
    value=html.escape(str(value)), os=html.escape(platform.platform()),
    traceback=traceback_content, bitness=html.escape(bitness())))

        layout.addWidget(text_content, 1, 0)
        self.text_content = text_content

        report_url = cons.NEW_ISSUE_URL + '?' + urlencode({
            'title': _('Unhandled exception: [Enter a title]'),
            'body': _('''* Description: [Enter what you did and what happened]
* Version: {version}
* OS: {os} ({bitness})
* Type: `{extype}`
* Value: {value}
* Traceback:
```
{traceback}
```
''').format(version=version, extype=str(extype), value=str(value),
    traceback=tb_io.getvalue(), os=platform.platform(), bitness=bitness())
        })

        report_label = QLabel()
        report_label.setOpenExternalLinks(True)
        report_label.setText(_('Please help us make a better launcher '
            '<a href="{url}">by reporting this issue on GitHub</a>.').format(
                url=html.escape(report_url)))
        layout.addWidget(report_label, 2, 0)
        self.report_label = report_label

        exit_button = QPushButton()
        exit_button.setText(_('Exit'))
        exit_button.clicked.connect(lambda: self.app.exit(-100))
        layout.addWidget(exit_button, 3, 0, Qt.AlignRight)
        self.exit_button = exit_button

        self.setLayout(layout)
        self.setWindowTitle(_('Something went wrong'))
        self.setMinimumSize(350, 0)
