#!/usr/bin/env python3
"""Used by bin/selftest-security.sh, inside the sandbox profile: what can this process do to ANOTHER process whose pid it is given?
Prints: "kill: allowed|denied", "proc_listpids bytes: N" (0 when listing is denied), "pidpath: <path>|denied".
Reading the arguments of a known pid (sysctl KERN_PROCARGS2) is not tested: no sandbox rule reaches it (docs/public/SECURITY.md says so)."""
import ctypes
import os
import sys

libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
pid = int(sys.argv[1])
try:
    os.kill(pid, 0)
    print("kill: allowed")
except OSError:
    print("kill: denied")
print("proc_listpids bytes:", libc.proc_listpids(1, 0, None, 0))
buf = ctypes.create_string_buffer(1024)
print("pidpath:", buf.value.decode() if libc.proc_pidpath(pid, buf, 1024) > 0 else "denied")
