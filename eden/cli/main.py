#!/usr/bin/env python3
#
# Copyright (c) 2016-present, Facebook, Inc.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree. An additional grant
# of patent rights can be found in the PATENTS file in the same directory.

import argparse
from eden.thrift import EdenNotRunningError
import errno
import json
import os
import signal
import subprocess
import sys
import typing
from typing import Any, List, Optional, Set

from . import config as config_mod
from . import debug as debug_mod
from . import doctor as doctor_mod
from . import mtab
from . import rage as rage_mod
from . import stats as stats_mod
from . import subcmd as subcmd_mod
from . import version as version_mod
from . import util
from .cmd_util import create_config
from .subcmd import Subcmd
from .util import print_stderr
from facebook.eden import EdenService

subcmd = subcmd_mod.Decorator()


def infer_client_from_cwd(config: config_mod.Config, clientname: str) -> str:
    if clientname:
        return clientname

    all_clients = config.get_all_client_config_info()
    path = normalize_path_arg(os.getcwd())

    # Keep going while we're not in the root, as dirname(/) is /
    # and we can keep iterating forever.
    while len(path) > 1:
        for _, info in all_clients.items():
            if info['mount'] == path:
                return typing.cast(str, info['mount'])
        path = os.path.dirname(path)

    print_stderr(
        'cwd is not an eden mount point, and no client name was specified.')
    sys.exit(2)


def do_version(args: argparse.Namespace) -> int:
    config = create_config(args)
    print('Installed: %s' %
            version_mod.get_installed_eden_rpm_version())
    import eden
    try:
        rv = version_mod.get_running_eden_version(config)
        print('Running:   %s' % rv)
        if rv.startswith('-') or rv.endswith('-'):
            print('(Dev version of eden seems to be running)')
    except eden.thrift.client.EdenNotRunningError:
        print('Running:   Unknown (edenfs does not appear to be running)')
    return 0


@subcmd('version', "Print Eden's version information.")
class VersionCmd(Subcmd):
    def run(self, args: argparse.Namespace) -> int:
        return do_version(args)


@subcmd('info', 'Get details about a client')
class InfoCmd(Subcmd):
    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            'client',
            default=None,
            nargs='?',
            help='Name of the client')

    def run(self, args: argparse.Namespace) -> int:
        config = create_config(args)
        info = config.get_client_info(
            infer_client_from_cwd(config, args.client)
        )
        json.dump(info, sys.stdout, indent=2)
        sys.stdout.write('\n')
        return 0


@subcmd('health', 'Check the health of the Eden service')
class HealthCmd(Subcmd):
    def run(self, args: argparse.Namespace) -> int:
        config = create_config(args)
        health_info = config.check_health()
        if health_info.is_healthy():
            print('eden running normally (pid {})'.format(health_info.pid))
            return 0

        print('edenfs not healthy: {}'.format(health_info.detail))
        return 1


@subcmd('repository', 'List all repositories')
class RepositoryCmd(Subcmd):
    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            'name',
            nargs='?', default=None,
            help='Name of the client to mount')
        parser.add_argument(
            'path',
            nargs='?', default=None,
            help='Path to the repository to import')
        parser.add_argument(
            '--with-buck', '-b', action='store_true',
            help='Client should create a bind mount for buck-out/.')

    def run(self, args: argparse.Namespace) -> int:
        config = create_config(args)
        if (args.name and args.path):
            repo_source, repo_type = util.get_repo_source_and_type(args.path)
            if repo_type is None:
                print_stderr(
                    '%s does not look like a git or hg repository' % args.path)
                return 1
            try:
                config.add_repository(args.name,
                                      repo_type=repo_type,
                                      source=repo_source,
                                      with_buck=args.with_buck)
            except config_mod.UsageError as ex:
                print_stderr('error: {}', ex)
                return 1
        elif (args.name or args.path):
            print_stderr('repository command called with incorrect arguments')
            return 1
        else:
            repo_list = config.get_repository_list()
            for repo in sorted(repo_list):
                print(repo)
        return 0


