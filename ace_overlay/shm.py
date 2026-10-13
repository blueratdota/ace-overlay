"""Read-only access to Assetto Corsa EVO's shared-memory telemetry.

AC EVO publishes three named file mappings: Local\\acevo_pmf_physics,
Local\\acevo_pmf_graphics and Local\\acevo_pmf_static. The physics block is a
fixed 800-byte, 4-byte-packed struct. The first 416 bytes match AC1's
SPageFilePhysics. A few things EVO only fills in the graphics block; see LiveSource.

Layout reference: Kunos' Steam guide #3707421508 and
https://github.com/albertowd/live-telemetry-evo/blob/develop/docs/SHARED_MEMORY.md
"""

import ctypes
import time
from ctypes import wintypes

PHYSICS_TAG = "Local\\acevo_pmf_physics"
GRAPHICS_TAG = "Local\\acevo_pmf_graphics"
STATUS_LIVE = 2  # graphics.status while in a session: both in the pit box and on track (verified live)

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


_b = ctypes.c_bool
_c33 = ctypes.c_char * 33


class TyreState(ctypes.Structure):
    """SMEvoTyreState, 256 bytes. Pressures are psi. left/right are faces of the contact patch relative to the car
    (verified live), so on left-side wheels left = outer, and on right-side wheels left = inner."""

    _pack_ = 4
    _fields_ = [
        ("slip", _f),
        ("lock", _b),
        ("pressure", _f),
        ("temperature_c", _f),
        ("brake_temperature_c", _f),
        ("brake_pressure", _f),
        ("temperature_left", _f),
        ("temperature_center", _f),
        ("temperature_right", _f),
        ("compound_front", _c33),
        ("compound_rear", _c33),
        ("normalized_pressure", _f),
        ("normalized_temperature_left", _f),
        ("normalized_temperature_center", _f),
        ("normalized_temperature_right", _f),
        ("brake_normalized_temperature", _f),
        ("normalized_temperature_core", _f),
        ("_reserved", ctypes.c_byte * 128),
    ]


class Electronics(ctypes.Structure):
    """SMEvoElectronics, 128 bytes: the driver-adjustable aid / map settings."""

    _pack_ = 4
    _fields_ = [
        ("tc_level", ctypes.c_int8),
        ("tc_cut_level", ctypes.c_int8),
        ("abs_level", ctypes.c_int8),
        ("esc_level", ctypes.c_int8),
        ("ebb_level", ctypes.c_int8),
        ("brake_bias", _f),
        ("engine_map_level", ctypes.c_int8),
        ("turbo_level", _f),
        ("ers_deployment_map", ctypes.c_int8),
        ("ers_recharge_map", _f),
        ("is_ers_heat_charging_on", _b),
        ("is_ers_overtake_mode_on", _b),
        ("is_drs_open", _b),
        ("diff_power_level", ctypes.c_int8),
        ("diff_coast_level", ctypes.c_int8),
        ("damper_levels", ctypes.c_int8 * 4),  # front bump, front rebound, rear bump, rear rebound
        ("is_ignition_on", _b),
        ("is_pitlimiter_on", _b),
        ("active_performance_mode", ctypes.c_int8),
        ("_reserved", ctypes.c_byte * 88),
    ]


class SessionState(ctypes.Structure):
    """SMEvoSessionState, 256 bytes."""

    _pack_ = 4
    _fields_ = [
        ("phase_name", _c33),
        ("time_left", ctypes.c_char * 15),
        ("time_left_ms", _i),
        ("wait_time", ctypes.c_char * 15),
        ("total_lap", _i),  # 0 in timed sessions
        ("current_lap", _i),
        ("lights_on", _i),
        ("lights_mode", _i),
        ("lap_length_km", _f),
        ("end_session_flag", _i),
        ("time_to_next_session", ctypes.c_char * 15),
        ("flags", _b * 6),
        ("_reserved", ctypes.c_byte * 143),
    ]


