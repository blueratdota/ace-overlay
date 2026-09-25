"""Read-only access to Assetto Corsa EVO's shared-memory telemetry.

AC EVO publishes three named file mappings: Local\\acevo_pmf_physics,
Local\\acevo_pmf_graphics and Local\\acevo_pmf_static. The physics block is a
fixed 800-byte, 4-byte-packed struct. The first 416 bytes match AC1's
SPageFilePhysics.

Layout reference: Kunos' Steam guide #3707421508 and
https://github.com/albertowd/live-telemetry-evo/blob/develop/docs/SHARED_MEMORY.md
"""

import ctypes
import time
from ctypes import wintypes

PHYSICS_TAG = "Local\\acevo_pmf_physics"

_f = ctypes.c_float
_i = ctypes.c_int32
_F3 = _f * 3
_F4 = _f * 4
_V4 = _F3 * 4


class Physics(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        # --- AC1-compatible prefix (0..415) ---
        ("packetId", _i),
        ("gas", _f),  # 0..1
        ("brake", _f),  # 0..1
        ("fuel", _f),
        ("gear", _i),  # 0=R, 1=N, 2..=forward
        ("rpms", _i),
        ("steerAngle", _f),  # rad, negative = left
        ("speedKmh", _f),
        ("velocity", _F3),
        ("accG", _F3),  # [lat, vert, long]
        ("wheelSlip", _F4),
        ("wheelLoad", _F4),
        ("wheelsPressure", _F4),
        ("wheelAngularSpeed", _F4),
        ("tyreWear", _F4),  # always 0 in EVO
        ("tyreDirtyLevel", _F4),
        ("tyreCoreTemperature", _F4),
        ("camberRAD", _F4),
        ("suspensionTravel", _F4),
        ("drs", _f),
        ("tc", _f),  # aid setting, not "active"
        ("heading", _f),
        ("pitch", _f),
        ("roll", _f),
        ("cgHeight", _f),
        ("carDamage", _f * 5),
        ("numberOfTyresOut", _i),
        ("pitLimiterOn", _i),
        ("abs", _f),  # aid setting, not "active"
        ("kersCharge", _f),
        ("kersInput", _f),
        ("autoShifterOn", _i),
        ("rideHeight", _f * 2),
        ("turboBoost", _f),
        ("ballast", _f),
        ("airDensity", _f),
        ("airTemp", _f),
        ("roadTemp", _f),
        ("localAngularVel", _F3),
        ("finalFF", _f),
        ("performanceMeter", _f),
        ("engineBrake", _i),
        ("ersRecoveryLevel", _i),
        ("ersPowerLevel", _i),
        ("ersHeatCharging", _i),
        ("ersIsCharging", _i),
        ("kersCurrentKJ", _f),
        ("drsAvailable", _i),
        ("drsEnabled", _i),
        ("brakeTemp", _F4),
        ("clutch", _f),  # 0..1
        ("tyreTempI", _F4),
        ("tyreTempM", _F4),
        ("tyreTempO", _F4),
        # --- AC EVO additions (416..799) ---
        ("isAIControlled", _i),
        ("tyreContactPoint", _V4),
        ("tyreContactNormal", _V4),
        ("tyreContactHeading", _V4),
        ("brakeBias", _f),
        ("localVelocity", _F3),
        ("P2PActivations", _i),
        ("P2PStatus", _i),
        ("currentMaxRpm", _i),  # replaces AC1's static maxRpm
        ("mz", _F4),
        ("fx", _F4),
        ("fy", _F4),
        ("slipRatio", _F4),
        ("slipAngle", _F4),
        ("tcInAction", _i),  # TC cutting right now
        ("absInAction", _i),  # ABS modulating right now
        ("suspensionDamage", _F4),
        ("tyreTemp", _F4),
        ("waterTemp", _f),
        ("brakeTorque", _F4),
        ("frontBrakeCompound", _i),
        ("rearBrakeCompound", _i),
        ("padLife", _F4),
        ("discLife", _F4),
        ("ignitionOn", _i),
        ("starterEngineOn", _i),
        ("isEngineRunning", _i),
        ("kerbVibration", _f),
        ("slipVibrations", _f),
        ("roadVibrations", _f),
        ("absVibrations", _f),
    ]


_FILE_MAP_READ = 0x0004
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.OpenFileMappingW.restype = wintypes.HANDLE
_kernel32.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
_kernel32.MapViewOfFile.restype = ctypes.c_void_p
_kernel32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


class SharedBlock:
    """Attach to an existing named mapping and snapshot it into a ctypes struct.

    OpenFileMappingW is used instead of mmap.mmap(tagname=...), because mmap
    silently *creates* an empty mapping when the game isn't running.
    """

    def __init__(self, tag, struct):
        self.tag = tag
        self.struct = struct
        self._handle = None
        self._view = None

    def open(self):
        handle = _kernel32.OpenFileMappingW(_FILE_MAP_READ, False, self.tag)
        if not handle:
            return False
        view = _kernel32.MapViewOfFile(handle, _FILE_MAP_READ, 0, 0, 0)
        if not view:
            _kernel32.CloseHandle(handle)
            return False
        self._handle, self._view = handle, view
        return True

    def close(self):
        if self._view:
            _kernel32.UnmapViewOfFile(self._view)
        if self._handle:
            _kernel32.CloseHandle(self._handle)
        self._handle = self._view = None

    def read(self):
        """Return a copy of the block, or None if the game isn't running."""
        if not self._view and not self.open():
            return None
        out = self.struct()
        ctypes.memmove(ctypes.addressof(out), self._view, ctypes.sizeof(out))
        return out


class LiveSource:
    """Physics telemetry from the running game.

    Our open handle keeps the mapping alive after the game exits. When packetId
    stops changing, reattach: that fails once the game is gone and picks up a
    fresh mapping after a restart.
    """

    STALE_AFTER_S = 3.0

    def __init__(self):
        self._block = SharedBlock(PHYSICS_TAG, Physics)
        self._last_packet = None
        self._last_change = time.monotonic()

    def read(self):
        frame = self._block.read()
        if frame is None:
            return None
        now = time.monotonic()
        if frame.packetId != self._last_packet:
            self._last_packet = frame.packetId
            self._last_change = now
        elif now - self._last_change > self.STALE_AFTER_S:
            self._block.close()
            self._last_change = now
        return frame
