"""Trusted entrypoint mounted inside the import sandbox, never an application CLI."""
import ctypes
import errno
import json
from pathlib import Path
import sys


def restrict_syscalls():
    """Deny networking, new processes/namespaces and re-execution before parsing."""
    library = ctypes.CDLL("libseccomp.so.2", use_errno=True)
    library.seccomp_init.argtypes = [ctypes.c_uint32]
    library.seccomp_init.restype = ctypes.c_void_p
    library.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    library.seccomp_syscall_resolve_name.restype = ctypes.c_int
    library.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    library.seccomp_load.argtypes = [ctypes.c_void_p]
    library.seccomp_release.argtypes = [ctypes.c_void_p]
    context = library.seccomp_init(0x7FFF0000)  # SCMP_ACT_ALLOW
    if not context:
        raise RuntimeError("seccomp_unavailable")
    try:
        for name in ("socket", "socketpair", "fork", "vfork", "clone", "clone3", "execve", "execveat",
                     "unshare", "setns", "ptrace", "process_vm_readv", "process_vm_writev"):
            syscall = library.seccomp_syscall_resolve_name(name.encode("ascii"))
            if syscall >= 0 and library.seccomp_rule_add(context, 0x50000 | errno.EPERM, syscall, 0) != 0:
                raise RuntimeError("seccomp_unavailable")
        if library.seccomp_load(context) != 0:
            raise RuntimeError("seccomp_unavailable")
    finally:
        library.seccomp_release(context)


def main():
    restrict_syscalls()
    # -I -S excludes ambient modules and site hooks. Only explicitly mounted
    # decoder dependencies and these two trusted files enter the import path.
    sys.path[:0] = ["/code", "/deps"]
    from dataset_zip import ImportLimits, validate_zip

    configuration = json.loads(sys.argv[1])
    result = validate_zip(Path("/input.zip"), Path("/staging"),
                          root=configuration["root"], limits=ImportLimits(**configuration["limits"]))
    print(json.dumps(result, ensure_ascii=True, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
