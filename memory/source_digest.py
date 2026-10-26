"""Hash captured bytes and link text. Never follow links or omit folders.

File hashes are ordinary SHA-256. Tree hashes use framed, sorted records
for all directories, regular files, and symbolic links. Unsafe names,
unreadable entries, special files, and concurrent changes raise errors.
No incomplete scan can return a passing digest.
"""
import hashlib
import os
import stat
from pathlib import Path


class UnsafeSource(ValueError):
    pass


def _safe_name(name):
    lower = name.lower()
    if (lower.startswith('.env') or lower in
            {'.ssh', '.netrc', 'auth.json', 'credentials', '.credentials',
             'credentials.json', 'secrets', '.git-credentials', 'id_rsa'}
            or lower.endswith(('.pem', '.key', '.p12'))
            or lower.startswith('client_secret')):
        raise UnsafeSource('Protected source name; no content read')


def _stamp(s):
    return (s.st_dev, s.st_ino, s.st_mode, s.st_size,
            s.st_mtime_ns, s.st_ctime_ns)


def _root(path):
    path = Path(os.path.abspath(os.fspath(path)))
    for ancestor in list(reversed(path.parents)) + [path]:
        _safe_name(ancestor.name)
        if ancestor != path and ancestor.is_symlink():
            raise UnsafeSource('Source ancestor is a symbolic link')
    return path


def _parent_fd(path):
    """Open each parent without following even a concurrently changed link."""
    fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parent.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _file(path, before, parent_fd=None):
    owned_parent = parent_fd is None
    if owned_parent:
        parent_fd = _parent_fd(path)
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                     dir_fd=parent_fd)
    except BaseException:
        if owned_parent:
            os.close(parent_fd)
        raise
    try:
        with os.fdopen(fd, 'rb') as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode) or _stamp(opened) != _stamp(before):
                raise UnsafeSource('Source changed before reading')
            h = hashlib.sha256()
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                h.update(block)
            if _stamp(os.fstat(stream.fileno())) != _stamp(before):
                raise UnsafeSource('Source changed while reading')
        if _stamp(os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)) != _stamp(before):
            raise UnsafeSource('Source changed after reading')
    finally:
        if owned_parent:
            os.close(parent_fd)
    return h.hexdigest()


def _frame(h, *values):
    for value in values:
        h.update(len(value).to_bytes(8, 'big'))
        h.update(value)


def digest_tree(path):
    root = _root(path)
    if not stat.S_ISDIR(root.lstat().st_mode):
        raise UnsafeSource('A tree root must be a directory')
    records, observed = [], []

    def visit(folder, parent_fd):
        before = os.stat(folder.name, dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISDIR(before.st_mode):
            raise UnsafeSource('Directory changed during scan')
        # No link traversal, including a directory replaced before opening.
        fd = os.open(folder.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                     dir_fd=parent_fd)
        try:
            if _stamp(os.fstat(fd)) != _stamp(before):
                raise UnsafeSource('Directory changed before listing')
            names = sorted(os.listdir(fd), key=os.fsencode)
            observed.append((folder, _stamp(before)))
            for name in names:
                _safe_name(name)
                entry = folder / name
                s = os.stat(name, dir_fd=fd, follow_symlinks=False)
                relative = os.fsencode(str(entry.relative_to(root)))
                if stat.S_ISLNK(s.st_mode):
                    value = os.fsencode(os.readlink(name, dir_fd=fd))
                    records.append((relative, b'L', value))
                    observed.append((entry, _stamp(s)))
                elif stat.S_ISDIR(s.st_mode):
                    records.append((relative, b'D', b''))
                    visit(entry, fd)
                elif stat.S_ISREG(s.st_mode):
                    records.append((relative, b'F', bytes.fromhex(_file(entry, s, fd))))
                    observed.append((entry, _stamp(s)))
                else:
                    raise UnsafeSource('Unsupported source entry; no content read')
            if _stamp(os.fstat(fd)) != _stamp(before):
                raise UnsafeSource('Directory changed during scan')
        finally:
            os.close(fd)

    parent_fd = _parent_fd(root)
    try:
        visit(root, parent_fd)
    finally:
        os.close(parent_fd)
    for entry, stamp in observed:
        if _stamp(entry.lstat()) != stamp:
            raise UnsafeSource('Source changed during tree scan')
    h = hashlib.sha256(b'foxrun-raw-tree-v1\0')
    for relative, kind, value in sorted(records):
        _frame(h, kind, relative, value)
    return h.hexdigest()


def source_digest(path):
    path = _root(path)
    s = path.lstat()
    if stat.S_ISDIR(s.st_mode):
        return digest_tree(path)
    if stat.S_ISREG(s.st_mode):
        return _file(path, s)
    if stat.S_ISLNK(s.st_mode):
        h = hashlib.sha256(b'foxrun-raw-link-v1\0')
        _frame(h, os.fsencode(os.readlink(path)))
        if _stamp(path.lstat()) != _stamp(s):
            raise UnsafeSource('Link changed during scan')
        return h.hexdigest()
    raise UnsafeSource('Unsupported source entry; no content read')


def check_source(path, expected):
    """Read only. Errors remain errors; only an absent root is missing."""
    if len(expected) != 64 or any(c not in '0123456789abcdef' for c in expected):
        raise ValueError('Expected digest must contain 64 lowercase hex digits')
    root = _root(path)
    try:
        root.lstat()
    except FileNotFoundError:
        return 'missing'
    return 'ok' if source_digest(root) == expected else 'changed'
