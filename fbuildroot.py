from fbuild.builders.cxx import guess_static, guess_shared
from fbuild.builders.c.msvc import Builder as MsvcBuilder
from fbuild.builders.c.gcc import Builder as GccBuilder
from fbuild.builders.pkg_config import PkgConfig
from fbuild.builders import find_program
from fbuild.record import Record
from fbuild.path import Path
import fbuild

import sys, re, textwrap

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

@fbuild.db.caches
def gen_sfml_fpc(ctx, cxx):
    sys.path.insert(0, str(Path(__file__).dirname() / 'sfml'))
    import gen_fpc

    lib_arg = '' if isinstance(cxx, MsvcBuilder) else '-l'

    default_libs = {
        'system': ['system'],
        'window': ['window', 'system'],
        'graphics': ['graphics', 'window', 'system'],
    }

    all_libs = {}

    for pkg in gen_fpc.packages:
        try:
            libs = PkgConfig(ctx, 'sfml-' + pkg).libs()
        except:
            ctx.logger.check('trying to get libs for sfml-%s' % pkg)
            libs = ' '.join(map(lib_arg.__add__, default_libs[pkg]))
            ctx.logger.failed('failed (using defaults %s)' % libs)
        else:
            ctx.logger.check('trying to get libs for sfml-%s' % pkg)
            ctx.logger.passed('ok %s' % libs)

        all_libs[pkg] = libs

    for pkg, libs in all_libs.items():
        directory = ctx.buildroot / 'config'
        directory.makedirs()
        ctx.logger.check(' * generating fpc', directory / ('sfml-%s.fpc' % pkg),
                         color='yellow')
        gen_fpc.write(pkg, libs, str(directory))

def gen_fpc(*args):
    gen_sfml_fpc(*args)

class Felix(fbuild.db.PersistentObject):
    def __init__(self, ctx, flx=None, flx_pkgconfig=None):
        self.flx = find_program(ctx, [flx or 'flx'])
        self.ctx = ctx

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
                if output[1] or not output[0].endswith(b'Hello, world!\n'):
                    self.ctx.logger.failed()
                    raise fbuild.ConfigFailed(
                        'flx test program did not give correct output')
                else:
                    self.ctx.logger.passed()

    def uncached_run(self, path, *args, **kw):
        return self.ctx.execute([self.flx, path], *args, **kw)

    def tempfile(self, code):
        return fbuild.temp.tempfile(code, '.flx')

    @fbuild.db.cacheproperty
    def platform_extra(self):
        # XXX
        return {'clang'}
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
    felix = Felix(ctx)
    kw = dict(platform_extra=felix.platform_extra)
    static = guess_static(ctx, **kw)
    shared = guess_shared(ctx, **kw)
    gen_fpc(ctx, static)
    check_fluid(shared.lib_linker)
    return Record(static=static, shared=shared, felix=felix)

def build(ctx):
    rec = configure(ctx)
