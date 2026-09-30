import hashlib
import fcntl
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/battery.sh'
FIXTURES = ROOT / 'tests/fixtures/battery'
PRIVATE_SENTINELS = ('SECRET-SERIAL-123', 'private-host.example', 'private-user',
                     'ghp_not_a_real_token')


class BatteryDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='battery diagnostic ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / 'home'
        self.state = self.root / 'state'
        self.tmp = self.root / 'tmp'
        self.commands = self.root / 'commands'
        for directory in (self.home, self.tmp, self.commands):
            directory.mkdir(parents=True)
        self.calls = self.root / 'calls.txt'
        self.live = self.root / 'pmset-batt.txt'
        self.live.write_text(
            "Now drawing from 'Battery Power'\n"
            " -InternalBattery-0 (id=SECRET-SERIAL-123)\t050%; discharging; "
            "2:00 remaining present: true\n"
        )
        self.log_fixture = FIXTURES / 'pmset-log-batt.txt'
        self._write_commands()

    def _write_executable(self, name, body):
        path = self.commands / name
        path.write_text('#!/bin/bash\nset -eu\n' + body)
        path.chmod(0o755)
        return path

    def _write_commands(self):
        self.pmset = self._write_executable(
            'pmset',
            'printf "pmset:%s\\n" "$*" >>"$BATTERY_CALLS"\n'
            'case "$*" in\n'
            '  "-g batt") cat "$BATTERY_LIVE_FIXTURE" ;;\n'
            '  "-g log") cat "$BATTERY_LOG_FIXTURE" ;;\n'
            '  *) exit 64 ;;\n'
            'esac\n',
        )
        self.profiler = self._write_executable(
            'system_profiler',
            'printf "system_profiler:%s\\n" "$*" >>"$BATTERY_CALLS"\n'
            "cat <<'EOF'\n"
            'Power:\n'
            '    Battery Information:\n'
            '        Model Information:\n'
            '            Serial Number: SECRET-SERIAL-123\n'
            '            Manufacturer: private-user\n'
            '        Health Information:\n'
            '            Cycle Count: 0012\n'
            '            Condition: Normal\n'
            '            Maximum Capacity: 087%\n'
            '    Hostname: private-host.example\n'
            '    Credential: ghp_not_a_real_token\n'
            '    UPS Information:\n'
            '        Cycle Count: 9999\n'
            '        Condition: Replace Now\n'
            '        Maximum Capacity: 001%\n'
            'EOF\n',
        )
        self.ioreg = self._write_executable(
            'ioreg',
            'printf "ioreg:%s\\n" "$*" >>"$BATTERY_CALLS"\n'
            "cat <<'EOF'\n"
            '+-o AppleSmartBattery  <class AppleSmartBattery>\n'
            '  | |   "BatteryInstalled" = Yes\n'
            '  | |   "CycleCount" = 9999\n'
            '  | |   "AppleRawMaxCapacity" = 05000\n'
            '  | |   "DesignCapacity" = 06000\n'
            '  | |   "Voltage" = 12000\n'
            '  | |   "Amperage" = 5\n'
            '  | |   "InstantAmperage" = 18446744073709550206\n'
            '  | |   "BatterySerialNumber" = "SECRET-SERIAL-123"\n'
            '  | |   "Owner" = "private-user"\n'
            '  | |   "Token" = "ghp_not_a_real_token"\n'
            'EOF\n',
        )
        self.date = self._write_executable(
            'date',
            'case "$*" in\n'
            '  "-u +%s %Y-%m-%dT%H:%M:%SZ") printf "1788267600 2026-09-01T13:00:00Z\\n" ;;\n'
            '  "-u +%Y%m%dT%H%M%SZ") printf "20260901T130000Z\\n" ;;\n'
            '  *) exit 64 ;;\n'
            'esac\n',
        )
        for forbidden in ('brew', 'python3', 'jq'):
            self._write_executable(forbidden, 'exit 99\n')

    def environment(self, home=None, state=None):
        selected_home = home or self.home
        selected_state = state or self.state
        return {
            **os.environ,
            'HOME': str(selected_home),
            'XDG_STATE_HOME': str(selected_state),
            'TMPDIR': str(self.tmp),
            'PATH': f'{self.commands}:/usr/bin:/bin:/usr/sbin:/sbin',
            'ONE_BITE_BATTERY_PMSET_BIN': str(self.pmset),
            'ONE_BITE_BATTERY_SYSTEM_PROFILER_BIN': str(self.profiler),
            'ONE_BITE_BATTERY_IOREG_BIN': str(self.ioreg),
            'ONE_BITE_BATTERY_DATE_BIN': str(self.date),
            'BATTERY_CALLS': str(self.calls),
            'BATTERY_LIVE_FIXTURE': str(self.live),
            'BATTERY_LOG_FIXTURE': str(self.log_fixture),
        }

    def run_tool(self, *arguments, check=True, env=None, entry=SCRIPT):
        result = subprocess.run(
            ['/bin/bash', '--noprofile', '--norc', str(entry), *arguments],
            env=env or self.environment(), text=True, capture_output=True, timeout=30,
        )
        if check and result.returncode != 0:
            self.fail(f'{arguments} returned {result.returncode}:\n{result.stdout}\n{result.stderr}')
        return result

    def assert_private_sentinels_absent(self, text):
        for sentinel in PRIVATE_SENTINELS:
            self.assertNotIn(sentinel, text)

    def test_json_uses_allowlisted_numeric_fields_and_reconstructs_intervals(self):
        result = self.run_tool('--json')
        report = json.loads(result.stdout)
        self.assertEqual(report['schema_version'], 1)
        self.assertEqual(report['status'], 'ok')
        self.assertTrue(report['complete'])
        self.assertEqual(
            report['battery'],
            {
                'present': True,
                'charge_percent': 50,
                'power_source': 'battery',
                'state': 'discharging',
                'cycle_count': 12,
                'maximum_capacity_percent': 87,
                'maximum_capacity_mah': 5000,
                'design_capacity_mah': 6000,
                'health': 'normal',
                'voltage_mv': 12000,
                'current_ma': -1410,
            },
        )
        history = report['history']
        self.assertEqual(history['duration_basis'], 'wall_clock')
        self.assertTrue(history['may_include_sleep'])
        self.assertFalse(history['is_lifetime'])
        self.assertEqual(history['retained_event_count'], 5)
        self.assertEqual(history['interval_count'], 5)
        intervals = history['intervals']
        self.assertIn('Sleep Entering Sleep', self.log_fixture.read_text())
        self.assertEqual(
            [(item['source'], item['start_percent'], item['end_percent'],
              item['duration_seconds'], item['complete']) for item in intervals],
            [
                ('battery', 9, 8, 1800, True),
                ('ac', 8, 40, 1800, True),
                ('battery', 40, 40, 0, True),
                ('ac', 40, 100, 3600, True),
                ('battery', 100, 50, 10800, False),
            ],
        )
        self.assertEqual(report['warning_codes'], [])
        self.assert_private_sentinels_absent(result.stdout + result.stderr)

        cache_root = self.state / '1bite/battery'
        cache = cache_root / 'history-v1.tsv'
        self.assertEqual(stat.S_IMODE(cache_root.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(cache.stat().st_mode), 0o600)
        cached = cache.read_text()
        self.assertTrue(cached.startswith('one-bite-battery-history\t1\n'))
        self.assert_private_sentinels_absent(cached)
        self.assertFalse(list(cache_root.glob('.history-v1.tsv.*')))
        before = cache.read_bytes()
        self.run_tool('--json')
        self.assertEqual(cache.read_bytes(), before)

        calls = self.calls.read_text()
        self.assertIn('pmset:-g batt', calls)
        self.assertIn('pmset:-g log', calls)
        self.assertIn('system_profiler:-detailLevel mini -timeout 15 SPPowerDataType', calls)
        self.assertIn('ioreg:-r -c AppleSmartBattery', calls)
        expected_calls = {
            'pmset:-g batt',
            'pmset:-g log',
            'system_profiler:-detailLevel mini -timeout 15 SPPowerDataType',
            'ioreg:-r -c AppleSmartBattery',
        }
        self.assertEqual(set(calls.splitlines()), expected_calls)
        for call in expected_calls:
            self.assertEqual(calls.splitlines().count(call), 2)

    def test_versioned_json_contract_and_bash_32_boundary_are_explicit(self):
        report = json.loads(self.run_tool('--json', '--no-cache').stdout)
        schema = json.loads((ROOT / 'docs/battery.schema.json').read_text())
        self.assertEqual(set(report), set(schema['required']))
        self.assertEqual(set(report['battery']), set(schema['$defs']['battery']['required']))
        self.assertEqual(set(report['history']), set(schema['$defs']['history']['required']))
        self.assertEqual(
            set(report['history']['intervals'][0]),
            set(schema['$defs']['interval']['required']),
        )
        self.assertIsInstance(report['schema_version'], int)
        self.assertIsInstance(report['complete'], bool)
        self.assertIn(report['status'], ('ok', 'partial', 'no_battery', 'unavailable'))
        self.assertIsInstance(report['battery']['present'], bool)
        self.assertIn(report['battery']['power_source'], ('ac', 'battery', 'unknown', None))
        self.assertIn(report['battery']['state'],
                      ('charging', 'charged', 'discharging', 'not_charging', 'unknown', None))
        self.assertTrue(0 <= report['battery']['charge_percent'] <= 100)
        self.assertTrue(all(isinstance(value, int) for value in (
            report['history']['retained_event_count'], report['history']['interval_count'])))
        for interval in report['history']['intervals']:
            self.assertIn(interval['source'], ('ac', 'battery'))
            self.assertTrue(0 <= interval['start_percent'] <= 100)
            self.assertTrue(0 <= interval['end_percent'] <= 100)
            self.assertTrue(-100 <= interval['delta_percent'] <= 100)
            self.assertGreaterEqual(interval['duration_seconds'], 0)
            self.assertIsInstance(interval['complete'], bool)
        source = SCRIPT.read_text()
        version = (ROOT / 'VERSION').read_text().strip()
        self.assertIn(f'BATTERY_TOOL_VERSION={version}\n', source)
        self.assertTrue(source.startswith('#!/bin/bash\n'))
        for unsupported in ('declare -A', 'mapfile ', 'readarray ', '${value,,}'):
            self.assertNotIn(unsupported, source)

    def test_dashboard_json_tsv_shell_and_field_interfaces_are_consistent(self):
        dashboard = self.run_tool('--no-cache').stdout
        self.assertIn('50% (battery, discharging)', dashboard)
        self.assertIn('equivalent full cycles', dashboard)
        self.assertIn('not the number of times power was connected', dashboard)
        self.assertIn('wall-clock time and may include sleep', dashboard)
        self.assertIn('not lifetime charge/discharge totals', dashboard)

        report = json.loads(self.run_tool('--json', '--no-cache').stdout)
        tsv = self.run_tool('--tsv', '--no-cache').stdout
        self.assertTrue(tsv.startswith('schema_version\tsection\tindex\tkey\tvalue\tunit\n'))
        self.assertIn('1\tbattery\t-\tcharge_percent\t50\tpercent\n', tsv)
        self.assertIn('1\tinterval\t2\tduration_seconds\t0\tseconds\n', tsv)

        shell_output = self.run_tool('--shell', '--no-cache').stdout
        shell_file = self.root / 'battery-output.sh'
        shell_file.write_text(shell_output)
        sourced = subprocess.run(
            ['/bin/bash', '--noprofile', '--norc', '-c',
             'source "$1"; printf "%s|%s|%s\\n" "$ONE_BITE_BATTERY_CHARGE_PERCENT" '
             '"$ONE_BITE_BATTERY_CYCLE_COUNT" "$ONE_BITE_BATTERY_INTERVAL_2_DURATION_SECONDS"',
             'bash', str(shell_file)],
            text=True, capture_output=True, check=True,
        )
        self.assertEqual(sourced.stdout, '50|12|0\n')

        self.live.write_text("Now drawing from 'AC Power'\n")
        empty_shell_output = self.run_tool('--shell', '--no-cache').stdout
        shell_file.write_text(shell_output + empty_shell_output)
        cleared = subprocess.run(
            ['/bin/bash', '--noprofile', '--norc', '-c',
             'source "$1"; printf "%s|%s\\n" "$ONE_BITE_BATTERY_INTERVAL_COUNT" '
             '"${ONE_BITE_BATTERY_INTERVAL_0_SOURCE-unset}"', 'bash', str(shell_file)],
            text=True, capture_output=True, check=True,
        )
        self.assertEqual(cleared.stdout, '0|unset\n')
        self.live.write_text(
            "Now drawing from 'Battery Power'\n"
            " -InternalBattery-0\t050%; discharging; 2:00 remaining present: true\n"
        )
        field = self.run_tool('--field', 'battery.charge_percent', '--no-cache')
        self.assertEqual(field.stdout, f"{report['battery']['charge_percent']}\n")
        unknown = self.run_tool('--field', 'battery.serial_number', '--no-cache', check=False)
        self.assertEqual(unknown.returncode, 2)
        self.assertNotIn('SECRET', unknown.stdout + unknown.stderr)

        for output in (dashboard, tsv, shell_output):
            self.assert_private_sentinels_absent(output)

    def test_startup_summary_is_single_line_stateless_and_handles_absent_data(self):
        summary = self.run_tool('--summary')
        self.assertEqual(
            summary.stdout,
            'Battery: charge 50%; battery power, discharging; maximum capacity 87%; '
            'cycle count 12 equivalent full cycles.\n',
        )
        self.assertEqual(summary.stderr, '')
        self.assertEqual(summary.stdout.count('\n'), 1)
        self.assertEqual(
            self.calls.read_text().splitlines(),
            [
                'pmset:-g batt',
                'system_profiler:-detailLevel mini -timeout 15 SPPowerDataType',
                'ioreg:-r -c AppleSmartBattery',
            ],
        )
        self.assertNotIn('pmset:-g log', self.calls.read_text())
        self.assertFalse(self.state.exists())
        self.assert_private_sentinels_absent(summary.stdout + summary.stderr)

        self.calls.unlink()
        self.live.write_text('')
        unavailable = self.run_tool('--summary', check=False)
        self.assertEqual(unavailable.returncode, 1)
        self.assertEqual(unavailable.stdout, 'Battery: unavailable; setup will continue.\n')
        self.assertEqual(self.calls.read_text().splitlines(), ['pmset:-g batt'])
        self.assertFalse(self.state.exists())

        self.calls.unlink()
        self.live.write_text("Now drawing from 'AC Power'\n")
        no_battery = self.run_tool('--summary')
        self.assertEqual(no_battery.stdout, 'Battery: not present.\n')
        self.assertEqual(self.calls.read_text().splitlines(), ['pmset:-g batt'])
        self.assertFalse(self.state.exists())

    def test_uppercase_log_spacing_and_leading_zero_percent_are_numeric(self):
        self.log_fixture = FIXTURES / 'pmset-log-batt-uppercase.txt'
        self.live.write_text(
            "Now drawing from 'AC Power'\n"
            " -InternalBattery-0\t010%; charging; 0:20 remaining present: true\n"
        )
        result = self.run_tool('--json', '--no-cache')
        report = json.loads(result.stdout)
        intervals = report['history']['intervals']
        self.assertEqual(
            [(item['source'], item['start_percent'], item['end_percent'], item['duration_seconds'])
             for item in intervals[:2]],
            [('ac', 5, 5, 900), ('battery', 5, 4, 2700)],
        )
        self.assertIsInstance(report['battery']['charge_percent'], int)
        self.assertEqual(report['battery']['charge_percent'], 10)

    def test_unparseable_history_is_partial_without_exposing_raw_lines(self):
        malformed = self.root / 'malformed-history.txt'
        malformed.write_text(
            'private-host.example SECRET-SERIAL-123 Using BATT with no date or charge\n'
        )
        self.log_fixture = malformed
        report = json.loads(self.run_tool('--json', '--no-cache').stdout)
        self.assertEqual(report['status'], 'partial')
        self.assertFalse(report['complete'])
        self.assertIn('history_parse_failed', report['warning_codes'])
        self.assertEqual(report['history']['retained_event_count'], 1)
        self.assertEqual(report['history']['interval_count'], 1)
        self.assert_private_sentinels_absent(json.dumps(report))

        malformed.write_text(
            '2026-09-01 08:00:00 +0000 Wake Using Batt (Charge: 50%)\n'
            'new-format private-host.example Using AC (Charge: 51%) SECRET-SERIAL-123\n'
        )
        report = json.loads(self.run_tool('--json', '--no-cache').stdout)
        self.assertEqual(report['status'], 'partial')
        self.assertIn('history_parse_partial', report['warning_codes'])
        self.assert_private_sentinels_absent(json.dumps(report))

    def test_unavailable_live_probe_and_unsafe_state_still_have_predictable_results(self):
        self.live.write_text('')
        unavailable = self.run_tool('--json', check=False)
        self.assertEqual(unavailable.returncode, 1)
        report = json.loads(unavailable.stdout)
        self.assertEqual(report['status'], 'unavailable')
        self.assertFalse(report['complete'])
        self.assertIsNone(report['battery']['present'])
        self.assertIn('pmset_batt_incomplete', report['warning_codes'])
        self.assertFalse(self.state.exists())

        dashboard = self.run_tool('--no-cache', check=False)
        self.assertEqual(dashboard.returncode, 1)
        self.assertIn('Battery data: unavailable', dashboard.stdout)
        self.assertNotIn('Battery: not present', dashboard.stdout)
        tsv = self.run_tool('--tsv', '--no-cache', check=False)
        self.assertIn('1\tbattery\t-\tpresent\tnull\tboolean\n', tsv.stdout)

        self.live.write_text("Now drawing from 'Battery Power'\n")
        incomplete = self.run_tool('--json', '--no-cache', check=False)
        self.assertEqual(incomplete.returncode, 1)
        self.assertEqual(json.loads(incomplete.stdout)['battery']['present'], None)

        self.live.write_text(
            "Now drawing from 'Battery Power'\n"
            " -InternalBattery-0\t50%; discharging; 2:00 remaining present: true\n"
        )
        self.state.mkdir()
        blocker = self.state / '1bite'
        blocker.write_text('preserve this file\n')
        result = self.run_tool('--json')
        report = json.loads(result.stdout)
        self.assertEqual(report['status'], 'ok')
        self.assertIn('state_path_unsafe', report['warning_codes'])
        self.assertEqual(blocker.read_text(), 'preserve this file\n')

    def test_unsigned_current_wrap_modulus_is_rejected_instead_of_becoming_zero(self):
        source = self.ioreg.read_text().replace(
            '18446744073709550206', '18446744073709551616'
        )
        self.ioreg.write_text(source)
        self.ioreg.chmod(0o755)
        report = json.loads(self.run_tool('--json', '--no-cache').stdout)
        self.assertIsNone(report['battery']['current_ma'])
        self.assertEqual(report['status'], 'partial')

    def test_unknown_field_fails_before_probes_or_cache_writes(self):
        result = self.run_tool('--field', 'battery.serial_number', check=False)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, '')
        self.assertFalse(self.calls.exists())
        self.assertFalse(self.state.exists())

    def test_no_battery_is_success_and_does_not_probe_or_cache_history(self):
        self.live.write_text("Now drawing from 'AC Power'\n")
        result = self.run_tool('--json')
        report = json.loads(result.stdout)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(report['status'], 'no_battery')
        self.assertTrue(report['complete'])
        self.assertFalse(report['battery']['present'])
        self.assertEqual(report['history']['intervals'], [])
        self.assertFalse(self.state.exists())
        calls = self.calls.read_text().splitlines()
        self.assertEqual(calls, ['pmset:-g batt'])
        missing = self.run_tool('--field', 'battery.cycle_count', '--no-cache', check=False)
        self.assertEqual(missing.returncode, 3)
        self.assertEqual(missing.stdout, '')

    def test_corrupt_unknown_and_symlink_caches_have_safe_boundaries(self):
        cache_root = self.state / '1bite/battery'
        cache_root.mkdir(parents=True)
        cache = cache_root / 'history-v1.tsv'

        cache.write_text(
            'one-bite-battery-history\t1\n'
            'event\t1788249600\tSECRET-SERIAL-123"\tbattery\t50\t0\n'
        )
        result = self.run_tool('--json')
        self.assertIn('cache_corrupt', json.loads(result.stdout)['warning_codes'])
        self.assertNotIn('SECRET-SERIAL-123', cache.read_text())

        cache.write_text(
            'one-bite-battery-history\t1\n'
            'event\t1788249600\t2026-09-01T08:00:00Z\tbattery\t050\t0\n'
        )
        result = self.run_tool('--json')
        report = json.loads(result.stdout)
        self.assertIn('cache_corrupt', report['warning_codes'])
        self.assertNotIn('\t050\t', cache.read_text())

        unknown = b'user-owned unknown cache\nSECRET-SERIAL-123\n'
        cache.write_bytes(unknown)
        result = self.run_tool('--json')
        self.assertIn('cache_unknown', json.loads(result.stdout)['warning_codes'])
        self.assertEqual(cache.read_bytes(), unknown)
        self.assert_private_sentinels_absent(result.stdout + result.stderr)

        cache.unlink()
        target = self.root / 'cache-target'
        target.write_text('do not replace\n')
        cache.symlink_to(target)
        result = self.run_tool('--json')
        self.assertIn('cache_symlink', json.loads(result.stdout)['warning_codes'])
        self.assertEqual(target.read_text(), 'do not replace\n')
        self.assertTrue(cache.is_symlink())

    def test_invalid_optional_metrics_and_collection_time_fail_predictably(self):
        source = self.profiler.read_text().replace('Maximum Capacity: 087%',
                                                   'Maximum Capacity: 101%')
        self.profiler.write_text(source)
        self.profiler.chmod(0o755)
        report = json.loads(self.run_tool('--json', '--no-cache').stdout)
        self.assertEqual(report['status'], 'partial')
        self.assertIsNone(report['battery']['maximum_capacity_percent'])
        self.assertIn('metrics_incomplete', report['warning_codes'])

        self.date.write_text(
            '#!/bin/bash\nset -eu\n'
            'printf "1788267600 2026-09-01T13:00:01Z\\n"\n'
        )
        self.date.chmod(0o755)
        failed = self.run_tool('--json', '--no-cache', check=False)
        self.assertEqual(failed.returncode, 1)
        self.assertEqual(failed.stdout, '')
        self.assertIn('inconsistent timestamp', failed.stderr)

    def test_main_dispatch_bypasses_install_session_and_lock(self):
        result = self.run_tool('--battery', '--json', '--no-cache', entry=ROOT / '1bite')
        self.assertEqual(json.loads(result.stdout)['battery']['charge_percent'], 50)
        self.assertFalse(list(self.state.rglob('session.lock')))
        self.assertFalse(list(self.state.rglob('environment.json')))
        self.assertFalse(list(self.state.rglob('result.json')))

        installed = self.run_tool('--install-battery', entry=ROOT / '1bite')
        self.assertIn('Installed One Bite battery tool', installed.stdout)
        self.assertTrue((self.home / '.local/bin/1bite-battery').is_file())
        self.assertFalse(list(self.state.rglob('session.lock')))
        self.assertFalse(list(self.state.rglob('result.json')))

    def test_explicit_tool_install_skips_current_and_updates_only_owned_bytes(self):
        result = self.run_tool('--install-tool')
        target = self.home / '.local/bin/1bite-battery'
        receipt = self.state / '1bite/battery/tool-receipt-v1.tsv'
        self.assertIn('Installed One Bite battery tool', result.stdout)
        self.assertEqual(target.read_bytes(), SCRIPT.read_bytes())
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE(receipt.stat().st_mode), 0o600)
        original_mtime = target.stat().st_mtime_ns
        result = self.run_tool('--install-tool')
        self.assertIn('already current', result.stdout)
        self.assertEqual(target.stat().st_mtime_ns, original_mtime)

        current_digest = hashlib.sha256(target.read_bytes()).hexdigest()
        current_version = (ROOT / 'VERSION').read_text().strip()
        receipt.unlink()
        pending = self.state / '1bite/battery/tool-pending-v1.tsv'
        pending.write_text(
            f'one-bite-battery-tool-pending\t1\nversion\t{current_version}\n'
            f'sha256\t{current_digest}\n'
        )
        pending.chmod(0o600)
        result = self.run_tool('--install-tool')
        self.assertIn('Recovered ownership', result.stdout)
        self.assertTrue(receipt.is_file())
        self.assertFalse(pending.exists())

        target.write_bytes(target.read_bytes() + b'\n# older managed release\n')
        target.chmod(0o755)
        old_bytes = target.read_bytes()
        old_digest = hashlib.sha256(old_bytes).hexdigest()
        receipt.write_text(
            f'one-bite-battery-tool\t1\nversion\t0.0.6\nsha256\t{old_digest}\n'
        )
        receipt.chmod(0o600)
        result = self.run_tool('--install-tool')
        self.assertIn('Run with --update', result.stdout)
        self.assertEqual(target.read_bytes(), old_bytes)
        result = self.run_tool('--install-tool', '--update')
        self.assertIn('Installed One Bite battery tool', result.stdout)
        self.assertEqual(target.read_bytes(), SCRIPT.read_bytes())
        backups = list((self.state / '1bite/battery').glob('1bite-battery.backup-*'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), old_bytes)
        self.assertEqual(stat.S_IMODE(backups[0].stat().st_mode), 0o600)

    def test_explicit_tool_install_preserves_unknown_modified_and_symlink_targets(self):
        other_home = self.root / 'unknown-home'
        other_state = self.root / 'unknown-state'
        target = other_home / '.local/bin/1bite-battery'
        target.parent.mkdir(parents=True)
        target.write_bytes(SCRIPT.read_bytes())
        target.chmod(0o755)
        env = self.environment(other_home, other_state)
        result = self.run_tool('--install-tool', '--update', check=False, env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(target.read_bytes(), SCRIPT.read_bytes())

        target.write_text('#!/bin/bash\necho user tool\n')
        target.chmod(0o755)
        result = self.run_tool('--install-tool', '--update', check=False, env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(target.read_text(), '#!/bin/bash\necho user tool\n')

        target.unlink()
        link_target = self.root / 'user-tool'
        link_target.write_text('user bytes\n')
        target.symlink_to(link_target)
        result = self.run_tool('--install-tool', '--update', check=False, env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(target.is_symlink())
        self.assertEqual(link_target.read_text(), 'user bytes\n')

    def test_tool_install_preserves_unknown_receipt_and_repairs_damage_only_on_update(self):
        receipt_root = self.state / '1bite/battery'
        receipt_root.mkdir(parents=True)
        receipt = receipt_root / 'tool-receipt-v1.tsv'
        receipt.write_text('USER-OWNED\nSECRET-SERIAL-123\n')
        result = self.run_tool('--install-tool', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(receipt.read_text(), 'USER-OWNED\nSECRET-SERIAL-123\n')
        self.assertFalse((self.home / '.local/bin/1bite-battery').exists())

        receipt.unlink()
        self.run_tool('--install-tool')
        target = self.home / '.local/bin/1bite-battery'
        target.chmod(0o644)
        result = self.run_tool('--install-tool', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('damaged', result.stderr)
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o644)
        self.run_tool('--install-tool', '--update')
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o755)

        receipt.chmod(0o644)
        refused = self.run_tool('--install-tool', '--update', check=False)
        self.assertNotEqual(refused.returncode, 0)
        self.assertEqual(stat.S_IMODE(receipt.stat().st_mode), 0o644)
        self.assertEqual(target.read_bytes(), SCRIPT.read_bytes())

    def test_tool_install_recovers_each_safe_pending_state(self):
        private_root = self.state / '1bite/battery'
        private_root.mkdir(parents=True)
        pending = private_root / 'tool-pending-v1.tsv'
        current_digest = hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
        current_version = (ROOT / 'VERSION').read_text().strip()
        pending.write_text(
            f'one-bite-battery-tool-pending\t1\nversion\t{current_version}\n'
            f'sha256\t{current_digest}\n'
        )
        pending.chmod(0o600)
        self.run_tool('--install-tool')
        target = self.home / '.local/bin/1bite-battery'
        receipt = private_root / 'tool-receipt-v1.tsv'
        self.assertEqual(target.read_bytes(), SCRIPT.read_bytes())
        self.assertFalse(pending.exists())

        old_bytes = SCRIPT.read_bytes() + b'\n# previous managed bytes\n'
        old_digest = hashlib.sha256(old_bytes).hexdigest()
        target.write_bytes(old_bytes)
        target.chmod(0o755)
        receipt.write_text(
            f'one-bite-battery-tool\t1\nversion\t0.0.6\nsha256\t{old_digest}\n'
        )
        receipt.chmod(0o600)
        pending.write_text(
            f'one-bite-battery-tool-pending\t1\nversion\t{current_version}\n'
            f'sha256\t{current_digest}\n'
        )
        pending.chmod(0o600)
        refused = self.run_tool('--install-tool', check=False)
        self.assertNotEqual(refused.returncode, 0)
        self.assertEqual(target.read_bytes(), old_bytes)
        self.assertTrue(pending.exists())
        self.run_tool('--install-tool', '--update')
        self.assertEqual(target.read_bytes(), SCRIPT.read_bytes())
        self.assertFalse(pending.exists())

    def test_tool_install_lock_rejects_a_concurrent_operation(self):
        private_root = self.state / '1bite/battery'
        private_root.mkdir(parents=True)
        lock_path = private_root / 'tool.lock'
        with lock_path.open('a') as lock_file:
            lock_path.chmod(0o600)
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.run_tool('--install-tool', check=False)
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertIn('another battery-tool install', result.stderr)
        self.assertFalse((self.home / '.local/bin/1bite-battery').exists())

        installed = self.run_tool('--install-tool')
        self.assertIn('Installed One Bite battery tool', installed.stdout)
        self.assertTrue(lock_path.is_file())
        self.assertEqual(stat.S_IMODE(lock_path.stat().st_mode), 0o600)

        fifo_home = self.root / 'fifo-home'
        fifo_state = self.root / 'fifo-state'
        fifo_root = fifo_state / '1bite/battery'
        fifo_root.mkdir(parents=True)
        fifo_lock = fifo_root / 'tool.lock'
        os.mkfifo(fifo_lock, 0o600)
        refused = self.run_tool('--install-tool', check=False,
                                env=self.environment(fifo_home, fifo_state))
        self.assertEqual(refused.returncode, 1)
        self.assertTrue(stat.S_ISFIFO(fifo_lock.lstat().st_mode))

    def test_tool_install_publish_race_and_noncanonical_home_preserve_user_paths(self):
        race_target = self.home / '.local/bin/1bite-battery'
        race_marker = self.root / 'race-marker'
        self._write_executable(
            'mv',
            'last=""\n'
            'for value in "$@"; do last=$value; done\n'
            'if [[ "$last" == "$RACE_TARGET" && ! -e "$RACE_MARKER" ]]; then\n'
            '  mkdir -p "${RACE_TARGET%/*}"\n'
            '  printf "#!/bin/bash\\necho user-race\\n" >"$RACE_TARGET"\n'
            '  chmod 755 "$RACE_TARGET"\n'
            '  : >"$RACE_MARKER"\n'
            'fi\n'
            'exec /bin/mv "$@"\n',
        )
        env = self.environment()
        env.update(RACE_TARGET=str(race_target), RACE_MARKER=str(race_marker))
        result = self.run_tool('--install-tool', check=False, env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(race_target.read_text(), '#!/bin/bash\necho user-race\n')
        self.assertFalse((self.state / '1bite/battery/tool-receipt-v1.tsv').exists())

        swap_home = self.root / 'swap-home'
        swap_state = self.root / 'swap-state'
        swap_bin = swap_home / '.local/bin'
        swapped_bin = swap_home / '.local/bin-before-swap'
        outside = self.root / 'outside-bin'
        outside.mkdir()
        outside_target = outside / '1bite-battery'
        outside_target.write_bytes(SCRIPT.read_bytes())
        outside_target.chmod(0o755)
        swap_marker = self.root / 'swap-marker'
        self._write_executable(
            'mv',
            'last=""\n'
            'for value in "$@"; do last=$value; done\n'
            'if [[ "$last" == "$SWAP_TARGET" && ! -e "$SWAP_MARKER" ]]; then\n'
            '  /bin/mv "$SWAP_BIN" "$SWAPPED_BIN"\n'
            '  ln -s "$OUTSIDE_BIN" "$SWAP_BIN"\n'
            '  : >"$SWAP_MARKER"\n'
            'fi\n'
            'exec /bin/mv "$@"\n',
        )
        swap_env = self.environment(swap_home, swap_state)
        swap_env.update(
            SWAP_TARGET=str(swap_bin / '1bite-battery'),
            SWAP_BIN=str(swap_bin),
            SWAPPED_BIN=str(swapped_bin),
            OUTSIDE_BIN=str(outside),
            SWAP_MARKER=str(swap_marker),
        )
        swapped = self.run_tool('--install-tool', check=False, env=swap_env)
        self.assertNotEqual(swapped.returncode, 0)
        self.assertEqual(outside_target.read_bytes(), SCRIPT.read_bytes())
        self.assertFalse((swap_state / '1bite/battery/tool-receipt-v1.tsv').exists())

        base = self.root / 'noncanonical'
        real_home = base / 'real-home'
        real_home.mkdir(parents=True)
        (base / 'link-home').symlink_to(real_home, target_is_directory=True)
        odd_home = base / 'missing/../link-home'
        odd_state = self.root / 'odd-state'
        refused = self.run_tool('--install-tool', check=False,
                                env=self.environment(odd_home, odd_state))
        self.assertNotEqual(refused.returncode, 0)
        self.assertFalse((base / 'missing').exists())
        self.assertFalse((real_home / '.local/bin/1bite-battery').exists())

    def test_pending_recovery_rejects_bin_parent_replacement_after_receipt_publish(self):
        bin_parent = self.home / '.local/bin'
        target = bin_parent / '1bite-battery'
        bin_parent.mkdir(parents=True)
        target.write_bytes(SCRIPT.read_bytes())
        target.chmod(0o755)

        private_root = self.state / '1bite/battery'
        private_root.mkdir(parents=True)
        pending = private_root / 'tool-pending-v1.tsv'
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        pending.write_text(
            'one-bite-battery-tool-pending\t1\nversion\t0.0.6\n'
            f'sha256\t{digest}\n'
        )
        pending.chmod(0o600)

        external_bin = self.root / 'external-user-bin'
        external_bin.mkdir()
        external_target = external_bin / '1bite-battery'
        external_bytes = b'#!/bin/bash\necho external-user\n'
        external_target.write_bytes(external_bytes)
        external_target.chmod(0o755)
        saved_bin = self.root / 'managed-bin-before-race'
        receipt = private_root / 'tool-receipt-v1.tsv'
        marker = self.root / 'receipt-parent-race'
        self._write_executable(
            'mv',
            'last=""\n'
            'for value in "$@"; do last=$value; done\n'
            'status=0\n'
            '/bin/mv "$@" || status=$?\n'
            'if [[ "$status" -eq 0 && "$last" == "$RACE_RECEIPT" && '
            '! -e "$RACE_MARKER" ]]; then\n'
            '  /bin/mv "$RACE_BIN_PARENT" "$RACE_SAVED_BIN"\n'
            '  /bin/ln -s "$RACE_EXTERNAL_BIN" "$RACE_BIN_PARENT"\n'
            '  : >"$RACE_MARKER"\n'
            'fi\n'
            'exit "$status"\n',
        )
        env = self.environment()
        env.update(
            RACE_RECEIPT=str(receipt),
            RACE_MARKER=str(marker),
            RACE_BIN_PARENT=str(bin_parent),
            RACE_SAVED_BIN=str(saved_bin),
            RACE_EXTERNAL_BIN=str(external_bin),
        )
        result = self.run_tool('--install-tool', check=False, env=env)

        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(pending.is_file())
        self.assertEqual(external_target.read_bytes(), external_bytes)
        self.assertNotIn('Recovered ownership', result.stdout)
        self.assertNotIn('already current', result.stdout)

    def test_receipt_publish_permission_race_keeps_pending_and_never_reports_success(self):
        target = self.home / '.local/bin/1bite-battery'
        receipt = self.state / '1bite/battery/tool-receipt-v1.tsv'
        pending = self.state / '1bite/battery/tool-pending-v1.tsv'
        marker = self.root / 'receipt-permission-race'
        self._write_executable(
            'mv',
            'last=""\n'
            'for value in "$@"; do last=$value; done\n'
            'status=0\n'
            '/bin/mv "$@" || status=$?\n'
            'if [[ "$status" -eq 0 && "$last" == "$RACE_RECEIPT" && '
            '! -e "$RACE_MARKER" ]]; then\n'
            '  chmod 0644 "$RACE_TARGET"\n'
            '  : >"$RACE_MARKER"\n'
            'fi\n'
            'exit "$status"\n',
        )
        env = self.environment()
        env.update(
            RACE_RECEIPT=str(receipt),
            RACE_MARKER=str(marker),
            RACE_TARGET=str(target),
        )
        result = self.run_tool('--install-tool', check=False, env=env)

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(target.read_bytes(), SCRIPT.read_bytes())
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o644)
        self.assertTrue(pending.is_file())
        self.assertNotIn('Installed One Bite battery tool', result.stdout)
        self.assertNotIn('Recovered ownership', result.stdout)
        self.assertNotIn('already current', result.stdout)

    def test_update_rejects_traversal_in_backup_timestamp_before_creating_a_backup(self):
        self.run_tool('--install-tool')
        target = self.home / '.local/bin/1bite-battery'
        private_root = self.state / '1bite/battery'
        receipt = private_root / 'tool-receipt-v1.tsv'
        pending = private_root / 'tool-pending-v1.tsv'

        old_bytes = SCRIPT.read_bytes() + b'\n# previous managed bytes\n'
        old_digest = hashlib.sha256(old_bytes).hexdigest()
        target.write_bytes(old_bytes)
        target.chmod(0o755)
        receipt.write_text(
            f'one-bite-battery-tool\t1\nversion\t0.0.6\nsha256\t{old_digest}\n'
        )
        receipt.chmod(0o600)
        target_before = target.read_bytes()
        receipt_before = receipt.read_bytes()
        target_mtime = target.stat().st_mtime_ns
        receipt_mtime = receipt.stat().st_mtime_ns

        traversal_parent = private_root / '.1bite-battery.backup-slot'
        traversal_parent.mkdir()
        self.date.write_text(
            '#!/bin/bash\nset -eu\n'
            'case "$*" in\n'
            '  "-u +%Y%m%dT%H%M%SZ") printf "slot/../../escape\\n" ;;\n'
            '  *) exit 64 ;;\n'
            'esac\n'
        )
        self.date.chmod(0o755)

        result = self.run_tool('--install-tool', '--update', check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(target.read_bytes(), target_before)
        self.assertEqual(receipt.read_bytes(), receipt_before)
        self.assertEqual(target.stat().st_mtime_ns, target_mtime)
        self.assertEqual(receipt.stat().st_mtime_ns, receipt_mtime)
        self.assertFalse(pending.exists())
        self.assertEqual(list(traversal_parent.iterdir()), [])
        self.assertFalse(list((self.state / '1bite').glob('escape.*')))
        self.assertFalse(list(private_root.glob('escape.*')))
        self.assertFalse([
            path for path in private_root.glob('*backup*')
            if path.is_file()
        ])
        self.assertNotIn('Installed One Bite battery tool', result.stdout)

    def test_tool_install_parent_swap_cannot_delete_or_claim_unknown_paths(self):
        current_digest = hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
        current_version = (ROOT / 'VERSION').read_text().strip()

        state_home = self.root / 'state-swap-home'
        state_root = self.root / 'state-swap-state/1bite/battery'
        moved_state = self.root / 'state-before-swap'
        outside_state = self.root / 'outside-state'
        outside_state.mkdir()
        outside_pending = outside_state / 'tool-pending-v1.tsv'
        outside_pending.write_text(
            f'one-bite-battery-tool-pending\t1\nversion\t{current_version}\n'
            f'sha256\t{current_digest}\n'
        )
        outside_pending.chmod(0o600)
        state_marker = self.root / 'state-swap-marker'
        self._write_executable(
            'mv',
            'last=""\n'
            'for value in "$@"; do last=$value; done\n'
            'case "$last" in\n'
            '  "$STATE_ROOT"/tool-pending-v1.tsv.removed.*)\n'
            '    if [[ ! -e "$STATE_MARKER" ]]; then\n'
            '      /bin/mv "$STATE_ROOT" "$MOVED_STATE"\n'
            '      ln -s "$OUTSIDE_STATE" "$STATE_ROOT"\n'
            '      : >"$STATE_MARKER"\n'
            '    fi\n'
            '    ;;\n'
            'esac\n'
            'exec /bin/mv "$@"\n',
        )
        state_env = self.environment(state_home, self.root / 'state-swap-state')
        state_env.update(
            STATE_ROOT=str(state_root), MOVED_STATE=str(moved_state),
            OUTSIDE_STATE=str(outside_state), STATE_MARKER=str(state_marker),
        )
        state_result = self.run_tool('--install-tool', check=False, env=state_env)
        self.assertNotEqual(state_result.returncode, 0)
        self.assertEqual(outside_pending.read_text(),
                         f'one-bite-battery-tool-pending\t1\nversion\t{current_version}\n'
                         f'sha256\t{current_digest}\n')
        self.assertNotIn('Installed One Bite battery tool', state_result.stdout)

        bin_home = self.root / 'late-bin-home'
        bin_state = self.root / 'late-bin-state'
        bin_dir = bin_home / '.local/bin'
        moved_bin = bin_home / '.local/bin-before-late-swap'
        outside_bin = self.root / 'late-outside-bin'
        outside_bin.mkdir()
        outside_target = outside_bin / '1bite-battery'
        outside_target.write_text('#!/bin/bash\necho outside-user-tool\n')
        outside_target.chmod(0o755)
        bin_marker = self.root / 'late-bin-marker'
        self._write_executable(
            'mv',
            'last=""\n'
            'for value in "$@"; do last=$value; done\n'
            '/bin/mv "$@"\n'
            'if [[ "$last" == "$RECEIPT" && ! -e "$BIN_MARKER" ]]; then\n'
            '  /bin/mv "$BIN_DIR" "$MOVED_BIN"\n'
            '  ln -s "$OUTSIDE_BIN" "$BIN_DIR"\n'
            '  : >"$BIN_MARKER"\n'
            'fi\n',
        )
        bin_env = self.environment(bin_home, bin_state)
        bin_env.update(
            RECEIPT=str(bin_state / '1bite/battery/tool-receipt-v1.tsv'),
            BIN_DIR=str(bin_dir), MOVED_BIN=str(moved_bin), OUTSIDE_BIN=str(outside_bin),
            BIN_MARKER=str(bin_marker),
        )
        bin_result = self.run_tool('--install-tool', check=False, env=bin_env)
        self.assertNotEqual(bin_result.returncode, 0)
        self.assertEqual(outside_target.read_text(), '#!/bin/bash\necho outside-user-tool\n')
        self.assertTrue((bin_state / '1bite/battery/tool-pending-v1.tsv').is_file())
        self.assertNotIn('Installed One Bite battery tool', bin_result.stdout)

        recovery_home = self.root / 'recovery-bin-home'
        recovery_state = self.root / 'recovery-bin-state'
        recovery_bin = recovery_home / '.local/bin'
        recovery_bin.mkdir(parents=True)
        recovery_target = recovery_bin / '1bite-battery'
        recovery_target.write_bytes(SCRIPT.read_bytes())
        recovery_target.chmod(0o755)
        recovery_root = recovery_state / '1bite/battery'
        recovery_root.mkdir(parents=True)
        recovery_root.chmod(0o700)
        recovery_pending = recovery_root / 'tool-pending-v1.tsv'
        recovery_pending.write_text(
            f'one-bite-battery-tool-pending\t1\nversion\t{current_version}\n'
            f'sha256\t{current_digest}\n'
        )
        recovery_pending.chmod(0o600)
        recovery_moved_bin = recovery_home / '.local/bin-before-recovery-swap'
        recovery_outside = self.root / 'recovery-outside-bin'
        recovery_outside.mkdir()
        recovery_outside_target = recovery_outside / '1bite-battery'
        recovery_outside_target.write_text('#!/bin/bash\necho recovery-user-tool\n')
        recovery_outside_target.chmod(0o755)
        recovery_marker = self.root / 'recovery-bin-marker'
        self._write_executable(
            'mv',
            'last=""\n'
            'for value in "$@"; do last=$value; done\n'
            '/bin/mv "$@"\n'
            'if [[ "$last" == "$RECOVERY_RECEIPT" && ! -e "$RECOVERY_MARKER" ]]; then\n'
            '  /bin/mv "$RECOVERY_BIN" "$RECOVERY_MOVED_BIN"\n'
            '  ln -s "$RECOVERY_OUTSIDE" "$RECOVERY_BIN"\n'
            '  : >"$RECOVERY_MARKER"\n'
            'fi\n',
        )
        recovery_env = self.environment(recovery_home, recovery_state)
        recovery_env.update(
            RECOVERY_RECEIPT=str(recovery_root / 'tool-receipt-v1.tsv'),
            RECOVERY_BIN=str(recovery_bin), RECOVERY_MOVED_BIN=str(recovery_moved_bin),
            RECOVERY_OUTSIDE=str(recovery_outside), RECOVERY_MARKER=str(recovery_marker),
        )
        recovered = self.run_tool('--install-tool', check=False, env=recovery_env)
        self.assertNotEqual(recovered.returncode, 0)
        self.assertEqual(recovery_outside_target.read_text(),
                         '#!/bin/bash\necho recovery-user-tool\n')
        self.assertTrue(recovery_pending.is_file())
        self.assertNotIn('Recovered ownership', recovered.stdout)
        self.assertNotIn('already current', recovered.stdout)

    def test_tool_install_receipt_write_failure_remains_recoverable(self):
        self._write_executable(
            'chmod',
            'last=""\n'
            'for value in "$@"; do last=$value; done\n'
            'case "$last" in\n'
            '  */.tool-receipt-v1.tsv.*) /bin/chmod 644 "$last"; exit 1 ;;\n'
            '  *) exec /bin/chmod "$@" ;;\n'
            'esac\n',
        )
        failed = self.run_tool('--install-tool', check=False)
        target = self.home / '.local/bin/1bite-battery'
        private_root = self.state / '1bite/battery'
        receipt = private_root / 'tool-receipt-v1.tsv'
        pending = private_root / 'tool-pending-v1.tsv'
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(target.read_bytes(), SCRIPT.read_bytes())
        self.assertTrue(pending.is_file())
        self.assertFalse(receipt.exists())

        self._write_executable('chmod', 'exec /bin/chmod "$@"\n')
        recovered = self.run_tool('--install-tool')
        self.assertIn('Recovered ownership', recovered.stdout)
        self.assertTrue(receipt.is_file())
        self.assertFalse(pending.exists())


if __name__ == '__main__':
    unittest.main()
