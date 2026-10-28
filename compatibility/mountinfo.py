from dataclasses import asdict, dataclass
import re


def unescape(value):
    return re.sub(r'\\(040|011|012|134)', lambda match: chr(int(match[1], 8)), value)


@dataclass(frozen=True)
class Mount:
    mountId: int
    parentId: int
    device: str
    root: str
    target: str
    options: str
    optional: tuple
    filesystem: str
    source: str
    superOptions: str

    def to_dict(self):
        result = asdict(self)
        result['optional'] = list(self.optional)
        return result


def parse_mountinfo(text):
    result = []
    seen = set()
    for line in text.splitlines():
        before, separator, after = line.partition(' - ')
        fields, tail = before.split(), after.split()
        if not separator or len(fields) < 6 or len(tail) != 3:
            raise ValueError('Invalid mountinfo record')
        mount = Mount(int(fields[0]), int(fields[1]), fields[2], unescape(fields[3]),
                      unescape(fields[4]), fields[5], tuple(fields[6:]),
                      tail[0], unescape(tail[1]), tail[2])
        if mount.mountId in seen or not mount.target.startswith('/'):
            raise ValueError('Ambiguous mountinfo record')
        seen.add(mount.mountId)
        result.append(mount)
    return result


def related_mounts(mounts, target):
    return [m for m in mounts if m.target == target or m.target.startswith(target.rstrip('/') + '/')]
