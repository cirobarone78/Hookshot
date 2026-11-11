Hookshot Builder for macOS (Apple Silicon)
=========================================

This is a native arm64 Builder and game build for Apple Silicon Macs. It uses
SDL2 for input and wgpu-native's Metal backend. macOS 13.3 or newer is required;
Intel Macs and Rosetta are not supported. Xcode Command Line Tools are required.

The package includes the Hookshot source, Python runtime and modules, SDL2,
static FFmpeg with dav1d, Metal-enabled wgpu-native, and dependency license
notices. It does not include a game dump or a built game. Use your own legally
obtained dump.

Use the Builder app
-------------------

1. Unzip the package.
2. Open HookshotBuilder.app (inside HookshotBuilder/ for the folder archive).
3. Choose your .nup dump and output folder in the Builder window.
4. Start the build and follow its progress. The output folder contains the
   generated game and the libraries needed to run it.
5. Open Terminal, change to the output folder, and run ./hookshot to launch.

For a dump that is already extracted, use the --romfs and --exefs options
instead of --nup.

Command-line use
----------------

From Terminal, in the unpacked HookshotBuilder folder:

  ./HookshotBuilder.command --help
  ./HookshotBuilder.command --check --nup "/path/to/your-game.nup"
  ./HookshotBuilder.command --nup "/path/to/your-game.nup" \
      --out "$HOME/Games/Hookshot" --jobs 4 --language en-US

Use --romfs "/path/to/romfs" --exefs "/path/to/exefs" instead of --nup for
an extracted dump. --check verifies the dump without building. --jobs limits
how many compiler tasks run at once; omit it to use the memory-aware default.
Use --log "/path/to/build.log" to save build output.

The generated executable, SDL2 dylib, and wgpu-native dylib are placed beside
the game data in the output folder. FFmpeg is linked statically. dav1d is
included for AV1 movie decoding.

Build dependencies and package the Builder from source
------------------------------------------------------

On an Apple Silicon Mac running macOS 13.3 or newer, install Xcode Command Line
Tools and Homebrew's dependency build tools:

  xcode-select --install
  brew install cmake nasm meson ninja
  git submodule update --init --recursive

From the repository root, fetch and build the pinned arm64 Python, SDL2,
FFmpeg/dav1d, and wgpu-native dependencies, then assemble both Builder archives:

  bash scripts/macos/deps.sh
  bash scripts/macos/package-builder.sh

Dependencies default to build-macos/deps; set DEPS=/path/to/deps to use another
directory. Packages default to build-macos; set OUT=/path/to/output to change
that location. The first dependency build downloads upstream sources and needs
network access and substantial free disk space. Later runs reuse downloaded and
built dependencies.

The build produces:

  build-macos/HookshotBuilder-macos-arm64.zip
      Builder folder containing the app, command-line launcher, source, tools,
      and license notices.
  build-macos/HookshotBuilder-macos-arm64.app.zip
      Standalone HookshotBuilder.app.

The package script checks the arm64 architecture, signs the completed app
ad hoc, and verifies the signature. The app is not notarized. A CI artifact
from a pull request is a test build, not a published stable release.

Build a game directly from a source clone
----------------------------------------

After running scripts/macos/deps.sh, build directly with the bundled native
Python and libraries. Replace the paths below with the location of your dump
and the folder where you want the game:

  export WGPU_NATIVE="$PWD/build-macos/deps/wgpu-native"
  export HOOKSHOT_SDL2="$PWD/build-macos/deps/sdl2/lib/libSDL2-2.0.0.dylib"
  export HOOKSHOT_FFMPEG="$PWD/build-macos/deps/ffmpeg"
  export RX_BACKEND=metal
  build-macos/deps/python/bin/python3 -I nx2/make_game.py \
      --nup "/path/to/your-game.nup" \
      --out "$HOME/Games/Hookshot" --jobs 4 --language en-US

The same --romfs/--exefs, --check, --log, and --jobs options described above
are available. The generated game uses the dump supplied by the user; neither
the source checkout nor this package supplies game data.

Updating the Builder
--------------------

The app checks GitHub for the latest stable Builder release when it starts. If
a newer version is offered, choose “Update builder”. The updater downloads and
validates the release, stages the replacement, then reopens the app. Keep the
app in a folder writable by your account, such as Applications in your home
folder. A pull-request artifact is not a release; its updater may see the
latest published stable version instead of a newer test build.

Testing and reporting issues
----------------------------

CI checks compilation, dependency architecture, package signature and Builder
startup, but does not run a game. Mac testers are needed to verify actual game
launch, window focus, saves, controller rumble, movie playback, and Builder
installation/update. When reporting an issue, include the Mac model/chip,
macOS version, exact steps, and build log. For a missing logo triangle or other
rendering defect, an Xcode Metal GPU frame capture is especially useful.
