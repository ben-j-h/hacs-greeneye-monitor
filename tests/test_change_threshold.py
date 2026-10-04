"""Held-value change thresholds on power/current/voltage sensors."""
from types import SimpleNamespace

import pytest

from custom_components.greeneye_monitor.sensor import CurrentSensor
from custom_components.greeneye_monitor.sensor import PowerSensor
from custom_components.greeneye_monitor.sensor import VoltageSensor


class FakeBatcher:
    def __init__(self) -> None:
        self.marks = 0

    def mark_dirty(self, entity) -> None:
        self.marks += 1


def _monitor(voltage=None):
    return SimpleNamespace(
        serial_number=1121887, voltage_sensor=SimpleNamespace(voltage=voltage)
    )


def _power(watts):
    channel = SimpleNamespace(watts=watts, amps=None, is_aux=False, number=0)
    batcher = FakeBatcher()
    return PowerSensor(_monitor(), channel, False, batcher), channel, batcher


def _feed(sensor, channel, values, attr="watts"):
    seen = []
    for v in values:
        setattr(channel, attr, v)
        sensor._maybe_mark_dirty()
        seen.append(sensor.native_value)
    return seen


@pytest.mark.parametrize(
    ("published", "threshold"),
    [(0.0, 0.5), (19.0, 0.5), (25.0, 0.5), (50.0, 1.0), (100.0, 2.0), (250.0, 5.0), (3000.0, 5.0)],
)
def test_power_threshold_clamp(published, threshold):
    sensor, _, _ = _power(None)
    assert sensor._change_threshold(published) == pytest.approx(threshold)
    assert sensor._change_threshold(-published) == pytest.approx(threshold)


def test_power_holds_sub_threshold_noise_but_writes_every_packet():
    sensor, channel, batcher = _power(None)
    # steady 78 W load jittering by the GEM's ~1.1 W ADC step (threshold 1.56 W)
    seen = _feed(sensor, channel, [78.0, 77.4, 78.6, 77.4, 78.6])
    assert seen == [78.0] * 5
    # every packet still reaches the batcher so last_reported stays fresh
    assert batcher.marks == 5


def test_power_republishes_on_real_change_and_caps_at_5w():
    sensor, channel, _ = _power(None)
    assert _feed(sensor, channel, [1000.0, 1004.9, 1005.0]) == [1000.0, 1000.0, 1005.0]
    # small load: 0.5 W floor
    sensor, channel, _ = _power(None)
    assert _feed(sensor, channel, [10.0, 10.4, 10.5]) == [10.0, 10.0, 10.5]


def test_power_drift_is_measured_from_published_value():
    sensor, channel, _ = _power(None)
    # creeping load: each step is small, but the total crosses the threshold
    assert _feed(sensor, channel, [100.0, 101.0, 101.9, 102.0]) == [100.0, 100.0, 100.0, 102.0]


def test_power_unknown_passes_through():
    sensor, channel, _ = _power(None)
    assert _feed(sensor, channel, [None, 50.0, 50.2, None, 50.2]) == [None, 50.0, 50.0, None, 50.2]


def test_current_and_voltage_hold_fixed_thresholds():
    channel = SimpleNamespace(watts=None, amps=None, is_aux=False, number=0)
    current = CurrentSensor(_monitor(), channel, FakeBatcher())
    assert _feed(current, channel, [1.00, 1.004, 1.01], attr="amps") == [1.0, 1.0, 1.01]

    monitor = _monitor()
    volts = VoltageSensor(monitor, FakeBatcher())
    assert _feed(volts, monitor.voltage_sensor, [121.0, 121.04, 121.1], attr="voltage") == [
        121.0,
        121.0,
        121.1,
    ]
