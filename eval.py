#!/usr/bin/env python

from __future__ import print_function

from collections import defaultdict
import shutil
import os
import subprocess
import sys
import tempfile



FUZZER = os.path.abspath('../mkcheck/tools/fuzz_test')



def run_proc(cmd, cwd=None, default=None):
    """Runs a process, printing its output if it fails."""

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd)
    stdout, stderr = proc.communicate()
    if proc.returncode == 0:
        return stdout.strip()
    if default:
        return default
    print(' '.join(cmd))
    print(stdout, stderr)
    sys.exit(proc.returncode)

def build_proc(cmd, cwd, output):
    """Runs a process, piping output to file."""

    with open(output, 'a+') as o:
        proc = subprocess.Popen(cmd, stdout=o, stderr=o, cwd=cwd)
        proc.communicate()
        if proc.returncode == 0:
            return

    print('Error: ', ' '.join(cmd))
    shutil.move(output, output + '.fail')
    sys.exit(proc.returncode)



class Src(object):
    """Base class for all source definitions."""

class GitHubSrc(Src):
    """Sources downloaded from GitHub."""

    def __init__(self, name, version):
        self._name = name
        self._version = version

    def download(self, path):
        """Downloads the specified tag of the git repository."""

        url = 'https://github.com/%s.git' % self._name

        # Check if hash matches - skip if version is there.
        if os.path.exists(path):
            version = run_proc(['git', 'rev-parse', 'HEAD'], cwd=path, default='')
            if version == self._version:
                return
            shutil.rmtree(path)
        os.makedirs(path)

        # Download the specified hash.
        print('Downloading %s' % url)
        run_proc(['git', 'clone', '--recursive', url, path])
        run_proc(['git', 'reset', '--hard', self._version], cwd=path)
        run_proc(['git', 'submodule', 'update', '--recursive'], cwd=path)

    def patch(self, path, patch):
        """Patches the project with a file."""

class HttpSrc(Src):
    """Sources downloaded using http."""

    def __init__(self, url):
        self._url = url

    def download(self, path):
        if os.path.exists(path):
            version = run_proc(['git', 'rev-parse', 'HEAD'], cwd=path, default='')
            if version:
                return
            shutil.rmtree(path)
        os.makedirs(path)

        # Download the tar archive and create a git repo.
        print('Downloading %s' % self._url)
        with tempfile.NamedTemporaryFile() as f:
            run_proc(['wget', self._url, '-O', f.name])
            run_proc(['tar', 'xf', f.name, '-C', path, '--strip-components', '1'])

        run_proc(['git', 'init'], cwd=path)
        run_proc(['git', 'add', '-A'], cwd=path)
        run_proc(['git', 'commit', '-m', '"Initial commit"'], cwd=path)

class LocalSrc(Src):
    """Local source, copied from a directory. Assumes source is a git repo."""

    def __init__(self, path):
        self._path = os.path.expanduser(path)

    def download(self, path):
        if os.path.exists(path):
            return

        print('Copying %s' % self._path)
        shutil.copytree(self._path, path)


