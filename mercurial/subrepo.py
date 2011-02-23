# subrepo.py - sub-repository handling for Mercurial
#
# Copyright 2009-2010 Matt Mackall <mpm@selenic.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

import errno, os, re, xml.dom.minidom, shutil, urlparse, posixpath
import stat, subprocess, tarfile
from i18n import _
import config, util, node, error, cmdutil
hg = None

nullstate = ('', '', 'empty')

def state(ctx, ui):
    """return a state dict, mapping subrepo paths configured in .hgsub
    to tuple: (source from .hgsub, revision from .hgsubstate, kind
    (key in types dict))
    """
    p = config.config()
    def read(f, sections=None, remap=None):
        if f in ctx:
            try:
                data = ctx[f].data()
            except IOError, err:
                if err.errno != errno.ENOENT:
                    raise
                # handle missing subrepo spec files as removed
                ui.warn(_("warning: subrepo spec file %s not found\n") % f)
                return
            p.parse(f, data, sections, remap, read)
        else:
            raise util.Abort(_("subrepo spec file %s not found") % f)

    if '.hgsub' in ctx:
        read('.hgsub')

    for path, src in ui.configitems('subpaths'):
        p.set('subpaths', path, src, ui.configsource('subpaths', path))

    rev = {}
    if '.hgsubstate' in ctx:
        try:
            for l in ctx['.hgsubstate'].data().splitlines():
                revision, path = l.split(" ", 1)
                rev[path] = revision
        except IOError, err:
            if err.errno != errno.ENOENT:
                raise

    state = {}
    for path, src in p[''].items():
        kind = 'hg'
        if src.startswith('['):
            if ']' not in src:
                raise util.Abort(_('missing ] in subrepo source'))
            kind, src = src.split(']', 1)
            kind = kind[1:]

        for pattern, repl in p.items('subpaths'):
            # Turn r'C:\foo\bar' into r'C:\\foo\\bar' since re.sub
            # does a string decode.
            repl = repl.encode('string-escape')
            # However, we still want to allow back references to go
            # through unharmed, so we turn r'\\1' into r'\1'. Again,
            # extra escapes are needed because re.sub string decodes.
            repl = re.sub(r'\\\\([0-9]+)', r'\\\1', repl)
            try:
                src = re.sub(pattern, repl, src, 1)
            except re.error, e:
                raise util.Abort(_("bad subrepository pattern in %s: %s")
                                 % (p.source('subpaths', pattern), e))

        state[path] = (src.strip(), rev.get(path, ''), kind)

    return state

def writestate(repo, state):
    """rewrite .hgsubstate in (outer) repo with these subrepo states"""
    repo.wwrite('.hgsubstate',
                ''.join(['%s %s\n' % (state[s][1], s)
                         for s in sorted(state)]), '')

def submerge(repo, wctx, mctx, actx, overwrite):
    """delegated from merge.applyupdates: merging of .hgsubstate file
    in working context, merging context and ancestor context"""
    if mctx == actx: # backwards?
        actx = wctx.p1()
    s1 = wctx.substate
    s2 = mctx.substate
    sa = actx.substate
    sm = {}

    repo.ui.debug("subrepo merge %s %s %s\n" % (wctx, mctx, actx))

    def debug(s, msg, r=""):
        if r:
            r = "%s:%s:%s" % r
        repo.ui.debug("  subrepo %s: %s %s\n" % (s, msg, r))

    for s, l in s1.items():
        a = sa.get(s, nullstate)
        ld = l # local state with possible dirty flag for compares
        if wctx.sub(s).dirty():
            ld = (l[0], l[1] + "+")
        if wctx == actx: # overwrite
            a = ld

        if s in s2:
            r = s2[s]
            if ld == r or r == a: # no change or local is newer
                sm[s] = l
                continue
            elif ld == a: # other side changed
                debug(s, "other changed, get", r)
                wctx.sub(s).get(r, overwrite)
                sm[s] = r
            elif ld[0] != r[0]: # sources differ
                if repo.ui.promptchoice(
                    _(' subrepository sources for %s differ\n'
                      'use (l)ocal source (%s) or (r)emote source (%s)?')
                      % (s, l[0], r[0]),
                      (_('&Local'), _('&Remote')), 0):
                    debug(s, "prompt changed, get", r)
                    wctx.sub(s).get(r, overwrite)
                    sm[s] = r
            elif ld[1] == a[1]: # local side is unchanged
                debug(s, "other side changed, get", r)
                wctx.sub(s).get(r, overwrite)
                sm[s] = r
            else:
                debug(s, "both sides changed, merge with", r)
                wctx.sub(s).merge(r)
                sm[s] = l
        elif ld == a: # remote removed, local unchanged
            debug(s, "remote removed, remove")
            wctx.sub(s).remove()
        else:
            if repo.ui.promptchoice(
                _(' local changed subrepository %s which remote removed\n'
                  'use (c)hanged version or (d)elete?') % s,
                (_('&Changed'), _('&Delete')), 0):
                debug(s, "prompt remove")
                wctx.sub(s).remove()

    for s, r in s2.items():
        if s in s1:
            continue
        elif s not in sa:
            debug(s, "remote added, get", r)
            mctx.sub(s).get(r)
            sm[s] = r
        elif r != sa[s]:
            if repo.ui.promptchoice(
                _(' remote changed subrepository %s which local removed\n'
                  'use (c)hanged version or (d)elete?') % s,
                (_('&Changed'), _('&Delete')), 0) == 0:
                debug(s, "prompt recreate", r)
                wctx.sub(s).get(r)
                sm[s] = r

    # record merged .hgsubstate
    writestate(repo, sm)

