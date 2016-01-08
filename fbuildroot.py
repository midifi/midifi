# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from fbuild.builders.cxx import guess_static, guess_shared
from fbuild.builders.c.msvc import Builder as MsvcBuilder
from fbuild.builders.pkg_config import PkgConfig
from fbuild.builders.file import copy
from fbuild.builders.c import Library
from fbuild.builders import find_program
from fbuild.record import Record
from fbuild.path import Path
import fbuild

import sys, re, textwrap, os, shutil, tarfile, urllib.request,\
       xml.etree.ElementTree as etree
from optparse import make_option

def pre_options(parser):
    group = parser.add_option_group('config options')
    group.add_options((
        make_option('--flx', help='Use the given Felix compiler'),
        make_option('--flxflag', help='Pass the given flag to flx',
                    action='append', default=[]),
        make_option('--release', help='Build a release build',
                    action='store_true'),
    ))

def check_fluid(linker):
    fluidsynth = Path(linker.prefix + 'fluidsynth' + linker.suffix)
    fluidsynth = fluidsynth.addroot(Path('fluidsynth') / 'fluidsynth' / 'src')

    message = textwrap.dedent('''
    You need to build Fluidsynth separately first!
    Try runnung 'cd fluidsynth/fluidsynth; cmake'.
    (See http://sourceforge.net/p/fluidsynth/wiki/BuildingWithCMake/ for info.)
    '''.rstrip().lstrip('\n')).replace('\n', ' ', 1)

    if not fluidsynth.exists():
        raise fbuild.ConfigFailed(message)

    return fluidsynth

def make_lib_args(cxx, path):
    if isinstance(cxx, MsvcBuilder):
        return path + '.lib'
    else:
        return '-l' + path

def get_info_for(ctx, cxx, pkg, defaults):
    try:
        pkgconfig = PkgConfig(ctx, pkg)
        cflags = pkgconfig.cflags()
        libs = pkgconfig.libs()
        if isinstance(cxx, MsvcBuilder):
            for lib in libs.split():
                if lib.startswith('-l'):
                    libs = libs.replace(lib, '')
    except:
        ctx.logger.check('trying to get libs for %s' % pkg)
        cflags = []
        libs = ' '.join(map(lambda l: make_lib_args(cxx, l),
                            defaults.get(pkg, [])))
        failmsg = 'failed'
        if libs:
            failmsg += ' (using defaults %s)' % libs
        ctx.logger.failed(failmsg)
    else:
        ctx.logger.check('trying to get libs for -%s' % pkg)
        ctx.logger.passed('ok %s' % libs)

    return cflags, libs

def write_fpc(ctx, fpc, write):
    directory = ctx.buildroot / 'config'
    directory.makedirs()
    ctx.logger.check(' * generating fpc', directory / fpc, color='yellow')
    write(directory)

@fbuild.db.caches
def gen_sfml_fpc(ctx, cxx):
    sys.path.insert(0, str(Path(__file__).dirname() / 'sfml'))
    import gen_fpc

    default_libs = {
        'sfml-system': ['sfml-system'],
        'sfml-window': ['sfml-window', 'sfml-system'],
        'sfml-graphics': ['sfml-graphics', 'sfml-window', 'sfml-system'],
    }

    all_libs = {}

    for pkg in gen_fpc.packages:
        all_libs[pkg] = get_info_for(ctx, cxx, 'sfml-' + pkg, default_libs)[1]

    for pkg, libs in all_libs.items():
        write_fpc(ctx, 'sfml-%s.fpc' % pkg, lambda d: gen_fpc.write(pkg, libs, d))

@fbuild.db.caches
def gen_midifile_fpc(ctx, cxx):
    def write(directory):
        with open('midifile-flx/midifile.fpc') as base_f:
                base = base_f.read()

        # XXX: This is an ugly hack!
        fpc = base.replace('lib: -lmidifile',
                           'lib: -L%s %s' % (ctx.buildroot,
                                             make_lib_args(cxx, 'midifile')))
        fpc = fpc.replace('provides_dlib',
                          'cflags: -Imidifile/include\nprovides_dlib')

        with open(directory / 'midifile.fpc', 'w') as f:
            f.write(fpc)

    write_fpc(ctx, 'midifile.fpc', write)

