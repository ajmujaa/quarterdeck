#!/usr/bin/env python3
"""Used by bin/selftest-security.sh, inside the sandbox profile: can this process look up these Mach services?
Prints "<name> OK" or "<name> DENIED". Read-only; it only asks the bootstrap server for a port."""
import ctypes
import sys

lib = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
bootstrap = ctypes.c_uint32.in_dll(lib, "bootstrap_port")
lib.bootstrap_look_up.argtypes = [ctypes.c_uint32, ctypes.c_char_p, ctypes.POINTER(ctypes.c_uint32)]
for name in sys.argv[1:]:
    port = ctypes.c_uint32()
    print(name, "OK" if lib.bootstrap_look_up(bootstrap.value, name.encode(), ctypes.byref(port)) == 0 else "DENIED")