def _updateprompt(ui, sub, dirty, local, remote):
    if dirty:
        msg = (_(' subrepository sources for %s differ\n'
                 'use (l)ocal source (%s) or (r)emote source (%s)?\n')
               % (subrelpath(sub), local, remote))
    else:
        msg = (_(' subrepository sources for %s differ (in checked out version)\n'
                 'use (l)ocal source (%s) or (r)emote source (%s)?\n')
               % (subrelpath(sub), local, remote))
    return ui.promptchoice(msg, (_('&Local'), _('&Remote')), 0)

def reporelpath(repo):
    """return path to this (sub)repo as seen from outermost repo"""
    parent = repo
    while hasattr(parent, '_subparent'):
        parent = parent._subparent
    return repo.root[len(parent.root)+1:]

def subrelpath(sub):
    """return path to this subrepo as seen from outermost repo"""
    if hasattr(sub, '_relpath'):
        return sub._relpath
    if not hasattr(sub, '_repo'):
        return sub._path
    return reporelpath(sub._repo)

def _abssource(repo, push=False, abort=True):
    """return pull/push path of repo - either based on parent repo .hgsub info
    or on the top repo config. Abort or return None if no source found."""
    if hasattr(repo, '_subparent'):
        source = repo._subsource
        if source.startswith('/') or '://' in source:
            return source
        parent = _abssource(repo._subparent, push, abort=False)
        if parent:
            if '://' in parent:
                if parent[-1] == '/':
                    parent = parent[:-1]
                r = urlparse.urlparse(parent + '/' + source)
                r = urlparse.urlunparse((r[0], r[1],
                                         posixpath.normpath(r[2]),
                                         r[3], r[4], r[5]))
                return r
            else: # plain file system path
                return posixpath.normpath(os.path.join(parent, repo._subsource))
    else: # recursion reached top repo
        if hasattr(repo, '_subtoppath'):
            return repo._subtoppath
        if push and repo.ui.config('paths', 'default-push'):
            return repo.ui.config('paths', 'default-push')
        if repo.ui.config('paths', 'default'):
            return repo.ui.config('paths', 'default')
    if abort:
        raise util.Abort(_("default path for subrepository %s not found") %
            reporelpath(repo))

def itersubrepos(ctx1, ctx2):
    """find subrepos in ctx1 or ctx2"""
    # Create a (subpath, ctx) mapping where we prefer subpaths from
    # ctx1. The subpaths from ctx2 are important when the .hgsub file
    # has been modified (in ctx2) but not yet committed (in ctx1).
    subpaths = dict.fromkeys(ctx2.substate, ctx2)
    subpaths.update(dict.fromkeys(ctx1.substate, ctx1))
    for subpath, ctx in sorted(subpaths.iteritems()):
        yield subpath, ctx.sub(subpath)

