###########################################################################
# Copyright (c) 2025, Ampere Computing LLC
#
# SPDX-License-Identifier: BSD-3-Clause
# License terms can be found in the LICENSE.TXT file at the root of this project.
###########################################################################

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from multiprocessing import Event, Process
from pathlib import Path
import contextlib
import os
import platform
import re
import signal
import subprocess
import time
from typing import TypeAlias


@dataclass(slots=True)
class CollectorConfig:
    interval: int
    sample_count: int
    output_dir: Path
    system_architecture: str = field(default_factory=platform.machine)
    network_interface: str | None = None
    perf_frequency: int = 99
    perf_disabled: bool = False
    perf_unavailable: bool = False
    numastat_disabled: bool = False


class Collector(ABC):
    name = "collector"

    def __init__(self, config: CollectorConfig) -> None:
        self.config = config
        self._stop = Event()
        self._process: Process | None = None

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process else None

    @property
    def exitcode(self) -> int | None:
        return self._process.exitcode if self._process else None

    @property
    def is_alive(self) -> bool:
        return self._process.is_alive() if self._process else False

    def start(self) -> None:
        self._process = Process(target=self._bootstrap, name=self.name, daemon=False)
        self._process.start()

    def stop(self) -> None:
        self._stop.set()

    def join(self, timeout: float | None = None) -> None:
        if self._process is not None:
            self._process.join(timeout)

    def terminate(self) -> None:
        if self._process is not None and self._process.is_alive():
            self._process.terminate()

    def kill(self) -> None:
        if self._process is not None and self._process.is_alive():
            self._process.kill()

    def _bootstrap(self) -> None:
        def _handle_signal(_signum, _frame) -> None:
            self._stop.set()

        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)
        self.config.output_dir.mkdir(parents=True, exist_ok=True)

        try:
            self.collect()
        finally:
            self.post_process()

    def sleep_or_stop(self, seconds: float) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self._stop.is_set():
                return False
            time.sleep(min(0.2, deadline - time.monotonic()))
        return True

    def run_process(self, cmd: list[str], stdout_path: Path | None = None) -> None:
        handle = None
        try:
            if stdout_path is not None:
                handle = stdout_path.open("w", encoding="utf-8")
            proc = subprocess.Popen(
                cmd,
                stdout=handle or subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                preexec_fn=os.setsid,
            )
            while proc.poll() is None:
                if self._stop.is_set():
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(proc.pid, signal.SIGINT)
                    break
                time.sleep(0.2)

            _, stderr = proc.communicate()
            if proc.returncode not in (0, -signal.SIGINT, 130, -signal.SIGTERM, 143):
                raise RuntimeError(f"{self.name} failed: {' '.join(cmd)}\n{stderr}")
        finally:
            if handle is not None:
                handle.close()

    @abstractmethod
    def collect(self) -> None:
        raise NotImplementedError

    def post_process(self) -> None:
        pass


CollectorFactory: TypeAlias = Callable[[CollectorConfig], Collector]


