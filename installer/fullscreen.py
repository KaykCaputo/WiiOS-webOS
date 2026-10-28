import curses
import json
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
from textwrap import wrap

from installer.errors import InstallerError
from installer.version import INSTALLER_VERSION


MENU = (
    ('1', 'Install WiiOS', 'Install the launcher as an application without changing LG Home.'),
    ('2', 'Inspect compatibility', 'Read firmware, Home implementation and supported capabilities.'),
    ('3', 'Replace LG Home', 'Attempt Home replacement only on an explicitly qualified firmware.'),
    ('4', 'Update WiiOS', 'Update the installed application without changing LG Home.'),
    ('5', 'Restore LG Home', 'Recover an existing Home transaction using its recorded identifier.'),
    ('6', 'Uninstall WiiOS', 'Remove the application after verifying that no Home hook is active.'),
    ('7', 'Export diagnostics', 'Save a device and compatibility report to your computer.'),
    ('8', 'Launch WiiOS', 'Request that LG webOS start the installed WiiOS application.'),
    ('9', 'Reconcile installation', 'Verify and close a previously interrupted installation.'),
    ('a', 'Verify Home trial', 'Confirm firmware health and the physical Home key during a temporary trial.'),
    ('b', 'Enable guarded boot', 'Requires another independently restored trial and explicit approval.'),
    ('c', 'Finalize guarded boot', 'After restarting the TV, confirm the Home key and finish the boot trial.'),
    ('0', 'Exit', 'Close the installer without making additional changes.'),
)


def formatted(value):
    return json.dumps(value, indent=2, ensure_ascii=True, sort_keys=False)


def summary(value):
    if not isinstance(value, dict):
        return [str(value)]
    if 'deviceProfile' in value:
        profile = value['deviceProfile']
        identity = profile.get('identity', {})
        home = profile.get('home', {})
        decision = value.get('compatibility', {})
        return [
            'Device: ' + str(identity.get('model') or 'Unknown'),
            'Firmware: ' + str(identity.get('firmware') or 'Unknown'),
            'SDK: ' + str(identity.get('sdkVersion') or 'Unknown'),
            'Home: ' + str(home.get('appId') or 'Not confirmed'),
            'Home implementation: ' + str(home.get('implementation') or 'Unknown'),
            'App eligibility: ' + str(decision.get('appStatus') or 'Unknown'),
            'Home status: ' + str(decision.get('homeStatus') or 'Not qualified'),
            'WiiOS Home ownership: ' + str(home.get('ownershipStatus') or 'Unknown'),
            'Home assessment: ' + ', '.join(decision.get('reasonCodes') or ['No blocking reason']),
            'Ownership check: ' + str(home.get('ownershipFailureCheck') or 'No ownership check failure'),
            'Foreign Home mounts: ' + str(len(home.get('foreignMounts', []))),
            'Conflicting startup hooks: ' + str(len(home.get('conflictingHooks', []))),
            'Pending transactions: ' + str(len(value.get('pendingTransactions', []))),
        ]
    pairs = [('ok', 'Outcome'), ('state', 'State'), ('version', 'Version'),
             ('transactionId', 'Transaction'), ('reasonCode', 'Reason'),
             ('changed', 'Changed'), ('uiConfirmed', 'UI confirmed'),
             ('homeConfirmed', 'Home confirmed'), ('report', 'Saved to')]
    lines = [label + ': ' + str(value[key]) for key, label in pairs if key in value]
    return lines or ['Operation completed. Press D for the complete response.']