def subrepo(ctx, path):
    """return instance of the right subrepo class for subrepo in path"""
    # subrepo inherently violates our import layering rules
    # because it wants to make repo objects from deep inside the stack
    # so we manually delay the circular imports to not break
    # scripts that don't use our demand-loading
    global hg
    import hg as h
    hg = h

    util.path_auditor(ctx._repo.root)(path)
    state = ctx.substate.get(path, nullstate)
    if state[2] not in types:
        raise util.Abort(_('unknown subrepo type %s') % state[2])
    return types[state[2]](ctx, path, state[:2])

# subrepo classes need to implement the following abstract class:

class abstractsubrepo(object):

    def dirty(self, ignoreupdate=False):
        """returns true if the dirstate of the subrepo is dirty or does not
        match current stored state. If ignoreupdate is true, only check
        whether the subrepo has uncommitted changes in its dirstate.
        """
        raise NotImplementedError

    def checknested(self, path):
        """check if path is a subrepository within this repository"""
        return False

    def commit(self, text, user, date):
        """commit the current changes to the subrepo with the given
        log message. Use given user and date if possible. Return the
        new state of the subrepo.
        """
        raise NotImplementedError

    def remove(self):
        """remove the subrepo

        (should verify the dirstate is not dirty first)
        """
        raise NotImplementedError

    def get(self, state, overwrite=False):
        """run whatever commands are needed to put the subrepo into
        this state
        """
        raise NotImplementedError

    def merge(self, state):
        """merge currently-saved state with the new state."""
        raise NotImplementedError

    def push(self, force):
        """perform whatever action is analogous to 'hg push'

        This may be a no-op on some systems.
        """
        raise NotImplementedError

    def add(self, ui, match, dryrun, prefix):
        return []

    def status(self, rev2, **opts):
        return [], [], [], [], [], [], []

    def diff(self, diffopts, node2, match, prefix, **opts):
        pass

    def outgoing(self, ui, dest, opts):
        return 1

    def incoming(self, ui, source, opts):
        return 1

    def files(self):
        """return filename iterator"""
        raise NotImplementedError

    def filedata(self, name):
        """return file data"""
        raise NotImplementedError

    def fileflags(self, name):
        """return file flags"""
        return ''

    def archive(self, ui, archiver, prefix):
        files = self.files()
        total = len(files)
        relpath = subrelpath(self)
        ui.progress(_('archiving (%s)') % relpath, 0,
                    unit=_('files'), total=total)
        for i, name in enumerate(files):
            flags = self.fileflags(name)
            mode = 'x' in flags and 0755 or 0644
            symlink = 'l' in flags
            archiver.addfile(os.path.join(prefix, self._path, name),
                             mode, symlink, self.filedata(name))
            ui.progress(_('archiving (%s)') % relpath, i + 1,
                        unit=_('files'), total=total)
        ui.progress(_('archiving (%s)') % relpath, None)


