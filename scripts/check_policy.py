import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


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
        if name in policy['forbiddenFiles'] or path.suffix in policy['forbiddenExtensions']:
            errors.append(name + ': proprietary vendor source must not be distributed')
            continue
        if path.suffix in ('.js', '.cjs', '.css'):
            javascript.append(name)
        if path.suffix not in ('.py', '.sh', '.js', '.cjs', '.css', '.html', '.md', '.json', '.yml', '.yaml') and name not in policy['shellFiles']:
            continue
        source = path.read_text()
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
    print('Source policy passed; English comments and documentation are allowed and encouraged.')


if __name__ == '__main__':
    main()