@fbuild.db.caches
def gen_fluid_fpc(ctx, cxx):
    all_flags = '-I%s ' % ctx.buildroot
    all_libs = ''

    for pkg in 'glib-2.0', 'gthread-2.0':
        cflags, libs = get_info_for(ctx, cxx, pkg, {})
        all_flags += ' '.join(cflags) + ' '
        all_libs += libs + ' '

    all_libs += make_lib_args(cxx, 'fluidsynth')

    fluidsynth_root = Path('fluidsynth') / 'fluidsynth'
    fluidsynth_includes = ['include', 'src/midi', 'src/utils']
    for include in fluidsynth_includes:
        all_flags += ' -I' + str(fluidsynth_root / include)

    def write(directory):
        template = textwrap.dedent('''
        Name: fluid
        Description: Midifi fluidsynth stuff!
        cflags: {flags}
        provides_dlib: {libs}
        provides_slib: {libs}
        '''.lstrip('\n').rstrip(' '))

        fpc = template.format(flags=all_flags, libs=all_libs)

        with open(directory / 'fluid.fpc', 'w') as f:
            f.write(fpc)

    write_fpc(ctx, 'fluid.fpc', write)

def gen_fpc(*args):
    gen_sfml_fpc(*args)
    gen_midifile_fpc(*args)
    gen_fluid_fpc(*args)

class Felix(fbuild.db.PersistentObject):
    def __init__(self, ctx, flx=None, flx_pkgconfig=None, debug=False,
                 optimize=False, flags=[]):
        self.flx = find_program(ctx, [flx or 'flx'])
        self.ctx = ctx
        self.debug = debug
        self.optimize = optimize
        self.flags = flags

        self._test()

    def _test(self):
        self.ctx.logger.check('checking flx')
        failed = False
        with self.tempfile("println 'Hello, world!';") as f:
            try:
                output = self.uncached_run(f, quieter=1)
            except:
                self.ctx.logger.failed()
                raise
            else:
                if output[1] or not output[0].rstrip().endswith(b'Hello, world!'):
                    self.ctx.logger.failed()
                    raise fbuild.ConfigFailed(
                        'flx test program did not give correct output')
                else:
                    self.ctx.logger.passed()

    def uncached_compile(self, dst, src, cxx, includes=[], pkgconfig_paths=[],
                         libpaths=[], libs=[], cflags=[]):
        dst = Path(dst).addroot(self.ctx.buildroot)
        dst = dst.replaceext(cxx.exe_linker.suffix)

        new_libs = []

        def process_library(lib):
            if isinstance(lib, Library):
                for sublib in lib.libs:
                    process_library(sublib)

                new_libs.extend(lib.external_libs)
                libpaths.append(lib.dirname())
                slib = str(lib.basename().replaceext(''))
                if slib.startswith('lib') and lib.splitext()[1] == '.a':
                    slib = slib[3:]
                new_libs.append(slib)
                libpaths.extend(lib.libpaths)

        for lib in libs:
            process_library(lib)

        cmd = [self.flx, '-c', '--static']
        if self.debug:
            cmd.append('--debug')
        if self.optimize:
            cmd.append('--usage=hyperlight')
        cmd.extend(('-o', dst))
        cmd.extend('--pkgconfig-path+=' + path for path in pkgconfig_paths)
        cmd.extend('-I' + include for include in includes)
        cmd.extend('-L' + path for path in libpaths)
        cmd.extend('-l' + lib for lib in new_libs)
        cmd.extend('--cflags=' + flag for flag in cflags)
        cmd.extend(self.flags)
        cmd.append(src)

        self.ctx.execute(cmd, 'flx', '%s -> %s' % (src, dst), color='link')
        return dst

    @fbuild.db.cachemethod
    def compile(self, dst, src: fbuild.db.SRC, others: fbuild.db.SRCS, *args,
        **kw) -> fbuild.db.DST:
        return self.uncached_compile(dst, src, *args, **kw)

    def uncached_run(self, path, *args, **kw):
        return self.ctx.execute([self.flx, path], *args, **kw)

    def tempfile(self, code):
        return fbuild.temp.tempfile(code, '.flx')

    @fbuild.db.cacheproperty
    def platform_extra(self):
        get_toolchain = '''
        include 'std/felix/toolchain_clang_config';
        include 'std/felix/toolchain_interface';
        include 'std/felix/flx_pkgconfig';

        config_dirs := #Config::std_config.FLX_CONFIG_DIRS;
        pkgconfig := FlxPkgConfig::FlxPkgConfigQuery config_dirs;
        toolchain := pkgconfig.getpkgfield1 ('toolchain', 'toolchain');

        for arg in #System::args perform
            if arg.startswith('--toolchain=') perform
                toolchain = arg.[12 to];

        println toolchain;
        '''

        with self.tempfile(get_toolchain) as f:
            self.ctx.logger.check('detecting toolchain used by flx '\
                                  '(this may take a while!)')
            try:
                toolchain = self.uncached_run(f, quieter=1)[0]
            except:
                self.ctx.logger.failed()
                raise fbuild.ConfigFailed('could not detect flx toolchain')
            else:
                toolchain = toolchain.decode('utf-8').strip().split('\n')[-1]
                self.ctx.logger.passed('ok %s' % toolchain)

        if 'msvc' in toolchain:
            return {'windows'}
        elif 'gcc' in toolchain:
            return {'gcc'}
        elif 'clang' in toolchain:
            return {'clang'}
        else:
            raise fbuild.ConfigFailed('unknown toolchain %s' % toolchain)