class Graphics(ctypes.Structure):
    """SPageFileGraphicEvo, the HUD-rate block. Substructs the overlay doesn't read are opaque bytes.

    Unlike physics, this block mixes bool / int16 / char[33] fields, so offsets depend on every
    field before them. The layout was checked against the live game (car_model, lap times and fuel
    decode correctly), and tests/test_shm.py pins the offsets used.
    """

    _pack_ = 4
    _fields_ = [
        ("packetId", _i),
        ("status", _i),
        ("focused_car_id", ctypes.c_uint64 * 2),
        ("player_car_id", ctypes.c_uint64 * 2),
        ("rpm", ctypes.c_uint16),
        ("is_rpm_limiter_on", _b),
        ("is_change_up_rpm", _b),
        ("is_change_down_rpm", _b),
        ("tc_active", _b),
        ("abs_active", _b),
        ("esc_active", _b),
        ("launch_active", _b),
        ("is_ignition_on", _b),
        ("is_engine_running", _b),
        ("kers_is_charging", _b),
        ("is_wrong_way", _b),
        ("is_drs_available", _b),
        ("battery_is_charging", _b),
        ("is_max_kj_per_lap_reached", _b),
        ("is_max_charge_kj_per_lap_reached", _b),
        ("display_speed_kmh", ctypes.c_int16),
        ("display_speed_mph", ctypes.c_int16),
        ("display_speed_ms", ctypes.c_int16),
        ("pitspeeding_delta", _f),
        ("gear_int", ctypes.c_int16),
        ("rpm_percent", _f),
        ("gas_percent", _f),
        ("brake_percent", _f),
        ("handbrake_percent", _f),
        ("clutch_percent", _f),
        ("steering_percent", _f),
        ("ffb_strength", _f),
        ("car_ffb_multiplier", _f),
        ("water_temperature_percent", _f),
        ("water_pressure_bar", _f),
        ("fuel_pressure_bar", _f),
        ("water_temperature_c", ctypes.c_int8),
        ("air_temperature_c", ctypes.c_int8),
        ("oil_temperature_c", _f),
        ("oil_pressure_bar", _f),
        ("exhaust_temperature_c", _f),
        ("g_forces", _F3),
        ("turbo_boost", _f),
        ("turbo_boost_level", _f),
        ("turbo_boost_perc", _f),
        ("steer_degrees", _i),
        ("current_km", _f),
        ("total_km", ctypes.c_uint32),
        ("total_driving_time_s", ctypes.c_uint32),
        ("time_of_day", _i * 3),
        ("delta_time_ms", _i),
        ("current_lap_time_ms", _i),
        ("predicted_lap_time_ms", _i),
        ("fuel_liter_current_quantity", _f),
        ("fuel_liter_current_quantity_percent", _f),
        ("fuel_liter_per_km", _f),
        ("km_per_fuel_liter", _f),
        ("current_torque", _f),
        ("current_bhp", _i),
        ("tyres", TyreState * 4),  # FL, FR, RL, RR (Kunos: tyre_lf, tyre_rf, tyre_lr, tyre_rr)
        ("npos", _f),  # 0..1 position around the lap
        ("kers_charge_perc", _f),
        ("kers_current_perc", _f),
        ("control_lock_time", _f),
        ("car_damage", ctypes.c_byte * 128),
        ("car_location", _i),
        ("pit_info", ctypes.c_byte * 64),
        ("fuel_liter_used", _f),
        ("fuel_liter_per_lap", _f),
        ("laps_possible_with_fuel", _f),
        ("battery_temperature", _f),
        ("battery_voltage", _f),
        ("instantaneous_fuel_liter_per_km", _f),
        ("instantaneous_km_per_fuel_liter", _f),
        ("gear_rpm_window", _f),
        ("instrumentation", ctypes.c_byte * (3 * 128)),  # current, min limit, max limit
        ("electronics", Electronics),
        ("electronics_min_limit", Electronics),
        ("electronics_max_limit", Electronics),
        ("electronics_is_modifiable", Electronics),
        ("total_lap_count", _i),  # completed laps
        ("current_pos", ctypes.c_uint32),  # 0 when the session doesn't rank
        ("total_drivers", ctypes.c_uint32),
        ("last_laptime_ms", _i),
        ("best_laptime_ms", _i),
        ("flag", _i),
        ("global_flag", _i),
        ("max_gears", ctypes.c_uint32),
        ("engine_type", _i),
        ("has_kers", _b),
        ("is_last_lap", _b),
        ("performance_mode_name", _c33),
        ("diff_coast_raw_value", _f),
        ("diff_power_raw_value", _f),
        ("race_cut_gained_time_ms", _i),
        ("distance_to_deadline", _i),
        ("race_cut_current_delta", _f),
        ("session_state", SessionState),
        ("timing_state", ctypes.c_byte * 256),
        ("player_ping", _i),
        ("player_latency", _i),
        ("player_cpu_usage", _i),
        ("player_cpu_usage_avg", _i),
        ("player_qos", _i),
        ("player_qos_avg", _i),
        ("player_fps", _i),
        ("player_fps_avg", _i),
        ("driver_name", _c33),
        ("driver_surname", _c33),
        ("car_model", _c33),
        ("is_in_pit_box", _b),
        ("is_in_pit_lane", _b),
        ("is_valid_lap", _b),
        ("car_coordinates", _F3 * 60),
        ("gap_ahead", _f),  # s
        ("gap_behind", _f),  # s
        ("active_cars", ctypes.c_uint8),
        ("fuel_per_lap", _f),
        ("fuel_estimated_laps", _f),
        ("assists_state", ctypes.c_byte * 64),
        ("max_fuel", _f),
        ("max_turbo_boost", _f),
        ("use_single_compound", _b),
        ("car_ids", (ctypes.c_uint64 * 2) * 60),
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


def air_temp(physics, graphics):
    """Air temperature in °C, or None. Physics airTemp reads 0 in some states (seen during a replay),
    where the graphics block's whole-degree air temperature still works."""
    if physics is not None and physics.airTemp:
        return physics.airTemp
    if graphics is not None and graphics.air_temperature_c:
        return float(graphics.air_temperature_c)
    return None


def track_temp(physics):
    """Track temperature in °C, or None when the game sends 0 (no graphics-block equivalent)."""
    return physics.roadTemp if physics is not None and physics.roadTemp else None


def is_driving(graphics):
    """True once the car is out of the garage / pit box in a live session (pit lane counts)."""
    return graphics is not None and graphics.status == STATUS_LIVE and not graphics.is_in_pit_box


class LiveSource:
    """Telemetry from the running game, as a Physics frame patched with what EVO only
    publishes in the graphics block (verified live on a Golf 8 R, 2026-09-29):

    - tyreTempI/M/O are always 0 in EVO. The real per-face temperatures come from the
      graphics TyreStates.
    - absInAction stays 0 even while ABS works. physics.abs (0/1) and graphics.abs_active
      fire together instead, so every source is OR-ed in. TC is treated the same way.

    Our open handle keeps the mapping alive after the game exits. When packetId stops
    changing, reattach: that fails once the game is gone and picks up a fresh mapping
    after a restart.
    """

    STALE_AFTER_S = 3.0

    def __init__(self):
        self._physics = SharedBlock(PHYSICS_TAG, Physics)
        self._graphics = SharedBlock(GRAPHICS_TAG, Graphics)
        self._last_packet = None
        self._last_change = time.monotonic()
        self.graphics = None  # the Graphics snapshot taken with the last read(), for the info panel

    def read(self):
        frame = self._physics.read()
        if frame is None:
            self.graphics = None
            return None
        now = time.monotonic()
        if frame.packetId != self._last_packet:
            self._last_packet = frame.packetId
            self._last_change = now
        elif now - self._last_change > self.STALE_AFTER_S:
            self._physics.close()
            self._graphics.close()
            self._last_change = now

        frame.absInAction = int(bool(frame.absInAction or frame.abs > 0))
        frame.tcInAction = int(bool(frame.tcInAction or frame.tc > 0))
        graphics = self.graphics = self._graphics.read()
        if graphics is not None:
            frame.absInAction |= graphics.abs_active
            frame.tcInAction |= graphics.tc_active
            for w, tyre in enumerate(graphics.tyres):
                left_side = w % 2 == 0  # FL, RL
                outer, inner = ((tyre.temperature_left, tyre.temperature_right) if left_side
                                else (tyre.temperature_right, tyre.temperature_left))
                frame.tyreTempI[w], frame.tyreTempM[w], frame.tyreTempO[w] = inner, tyre.temperature_center, outer
        return frame