class TerminalModel:
    def __init__(self):
        self.page = 'menu'
        self.selected = 0
        self.scroll = 0
        self.title = 'Installation'
        self.description = ''
        self.lines = []
        self.details = None
        self.return_page = 'menu'
        self.input_value = ''
        self.input_cursor = 0
        self.input_label = ''
        self.input_hint = ''
        self.input_limit = 4096
        self.input_token = ''
        self.notice = 'Select an operation with the arrow keys and press Enter.'
        self.spinner = 0
        self.plan = None
        self.finished = False
        self.result = None
        self.options = []

    def menu(self, notice=None):
        self.page = 'menu'
        self.scroll = 0
        self.details = None
        self.options = []
        if notice is not None:
            self.notice = notice

    def input(self, title, label, token, hint='', limit=4096):
        self.page = 'input'
        self.title = title
        self.input_label = label
        self.input_hint = hint
        self.input_token = token
        self.input_value = ''
        self.input_cursor = 0
        self.input_limit = limit

    def list_options(self, title, options):
        self.page = 'options'
        self.title = title
        self.options = list(options)
        self.selected = 0

    def show(self, page, title, lines, details=None):
        self.page = page
        self.title = title
        self.lines = list(lines)
        self.details = details
        self.scroll = 0

    def show_details(self):
        if self.details is not None:
            self.return_page = self.page
            self.page = 'details'
            self.scroll = 0

    def begin(self, label):
        self.page = 'working'
        self.title = label
        self.spinner = 0

    def key(self, value):
        if self.page == 'working':
            return None
        if value == curses.KEY_RESIZE:
            return None
        if self.page == 'menu':
            if value in (curses.KEY_UP, 'k', 'K'):
                self.selected = (self.selected - 1) % len(MENU)
            elif value in (curses.KEY_DOWN, 'j', 'J'):
                self.selected = (self.selected + 1) % len(MENU)
            elif value in ('\n', '\r', curses.KEY_ENTER):
                return 'menu', MENU[self.selected][0]
            elif value == '\x1b':
                return 'menu', '0'
            elif value in ('?', curses.KEY_F1):
                return 'help', None
            elif isinstance(value, str) and value in [entry[0] for entry in MENU]:
                return 'menu', value
            return None
        if self.page == 'options':
            if value in (curses.KEY_UP, 'k', 'K'):
                self.selected = (self.selected - 1) % len(self.options)
            elif value in (curses.KEY_DOWN, 'j', 'J'):
                self.selected = (self.selected + 1) % len(self.options)
            elif value in ('\n', '\r', curses.KEY_ENTER):
                return 'option', self.options[self.selected][0]
            elif value == '\x1b':
                return 'back', None
            return None
        if self.page == 'input':
            if value in ('\n', '\r', curses.KEY_ENTER):
                return 'submit', (self.input_token, self.input_value.strip())
            if value == '\x1b':
                return 'back', None
            if value in ('\b', '\x7f', curses.KEY_BACKSPACE):
                if self.input_cursor:
                    self.input_value = (self.input_value[:self.input_cursor - 1] +
                                        self.input_value[self.input_cursor:])
                    self.input_cursor -= 1
            elif value == curses.KEY_DC:
                self.input_value = self.input_value[:self.input_cursor] + self.input_value[self.input_cursor + 1:]
            elif value == curses.KEY_LEFT:
                self.input_cursor = max(0, self.input_cursor - 1)
            elif value == curses.KEY_RIGHT:
                self.input_cursor = min(len(self.input_value), self.input_cursor + 1)
            elif value in (curses.KEY_HOME, '\x01'):
                self.input_cursor = 0
            elif value in (curses.KEY_END, '\x05'):
                self.input_cursor = len(self.input_value)
            elif value == '\x15':
                self.input_value = ''
                self.input_cursor = 0
            elif value == '\x17':
                start = self.input_cursor
                while start > 0 and self.input_value[start - 1].isspace():
                    start -= 1
                while start > 0 and not self.input_value[start - 1].isspace():
                    start -= 1
                self.input_value = self.input_value[:start] + self.input_value[self.input_cursor:]
                self.input_cursor = start
            elif isinstance(value, str) and value.isprintable() and len(self.input_value) < self.input_limit:
                self.input_value = self.input_value[:self.input_cursor] + value + self.input_value[self.input_cursor:]
                self.input_cursor += len(value)
            return None
        if self.page == 'plan':
            if value in ('a', 'A', '\n', '\r', curses.KEY_ENTER):
                return 'approve', None
            if value in ('d', 'D'):
                self.show_details()
            elif value == '\x1b':
                return 'back', None
            elif value in ('?', curses.KEY_F1):
                return 'help', None
            return None
        if self.page == 'details':
            if value in (curses.KEY_DOWN, 'j', 'J'):
                self.scroll += 1
            elif value in (curses.KEY_UP, 'k', 'K'):
                self.scroll = max(0, self.scroll - 1)
            elif value == curses.KEY_NPAGE:
                self.scroll += 12
            elif value == curses.KEY_PPAGE:
                self.scroll = max(0, self.scroll - 12)
            elif value in (curses.KEY_HOME, 'g'):
                self.scroll = 0
            elif value in ('\x1b', 'q', 'Q', '\n', '\r', curses.KEY_ENTER):
                self.page = self.return_page
            return None
        if self.page in ('result', 'error', 'help'):
            if value in ('d', 'D') and self.details is not None:
                self.show_details()
            elif value in ('\x1b', '\n', '\r', curses.KEY_ENTER, 'm', 'M'):
                return 'back', None
        return None