@fbuild.db.caches
def configure(ctx):
    config_kw = dict()
    if ctx.options.release:
        config_kw['optimize'] = True
    else:
        config_kw['debug'] = True
    felix = Felix(ctx, flags=ctx.options.flxflag, **config_kw)
    extra = felix.platform_extra
    kw = dict(platform_extra=extra, platform_options=[
        ({'windows'}, {'flags+': ['/EHsc']}),
        ({'posix'}, {'flags+': ['-std=c++11']}),
    ], **config_kw)
    static = guess_static(ctx, **kw)
    shared = guess_shared(ctx, **kw)
    gen_fpc(ctx, static)
    linker = static.lib_linker if 'windows' in extra else shared.lib_linker
    fluidsynth = check_fluid(linker)
    return Record(static=static, shared=shared, felix=felix, fluidsynth=fluidsynth)

#--------------------------------------------------------------------------------
# BUILDING.
#--------------------------------------------------------------------------------

@fbuild.db.caches
def download_soundfont(ctx) -> fbuild.db.DST:
    ctx.logger.check('downloading FluidR3 GM (this will take a few moments)')
    tar = ctx.buildroot / 'fluid-soundfont.tar.gz'
    url = 'http://www.musescore.org/download/fluid-soundfont.tar.gz'
    try:
        with urllib.request.urlopen(url) as response, open(tar, 'wb') as f:
            shutil.copyfileobj(response, f)
    except:
        ctx.logger.failed()
        raise
    else:
        ctx.logger.passed('ok %s' % tar)

    return tar

@fbuild.db.caches
def extract_soundfont(ctx, tar: fbuild.db.SRC) -> fbuild.db.DST:
    dst = ctx.buildroot / 'data' / 'FluidR3_GM.sf2'
    dst.dirname().makedirs()
    member = 'FluidR3 GM2-2.SF2'
    ctx.logger.check('extracting FluidR3 GM (this will take a few moments)')
    try:
        with tarfile.open(str(tar)) as tf:
            tf.extract(member, ctx.buildroot)

        os.rename(ctx.buildroot / member, dst)
    except FileExistsError:
        pass
    except:
        ctx.logger.failed()
        raise
    else:
        ctx.logger.passed('ok %s' % dst)

    return dst

def get_soundfont(ctx):
    tar = download_soundfont(ctx)
    extract_soundfont(ctx, tar)