class hgsubrepo(abstractsubrepo):
    def __init__(self, ctx, path, state):
        self._path = path
        self._state = state
        r = ctx._repo
        root = r.wjoin(path)
        create = False
        if not os.path.exists(os.path.join(root, '.hg')):
            create = True
            util.makedirs(root)
        self._repo = hg.repository(r.ui, root, create=create)
        self._repo._subparent = r
        self._repo._subsource = state[0]

        if create:
            fp = self._repo.opener("hgrc", "w", text=True)
            fp.write('[paths]\n')

            def addpathconfig(key, value):
                if value:
                    fp.write('%s = %s\n' % (key, value))
                    self._repo.ui.setconfig('paths', key, value)

            defpath = _abssource(self._repo, abort=False)
            defpushpath = _abssource(self._repo, True, abort=False)
            addpathconfig('default', defpath)
            if defpath != defpushpath:
                addpathconfig('default-push', defpushpath)
            fp.close()

    def add(self, ui, match, dryrun, prefix):
        return cmdutil.add(ui, self._repo, match, dryrun, True,
                           os.path.join(prefix, self._path))

    def status(self, rev2, **opts):
        try:
            rev1 = self._state[1]
            ctx1 = self._repo[rev1]
            ctx2 = self._repo[rev2]
            return self._repo.status(ctx1, ctx2, **opts)
        except error.RepoLookupError, inst:
            self._repo.ui.warn(_('warning: error "%s" in subrepository "%s"\n')
                               % (inst, subrelpath(self)))
            return [], [], [], [], [], [], []

    def diff(self, diffopts, node2, match, prefix, **opts):
        try:
            node1 = node.bin(self._state[1])
            # We currently expect node2 to come from substate and be
            # in hex format
            if node2 is not None:
                node2 = node.bin(node2)
            cmdutil.diffordiffstat(self._repo.ui, self._repo, diffopts,
                                   node1, node2, match,
                                   prefix=os.path.join(prefix, self._path),
                                   listsubrepos=True, **opts)
        except error.RepoLookupError, inst:
            self._repo.ui.warn(_('warning: error "%s" in subrepository "%s"\n')
                               % (inst, subrelpath(self)))

    def archive(self, ui, archiver, prefix):
        abstractsubrepo.archive(self, ui, archiver, prefix)

        rev = self._state[1]
        ctx = self._repo[rev]
        for subpath in ctx.substate:
            s = subrepo(ctx, subpath)
            s.archive(ui, archiver, os.path.join(prefix, self._path))

    def dirty(self, ignoreupdate=False):
        r = self._state[1]
        if r == '' and not ignoreupdate: # no state recorded
            return True
        w = self._repo[None]
        if w.p1() != self._repo[r] and not ignoreupdate:
            # different version checked out
            return True
        return w.dirty() # working directory changed

    def checknested(self, path):
        return self._repo._checknested(self._repo.wjoin(path))

    def commit(self, text, user, date):
        self._repo.ui.debug("committing subrepo %s\n" % subrelpath(self))
        n = self._repo.commit(text, user, date)
        if not n:
            return self._repo['.'].hex() # different version checked out
        return node.hex(n)

    def remove(self):
        # we can't fully delete the repository as it may contain
        # local-only history
        self._repo.ui.note(_('removing subrepo %s\n') % subrelpath(self))
        hg.clean(self._repo, node.nullid, False)

    def _get(self, state):
        source, revision, kind = state
        try:
            self._repo.lookup(revision)
        except error.RepoError:
            self._repo._subsource = source
            srcurl = _abssource(self._repo)
            self._repo.ui.status(_('pulling subrepo %s from %s\n')
                                 % (subrelpath(self), srcurl))
            other = hg.repository(self._repo.ui, srcurl)
            self._repo.pull(other)

    def get(self, state, overwrite=False):
        self._get(state)
        source, revision, kind = state
        self._repo.ui.debug("getting subrepo %s\n" % self._path)
        hg.clean(self._repo, revision, False)

    def merge(self, state):
        self._get(state)
        cur = self._repo['.']
        dst = self._repo[state[1]]
        anc = dst.ancestor(cur)

        def mergefunc():
            if anc == cur:
                self._repo.ui.debug("updating subrepo %s\n" % subrelpath(self))
                hg.update(self._repo, state[1])
            elif anc == dst:
                self._repo.ui.debug("skipping subrepo %s\n" % subrelpath(self))
            else:
                self._repo.ui.debug("merging subrepo %s\n" % subrelpath(self))
                hg.merge(self._repo, state[1], remind=False)

        wctx = self._repo[None]
        if self.dirty():
            if anc != dst:
                if _updateprompt(self._repo.ui, self, wctx.dirty(), cur, dst):
                    mergefunc()
            else:
                mergefunc()
        else:
            mergefunc()

    def push(self, force):
        # push subrepos depth-first for coherent ordering
        c = self._repo['']
        subs = c.substate # only repos that are committed
        for s in sorted(subs):
            if not c.sub(s).push(force):
                return False

        dsturl = _abssource(self._repo, True)
        self._repo.ui.status(_('pushing subrepo %s to %s\n') %
            (subrelpath(self), dsturl))
        other = hg.repository(self._repo.ui, dsturl)
        return self._repo.push(other, force)

    def outgoing(self, ui, dest, opts):
        return hg.outgoing(ui, self._repo, _abssource(self._repo, True), opts)

    def incoming(self, ui, source, opts):
        return hg.incoming(ui, self._repo, _abssource(self._repo, False), opts)

    def files(self):
        rev = self._state[1]
        ctx = self._repo[rev]
        return ctx.manifest()

    def filedata(self, name):
        rev = self._state[1]
        return self._repo[rev][name].data()

    def fileflags(self, name):
        rev = self._state[1]
        ctx = self._repo[rev]
        return ctx.flags(name)