class Project(object):
    """Base class for all project definitions."""

    def __init__(self, name, fixed, src, dirs, use_hash, args):
        self._name = name
        self._fixed = fixed
        self._src = src
        self._dirs = dirs if dirs else ['.']
        self._use_hash = use_hash
        self._args = args

    def download(self, path):
        self._src.download(path)

    def get_name(self):
        return self._name

    def get_dirs(self):
        return self._dirs

    def is_fixed(self):
        return self._fixed

    def patch(self, path, patch):
        """Applies a patch to the project."""

        diff = run_proc([
            'git',
            'status',
            '--porcelain',
            '--ignore-submodules=all'
        ], cwd=path, default='')
        if diff: return
        run_proc(['git', 'apply', patch], cwd=path)

    def build(self, path, graph, log):
        """Builds the project using GNU Make."""

        self._mkcheck(self._get_path(path), graph, log, 'build')

    def fuzz(self, path, graph, log):
        """Fuzzes the GNU Make project"""

        self._mkcheck(self._get_path(path), graph, log, 'fuzz')

    def race(self, path, graph, log):
        """Tests the GNU Make project for races"""

        self._mkcheck(self._get_path(path), graph, log, 'race')

    def _mkcheck(self, path, graph, log, command):
        """Fuzzes the project."""

        if os.path.exists(log): return

        args = []
        rule_path = os.path.join('rules', self.get_name() + '.yaml')
        if os.path.exists(rule_path):
            args += ['--rule-path=%s' % os.path.abspath(rule_path)]
        if self._use_hash:
            args += ['--use-hash']
        if self._args:
            args += ['--argv=%s' % ','.join(self._args)]

        print('Running %s: %s' % (self._name, command))
        build_proc(
            ['python', FUZZER, '--graph-path=%s' % graph] + args + [command],
            path,
            log
        )

class MakeProject(Project):
    """GNU Make based project."""

    def __init__(self, name, fixed, src, dirs=[], config=[], use_hash=False, args=None):
        super(MakeProject, self).__init__(name, fixed, src, dirs, use_hash, args)
        self._config = config

    def configure(self, path):
        """Nothing to configure for GNU Make."""

        if not self._config:
            return

        if type(self._config[0]) is list:
            for config in self._config:
                run_proc(config, cwd=path)
        else:
            run_proc(self._config, cwd=path)

    def _get_path(self, path):
        """No adjusment for SCons."""

        return path

class CMakeProject(Project):
    """CMake based project."""

    def __init__(self, name, fixed, src, in_source, config=[], dirs=[], args=None):
        super(CMakeProject, self).__init__(name, fixed, src, dirs, False, args)
        self._in_source = in_source
        self._config = config

    def configure(self, path):
        """Invoke CMake"""

        if self._in_source:
            if os.path.exists(os.path.join(path, 'Makefile')):
                return
            run_proc(['cmake', '.'] + self._config, cwd=path)
        else:
            build_path = os.path.join(path, 'build')
            if os.path.exists(os.path.join(build_path, 'Makefile')):
                return
            os.makedirs(build_path)
            run_proc(['cmake', '..'] + self._config, cwd=build_path)

    def _get_path(self, path):
        """Adjust path to CMake directory."""

        return path if self._in_source else os.path.join(path, 'build')

class SConsProject(Project):
    """SCons based project."""

    def __init__(self, name, fixed, src, dirs=[], use_hash=False, config=[], args=None):
        super(SConsProject, self).__init__(name, fixed, src, dirs, use_hash, args)
        self._config = config

    def configure(self, path):
        """Nothing to configure for SCons."""

        if self._config:
            run_proc(self._config, cwd=path)

    def _get_path(self, path):
        """No adjusment for SCons."""

        return path