@subcmd('list', 'List available clients')
class ListCmd(Subcmd):
    def run(self, args: argparse.Namespace) -> int:
        config = create_config(args)

        try:
            with config.get_thrift_client() as client:
                active_mount_points: Set[Optional[str]] = {
                    mount.mountPoint
                    for mount in client.listMounts()
                }
        except EdenNotRunningError:
            active_mount_points = set()

        config_mount_points = set(config.get_mount_paths())

        for path in sorted(active_mount_points | config_mount_points):
            assert path is not None
            if path not in config_mount_points:
                print(path + ' (unconfigured)')
            elif path in active_mount_points:
                print(path + ' (active)')
            else:
                print(path)
        return 0


@subcmd('clone', 'Create a clone of a specific repo')
class CloneCmd(Subcmd):

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            'repo',
            help='Name of a repository config or path to an existing repo '
            'to clone')
        parser.add_argument(
            'path', help='Path where the client should be mounted')
        parser.add_argument(
            '--snapshot', '-s', type=str, help='Snapshot id of revision')
        parser.add_argument(
            '--allow-empty-repo', '-e', action='store_true',
            help='Allow repo with null revision (no revisions)')
        # Optional arguments to control how to start the daemon if clone needs
        # to start edenfs.  We do not show these in --help by default These
        # behave identically to the daemon arguments with the same name.
        parser.add_argument(
            '--daemon-binary',
            help=argparse.SUPPRESS)
        parser.add_argument(
            '--daemon-args',
            dest='edenfs_args',
            nargs=argparse.REMAINDER,
            help=argparse.SUPPRESS)

    def run(self, args: argparse.Namespace) -> int:
        NULL_REVISION = '0' * 40
        config = create_config(args)
        try:
            client_config = config.find_config_for_alias(args.repo)
        except Exception as e:
            print_stderr('error: {}', e)
            return 1

        if client_config is None:
            # If args.repo does not identify a named repository defined in
            # .edenrc, see if the argument corresponds to a local path that
            # contains a repository.
            client_config = try_create_config_from_repo(args.repo, config)
            assert client_config is not None

        args.path = normalize_path_arg(args.path)
        try:
            bm = args.snapshot or client_config.default_revision
            if client_config.scm_type == 'git':
                snapshot_id = util.get_git_commit(
                    git_dir=client_config.path, bookmark=bm)
            elif client_config.scm_type == 'hg':
                snapshot_id = util.get_hg_commit(
                    repo=client_config.path, bookmark=bm)
            else:
                print_stderr(
                    '%s does not look like a git or hg repository' %
                    client_config.path
                )
                return 1
        except Exception as e:
            print_stderr('error: {}', e)
            # set snapshot_id just to trigger error clause below
            snapshot_id = NULL_REVISION
        if ((not util.is_valid_sha1(snapshot_id)) or
                (snapshot_id == NULL_REVISION and not args.allow_empty_repo)):
            print_stderr(
                'Obtained commit for repo is invalid: %s' % snapshot_id
            )
            print_stderr(
                ' %s repository may still be cloning.' % client_config.path
            )
            print_stderr(
                'Please make sure cloning completes before running '
                '`eden clone`.'
            )
            print_stderr('If null revision is valid, add --allow-empty-repo .')
            return 1

        # Attempt to start the daemon if it is not already running.
        health_info = config.check_health()
        if not health_info.is_healthy():
            # Sometimes this returns a non-zero exit code if it does not finish
            # startup within the default timeout.
            exit_code = start_daemon(
                config, args.daemon_binary, args.edenfs_args
            )
            if exit_code != 0:
                return exit_code

        try:
            config.clone(client_config, args.path, snapshot_id)
            return 0
        except Exception as ex:
            print_stderr('error: {}', ex)
            return 1