class svnsubrepo(abstractsubrepo):
    def __init__(self, ctx, path, state):
        self._path = path
        self._state = state
        self._ctx = ctx
        self._ui = ctx._repo.ui

    def _svncommand(self, commands, filename=''):
        path = os.path.join(self._ctx._repo.origroot, self._path, filename)
        cmd = ['svn'] + commands + [path]
        env = dict(os.environ)
        # Avoid localized output, preserve current locale for everything else.
        env['LC_MESSAGES'] = 'C'
        p = subprocess.Popen(cmd, bufsize=-1, close_fds=util.closefds,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             universal_newlines=True, env=env)
        stdout, stderr = p.communicate()
        stderr = stderr.strip()
        if stderr:
            raise util.Abort(stderr)
        return stdout

    def _wcrevs(self):
        # Get the working directory revision as well as the last
        # commit revision so we can compare the subrepo state with
        # both. We used to store the working directory one.
        output = self._svncommand(['info', '--xml'])
        doc = xml.dom.minidom.parseString(output)
        entries = doc.getElementsByTagName('entry')
        lastrev, rev = '0', '0'
        if entries:
            rev = str(entries[0].getAttribute('revision')) or '0'
            commits = entries[0].getElementsByTagName('commit')
            if commits:
                lastrev = str(commits[0].getAttribute('revision')) or '0'
        return (lastrev, rev)

    def _wcrev(self):
        return self._wcrevs()[0]

    def _wcchanged(self):
        """Return (changes, extchanges) where changes is True
        if the working directory was changed, and extchanges is
        True if any of these changes concern an external entry.
        """
        output = self._svncommand(['status', '--xml'])
        externals, changes = [], []
        doc = xml.dom.minidom.parseString(output)
        for e in doc.getElementsByTagName('entry'):
            s = e.getElementsByTagName('wc-status')
            if not s:
                continue
            item = s[0].getAttribute('item')
            props = s[0].getAttribute('props')
            path = e.getAttribute('path')
            if item == 'external':
                externals.append(path)
            if (item not in ('', 'normal', 'unversioned', 'external')
                or props not in ('', 'none')):
                changes.append(path)
        for path in changes:
            for ext in externals:
                if path == ext or path.startswith(ext + os.sep):
                    return True, True
        return bool(changes), False

    def dirty(self, ignoreupdate=False):
        if not self._wcchanged()[0]:
            if self._state[1] in self._wcrevs() or ignoreupdate:
                return False
        return True

    def commit(self, text, user, date):
        # user and date are out of our hands since svn is centralized
        changed, extchanged = self._wcchanged()
        if not changed:
            return self._wcrev()
        if extchanged:
            # Do not try to commit externals
            raise util.Abort(_('cannot commit svn externals'))
        commitinfo = self._svncommand(['commit', '-m', text])
        self._ui.status(commitinfo)
        newrev = re.search('Committed revision ([0-9]+).', commitinfo)
        if not newrev:
            raise util.Abort(commitinfo.splitlines()[-1])
        newrev = newrev.groups()[0]
        self._ui.status(self._svncommand(['update', '-r', newrev]))
        return newrev

    def remove(self):
        if self.dirty():
            self._ui.warn(_('not removing repo %s because '
                            'it has changes.\n' % self._path))
            return
        self._ui.note(_('removing subrepo %s\n') % self._path)

        def onerror(function, path, excinfo):
            if function is not os.remove:
                raise
            # read-only files cannot be unlinked under Windows
            s = os.stat(path)
            if (s.st_mode & stat.S_IWRITE) != 0:
                raise
            os.chmod(path, stat.S_IMODE(s.st_mode) | stat.S_IWRITE)
            os.remove(path)

        path = self._ctx._repo.wjoin(self._path)
        shutil.rmtree(path, onerror=onerror)
        try:
            os.removedirs(os.path.dirname(path))
        except OSError:
            pass

    def get(self, state, overwrite=False):
        if overwrite:
            self._svncommand(['revert', '--recursive'])
        status = self._svncommand(['checkout', state[0], '--revision', state[1]])
        if not re.search('Checked out revision [0-9]+.', status):
            raise util.Abort(status.splitlines()[-1])
        self._ui.status(status)

    def merge(self, state):
        old = self._state[1]
        new = state[1]
        if new != self._wcrev():
            dirty = old == self._wcrev() or self._wcchanged()[0]
            if _updateprompt(self._ui, self, dirty, self._wcrev(), new):
                self.get(state, False)

    def push(self, force):
        # push is a no-op for SVN
        return True

    def files(self):
        output = self._svncommand(['list'])
        # This works because svn forbids \n in filenames.
        return output.splitlines()

    def filedata(self, name):
        return self._svncommand(['cat'], name)


