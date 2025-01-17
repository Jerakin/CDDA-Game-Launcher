# CDDA Game Launcher

A [Cataclysm: Dark Days Ahead](https://cataclysmdda.org/) launcher with additional features.

[Download here](https://github.com/remyroy/CDDA-Game-Launcher/releases).

## Implemented features

* Launching the game
* Detecting the game version and build number
* Retreiving the available update builds
* Automatically updating the game while preserving the user modifications
* Soundpack manager
* Mod manager
* Save backups and automatic backups

## Planned features

* Tileset manager
* Font presets

## FAQ

### Where is my previous version?

Is it stored in the `previous_version` directory inside your game directory.

### How does the launcher update my game?

* The launcher downloads the archive for the new version.
* If the `previous_version` subdirectory exists, the launcher moves it in the recycle bin.
* The launcher moves everything from the game directory in the `previous_version` subdirectory.
* The launcher extracts the downloaded archive in the game directory.
* The launcher inspect what is in the `previous_version` directory and it copies the saves, the mods, the tilesets, the soundpacks and a bunch of others useful files from the `previous_version` directory that are missing from the downloaded archive to the real game directory. It will assume that mods that are included in the downloaded archive are the newest and latest version and it will keep those by comparing their unique ident value.

### I think the launcher just deleted my files. What can I do?

The launcher goes to great lengths not to delete any file that could be important to you. With the default and recommended settings, the launcher will always move files instead of deleting them. If you think you lost files during an update, check out the `previous_version` subdirectory. That is where you should be able to find your previous game version. You can also check for files in your recycle bin. Those are the main 2 places where files are moved and where you should be able to find them.

### My antivirus product detected the launcher as a threat. What can I do?

Poor antivirus products are known to detect the launcher as a threat and block its execution or delete the launcher. A simple workaround is to add the launcher binary in your antivirus whitelist or select the action to trust this binary when detected.

If you are paranoid, you can always inspect the source code yourself and build the launcher from the source code. You are still likely to get false positives. There is little productive efforts we can do as software developers with these. We have [a nice building guide](https://github.com/remyroy/CDDA-Game-Launcher/blob/master/BUILDING.md) for those who want to build the launcher from the source code.

### How do I update to a new version of the game launcher?

The launcher will automatically check for updated version on start. If it finds one, the launcher will prompt you to update. You can always download [the latest version on github](https://github.com/remyroy/CDDA-Game-Launcher/releases). Those using the portable version will have to manually download and manually update the launcher. From the help menu, you can also check for new updates.

### The launcher keeps crashing when I start it. What can I do?

You might need to delete your configs file to work around this issue. That filename is `configs.db` and it is located in `%LOCALAPPDATA%\CDDA Game Launcher\`. Some users have reported and encountered unrelated starting issues. In some cases, running a debug version of the launcher to get more logs might help to locate the issue. [Creating an issue about this](https://github.com/remyroy/CDDA-Game-Launcher/issues) is probably the way to go.

### Will you make a Linux or macOS version?

Most likely not. You can check [the linux issue](https://github.com/remyroy/CDDA-Game-Launcher/issues/329) and [the mac issue](https://github.com/remyroy/CDDA-Game-Launcher/issues/73) for more information.

### It does not work? Can you help me?

Submit your issues [on Github](https://github.com/remyroy/CDDA-Game-Launcher/issues). Try to [report bugs effectively](http://www.chiark.greenend.org.uk/~sgtatham/bugs.html).

## Building

You can learn how to run and build the launcher by checking our [building guide](BUILDING.md).

## License

This project is licensed under the terms of [the MIT license](LICENSE).

Permission to use [the launcher icon](cddagl/resources/launcher.ico) was given by [Paul Davey aka Mattahan](http://mattahan.deviantart.com/).

## Contributing to this project

Anyone and everyone is welcome to contribute. Please take a moment to review the [guidelines for contributing](CONTRIBUTING.md).

* [Bug reports](CONTRIBUTING.md#bugs)
* [Feature requests](CONTRIBUTING.md#features)
* [Pull requests](CONTRIBUTING.md#pull-requests)
* [Translation contributions](CONTRIBUTING.md#translations)

## Code of conduct

Participants in this projet are expected to follow [the Code of Conduct](CODE_OF_CONDUCT.md).