def try_create_config_from_repo(
        repo: str,
        config: config_mod.Config
) -> config_mod.ClientConfig:
    '''Checks if repo is a path to a Git or Hg repository, and if so, creates an
    appropriate ClientConfig for that repository. Throws an Exception if repo
    does not identify a Git or Hg repository.
    '''
    path_to_repo = normalize_path_arg(repo)
    if not path_to_repo or not os.path.isdir(path_to_repo):
        ex = config.create_no_such_repository_exception(repo)
        raise ex

    # Check whether path_to_repo is an Eden mount. Note this could theoretically
    # be an Eden mount owned by a different user, so we must be sure it is
    # defined in our own config.
    client_config = config.get_client_config_for_path(path_to_repo)
    if client_config is not None:
        return client_config

    # TODO(mbolin): Check whether there is a config alias whose path matches
    # path_to_repo.

    for extension, _scm_type in config_mod.REPO_FOR_EXTENSION.items():
        if os.path.isdir(os.path.join(path_to_repo, extension)):
            break
    else:
        raise Exception(f'Could not determine repo type for: {path_to_repo}')

    return config_mod.ClientConfig(
        path=path_to_repo,
        scm_type=_scm_type,
        hooks_path=config.get_default_hooks_path(),
        bind_mounts={},
        default_revision=config_mod.DEFAULT_REVISION[_scm_type])


@subcmd('config', 'Query Eden configuration')
class ConfigCmd(Subcmd):
    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument('--get', help='Name of value to get')

    def run(self, args: argparse.Namespace) -> int:
        config = create_config(args)
        if args.get:
            try:
                print(config.get_config_value(args.get))
            except (KeyError, ValueError):
                # mirrors `git config --get invalid`; just exit with code 1
                return 1
        else:
            config.print_full_config()
        return 0


@subcmd('doctor', 'Debug and fix issues with Eden')
class DoctorCmd(Subcmd):
    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            '--dry-run', '-n', action='store_true',
            help='Do not try to fix any issues: only report them.')

    def run(self, args: argparse.Namespace) -> int:
        config = create_config(args)
        return doctor_mod.cure_what_ails_you(
            config,
            args.dry_run,
            out=sys.stdout,
            mount_table=mtab.LinuxMountTable()
        )


@subcmd(
    'mount', (
        'Remount an existing client (for instance, after it was '
        'unmounted with "unmount")'
    )
)
class MountCmd(Subcmd):
    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            'paths', nargs='+', metavar='path', help='The client mount path')

    def run(self, args: argparse.Namespace) -> int:
        config = create_config(args)
        for path in args.paths:
            try:
                exitcode = config.mount(path)
                if exitcode:
                    return exitcode
            except EdenNotRunningError as ex:
                print_stderr('error: {}', ex)
                return 1
        return 0


@subcmd('unmount', 'Unmount a specific client')
class UnmountCmd(Subcmd):
    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            '--destroy',
            action='store_true',
            help='Permanently delete all state associated with the client.')
        parser.add_argument(
            'paths', nargs='+', metavar='path',
            help='Path where client should be unmounted from')

    def run(self, args: argparse.Namespace) -> int:
        config = create_config(args)
        for path in args.paths:
            path = normalize_path_arg(path)
            try:
                config.unmount(path, delete_config=args.destroy)
            except EdenService.EdenError as ex:
                print_stderr('error: {}', ex)
                return 1
        return 0


@subcmd('checkout', 'Check out an alternative snapshot hash')
class CheckoutCmd(Subcmd):

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            '--client', '-c',
            default=None,
            help='Name of the mounted client')
        parser.add_argument(
            'snapshot',
            help='Snapshot hash to check out')

    def run(self, args: argparse.Namespace) -> int:
        config = create_config(args)
        try:
            config.checkout(infer_client_from_cwd(config, args.client),
                            args.snapshot)
        except Exception as ex:
            print_stderr('checkout of %s failed for client %s: %s' % (
                         args.snapshot,
                         args.client,
                         str(ex)))
            return 1
        return 0


