from dataclasses import asdict, dataclass

from compatibility.mountinfo import related_mounts
from installer.errors import InstallerError


@dataclass(frozen=True)
class Ownership:
    source: str
    target: str
    mount_id: int
    device: str
    root: str
    namespace: str
    boot_id: str
    inode: str
    baseline: tuple

    def to_dict(self):
        return asdict(self)


def verify_ownership(record, mounts, namespace, boot_id, source_inode, target_inode):
    if namespace != record.namespace or boot_id != record.boot_id:
        raise InstallerError('MOUNT_CONTEXT_CHANGED', 'Boot identity or mount namespace changed.', 7)
    if source_inode != record.inode or target_inode != record.inode:
        raise InstallerError('MOUNT_INODE_CHANGED', 'The owned source or target changed.', 7)
    related = related_mounts(mounts, record.target)
    owned = [m for m in related if m.mountId == record.mount_id and m.target == record.target
             and m.device == record.device and m.root == record.root]
    if len(owned) != 1 or len(related) != len(record.baseline) + 1:
        raise InstallerError('MOUNT_OWNERSHIP_CONFLICT', 'The mount is missing, stacked, nested, or foreign.', 7)
    others = [m.to_dict() for m in related if m.mountId != record.mount_id]
    if others != list(record.baseline):
        raise InstallerError('MOUNT_BASELINE_CHANGED', 'The underlying mount records changed.', 7)
    return owned[0]
