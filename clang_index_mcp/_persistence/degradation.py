"""Per-operation-class degradation mode (epic clang_index_mcp-ent, child .10).

Decision D3: degradation is scoped per operation class (read / write), not
global. After ``failure_threshold`` consecutive backend failures a class enters
Degraded: the wrapper short-circuits to safe values without hitting the backend
and logs at most once per cooldown. After a cooldown a recovery probe (the next
admitted backend call) runs at most once per probe interval; success returns the
class to Normal so reads/persistence resume without a process restart.

Time is injectable (``clock``, default ``time.monotonic``) so tests drive
transitions deterministically without sleeps.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Literal

from .._core.error_tracking import OperationClass, operation_class

# Thresholds are constructor-injectable (or overridable here) so tests and
# sibling resilience seams can share the same policy without patching modules.
DEFAULT_FAILURE_THRESHOLD = 5
DEFAULT_COOLDOWN_SECONDS = 30.0
DEFAULT_PROBE_INTERVAL_SECONDS = 5.0


class CircuitOpenError(Exception):
    """Backend call short-circuited because its class is Degraded.

    Carries no domain meaning: callers map it through the typed safe-value
    contract (REQ-6.8.4) and the error-state channel (REQ-6.8.6).
    """


class CallAdmission(str, Enum):
    """Decision returned by :meth:`DegradationMode.admit`."""

    ALLOW = "allow"
    SHORT_CIRCUIT = "short_circuit"
    PROBE = "probe"


@dataclass
class _ClassState:
    """Mutable per-class state guarded by the mode lock."""

    consecutive_failures: int = 0
    degraded: bool = False
    degraded_at: float | None = None
    last_log_at: float | None = None
    last_probe_at: float | None = None
    probe_in_flight: bool = False
    short_circuit_count: int = 0
    probe_count: int = 0
    recovered_count: int = 0
    entered_count: int = 0


@dataclass
class ClassModeSnapshot:
    """Immutable-ish view of one class's mode for tests and error summaries."""

    mode: Literal["normal", "degraded"]
    consecutive_failures: int
    short_circuit_count: int
    probe_count: int
    recovered_count: int
    entered_count: int

    def as_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "consecutive_failures": self.consecutive_failures,
            "short_circuit_count": self.short_circuit_count,
            "probe_count": self.probe_count,
            "recovered_count": self.recovered_count,
            "entered_count": self.entered_count,
        }


class DegradationMode:
    """State machine per operation class (Normal / Degraded + recovery probe).

    Thread-safe: used concurrently from indexing, writer, and query threads.
    """

    def __init__(
        self,
        *,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
        probe_interval_seconds: float = DEFAULT_PROBE_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.failure_threshold = max(1, failure_threshold)
        self.cooldown_seconds = max(0.0, cooldown_seconds)
        self.probe_interval_seconds = max(0.0, probe_interval_seconds)
        self._clock = clock
        self._lock = threading.RLock()
        self._states: dict[OperationClass, _ClassState] = {
            "read": _ClassState(),
            "write": _ClassState(),
        }

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def is_degraded(self, operation: str) -> bool:
        """True when the operation's class is currently Degraded."""
        with self._lock:
            return self._states[operation_class(operation)].degraded

    def mode_for(self, operation: str) -> Literal["normal", "degraded"]:
        """Return the mode name for the operation's class."""
        with self._lock:
            state = self._states[operation_class(operation)]
            return "degraded" if state.degraded else "normal"

    def snapshot(self, operation_or_class: str) -> ClassModeSnapshot:
        """Return a snapshot for an operation name or a class name."""
        cls: OperationClass
        if operation_or_class in ("read", "write"):
            cls = operation_or_class  # type: ignore[assignment]
        else:
            cls = operation_class(operation_or_class)
        with self._lock:
            state = self._states[cls]
            return ClassModeSnapshot(
                mode="degraded" if state.degraded else "normal",
                consecutive_failures=state.consecutive_failures,
                short_circuit_count=state.short_circuit_count,
                probe_count=state.probe_count,
                recovered_count=state.recovered_count,
                entered_count=state.entered_count,
            )

    def get_states(self) -> dict[str, dict[str, object]]:
        """Return additive degradation state for the error-summary channel."""
        return {
            "read": self.snapshot("read").as_dict(),
            "write": self.snapshot("write").as_dict(),
        }

    def should_log(self, operation: str) -> bool:
        """Rate-limited short-circuit logging: at most once per cooldown.

        Returns True when the caller should emit a log entry now. Consumes the
        slot, so a burst of short-circuits produces one entry per cooldown.
        """
        with self._lock:
            state = self._states[operation_class(operation)]
            now = self._clock()
            if state.last_log_at is not None and (now - state.last_log_at) < self.cooldown_seconds:
                return False
            state.last_log_at = now
            return True

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------

    def admit(self, operation: str) -> CallAdmission:
        """Decide whether a backend call may proceed.

        - ALLOW: class is Normal — pass through.
        - SHORT_CIRCUIT: class is Degraded and no probe slot is ready — do not
          hit the backend.
        - PROBE: class is Degraded but the cooldown has elapsed — this call is
          the recovery probe (at most one per probe interval). Its outcome is
          reported via :meth:`note_success` / :meth:`note_failure`.
        """
        with self._lock:
            state = self._states[operation_class(operation)]
            if not state.degraded:
                return CallAdmission.ALLOW
            if not self._probe_ready(state):
                state.short_circuit_count += 1
                return CallAdmission.SHORT_CIRCUIT
            now = self._clock()
            state.last_probe_at = now
            state.probe_in_flight = True
            state.probe_count += 1
            return CallAdmission.PROBE

    def note_success(self, operation: str) -> None:
        """Record a backend success for the operation's class (probe or normal)."""
        with self._lock:
            state = self._states[operation_class(operation)]
            state.consecutive_failures = 0
            state.probe_in_flight = False
            if state.degraded:
                state.degraded = False
                state.degraded_at = None
                state.recovered_count += 1

    def note_failure(self, operation: str) -> bool:
        """Record a backend failure. Returns True when this call entered Degraded."""
        with self._lock:
            state = self._states[operation_class(operation)]
            state.consecutive_failures += 1
            state.probe_in_flight = False
            if state.degraded:
                return False
            if state.consecutive_failures < self.failure_threshold:
                return False
            state.degraded = True
            state.degraded_at = self._clock()
            state.entered_count += 1
            # Allow an immediate "entered degraded" log.
            state.last_log_at = None
            return True

    def reset(self) -> None:
        """Reset both classes to Normal (useful for testing and cache resets)."""
        with self._lock:
            self._states = {"read": _ClassState(), "write": _ClassState()}

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _probe_ready(self, state: _ClassState) -> bool:
        """True when a recovery probe may run now (caller holds the lock)."""
        if state.probe_in_flight:
            return False
        now = self._clock()
        if state.degraded_at is not None and (now - state.degraded_at) < self.cooldown_seconds:
            return False
        if (
            state.last_probe_at is not None
            and (now - state.last_probe_at) < self.probe_interval_seconds
        ):
            return False
        return True