@subcmd('daemon', 'Run the edenfs daemon')
class DaemonCmd(Subcmd):
    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            '--daemon-binary',
            help='Path to the binary for the Eden daemon.')
        parser.add_argument(
            '--foreground', '-F', action='store_true',
            help='Run eden in the foreground, rather than daemonizing')
        parser.add_argument(
            '--takeover', '-t', action='store_true',
            help='If an existing edenfs daemon is running, gracefully take '
            'over its mount points.')
        parser.add_argument(
            '--gdb', '-g', action='store_true', help='Run under gdb')
        parser.add_argument(
            '--gdb-arg', action='append', default=[],
            help='Extra arguments to pass to gdb')
        parser.add_argument(
            '--strace', '-s',
            metavar='FILE',
            help='Run eden under strace, and write strace output to FILE')
        parser.add_argument(
            'edenfs_args', nargs=argparse.REMAINDER,
            help='Any extra arguments after an "--" argument will be passed '
            'to the edenfs daemon.')

    def run(self, args: argparse.Namespace) -> int:
        config = create_config(args)
        return start_daemon(config,
                            args.daemon_binary,
                            args.edenfs_args,
                            takeover=args.takeover,
                            gdb=args.gdb,
                            gdb_args=args.gdb_arg,
                            strace_file=args.strace,
                            foreground=args.foreground)


RESTART_MODE_FULL = 'full'
RESTART_MODE_GRACEFUL = 'graceful'


@subcmd('restart', 'Restart the edenfs daemon')
class RestartCmd(Subcmd):
    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        mode_group = parser.add_mutually_exclusive_group()
        mode_group.add_argument(
            '--full',
            action='store_const',
            const=RESTART_MODE_FULL,
            dest='restart_type',
            help='Completely shut down edenfs before restarting it.  This '
            'will unmount and remount the edenfs mounts, requiring processes '
            'using them to re-open any files and directories they are using.'
        )
        mode_group.add_argument(
            '--graceful',
            action='store_const',
            const=RESTART_MODE_GRACEFUL,
            dest='restart_type',
            help='Perform a graceful restart.  The new edenfs daemon will '
            'take over the existing edenfs mount points with minimal '
            'disruption to clients.  Open file handles will continue to work '
            'across the restart.'
        )

        parser.add_argument(
            '--shutdown-timeout',
            type=float,
            default=30,
            help='How long to wait for the old edenfs process to exit when '
            'performing a full restart.'
        )

    def run(self, args: argparse.Namespace) -> int:
        self.args = args

        if self.args.restart_type is None:
            # Default to a full restart for now
            self.args.restart_type = RESTART_MODE_FULL

        self.config = create_config(args)
        stopping = False
        pid = None
        try:
            with self.config.get_thrift_client() as client:
                pid = client.getPid()
                if self.args.restart_type == RESTART_MODE_FULL:
                    # Ask the old edenfs daemon to shutdown
                    self.msg(
                        'Stopping the existing edenfs daemon (pid {})...', pid
                    )
                    client.shutdown()
                    stopping = True
        except EdenNotRunningError:
            pass

        if stopping:
            assert isinstance(pid, int)
            wait_for_shutdown(
                self.config, pid, timeout=self.args.shutdown_timeout
            )
            self._start()
        elif pid is None:
            self.msg('edenfs is not currently running.')
            self._start()
        else:
            self._graceful_start()
        return 0

    def msg(self, msg: str, *args: Any, **kwargs: Any) -> None:
        if args or kwargs:
            msg = msg.format(*args, **kwargs)
        print(msg)

    def _start(self) -> None:
        self.msg('Starting edenfs...')
        start_daemon(self.config)

    def _graceful_start(self) -> None:
        self.msg('Performing a graceful restart...')
        start_daemon(self.config, takeover=True)