def put(screen, y, x, text, width, attr=0):
    height, columns = screen.getmaxyx()
    if y < 0 or y >= height or x < 0 or x >= columns or width <= 0:
        return
    try:
        screen.addnstr(y, x, str(text).replace('\n', ' '), min(columns - x - 1, width), attr)
    except curses.error:
        return


def horizontal(screen, y):
    height, width = screen.getmaxyx()
    if 0 <= y < height and width > 1:
        put(screen, y, 0, '─' * (width - 1), width - 1)


def wrapped(text, width):
    return wrap(str(text), max(1, width), replace_whitespace=False, drop_whitespace=False, break_long_words=True) or ['']


def render(screen, model, endpoint='', artifact=''):
    height, width = screen.getmaxyx()
    screen.erase()
    if height < 14 or width < 52:
        put(screen, 0, 0, 'WiiOS Installer - resize terminal to 52x14 or larger', max(0, width - 1))
        screen.refresh()
        return
    try:
        curses.curs_set(1 if model.page == 'input' else 0)
    except curses.error:
        pass
    put(screen, 0, 2, f'WiiOS Installer {INSTALLER_VERSION}  /  LG webOS', width - 4, curses.A_BOLD)
    put(screen, 1, 2, endpoint, width - 4)
    horizontal(screen, 2)
    content_top, content_bottom = 4, height - 4
    available_height = max(1, content_bottom - content_top)
    if model.page == 'menu':
        put(screen, 3, 2, 'OPERATIONS', width - 4, curses.A_BOLD)
        sidebar = min(42, max(27, width // 2)) if width >= 86 else width - 4
        shown = min(len(MENU), available_height)
        start = min(max(0, model.selected - shown + 1), len(MENU) - shown)
        for pos, (number, label, _) in enumerate(MENU[start:start + shown]):
            index = start + pos
            attr = curses.A_REVERSE | curses.A_BOLD if index == model.selected else 0
            put(screen, content_top + pos, 2, (' ' + number + '  ' + label).ljust(sidebar - 2), sidebar - 2, attr)
        if sidebar < width - 18:
            x = sidebar + 2
            item = MENU[model.selected]
            put(screen, 4, x, 'SELECTED ACTION', width - x - 2, curses.A_BOLD)
            row = 6
            for line in wrapped(item[2], width - x - 4):
                put(screen, row, x, line, width - x - 3)
                row += 1
            row += 2
            put(screen, row, x, 'PACKAGE', width - x - 2, curses.A_BOLD)
            for line in wrapped(artifact or 'No IPK selected', width - x - 4):
                row += 1
                if row < content_bottom:
                    put(screen, row, x, line, width - x - 3)
    elif model.page == 'options':
        put(screen, 3, 2, model.title, width - 4, curses.A_BOLD)
        for index, (key, label) in enumerate(model.options[:available_height]):
            attr = curses.A_REVERSE | curses.A_BOLD if index == model.selected else 0
            put(screen, content_top + index, 3, (' ' + label).ljust(width - 8), width - 8, attr)
    elif model.page == 'input':
        put(screen, 3, 2, model.title, width - 4, curses.A_BOLD)
        for index, line in enumerate(wrapped(model.input_hint, width - 8)[:4]):
            put(screen, 5 + index, 4, line, width - 8)
        input_row = min(height - 7, 11)
        put(screen, input_row - 1, 4, model.input_label, width - 8, curses.A_BOLD)
        field_width = width - 10
        visible_width = max(1, field_width - 2)
        start = max(0, model.input_cursor - visible_width + 1)
        visible = model.input_value[start:start + visible_width]
        put(screen, input_row, 4, '[' + visible.ljust(visible_width) + ']', field_width, curses.A_REVERSE)
        try:
            screen.move(input_row, min(width - 4, 5 + model.input_cursor - start))
        except curses.error:
            pass
    elif model.page == 'working':
        put(screen, 3, 2, 'WORKING', width - 4, curses.A_BOLD)
        put(screen, 6, 4, model.title + '  ' + '|/-\\'[model.spinner % 4], width - 8)
        put(screen, 8, 4, 'Please keep this terminal open until the operation completes.', width - 8)
        put(screen, 9, 4, 'The installer will report success or failure on a separate screen.', width - 8)
    else:
        page_title = 'PLAN REVIEW' if model.page == 'plan' else 'DETAILS' if model.page == 'details' else model.title
        put(screen, 3, 2, page_title, width - 4, curses.A_BOLD)
        if model.page == 'details':
            raw_lines = formatted(model.details).splitlines() if model.details is not None else []
            lines = []
            for line in raw_lines:
                lines.extend(wrapped(line, width - 8))
            max_scroll = max(0, len(lines) - available_height)
            model.scroll = min(model.scroll, max_scroll)
            for index, line in enumerate(lines[model.scroll:model.scroll + available_height]):
                put(screen, content_top + index, 4, line, width - 8)
            put(screen, height - 4, 2, f'Lines {model.scroll + 1}-{min(model.scroll + available_height, len(lines))} of {len(lines)}', width - 4)
        else:
            row = content_top
            for line in model.lines:
                if row >= content_bottom:
                    break
                for segment in wrapped(line, width - 8):
                    if row >= content_bottom:
                        break
                    put(screen, row, 4, segment, width - 8)
                    row += 1
                row += 1
    horizontal(screen, height - 3)
    hints = {
        'menu': 'Up/Down  Select: Enter  Direct: 0-9/A-C  Help: F1  Exit: Esc',
        'options': 'Up/Down  Select: Enter  Back: Esc',
        'input': 'Type or paste  Edit: arrows/Home/End  Clear: Ctrl+U  Confirm: Enter  Cancel: Esc',
        'plan': 'Review the summary  Continue: A/Enter  Raw plan: D  Cancel: Esc',
        'details': 'Scroll: arrows/PageUp/PageDown  Back: Esc/Enter',
        'working': 'Operation running  |  Close only after a result is reported',
        'result': 'Continue: Enter/Esc  Full response: D',
        'error': 'Return to menu: Enter/Esc  Details: D',
        'help': 'Return to menu: Enter/Esc',
    }
    put(screen, height - 2, 2, hints.get(model.page, ''), width - 4)
    if model.page == 'menu':
        put(screen, height - 1, 2, model.notice, width - 4)
    screen.refresh()


class TerminalController:
    def __init__(self, engine):
        self.engine = engine
        self.model = TerminalModel()
        self.events = Queue()
        self.trusted = False
        self.pending_action = None
        self.plan = None
        self.report = None
        self.options = []
        self.home_transaction = None
        self.home_rehearsal = None
        self.completed = False
        self.output = {'ok': True, 'state': 'CLOSED'}

    def start(self):
        self.perform('trust-check', 'Checking SSH host trust', self.engine.transport.fingerprint)

    def perform(self, token, label, operation):
        self.model.begin(label)
        def worker():
            try:
                result = operation()
                self.events.put((token, True, result))
            except (Exception, KeyboardInterrupt) as error:
                self.events.put((token, False, error))
        Thread(target=worker, daemon=True).start()

    def poll(self):
        while True:
            try:
                token, ok, value = self.events.get_nowait()
            except Empty:
                break
            self.completed_operation(token, ok, value)
        self.model.spinner += 1

    def failure(self, error):
        if isinstance(error, InstallerError):
            self.model.show('error', 'Operation unavailable', [error.code, str(error)])
        else:
            self.model.show('error', 'Unexpected failure', [type(error).__name__, str(error) or 'Unknown error'])

    def completed_operation(self, token, ok, value):
        if not ok:
            if token == 'trust-check' and isinstance(value, InstallerError) and value.code == 'HOST_KEY_UNTRUSTED':
                self.model.input('SSH host verification', 'Verified SHA256 fingerprint', 'trust',
                                 'The SSH host is not in the trust store. Verify the fingerprint on an independent trusted channel. Never guess it.', 128)
                return
            self.failure(value)
            return
        if token in ('trust-check', 'trust'):
            self.trusted = True
            self.model.menu('SSH host identity verified. Select an operation.')
        elif token == 'artifact':
            self.request_plan()
        elif token == 'plan':
            self.plan = value
            operations = value.get('operations', [])
            lines = [
                'Target: ' + self.engine.transport.connection.endpoint,
                'Mode: ' + str(value.get('mode')),
                'Action: ' + str(value.get('action')),
                'Package: ' + str(value.get('version')),
                'Home strategy: ' + str(value.get('adapter') or 'None; LG Home unchanged'),
                'Changes: ' + (', '.join(str(item.get('action')) for item in operations) or 'None'),
                'Approval ID: ' + str(value.get('approvalDigest', ''))[:16],
                '',
                'Press A to approve this plan or Esc to return without changes.',
            ]
            self.model.show('plan', 'Installation plan', lines, value)
        elif token in ('apply', 'home-trial', 'home-verify', 'home-persist', 'home-finalize'):
            self.model.show('result', 'Home operation result' if token != 'apply' else 'Installation result', summary(value), value)
        elif token == 'diagnose':
            self.report = value
            self.model.show('result', 'Compatibility report', summary(value), value)
        elif token == 'export':
            self.model.show('result', 'Diagnostics exported', summary(value), value)
        elif token == 'restore' and value.get('state') == 'STOCK_FILES_RESTORED':
            self.home_transaction = value['transactionId']
            self.model.input('Verify original LG Home', 'Type LG HOME VERIFIED', 'stock-home-confirm',
                             'Open LG Home using the physical remote and verify navigation and applications first.', 32)
        elif token in ('restore', 'stock-home-confirm'):
            self.model.show('result', 'LG Home restoration', summary(value), value)
        elif token == 'uninstall':
            self.model.show('result', 'Uninstallation result', summary(value), value)
        elif token == 'launch':
            self.model.show('result', 'Launch result', summary(value), value)
        elif token == 'reconcile-list':
            entries = value
            if entries:
                self.options = entries
                self.model.list_options('Interrupted installations', [
                    (entry['transactionId'], entry['transactionId'][:18] + '  ' + entry['state']) for entry in entries])
            else:
                self.model.show('result', 'No pending installations',
                                ['All recorded installation transactions are complete.'], {'pendingTransactions': []})
        elif token == 'reconcile':
            self.model.show('result', 'Reconciliation result', summary(value), value)

    def request_plan(self):
        action = self.pending_action
        def create_plan():
            proposal = self.engine.plan(mode='home' if action == '3' else 'app',
                                        action='update' if action == '4' else 'install')
            if proposal['mode'] == 'home-replacement' and self.engine.journal.path(proposal['transactionId']).exists():
                import secrets
                from installer.plan import fresh_trial
                proposal = fresh_trial(proposal, secrets.token_hex(16))
            return proposal
        self.perform('plan', 'Inspecting firmware and preparing an installation plan', create_plan)

    def choose(self, number):
        if number == '0':
            self.completed = True
            return
        if not self.trusted:
            self.model.input('SSH host verification', 'Verified SHA256 fingerprint', 'trust',
                             'Confirm this TV SSH fingerprint using a trusted channel before connecting.', 128)
            return
        if number in ('1', '3', '4'):
            self.pending_action = number
            if self.engine.artifact is None:
                self.model.input('Select WiiOS package', 'IPK file path', 'artifact',
                                 'Enter the path to a WiiOS release IPK on this computer.')
            else:
                self.request_plan()
        elif number == '2':
            self.perform('diagnose', 'Reading compatibility information', self.engine.diagnose)
        elif number == '5':
            self.model.input('Restore LG Home', 'Transaction ID', 'restore-id',
                             'Enter an existing Home transaction ID. The original Home is not modified until confirmation.', 128)
        elif number == '6':
            self.model.input('Uninstall WiiOS', 'Type UNINSTALL', 'uninstall',
                             'The installer checks for an active Home takeover before removing the app.', 32)
        elif number == '7':
            self.model.input('Export diagnostics', 'Report file path', 'report',
                             'Enter a path on this computer. The file is written with restricted permissions.')
        elif number == '8':
            self.perform('launch', 'Launching WiiOS on the TV', self.engine.application.launch)
        elif number == '9':
            self.perform('reconcile-list', 'Checking interrupted installations', self.engine.reconcile)
        elif number == 'a':
            self.model.input('Verify Home trial', 'Temporary transaction ID', 'home-verify-id',
                             'Only confirm the Home key if you actually pressed it on the TV.', 128)
        elif number == 'b':
            self.model.input('Enable guarded Home boot', 'Live trial transaction ID', 'home-persist-id',
                             'Requires a separate successful restoration rehearsal of the exact firmware.', 128)
        elif number == 'c':
            self.model.input('Finalize guarded Home boot', 'Pending transaction ID', 'home-finalize-id',
                             'Use only after the TV has restarted and the physical Home key worked.', 128)

    def submit(self, token, value):
        if token == 'trust':
            if not value:
                self.model.menu('SSH host is not trusted. No TV command was executed.')
                return
            from installer.transport import trust_host
            self.perform('trust', 'Saving verified SSH host identity',
                         lambda: trust_host(self.engine.transport.connection, value))
        elif token == 'artifact':
            if not value:
                self.model.menu('Package selection cancelled.')
                return
            from installer.application import Artifact
            def load():
                self.engine.artifact = Artifact(Path(value).expanduser())
                return self.engine.artifact.version
            self.perform('artifact', 'Validating WiiOS package', load)
        elif token == 'approve':
            expected = 'REPLACE HOME' if self.plan['mode'] == 'home-replacement' else 'UPDATE' if self.plan['action'] == 'update' else 'INSTALL'
            if value != expected:
                self.model.show('result', 'Installation cancelled',
                                ['Approval phrase did not match. No installation changes were made.'])
                return
            if self.plan['mode'] == 'home-replacement':
                self.model.input('Temporary Home trial', 'Prepared Home bundle directory', 'home-bundle',
                                 'A tested independent recovery route and exact approved firmware are mandatory.', 512)
            else:
                self.perform('apply', 'Applying the approved plan',
                             lambda: self.engine.apply(self.plan, self.plan['approvalDigest']))
        elif token == 'home-bundle':
            if not value:
                self.model.menu('Home trial cancelled.')
                return
            self.home_bundle = str(Path(value).expanduser())
            from compatibility.resolver import load_verified
            profile = next((entry for entry in load_verified() if entry['profileId'] == self.plan['profileId']), None)
            if not profile:
                self.model.show('error', 'Unqualified Home profile', ['No exact approved profile was found.'])
                return
            self.home_qualification = profile['homeReplacement']
            if self.plan['adapter'] == 'native-home-standin':
                self.model.input('Native Home lifecycle', 'Approved WAM payload JSON file', 'home-wam',
                                 'The JSON payload must match the exact qualified firmware fingerprint.', 512)
            else:
                self.perform('home-trial', 'Running a time-limited Home trial',
                             lambda: self.engine.home_trial(self.plan, self.plan['approvalDigest'],
                                 self.home_bundle, self.home_qualification.get('samProtocol')))
        elif token == 'home-wam':
            if not value:
                self.model.menu('Native Home trial cancelled.')
                return
            def launch_native():
                payload = json.loads(Path(value).expanduser().read_text())
                return self.engine.home_trial(self.plan, self.plan['approvalDigest'], self.home_bundle,
                    native_contract=self.home_qualification.get('nativeContract'), launch_payload=payload)
            self.perform('home-trial', 'Running a time-limited native Home trial', launch_native)
        elif token in ('home-verify-id', 'home-persist-id', 'home-finalize-id'):
            if not value:
                self.model.menu('Home operation cancelled.')
                return
            self.home_transaction = value
            if token == 'home-persist-id':
                self.model.input('Restoration rehearsal', 'Separate restored transaction ID', 'home-rehearsal',
                                 'This transaction must prove the original LG Home was restored.', 128)
            else:
                self.model.input('Physical Home confirmation', 'Type HOME KEY VERIFIED',
                                 'home-verify-confirm' if token == 'home-verify-id' else 'home-finalize-confirm',
                                 'Confirm this only after pressing Home on the physical remote.', 32)
        elif token == 'home-rehearsal':
            if not value:
                self.model.menu('Guarded persistence cancelled.')
                return
            self.home_rehearsal = value
            self.model.input('Enable persistent Home', 'Type ENABLE BOOT', 'home-persist-confirm',
                             'The boot hook will be guarded. Reboot verification is still mandatory.', 32)
        elif token == 'home-verify-confirm':
            if value != 'HOME KEY VERIFIED':
                self.model.menu('Physical Home confirmation was not provided.')
                return
            self.perform('home-verify', 'Verifying temporary Home operation',
                         lambda: self.engine.home_trial_state(self.home_transaction, 'verify', True))
        elif token == 'home-persist-confirm':
            if value != 'ENABLE BOOT':
                self.model.menu('Persistent Home installation cancelled.')
                return
            def persist():
                approved = self.engine.journal.read(self.home_transaction)['plan']['approvalDigest']
                return self.engine.home_trial_state(self.home_transaction, 'persist', True,
                                                    self.home_rehearsal, approved)
            self.perform('home-persist', 'Enabling guarded Home startup', persist)
        elif token == 'home-finalize-confirm':
            if value != 'HOME KEY VERIFIED':
                self.model.menu('Boot verification was not confirmed.')
                return
            self.perform('home-finalize', 'Verifying Home after reboot',
                         lambda: self.engine.home_trial_state(self.home_transaction, 'finalize', True))
        elif token == 'stock-home-confirm':
            if value != 'LG HOME VERIFIED':
                self.model.menu('Files are restored. Operational LG Home verification is still pending.')
                return
            self.perform('stock-home-confirm', 'Verifying original LG Home',
                         lambda: self.engine.home_trial_state(self.home_transaction, 'confirm-stock', True))
        elif token == 'restore-id':
            if not value:
                self.model.menu('Home restoration cancelled.')
            else:
                self.pending_action = value
                self.model.input('Confirm LG Home restoration', 'Type RESTORE', 'restore-confirm',
                                 'Restore transaction ' + value + '. Check the target TV before proceeding.', 16)
        elif token == 'restore-confirm':
            if value != 'RESTORE':
                self.model.menu('Home restoration cancelled.')
            else:
                self.perform('restore', 'Restoring LG Home', lambda: self.engine.restore(self.pending_action))
        elif token == 'uninstall':
            if value != 'UNINSTALL':
                self.model.menu('Uninstallation cancelled.')
            else:
                self.perform('uninstall', 'Uninstalling WiiOS', self.engine.uninstall)
        elif token == 'report':
            if not value:
                self.model.menu('Diagnostic export cancelled.')
                return
            from installer.cli import write_report
            def export():
                report = self.engine.diagnose()
                write_report(value, report)
                return {'ok': True, 'report': str(Path(value).expanduser())}
            self.perform('export', 'Collecting and exporting diagnostics', export)

    def dispatch_key(self, key):
        event = self.model.key(key)
        if event is None:
            return
        token, value = event
        if token == 'menu':
            self.choose(value)
        elif token == 'submit':
            self.submit(*value)
        elif token == 'approve':
            expected = 'REPLACE HOME' if self.plan['mode'] == 'home-replacement' else 'UPDATE' if self.plan['action'] == 'update' else 'INSTALL'
            self.model.input('Confirm installation', 'Type ' + expected, 'approve',
                             'Review the plan before confirming. Only the approved operation will run.', 32)
        elif token == 'option':
            self.perform('reconcile', 'Reconciling installation',
                         lambda: self.engine.reconcile_transaction(value))
        elif token == 'help':
            self.model.show('help', 'Keyboard help', [
                'Up / Down: navigate menus or long reports.',
                'Enter: select an operation or submit a field.',
                'Escape: cancel the current screen without applying changes.',
                'Left / Right / Home / End: edit a text field.',
                'Backspace / Delete: remove characters.',
                'Ctrl+U: clear an input field.',
                'D: inspect the full operation result or exact approved plan.',
                'A: continue from plan review to confirmation.',
                'A running operation cannot be cancelled safely by closing the interface.',
            ])
        elif token == 'back':
            self.model.menu()


def session(screen, engine):
    controller = TerminalController(engine)
    screen.keypad(True)
    screen.timeout(100)
    screen.clear()
    screen.clearok(True)
    controller.start()
    while not controller.completed:
        controller.poll()
        artifact = str(engine.artifact.path) if engine.artifact else ''
        render(screen, controller.model, engine.transport.connection.endpoint, artifact)
        try:
            key = screen.get_wch()
        except curses.error:
            continue
        if key == curses.KEY_RESIZE:
            screen.clear()
            screen.clearok(True)
            continue
        if key == curses.KEY_F1 and controller.model.page != 'input':
            controller.dispatch_key('?')
        else:
            controller.dispatch_key(key)
    return controller.output


def run_fullscreen(engine, wrapper=curses.wrapper):
    return wrapper(lambda screen: session(screen, engine))