class gitsubrepo(abstractsubrepo):
    def __init__(self, ctx, path, state):
        # TODO add git version check.
        self._state = state
        self._ctx = ctx
        self._path = path
        self._relpath = os.path.join(reporelpath(ctx._repo), path)
        self._abspath = ctx._repo.wjoin(path)
        self._subparent = ctx._repo
        self._ui = ctx._repo.ui

    def _gitcommand(self, commands, env=None, stream=False):
        return self._gitdir(commands, env=env, stream=stream)[0]

    def _gitdir(self, commands, env=None, stream=False):
        return self._gitnodir(commands, env=env, stream=stream,
                              cwd=self._abspath)

    def _gitnodir(self, commands, env=None, stream=False, cwd=None):
        """Calls the git command

        The methods tries to call the git command. versions previor to 1.6.0
        are not supported and very probably fail.
        """
        self._ui.debug('%s: git %s\n' % (self._relpath, ' '.join(commands)))
        # unless ui.quiet is set, print git's stderr,
        # which is mostly progress and useful info
        errpipe = None
        if self._ui.quiet:
            errpipe = open(os.devnull, 'w')
        p = subprocess.Popen(['git'] + commands, bufsize=-1, cwd=cwd, env=env,
                             close_fds=util.closefds,
                             stdout=subprocess.PIPE, stderr=errpipe)
        if stream:
            return p.stdout, None

        retdata = p.stdout.read().strip()
        # wait for the child to exit to avoid race condition.
        p.wait()

        if p.returncode != 0 and p.returncode != 1:
            # there are certain error codes that are ok
            command = commands[0]
            if command in ('cat-file', 'symbolic-ref'):
                return retdata, p.returncode
            # for all others, abort
            raise util.Abort('git %s error %d in %s' %
                             (command, p.returncode, self._relpath))

        return retdata, p.returncode

    def _gitstate(self):
        return self._gitcommand(['rev-parse', 'HEAD'])

    def _gitcurrentbranch(self):
        current, err = self._gitdir(['symbolic-ref', 'HEAD', '--quiet'])
        if err:
            current = None
        return current

    def _githavelocally(self, revision):
        out, code = self._gitdir(['cat-file', '-e', revision])
        return code == 0

    def _gitisancestor(self, r1, r2):
        base = self._gitcommand(['merge-base', r1, r2])
        return base == r1

    def _gitbranchmap(self):
        '''returns 2 things:
        a map from git branch to revision
        a map from revision to branches'''
        branch2rev = {}
        rev2branch = {}

        out = self._gitcommand(['for-each-ref', '--format',
                                '%(objectname) %(refname)'])
        for line in out.split('\n'):
            revision, ref = line.split(' ')
            if (not ref.startswith('refs/heads/') and
                not ref.startswith('refs/remotes/')):
                continue
            if ref.startswith('refs/remotes/') and ref.endswith('/HEAD'):
                continue # ignore remote/HEAD redirects
            branch2rev[ref] = revision
            rev2branch.setdefault(revision, []).append(ref)
        return branch2rev, rev2branch

    def _gittracking(self, branches):
        'return map of remote branch to local tracking branch'
        # assumes no more than one local tracking branch for each remote
        tracking = {}
        for b in branches:
            if b.startswith('refs/remotes/'):
                continue
            remote = self._gitcommand(['config', 'branch.%s.remote' % b])
            if remote:
                ref = self._gitcommand(['config', 'branch.%s.merge' % b])
                tracking['refs/remotes/%s/%s' %
                         (remote, ref.split('/', 2)[2])] = b
        return tracking

    def _abssource(self, source):
        self._subsource = source
        return _abssource(self)

    def _fetch(self, source, revision):
        if not os.path.exists(os.path.join(self._abspath, '.git')):
            self._ui.status(_('cloning subrepo %s\n') % self._relpath)
            self._gitnodir(['clone', self._abssource(source), self._abspath])
        if self._githavelocally(revision):
            return
        self._ui.status(_('pulling subrepo %s\n') % self._relpath)
        # first try from origin
        self._gitcommand(['fetch'])
        if self._githavelocally(revision):
            return
        # then try from known subrepo source
        self._gitcommand(['fetch', self._abssource(source)])
        if not self._githavelocally(revision):
            raise util.Abort(_("revision %s does not exist in subrepo %s\n") %
                               (revision, self._relpath))

    def dirty(self, ignoreupdate=False):
        if not ignoreupdate and self._state[1] != self._gitstate():
            # different version checked out
            return True
        # check for staged changes or modified files; ignore untracked files
        out, code = self._gitdir(['diff-index', '--quiet', 'HEAD'])
        return code == 1

    def get(self, state, overwrite=False):
        source, revision, kind = state
        self._fetch(source, revision)
        # if the repo was set to be bare, unbare it
        if self._gitcommand(['config', '--bool', 'core.bare']) == 'true':
            self._gitcommand(['config', 'core.bare', 'false'])
            if self._gitstate() == revision:
                self._gitcommand(['reset', '--hard', 'HEAD'])
                return
        elif self._gitstate() == revision:
            if overwrite:
                # first reset the index to unmark new files for commit, because 
                # reset --hard will otherwise throw away files added for commit,
                # not just unmark them.
                self._gitcommand(['reset', 'HEAD'])
                self._gitcommand(['reset', '--hard', 'HEAD'])
            return
        branch2rev, rev2branch = self._gitbranchmap()

        def checkout(args):
            cmd = ['checkout']
            if overwrite:
                # first reset the index to unmark new files for commit, because
                # the -f option will otherwise throw away files added for
                # commit, not just unmark them.
                self._gitcommand(['reset', 'HEAD'])
                cmd.append('-f')
            self._gitcommand(cmd + args)

        def rawcheckout():
            # no branch to checkout, check it out with no branch
            self._ui.warn(_('checking out detached HEAD in subrepo %s\n') %
                          self._relpath)
            self._ui.warn(_('check out a git branch if you intend '
                            'to make changes\n'))
            checkout(['-q', revision])

        if revision not in rev2branch:
            rawcheckout()
            return
        branches = rev2branch[revision]
        firstlocalbranch = None
        for b in branches:
            if b == 'refs/heads/master':
                # master trumps all other branches
                checkout(['refs/heads/master'])
                return
            if not firstlocalbranch and not b.startswith('refs/remotes/'):
                firstlocalbranch = b
        if firstlocalbranch:
            checkout([firstlocalbranch])
            return

        tracking = self._gittracking(branch2rev.keys())
        # choose a remote branch already tracked if possible
        remote = branches[0]
        if remote not in tracking:
            for b in branches:
                if b in tracking:
                    remote = b
                    break

        if remote not in tracking:
            # create a new local tracking branch
            local = remote.split('/', 2)[2]
            checkout(['-b', local, remote])
        elif self._gitisancestor(branch2rev[tracking[remote]], remote):
            # When updating to a tracked remote branch,
            # if the local tracking branch is downstream of it,
            # a normal `git pull` would have performed a "fast-forward merge"
            # which is equivalent to updating the local branch to the remote.
            # Since we are only looking at branching at update, we need to
            # detect this situation and perform this action lazily.
            if tracking[remote] != self._gitcurrentbranch():
                checkout([tracking[remote]])
            self._gitcommand(['merge', '--ff', remote])
        else:
            # a real merge would be required, just checkout the revision
            rawcheckout()

    def commit(self, text, user, date):
        cmd = ['commit', '-a', '-m', text]
        env = os.environ.copy()
        if user:
            cmd += ['--author', user]
        if date:
            # git's date parser silently ignores when seconds < 1e9
            # convert to ISO8601
            env['GIT_AUTHOR_DATE'] = util.datestr(date,
                                                  '%Y-%m-%dT%H:%M:%S %1%2')
        self._gitcommand(cmd, env=env)
        # make sure commit works otherwise HEAD might not exist under certain
        # circumstances
        return self._gitstate()

    def merge(self, state):
        source, revision, kind = state
        self._fetch(source, revision)
        base = self._gitcommand(['merge-base', revision, self._state[1]])
        out, code = self._gitdir(['diff-index', '--quiet', 'HEAD'])

        def mergefunc():
            if base == revision:
                self.get(state) # fast forward merge
            elif base != self._state[1]:
                self._gitcommand(['merge', '--no-commit', revision])

        if self.dirty():
            if self._gitstate() != revision:
                dirty = self._gitstate() == self._state[1] or code != 0
                if _updateprompt(self._ui, self, dirty,
                                 self._state[1][:7], revision[:7]):
                    mergefunc()
        else:
            mergefunc()

    def push(self, force):
        # if a branch in origin contains the revision, nothing to do
        branch2rev, rev2branch = self._gitbranchmap()
        if self._state[1] in rev2branch:
            for b in rev2branch[self._state[1]]:
                if b.startswith('refs/remotes/origin/'):
                    return True
        for b, revision in branch2rev.iteritems():
            if b.startswith('refs/remotes/origin/'):
                if self._gitisancestor(self._state[1], revision):
                    return True
        # otherwise, try to push the currently checked out branch
        cmd = ['push']
        if force:
            cmd.append('--force')

        current = self._gitcurrentbranch()
        if current:
            # determine if the current branch is even useful
            if not self._gitisancestor(self._state[1], current):
                self._ui.warn(_('unrelated git branch checked out '
                                'in subrepo %s\n') % self._relpath)
                return False
            self._ui.status(_('pushing branch %s of subrepo %s\n') %
                            (current.split('/', 2)[2], self._relpath))
            self._gitcommand(cmd + ['origin', current])
            return True
        else:
            self._ui.warn(_('no branch checked out in subrepo %s\n'
                            'cannot push revision %s') %
                          (self._relpath, self._state[1]))
            return False

    def remove(self):
        if self.dirty():
            self._ui.warn(_('not removing repo %s because '
                            'it has changes.\n') % self._relpath)
            return
        # we can't fully delete the repository as it may contain
        # local-only history
        self._ui.note(_('removing subrepo %s\n') % self._relpath)
        self._gitcommand(['config', 'core.bare', 'true'])
        for f in os.listdir(self._abspath):
            if f == '.git':
                continue
            path = os.path.join(self._abspath, f)
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path)
            else:
                os.remove(path)

    def archive(self, ui, archiver, prefix):
        source, revision = self._state
        self._fetch(source, revision)

        # Parse git's native archive command.
        # This should be much faster than manually traversing the trees
        # and objects with many subprocess calls.
        tarstream = self._gitcommand(['archive', revision], stream=True)
        tar = tarfile.open(fileobj=tarstream, mode='r|')
        relpath = subrelpath(self)
        ui.progress(_('archiving (%s)') % relpath, 0, unit=_('files'))
        for i, info in enumerate(tar):
            if info.isdir():
                continue
            if info.issym():
                data = info.linkname
            else:
                data = tar.extractfile(info).read()
            archiver.addfile(os.path.join(prefix, self._path, info.name),
                             info.mode, info.issym(), data)
            ui.progress(_('archiving (%s)') % relpath, i + 1,
                        unit=_('files'))
        ui.progress(_('archiving (%s)') % relpath, None)


    def status(self, rev2, **opts):
        rev1 = self._state[1]
        modified, added, removed = [], [], []
        if rev2:
            command = ['diff-tree', rev1, rev2]
        else:
            command = ['diff-index', rev1]
        out = self._gitcommand(command)
        for line in out.split('\n'):
            tab = line.find('\t')
            if tab == -1:
                continue
            status, f = line[tab - 1], line[tab + 1:]
            if status == 'M':
                modified.append(f)
            elif status == 'A':
                added.append(f)
            elif status == 'D':
                removed.append(f)

        deleted = unknown = ignored = clean = []
        return modified, added, removed, deleted, unknown, ignored, clean

types = {
    'hg': hgsubrepo,
    'svn': svnsubrepo,
    'git': gitsubrepo,
    }
