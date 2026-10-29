"""Cross-process profile ownership for the server and offline maintenance."""
from contextlib import contextmanager
from pathlib import Path
import os


class ProfileBusyError(ValueError):
    pass


@contextmanager
def profile_lease(profile: Path):
    profile = profile.resolve()
    profile.mkdir(parents=True, exist_ok=True)
    # The file persists; ownership is the OS lock, never its mere existence.
    with (profile / ".profile.lock").open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ProfileBusyError("Profile is in use. Stop Photo Privateer before relinking or migrating this profile.") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