@fbuild.db.caches
def find_font(ctx) -> fbuild.db.DST:
    ctx.logger.check('locating arial font')
    font = None

    if sys.platform == 'win32':
        font = Path(os.environ['SYSTEMROOT']) / 'Fonts' / 'Arial.ttf'
        if not font.exists():
            font = None
    elif sys.platform.startswith('linux'):
        # Check /etc/fonts/fonts.conf.
        font_dirs = []
        fonts = Path('/etc/fonts/fonts.conf')
        if not fonts.exists():
            ctx.logger.failed()
            raise fbuild.ConfigFailed('cannot locate fonts.conf')

        tree = etree.parse(str(fonts))
        for element in tree.findall('dir'):
            path = Path(element.text)
            if element.attrib.get('prefix') == 'xdg' and \
                'XDG_DATA_HOME' in os.environ:
                path = path.addroot(os.environ['XDG_DATA_HOME'])

            try:
                font = Path(next(path.find('Arial.ttf', include_dirs=False)))
            except StopIteration:
                pass
            else:
                break

    if font is None:
        ctx.logger.failed()
        raise fbuild.ConfigFailed('cannot locate arial font')
    else:
        ctx.logger.passed('ok %s' % font)
        return font

@fbuild.db.caches
def save_font(ctx, font: fbuild.db.SRC) -> fbuild.db.DST:
    dst = ctx.buildroot / 'data' / 'Arial.ttf'
    return copy(ctx, font, dst)

def get_font(ctx):
    font = find_font(ctx)
    save_font(ctx, font)

@fbuild.db.caches
def save_exports(ctx, lib: fbuild.db.SRC) -> fbuild.db.DST:
    dst = ctx.buildroot / 'fluidsynth.def'
    ctx.logger.check(' * extracting exports', dst, color='yellow')
    output, _ = ctx.execute(['dumpbin', '/nologo', '/exports', lib], quieter=1)
    output = output.decode('ascii')
    export_res = re.search(r'name(.*)Summary', output, re.DOTALL | re.MULTILINE)
    exports = ['EXPORTS']
    exports.extend(map(str.strip, export_res.group(1).strip().splitlines()))
    exports.extend(['new_fluid_timer', 'delete_fluid_timer', 'new_fluid_track',
                    'fluid_track_add_event', 'fluid_player_add_track',
                    'fluid_player_callback'])
    with open(dst, 'w') as f:
        f.write('\n'.join(exports))

    # Create the lib file.
    return dst

@fbuild.db.caches
def make_lib(ctx, exports: fbuild.db.SRC, linker, fluid) -> fbuild.db.DST:
    dst = ctx.buildroot / fluid.basename()
    cmd = [linker.exe, '/nologo', '/def:' + exports, '/OUT:' + dst]
    ctx.execute(cmd, str(linker), '%s -> %s' % (exports, dst), color='link')
    return dst

def copy_dll2(ctx, fluid: fbuild.db.SRC) -> fbuild.db.DST:
    dst = ctx.buildroot / fluid.basename()
    copy(ctx, fluid, dst)
    return dst

def copy_dll(ctx, fluid):
    dll = fluid.replaceext('.dll')
    if not dll.exists():
        url = 'https://github.com/midifi/midifi/blob/master/README.md#windows-1'
        raise fbuild.ConfigFailed('cannot find %s\nsee %s for more info' % (dll,
                                                                            url))
    return copy_dll2(ctx, dll)

def build_midifile(ctx, rec):
    builder = rec.shared if isinstance(rec.shared, MsvcBuilder) else rec.static
    return builder.build_lib('midifile',
        Path.glob('midifile/src-library/*.cpp'), includes=['midifile/include'],
        ckwargs={'debug': True})

def build_midifi(ctx, rec, midifile):
    all_sources = []
    for pat in 'midifi/*.flx', 'sfml/sfml/*.flx', 'midifile-flx/midifile.flx':
        all_sources.extend(Path.glob(pat))

    rec.felix.compile('midifi', 'midifi.flx', all_sources, rec.static,
                      includes=['sfml', 'midifile', 'midifile-flx'],
                      pkgconfig_paths=['build/config'], libs=[midifile])

def build(ctx):
    rec = configure(ctx)
    get_soundfont(ctx)
    get_font(ctx)
    if isinstance(rec.static, MsvcBuilder):
        exports = save_exports(ctx, rec.fluidsynth)
        make_lib(ctx, exports, rec.static.lib_linker, rec.fluidsynth)
        copy_dll(ctx, rec.fluidsynth)
    else:
        copy(ctx, rec.fluidsynth, ctx.buildroot / rec.fluidsynth.basename())
    midifile = build_midifile(ctx, rec)
    build_midifi(ctx, rec, midifile)