def default_network_interface() -> str | None:
    try:
        output = subprocess.run(
            ["ip", "route", "show", "default"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        match = re.search(r"dev\s+(\S+)", output)
        return match.group(1) if match else None
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


class CPUCollector(Collector):
    name = "cpu"

    def collect(self) -> None:
        self.run_process(
            [
                "sar",
                "-P",
                "ALL",
                str(self.config.interval),
                str(self.config.sample_count),
            ],
            self.config.output_dir / "cpu_all.dat",
        )

    def post_process(self) -> None:
        raw = self.config.output_dir / "cpu_all.dat"
        if not raw.exists():
            return

        lines = raw.read_text(encoding="utf-8").splitlines()
        cpu_dat = self.config.output_dir / "cpu.dat"
        cpu_dat.write_text(
            "\n".join(
                line
                for idx, line in enumerate(lines, start=1)
                if idx < 4 or ("all" in line and "Average" not in line)
            )
            + "\n",
            encoding="utf-8",
        )

        totals: dict[int, list[float]] = {}
        for line in lines:
            parts = line.split()
            if len(parts) < 5 or not parts[1].isdigit():
                continue
            cpu_id = int(parts[1])
            bucket = totals.setdefault(cpu_id, [0.0, 0.0, 0.0])
            bucket[0] += float(parts[2])
            bucket[1] += float(parts[4])
            bucket[2] += 1

        out = ["CPU\t%user\t%system"]
        for cpu_id in sorted(totals):
            user_sum, system_sum, count = totals[cpu_id]
            out.append(f"{cpu_id}\t{user_sum / count:.2f}\t{system_sum / count:.2f}")

        (self.config.output_dir / "cpu_consolidated.dat").write_text(
            "\n".join(out) + "\n",
            encoding="utf-8",
        )


class CPUFreqCollector(Collector):
    name = "cpu_freq"

    def _freq_files(self) -> list[Path]:
        leaf = (
            "scaling_cur_freq"
            if self.config.system_architecture == "x86_64"
            else "cpuinfo_cur_freq"
        )
        paths = list(Path("/sys/devices/system/cpu").glob(f"cpu[0-9]*/cpufreq/{leaf}"))

        def cpu_sort_key(path: Path) -> int:
            match = re.search(r"cpu(\d+)", str(path))
            if match is None:
                raise RuntimeError(f"could not parse cpu id from path:{path}")
            return int(match.group(1))

        return sorted(paths, key=cpu_sort_key)

    def collect(self) -> None:
        if os.geteuid() != 0:
            raise RuntimeError("cpu_freq collector requires root privileges")

        out = self.config.output_dir / "cpu_freq.dat"
        freq_files = self._freq_files()
        if not freq_files:
            raise RuntimeError("cpu_freq collector could not find cpufreq sysfs files")

        out.write_text(
            "\t".join(str(i) for i in range(len(freq_files))) + "\n",
            encoding="utf-8",
        )

        for _ in range(self.config.sample_count):
            values = [path.read_text(encoding="utf-8").strip() for path in freq_files]
            with out.open("a", encoding="utf-8") as handle:
                handle.write("\t".join(values) + "\n")
            if not self.sleep_or_stop(self.config.interval):
                break

    def post_process(self) -> None:
        raw = self.config.output_dir / "cpu_freq.dat"
        if not raw.exists():
            return

        rows = [
            line.split()
            for line in raw.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if len(rows) < 2:
            return

        data_rows = rows[1:]
        out = ["CPU\tFrequency"]
        for idx in range(len(data_rows[0])):
            avg = sum(int(row[idx]) for row in data_rows) / len(data_rows)
            out.append(f"{idx}\t{int(avg)}")

        (self.config.output_dir / "cpu_freq_consolidated.dat").write_text(
            "\n".join(out) + "\n",
            encoding="utf-8",
        )


class CPUPowerCollector(Collector):
    name = "cpu_power"
    watts_re = re.compile(r":\s*([-+]?\d+(?:\.\d+)?)\s*W")

    def collect(self) -> None:
        out = self.config.output_dir / "cpu_power.dat"
        for _ in range(self.config.sample_count):
            try:
                result = subprocess.run(
                    ["sensors"],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except (FileNotFoundError, subprocess.CalledProcessError):
                return

            watts = [
                float(match.group(1)) for match in self.watts_re.finditer(result.stdout)
            ]
            timestamp = time.strftime("%H:%M:%S")
            row = [timestamp, *(f"{value:.2f}" for value in watts), f"{sum(watts):.2f}"]
            with out.open("a", encoding="utf-8") as handle:
                handle.write("\t".join(row) + "\n")
            if not self.sleep_or_stop(self.config.interval):
                break


class IOCollector(Collector):
    name = "io"

    def collect(self) -> None:
        self.run_process(
            ["sar", "-b", str(self.config.interval), str(self.config.sample_count)],
            self.config.output_dir / "iotransfer.dat",
        )


class IRQAffinityCollector(Collector):
    name = "irq_affinity"

    def collect(self) -> None:
        interface = self.config.network_interface or default_network_interface()
        if not interface:
            return

        cpu_count = os.cpu_count() or 1
        sums = [0] * cpu_count
        with open("/proc/interrupts", "r", encoding="utf-8") as handle:
            for line in handle:
                if interface.lower() not in line.lower():
                    continue
                parts = line.split()
                for idx, value in enumerate(parts[1 : 1 + cpu_count]):
                    sums[idx] += int(value)

        (self.config.output_dir / "irq.dat").write_text(
            "\t".join(str(value) for value in sums) + "\n",
            encoding="utf-8",
        )


class NetworkCollector(Collector):
    name = "network"

    def collect(self) -> None:
        header = "Time\tIFACE\trxpck/s\ttxpck/s\trxkB/s\ttxkB/s\trxcmp/s\ttxcmp/s\trxmcst/s\t%ifutil\n"
        (self.config.output_dir / "netinterface.dat").write_text(
            header, encoding="utf-8"
        )
        self.run_process(
            [
                "sar",
                "-n",
                "DEV",
                str(self.config.interval),
                str(self.config.sample_count),
            ],
            self.config.output_dir / "netinterface_all.dat",
        )

    def post_process(self) -> None:
        interface = self.config.network_interface or default_network_interface()
        raw = self.config.output_dir / "netinterface_all.dat"
        if not interface or not raw.exists():
            return

        filtered = [
            line
            for line in raw.read_text(encoding="utf-8").splitlines()
            if interface in line and "Average" not in line
        ]
        with (self.config.output_dir / "netinterface.dat").open(
            "a", encoding="utf-8"
        ) as handle:
            handle.write("\n".join(filtered) + ("\n" if filtered else ""))


class NUMAStatCollector(Collector):
    name = "numastat"

    def _snapshot(self, target: str) -> None:
        result = subprocess.run(
            ["numastat"], check=True, capture_output=True, text=True
        )
        lines = result.stdout.splitlines()
        if not lines:
            return
        selected = [f"node_type\t{lines[0]}"]
        selected.extend(line for line in lines[1:] if "_node" in line)
        (self.config.output_dir / target).write_text(
            "\n".join(selected) + "\n", encoding="utf-8"
        )

    def collect(self) -> None:
        if self.config.numastat_disabled:
            return
        self._snapshot("numastat_start.dat")
        self.sleep_or_stop(self.config.interval * self.config.sample_count)

    def post_process(self) -> None:
        if not self.config.numastat_disabled:
            self._snapshot("numastat_end.dat")


class PerfCollector(Collector):
    name = "perf"

    def collect(self) -> None:
        if self.config.perf_disabled or self.config.perf_unavailable:
            return
        total_seconds = self.config.interval * self.config.sample_count
        self.run_process(
            [
                "perf",
                "record",
                "-F",
                str(self.config.perf_frequency),
                "-a",
                "-e",
                "cycles",
                "-o",
                str(self.config.output_dir / "perf.dat"),
                "sleep",
                str(total_seconds),
            ]
        )


class CollectorManager:
    REGISTRY: dict[str, CollectorFactory] = {
        "cpu": CPUCollector,
        "cpu_freq": CPUFreqCollector,
        "cpu_power": CPUPowerCollector,
        "io": IOCollector,
        "irq_affinity": IRQAffinityCollector,
        "network": NetworkCollector,
        "numastat": NUMAStatCollector,
        "perf": PerfCollector,
    }

    def __init__(self, config: CollectorConfig, names: list[str]) -> None:
        enabled = list(self.REGISTRY) if "all" in names else names
        unknown = sorted(set(enabled) - set(self.REGISTRY))
        if unknown:
            raise ValueError(f"unknown collectors: {', '.join(unknown)}")
        self.collectors = [self.REGISTRY[name](config) for name in enabled]

    def start(self) -> None:
        for collector in self.collectors:
            collector.start()

    def stop(self, timeout: float = 10.0, kill_timeout: float = 5.0) -> None:
        for collector in self.collectors:
            collector.stop()

        deadline = time.monotonic() + timeout
        for collector in self.collectors:
            remaining = max(0.0, deadline - time.monotonic())
            collector.join(remaining)

        for collector in self.collectors:
            if collector.is_alive:
                collector.terminate()

        kill_deadline = time.monotonic() + kill_timeout
        for collector in self.collectors:
            remaining = max(0.0, kill_deadline - time.monotonic())
            collector.join(remaining)

        for collector in self.collectors:
            if collector.is_alive:
                collector.kill()

        for collector in self.collectors:
            collector.join()

    @property
    def is_running(self) -> bool:
        return any(collector.is_alive for collector in self.collectors)

    def wait(self) -> None:
        failures: list[str] = []

        for collector in self.collectors:
            collector.join()
            if collector.exitcode not in (0, None):
                failures.append(
                    f"{collector.name}: exited with code {collector.exitcode}"
                )

        if failures:
            raise RuntimeError("collector failures detected:\n" + "\n".join(failures))

    @property
    def pids(self) -> dict[str, int]:
        return {
            collector.name: collector.pid
            for collector in self.collectors
            if collector.pid is not None
        }
