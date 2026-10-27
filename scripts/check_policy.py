import ast
import hashlib
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import re
import subprocess
import tokenize

from bashlex import state, tokenizer

ROOT = Path(__file__).resolve().parents[1]


class ShellTokens(tokenizer.tokenizer):
    def __init__(self, source):
        super().__init__(source, state.parserstate())
        self.comments = []

    def _discard_until(self, character):
        start = self._shell_input_line_index - 1
        self.comments.append(start)
        super()._discard_until(character)


class HTMLComments(HTMLParser):
    def __init__(self):
        super().__init__()
        self.comments = []

    def handle_comment(self, data):
        self.comments.append(self.getpos())


def comments(path, source):
    suffix = Path(path).suffix
    if suffix == '.py':
        found = [token.start[0] for token in tokenize.generate_tokens(io.StringIO(source).readline)
                 if token.type == tokenize.COMMENT and not (token.start == (1, 0) and token.string.startswith('#!'))]
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and ast.get_docstring(node):
                found.append(node.body[0].lineno)
        return found
    if suffix == '.sh' or source.startswith('#!/bin/sh'):
        shell = ShellTokens(source)
        list(shell)
        return [position for position in shell.comments if not (position == 0 and source.startswith('#!'))]
    if suffix == '.html':
        parser = HTMLComments()
        parser.feed(source)
        return parser.comments
    return []


def english_findings(source):
    return re.findall(r'\b(?:configurações|aplicativos|instalação|não|televisão|pressione|atualização|memória|desativar)\b', source, re.I)


def main():
    policy = json.loads((ROOT / 'source-policy.json').read_text())
    paths = sorted(set(subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=ROOT).decode().split('\0')) - {''})
    errors, javascript = [], []
    for name in paths:
        path = ROOT / name
        if not path.is_file() or any(name.startswith(prefix) for prefix in policy['excludedDirectories']):
            continue
        exception = policy['frozenVendorFiles'].get(name)
        if exception:
            if hashlib.sha256(path.read_bytes()).hexdigest() != exception['sha256']:
                errors.append(name + ': vendor-derived source changed; review provenance and policy')
            continue
        if path.suffix in ('.js', '.cjs', '.css'):
            javascript.append(name)
        if path.suffix not in ('.py', '.sh', '.js', '.cjs', '.css', '.html', '.md', '.json', '.yml', '.yaml') and name not in policy['shellFiles']:
            continue
        source = path.read_text()
        try:
            if comments(name, source):
                errors.append(name + ': source comments or docstrings are not allowed')
        except Exception as error:
            errors.append(name + ': policy parser failed: ' + str(error))
        if name not in policy['languageTestFiles'] and english_findings(source):
            errors.append(name + ': non-English text requires review')
    result = subprocess.run(['node', 'scripts/check_source.cjs'], cwd=ROOT,
                            input=json.dumps(javascript), text=True, capture_output=True)
    if result.returncode and not result.stdout:
        errors.append('JavaScript policy checker failed')
    else:
        errors.extend(json.loads(result.stdout))
    if errors:
        raise SystemExit('\n'.join(errors))
    print('Source policy passed; language detection is heuristic and requires human review.')


if __name__ == '__main__':
    main()
