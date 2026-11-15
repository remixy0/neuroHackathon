"""HALO acquisition. All manager operations run on one worker thread."""
import math
import queue
import threading
import time

# Read via DeviceModel.HALO.defaultConfig() in the supplied Kotlin 2.3.1 SDK.
CHANNELS = ["O1", "O2", "Fp2", "Fp1"]


def convert_chunk(data, count, rows, missed=0, battery=None):
    if not 0 < count <= 100:
        raise ValueError("Invalid SDK chunk size")
    indices = [int(v) for v in data[rows["index"]]]
    if len(indices) != count or any(b != a + 1 for a, b in zip(indices, indices[1:])):
        raise ValueError("Discontinuous sample numbers inside SDK chunk")
    dummy = [not bool(v) for v in data[rows["streaming"]]]
    if len(dummy) != count:
        raise ValueError("Invalid STREAMING channel")
    def flatten(key):
        selected = rows[key]
        if not selected:
            return None
        if any(len(data[row]) != count for row in selected):
            raise ValueError("Invalid SDK channel length")
        values = [float(data[row][sample]) for sample in range(count) for row in selected]
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Non-finite SDK data")
        return values
    contacts = [all(bool(v) for v in data[row]) for row in rows["contact"]]
    if len(contacts) != 4 or any(len(data[row]) != count for row in rows["contact"]):
        raise ValueError("Invalid contact channels")
    missed += sum(dummy)
    return dict(sample_count=count, first_sample_index=str(indices[0]),
                wire_last_sample_index="-1", host_time_ns=str(time.monotonic_ns()),
                eeg=flatten("eeg"), accel=flatten("accel"), gyro=flatten("gyro"),
                is_dummy=dummy, contact=contacts, battery_pct=battery,
                phone_discarded_samples="0", ble_missed_samples=str(missed)), missed


class HaloSource:
    def __init__(self, device, simulate=False):
        self.device = device
        self.simulate = simulate
        self.queue = queue.Queue(maxsize=5)
        self.ready = threading.Event()
        self.start = threading.Event()
        self.stop = threading.Event()
        self.error = None
        self.metadata = None
        self.thread = threading.Thread(target=self._run, daemon=True, name="halo-sdk")
        self.thread.start()

    def _push(self, packet):
        if self.stop.is_set():
            return
        try:
            self.queue.put_nowait(packet)
        except queue.Full:
            self.error = "Most nie nadąża z transmisją; sesja została zatrzymana."
            self.stop.set()

    def _metadata(self, hardware, accel, gyro):
        self.metadata = dict(
            device=dict(id=self.device, name=self.device, hardware=hardware, sdk="brainaccess-python-4.0.0"),
            stream=dict(sample_rate_hz=250, channels=CHANNELS, layout="sample_major",
                        eeg_unit="uV", accel_unit="m/s2", gyro_unit="deg/s",
                        has_accel=accel, has_gyro=gyro),
            simulated=self.simulate)
        self.ready.set()

    def _run(self):
        try:
            if self.simulate:
                self._synthetic()
            else:
                self._hardware()
        except Exception as exc:
            self.error = str(exc)
        finally:
            self.ready.set()
            self.stop.set()

    def _hardware(self):
        from brainaccess import core
        from brainaccess.core.eeg_manager import EEGManager
        from brainaccess.core import eeg_channel as ch
        from brainaccess.core.gain_mode import GainMode
        from brainaccess.core.impedance_measurement_mode import ImpedanceMeasurementMode
        from brainaccess.core.output_mode import OutputMode
        core.init()
        try:
            core.config_set_chunk_size(25)
            with EEGManager() as mgr:
                mgr.connect(self.device)
                info = mgr.get_device_info()
                features = mgr.get_device_features()
                if info.device_model.name not in {"HALO", "HALO_V2", "HALO_V3"} or features.electrode_count() != 4:
                    raise ValueError("Ten most obsługuje wyłącznie czterokanałowe HALO.")
                mgr.set_impedance_mode(ImpedanceMeasurementMode.OFF)
                mgr.set_output_mode(OutputMode.NORMAL)
                mgr.set_sample_rate(250)
                ids = dict(eeg=[ch.ELECTRODE_MEASUREMENT + i for i in range(4)],
                           contact=[ch.ELECTRODE_CONTACT + i for i in range(4)],
                           accel=[ch.ACCELEROMETER + i for i in range(3)] if features.has_accel() else [],
                           gyro=[ch.GYROSCOPE + i for i in range(3)] if features.has_gyro() else [])
                for channel_ids in ids.values():
                    for channel in channel_ids:
                        mgr.set_channel_enabled(channel, True)
                for channel in ids["eeg"]:
                    mgr.set_channel_gain(channel, GainMode.X8)
                    mgr.set_channel_bias_feedback(channel)
                mgr.set_channel_enabled(ch.SAMPLE_NUMBER, True)
                mgr.set_channel_enabled(ch.STREAMING, True)
                mgr.load_config()
                if mgr.get_sample_frequency() != 250:
                    raise ValueError("HALO nie potwierdziło 250 Hz.")
                rows = {key: [mgr.get_channel_index(c) for c in values] for key, values in ids.items()}
                rows.update(index=mgr.get_channel_index(ch.SAMPLE_NUMBER), streaming=mgr.get_channel_index(ch.STREAMING))
                missed, battery = 0, None
                def battery_changed(value):
                    nonlocal battery
                    battery = float(value.level) if 0 <= value.level <= 100 else None
                def disconnected():
                    if not self.stop.is_set():
                        self.error = "HALO rozłączyło Bluetooth."
                        self.stop.set()
                def chunk(data, count):
                    nonlocal missed
                    try:
                        packet, missed = convert_chunk(data, count, rows, missed, battery)
                        self._push(packet)
                    except Exception as exc:
                        self.error = str(exc)
                        self.stop.set()
                mgr.set_callback_battery(battery_changed)
                mgr.set_callback_disconnect(disconnected)
                mgr.set_callback_chunk(chunk)
                self._metadata(info.device_model.name, features.has_accel(), features.has_gyro())
                while not self.start.wait(0.05):
                    if self.stop.is_set():
                        return
                if self.stop.is_set():
                    return
                try:
                    mgr.start_stream()
                    self.stop.wait()
                finally:
                    mgr.stop_stream()
        finally:
            core.close()

    def _synthetic(self):
        self.device = "SIMULATED HALO — NO EEG DEVICE"
        self._metadata("SIMULATED", True, True)
        while not self.start.wait(0.05):
            if self.stop.is_set():
                return
        index = 0
        while not self.stop.wait(0.1):
            self._push(dict(sample_count=25, first_sample_index=str(index), wire_last_sample_index="-1",
                            host_time_ns=str(time.monotonic_ns()),
                            eeg=[20 * math.sin((index + s) * 2 * math.pi * 10 / 250 + c) for s in range(25) for c in range(4)],
                            accel=[0.0, 0.0, 9.80665] * 25, gyro=[0.0] * 75,
                            is_dummy=[False] * 25, contact=[True] * 4, battery_pct=None,
                            phone_discarded_samples="0", ble_missed_samples="0"))
            index += 25