def start_daemon(
    config: config_mod.Config,
    daemon_binary: Optional[str]=None,
    edenfs_args: Optional[List[str]]=None,
    takeover: bool=False,
    gdb: bool=False,
    gdb_args: Optional[List[str]]=None,
    strace_file: Optional[str]=None,
    foreground: bool=False,
    timeout: Optional[float]=None,
) -> int:
    # If this is the first time running the daemon, the ~/.eden directory
    # structure needs to be set up.
    # TODO(mbolin): Check whether the user is running as sudo/root. In general,
    # we want to avoid creating ~/.eden as root.
    _ensure_dot_eden_folder_exists(config)

    if daemon_binary is None:
        valid_daemon_binary = _find_default_daemon_binary()
        if valid_daemon_binary is None:
            print_stderr('error: unable to find edenfs executable')
            return 1
    else:
        valid_daemon_binary = daemon_binary

    # If the user put an "--" argument before the edenfs args, argparse passes
    # that through to us.  Strip it out.
    if edenfs_args and edenfs_args[0] == '--':
        edenfs_args = edenfs_args[1:]

    try:
        health_info = config.spawn(valid_daemon_binary, edenfs_args,
                                   takeover=takeover, gdb=gdb,
                                   gdb_args=gdb_args, strace_file=strace_file,
                                   foreground=foreground,
                                   timeout=timeout)
    except config_mod.EdenStartError as ex:
        print_stderr('error: {}', ex)
        return 1
    print('Started edenfs (pid {}). Logs available at {}'.format(
        health_info.pid, config.get_log_path()))
    return 0


@subcmd('rage', 'Prints diagnostic information about eden')
class RageCmd(Subcmd):
    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            '--stdout',
            action='store_true',
            help='Print the rage report to stdout: ignore reporter.')

    def run(self, args: argparse.Namespace) -> int:
        rage_processor = None
        config = create_config(args)
        try:
            rage_processor = config.get_config_value('rage.reporter')
        except KeyError:
            pass

        proc: Optional[subprocess.Popen] = None
        if rage_processor and not args.stdout:
            proc = subprocess.Popen(
                ['sh', '-c', rage_processor], stdin=subprocess.PIPE
            )
            sink = proc.stdin
        else:
            proc = None
            sink = sys.stdout.buffer

        rage_mod.print_diagnostic_info(config, sink)
        if proc:
            sink.close()
            proc.wait()
        return 0


def _find_default_daemon_binary() -> Optional[str]:
    # By default, we look for the daemon executable alongside this file.
    script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    candidate = os.path.join(script_dir, 'edenfs')
    permissions = os.R_OK | os.X_OK
    if os.access(candidate, permissions):
        return candidate

    # This is where the binary will be found relative to this file when it is
    # run out of buck-out in debug mode.
    candidate = os.path.normpath(
        os.path.join(script_dir, '../fs/service/edenfs')
    )
    if os.access(candidate, permissions):
        return candidate
    else:
        return None


def _ensure_dot_eden_folder_exists(config: config_mod.Config) -> None:
    '''Creates the ~/.eden folder as specified by --config-dir/$EDEN_CONFIG_DIR.
    If the ~/.eden folder already exists, it will be left alone.
    '''
    config.get_or_create_path_to_rocks_db()


SHUTDOWN_EXIT_CODE_NORMAL = 0
SHUTDOWN_EXIT_CODE_REQUESTED_SHUTDOWN = 0
SHUTDOWN_EXIT_CODE_NOT_RUNNING_ERROR = 2
SHUTDOWN_EXIT_CODE_TERMINATED_VIA_SIGKILL = 3
SHUTDOWN_EXIT_CODE_ERROR = 4


class ShutdownError(Exception):
    pass


@subcmd('shutdown', 'Shutdown the daemon')
class ShutdownCmd(Subcmd):
    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            '-t', '--timeout', type=float, default=15.0,
            help='Wait up to TIMEOUT seconds for the daemon to exit '
            '(default=%(default)s). If it does not exit within the timeout, '
            'then SIGKILL will be sent. If timeout is 0, then do not wait at '
            'all and do not send SIGKILL.')

    def run(self, args: argparse.Namespace) -> int:
        config = create_config(args)
        try:
            with config.get_thrift_client() as client:
                pid = client.getPid()
                # Ask the client to shutdown
                client.shutdown()
        except EdenNotRunningError:
            print_stderr('error: edenfs is not running')
            return SHUTDOWN_EXIT_CODE_NOT_RUNNING_ERROR

        if args.timeout == 0:
            print_stderr('Sent async shutdown request to edenfs.')
            return SHUTDOWN_EXIT_CODE_REQUESTED_SHUTDOWN

        try:
            if wait_for_shutdown(config, pid, timeout=args.timeout):
                print_stderr('edenfs exited cleanly.')
                return SHUTDOWN_EXIT_CODE_NORMAL
            else:
                print_stderr('Terminated edenfs with SIGKILL.')
                return SHUTDOWN_EXIT_CODE_TERMINATED_VIA_SIGKILL
        except ShutdownError as ex:
            print_stderr('Error: ' + str(ex))
            return SHUTDOWN_EXIT_CODE_ERROR


