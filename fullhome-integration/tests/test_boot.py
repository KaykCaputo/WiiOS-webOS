import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BootLaunch(unittest.TestCase):
    def run_worker(self, mode):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            luna = '''#!/bin/sh
uri="$6"
printf '%s\n' "$uri" >> "$BOOT_TEST_DIR/calls"
case "$uri" in
  */getBootStatus)
    if [ "$BOOT_TEST_MODE" = not-ready ]; then
      printf '%s\n' '{"returnValue":true,"signals":{"boot-done":false}}'
    else
      printf '%s\n' '{"returnValue":true,"signals":{"boot-done":true}}'
    fi
    ;;
  */getPowerState)
    if [ "$BOOT_TEST_MODE" = off ]; then
      printf '%s\n' '{"returnValue":true,"state":"Suspend"}'
    else
      printf '%s\n' '{"returnValue":true,"state":"Active"}'
    fi
    ;;
  */getForegroundAppInfo)
    if [ "$BOOT_TEST_MODE" = never-foreground ]; then
      printf '%s\n' '{"returnValue":true,"appId":"com.webos.app.hdmi1"}'
    else
      count=$(grep -c '/getForegroundAppInfo' "$BOOT_TEST_DIR/calls")
      if [ "$count" -eq 1 ]; then
        printf '%s\n' '{"returnValue":true,"appId":"com.webos.app.fullhome"}'
      else
        printf '%s\n' '{"returnValue":true,"appId":"com.wiios.launcher"}'
      fi
    fi
    ;;
  *) printf '%s\n' '{"returnValue":true}' ;;
esac
'''
            (base/'luna-send').write_text(luna); (base/'luna-send').chmod(0o755)
            (base/'sleep').write_text('#!/bin/sh\nexit 0\n'); (base/'sleep').chmod(0o755)
            env = dict(os.environ, PATH=tmp+':'+os.environ['PATH'], BOOT_TEST_DIR=tmp, BOOT_TEST_MODE=mode)
            result = subprocess.run(['sh',str(ROOT/'bundle'/'launch-on-boot.sh')],env=env,capture_output=True,text=True)
            return result,(base/'calls').read_text().splitlines()

    def test_waits_for_boot_and_verifies_foreground(self):
        result,calls=self.run_worker('ready')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(calls[0].endswith('getBootStatus'))
        self.assertEqual(sum(c.endswith('/launch') for c in calls),1)
        self.assertEqual(sum(c.endswith('getForegroundAppInfo') for c in calls),2)
        self.assertIn('WIIOS_FOREGROUND_CONFIRMED',result.stdout)

    def test_no_launch_before_boot_complete(self):
        result,calls=self.run_worker('not-ready')
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(any(c.endswith('/launch') for c in calls))

    def test_accepted_launch_is_not_foreground_proof(self):
        result,calls=self.run_worker('never-foreground')
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(sum(c.endswith('/launch') for c in calls),3)
        self.assertNotIn('WIIOS_FOREGROUND_CONFIRMED',result.stdout)

    def test_does_not_launch_when_tv_is_off(self):
        result,calls=self.run_worker('off')
        self.assertEqual(result.returncode,0)
        self.assertFalse(any(c.endswith('/launch') for c in calls))