PROJECTS = [
    MakeProject ('linux',             False, HttpSrc('https://cdn.kernel.org/pub/linux/kernel/v4.x/linux-4.15.tar.xz'), config=['make', 'allnoconfig'], use_hash=True),
    MakeProject ('redis',             False, GitHubSrc('antirez/redis',                    '2717be63922df9775f1ae6f25163afe500646f3d'), args=['MALLOC=libc']),
    MakeProject ('tinycc',            False, HttpSrc('http://download.savannah.gnu.org/releases/tinycc/tcc-0.9.26.tar.bz2'), config=['./configure']),
    MakeProject ('namespaced_parser', True,  GitHubSrc('pyssling/namespaced_parser',       '996cdf743e5fd0b2dbf3843161ae196c8602b330')),
    MakeProject ('cboy',              False, GitHubSrc('jkbenaim/cboy',                    'a4432014789b991107779b92afa5925b0db8c863'), dirs=['bootrom', 'src']),
    MakeProject ('tinyvm',            True,  GitHubSrc('dcdelia/tinyvm',                   '7095461154d52e5dbef66ffba573854c6fb5fda0')),
    MakeProject ('x86-thing',         False, GitHubSrc('nicknytko/x86-thing',              '28c77af0b22db4a02c4f38e2ee6c45296176d7fd')),
    MakeProject ('CacheSimulator',    True,  GitHubSrc('sadiredd-sv/CacheSimulator',       'ec55d74962f7033abde692a0997503f65a1cf445'), config=['make', 'clean']),
    MakeProject ('lec',               True,  GitHubSrc('coldbloodx/lec',                   'd65a4ed238c2c2a82f8d8a9f8a5c34b4cebc3747')),
    MakeProject ('Generic-C-Project', False, GitHubSrc('kostrahb/Generic-C-Project',       '7bdc463a1c21fce181c338361532926add1b76f0'), config=[['make'], ['make', 'clean']]),
    MakeProject ('hindsight-is-8080', False, GitHubSrc('percivalgambit/hindsight-is-8080', '8ad0a77ed2ae9bb33b04592dac74ab09fdd67651')),
    MakeProject ('reon',              False, LocalSrc('~/deps/reon')),
    MakeProject ('apron',             False, GitHubSrc('aziem/apron-orig',                 '685e67bbf265ceb3844197a5caa606b17adfa6e6'), config=['./configure', '--no-ocaml', '-no-cxx', '-no-java', '--no-ppl']),

    CMakeProject('mysql-server',      False, HttpSrc('https://github.com/mysql/mysql-server/archive/mysql-5.5.62.tar.gz'), False),
    CMakeProject('anbox',             False, GitHubSrc('anbox/anbox',                      'ac2ccb47fb183364588298c426baccb9f05c7531'), False),
    CMakeProject('pifox',             False, GitHubSrc('icteam28/pifox',                   '4ae6f73c491347688dadf4bb823015a44d338be3'), False, config=['-DCMAKE_ASM_COMPILER=arm-none-eabi-gcc']),
    CMakeProject('gr-ieee802-11',     True,  GitHubSrc('bastibl/gr-ieee802-11',            '08787e1ddb706b3aa40ed9170d1ab37289d876f4'), False),
    CMakeProject('grappa',            False, GitHubSrc('uwsampa/grappa',                   '69f2f3674d6f8e512e0bf55264bb75b972fd82de'), False),
    CMakeProject('automate',          False, GitHubSrc('qknight/automate',                 'd1aa626163f4243523192804c0846c2b5cf67e01'), False),
    CMakeProject('ALang',             True,  GitHubSrc('regmi007/ALang',                   'cf5419d06e1328dd38b9c05653fa84b90591c2ff'), False),
    CMakeProject('specfem3d_geotech', False, GitHubSrc('geodynamics/specfem3d_geotech',    '451d29097169feffb8ed64fcb6cf36724698cf65'), False),
    CMakeProject('tiny3Dloader',      False, GitHubSrc('DavidPeicho/tiny3Dloader',         'f54aec1f6fd434f27141a5123d4e7086e4a4fe83'), False),
    CMakeProject('decaf',             True,  GitHubSrc('davidzchen/decaf',                 'c3b9b53054f82f6b2b1f09895ca59b9290ddd557'), True),
    CMakeProject('sppl',              False, GitHubSrc('prozum/sppl',                      '77de5db600a89b84bc8e6e851c9a766cd5203ce2'), False),
    CMakeProject('Pixslam',           True,  GitHubSrc('lukedodd/Pixslam',                 '296f289e433eb3319821611702fb60b245a192a7'), True),
    CMakeProject('tetris',            True,  GitHubSrc('leidav/tetris',                    '144b9cf3b888d5b6bf21ff81432f5a7ef092323d'), False),
    CMakeProject('libcalrom',         True,  GitHubSrc('calendarium-romanum/libcalrom',    '799ee13dbb3ffa08f15bd65dca7b492f7bb84ec9'), True),

    SConsProject('FreeNOS',           False, GitHubSrc('nieklinnenbank/FreeNOS',           '7a17783e7ed176676cdb113015add0719e03ff41')),
    SConsProject('baresifter',        False, GitHubSrc('blitz/baresifter',                 'c247bd6b7b537e3c747d25cf4124c05b4ff70455'), config=['git', 'describe', '--always', '--dirty']),
    SConsProject('steppinrazor',      False, GitHubSrc('profmaad/steppinrazor',            '92155167cda3c13062aa3189aa46005a4afa09c3')),
    SConsProject('nonpareil',         False, HttpSrc('http://nonpareil.brouhaha.com/download/nonpareil-0.79.tar.gz')),
    SConsProject('fsp',               False, HttpSrc('https://netix.dl.sourceforge.net/project/fsp/fsp/2.8.1b27/fsp-2.8.1b27.tar.gz')),
]