def wait_for_shutdown(
    config: config_mod.Config,
    pid: int,
    timeout: float,
    kill_timeout: float = 5.0
) -> bool:
    '''
    Wait for a process to exit.

    If it does not exit within `timeout` seconds kill it with SIGKILL.
    Returns True if the process exited on its own or False if it only exited
    after SIGKILL.

    Throws a ShutdownError if we failed to kill the process with SIGKILL
    (either because we failed to send the signal, or if the process still did
    not exit within kill_timeout seconds after sending SIGKILL).
    '''
    # Wait until the process exits on its own.
    def process_exited() -> Optional[bool]:
        try:
            os.kill(pid, 0)
        except OSError as ex:
            if ex.errno == errno.ESRCH:
                # The process has exited
                return True
            # EPERM is okay (and means the process is still running),
            # anything else is unexpected
            elif ex.errno != errno.EPERM:
                raise
        # Still running
        return None

    try:
        util.poll_until(process_exited, timeout=timeout)
        return True
    except util.TimeoutError:
        pass

    # client.shutdown() failed to terminate the process within the specified
    # timeout.  Take a more aggressive approach by sending SIGKILL.
    print_stderr(
        'error: sent shutdown request, but edenfs did not exit '
        'within {} seconds. Attempting SIGKILL.', timeout
    )
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError as ex:
        if ex.errno == errno.ESRCH:
            # The process exited before the SIGKILL was received.
            # Treat this just like a normal shutdown since it exited on its
            # own.
            return True
        elif ex.errno == errno.EPERM:
            raise ShutdownError(
                'Received EPERM when sending SIGKILL. '
                'Perhaps edenfs failed to drop root privileges properly?'
            )
        else:
            raise

    try:
        util.poll_until(process_exited, timeout=kill_timeout)
        return False
    except util.TimeoutError:
        raise ShutdownError(
            'edenfs process {} did not terminate within {} seconds of '
            'sending SIGKILL.'.format(pid, kill_timeout)
        )


def create_parser() -> argparse.ArgumentParser:
    '''Returns a parser'''
    parser = argparse.ArgumentParser(description='Manage Eden clients.')
    parser.add_argument(
        '--config-dir',
        help='Path to directory where client data is stored.')
    parser.add_argument(
        '--etc-eden-dir',
        help='Path to directory that holds the system configuration files.')
    parser.add_argument(
        '--home-dir',
        help='Path to directory where .edenrc config file is stored.')
    parser.add_argument('--version', '-v', action='store_true',
                        help='Print eden version.')

    subcmd_mod.add_subcommands(parser, subcmd.commands + [
        debug_mod.DebugCmd,
        subcmd_mod.HelpCmd,
        stats_mod.StatsCmd,
    ])

    return parser


def main() -> int:
    parser = create_parser()
    args = parser.parse_args()
    if args.version:
        return do_version(args)
    if getattr(args, 'func', None) is None:
        parser.print_help()
        return 0
    return_code: int = args.func(args)
    return return_code


def normalize_path_arg(
    path_arg: str, may_need_tilde_expansion: bool = False
) -> str:
    '''Normalizes a path by using os.path.realpath().

    Note that this function is expected to be used with command-line arguments.
    If the argument comes from a config file or GUI where tilde expansion is not
    done by the shell, then may_need_tilde_expansion=True should be specified.
    '''
    if path_arg:
        if may_need_tilde_expansion:
            path_arg = os.path.expanduser(path_arg)

        # Use the canonical version of the path.
        path_arg = os.path.realpath(path_arg)
    return path_arg


if __name__ == '__main__':
    retcode = main()
    sys.exit(retcode)
