#Midifi

Midifi is an open-source alternative to Synthesia written in Felix. Lots of stuff
hasn't been finished yet, like:

- Fast-forwarding and rewinding. (This is the biggest issue right now!)
- Pressing keys on the keyboard to play the piano.
- Nicer graphics.

However, it's great for casual use!

##Video

<a href="http://www.youtube.com/watch?feature=player_embedded&v=76NMR497JK8"
 target="_blank">
 <img src="http://img.youtube.com/vi/76NMR497JK8/0.jpg" alt="Preview video."
  width="240" height="180" border="10" />
</a>

##Downloading

If you're not a programmer and you use Windows, you don't need to mess with the
directions below under `Building`. Just download and run the installer!

##Using

###Windows

Midifi does not work on Windows yet.

###Linux

You need to call midifi from the command line with the midi file as the argument.

###Controls

Once the file is playing, you can click "Pause" or press the space bar to pause the
file. Clicking "Play" or pressing the space bar again will play it.

Also, clicking the large, red "X" will close Midifi.

##Building

You need the following:

- [Felix](http://felix-lang.org/).
- [Python 3](https://www.python.org/).
- [Fbuild](https://github.com/felix-lang/fbuild/).
- [Git](http://git-scm.com/).
- [SFML](http://www.sfml-dev.org/).

Clone midifi using:

```
$ git clone --recursive https://github.com/midifi/midifi.git
```

Then, you need to follow the normal [Fluidsynth build directions](
http://sourceforge.net/p/fluidsynth/wiki/BuildingWithCMake/). After that, run:

```
$ fbuild
```

To build in release mode:

```
$ fbuild --release
```

###Windows

Again, Windows doesn't work yet. But you can try building it anyway!

Building on Windows is a tad *messy*. You **MUST** use Visual Studio and build in
Debug mode! If you're building under Visual Studio 2015, comment out the lines that
define `snprintf` in `fluidsynth/fluidsynth/src/config_win32.cmake`. Now, `cd` into
`fluidsynth\fluidsynth` and run:

```
cmake -G "Visual Studio <version> <year>"
```

If you're building on x64, make sure you instead do:

```
cmake -G "Visual Studio <version> <year> Win64"
```

This bit me quite a few times!

Once CMake finishes, run:

```
msbuild ALL_BUILD.vcxproj
```

After Fluidsynth builds, you need to locate `fluidsynth_*.lib` and
`libfluidsynth_*.dll` (usually they're in `src\*`), where all the `*`'s are
replaced by `debug` or `release`, and copy them to `fluidsynth/fluidsynth/src`
under the names `fluidsynth.lib` and `fluidsynth.dll`, respectively.