def count_results(path):
    """Counts the number of files which trigger incorrect builds."""

    p = defaultdict(lambda: 0)
    m = defaultdict(lambda: 0)
    files = set()
    file = None
    with open(path, 'r') as f:
      for line in f.readlines():
        line = line.strip()
        if line.startswith('['):
            file = line.split(']')[1].strip()
        if not file:
            continue
        files.add(file)
        if line.startswith('+'):
            p[file] += 1
        if line.startswith('-'):
            m[file] += 1
    return len(files), len(m), len(p)


def has_races(path):
    """Checks if a result file has races."""

    with open(path, 'r') as f:
        return len(f.readlines()) > 2


def test_project(proj, kind):
    """Fully tests a version of a project."""

    # Set up the files required by the build.
    base_path = os.path.join('tmp/src-%s' % kind, proj.get_name())
    patch = os.path.abspath('patches/%s-%s.diff' % (proj.get_name(), kind))
    log_path = os.path.abspath('tmp/output/%s' % proj.get_name())
    if not os.path.exists(log_path): os.makedirs(log_path)

    # Get the source code and optionally patch it.
    proj.download(base_path)
    if os.path.exists(patch): proj.patch(base_path, patch)

    # Build and run each subfolder.
    tnf = 0
    tm = 0
    tp = 0
    races = False

    for subdir in proj.get_dirs():
        # Find the path of the subproject.
        suffix = ('-' + subdir) if subdir != '.' else ''
        path = os.path.abspath(os.path.join(base_path, subdir))
        graph_path = os.path.join(log_path, 'graph-%s%s' % (kind, suffix))
        fuzz_path = os.path.join(log_path, 'fuzz-%s%s.log' % (kind, suffix))
        race_path = os.path.join(log_path, 'race-%s%s.log' % (kind, suffix))
        build_path = os.path.join(log_path, 'build-%s%s.log' % (kind, suffix))

        # Configure the project, if required.
        proj.configure(path)

        # Generate the database and run all tests.
        proj.build(path, graph_path, build_path)
        proj.fuzz(path, graph_path, fuzz_path)
        proj.race(path, graph_path, race_path)

        # count the results.
        nf, m, p = count_results(fuzz_path)
        tnf += nf
        tm += m
        tp += p
        races = races | has_races(race_path)

    return tnf, tm, tp, races



if __name__ == '__main__':
    for proj in PROJECTS:
        if len(sys.argv) > 1 and proj.get_name() not in sys.argv:
            continue
        nf, m, p, races = test_project(proj, 'orig')
        if proj.is_fixed():
            _, fm, fp, fraces = test_project(proj, 'fixed')
            fixed = fm == 0 and fp == 0 and not fraces
        else:
            fixed = False
        print('%s %3d %3d %3d %5s %5s' % (proj.get_name().ljust(20), nf, m, p, races, fixed))

