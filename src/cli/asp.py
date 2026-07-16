###########################################################################
# Copyright (c) 2025, Ampere Computing LLC
#
# SPDX-License-Identifier: BSD-3-Clause
# License terms can be found in the LICENSE.TXT file at the root of this project.
###########################################################################

"""
A command-line tool for collecting system performance metrics such as CPU usage,
memory, disk I/O, and network statistics. Supports configurable sampling intervals,
custom collector sets, and optional plotting of results.
"""

import os
import subprocess
import time
import signal
import sys
from pathlib import Path
from importlib.resources import files
from cli.collectors.collectors import CollectorConfig, CollectorManager
import click

cur_dir = os.getcwd()
package_file = files("cli")
current_manager: CollectorManager | None = None


def subprocess_sighandler(plot_disabled, result_data_dir):
    """
    Subprocess Signal Handler
    """
    global current_manager
    try:
        if current_manager is not None:
            current_manager.stop(timeout=10.0)
    except Exception as e:
        print(f"Error occurred while stopping collectors: {e}")
    click.echo("Done!")
    clean_up(plot_disabled, result_data_dir)


def make_cleanup_handler(plot_disabled, result_data_dir):
    """
    Cleanup Handler for subprocesses
    """

    def cleanup_handler(_signum, _frame):
        print("Cleaning up")
        subprocess_sighandler(plot_disabled, result_data_dir)
        sys.exit(0)

    return cleanup_handler


def check_prerequisites(network_interface):
    """
    check prerequisites
    input param: network interface
    """
    if network_interface is None:
        click.echo(
            "Warning: 'network_interface' is not set. IRQ data may be incomplete."
        )

    if (
        subprocess.call(
            "command -v sar",
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        != 0
    ):
        click.echo("sar does not exist or is not in the PATH. Aborting...", err=True)
        sys.exit(1)

    required_cmds = {
        "sensors": (
            "The lm_sensors package does not exist or is not in the PATH. "
            "CPU Power data will not be available."
        ),
        "numastat": (
            "numastat does not exist or is not in the PATH. "
            "NUMA imbalance data will not be collected."
        ),
    }

    for cmd, message in required_cmds.items():
        if (
            subprocess.call(
                f"command -v {cmd}",
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            != 0
        ):
            click.echo(message)


def start_collectors(
    collectors,
    interval,
    samples,
    result_data_dir,
    perf_frequency,
    plot_disabled,
    network_interface,
    perf_disabled,
):
    """
    Start the specified system performance collectors.

    This function initializes and runs the given collectors for monitoring system
    performance metrics like CPU, memory, disk, network, etc. It collects data at
    the specified interval for a fixed number of samples, stores it in the provided
    directory, and optionally controls plotting and performance collection options.

    Args:
        collectors (list): List of collector names to start (e.g., ["cpu", "mem"]).
        interval (int or float): Time interval in seconds between each sample.
        samples (int): Total number of samples to collect.
        data_dir (str): Directory path where collected data will be saved.
        perf_frequency (int): Frequency setting for the 'perf' collector (e.g., 4000 Hz).
        plot_disabled (int): Set to 1 to disable plotting, 0 to enable.
        network_interface (str): Network interface to monitor (e.g., "eth0").

    Returns:
        None
    """
    global current_manager
    click.echo(f"Data collection for {samples} samples, {interval} second interval")
    os.makedirs(result_data_dir, exist_ok=True)
    for filename in os.listdir(result_data_dir):
        file_path = os.path.join(result_data_dir, filename)
        os.remove(file_path)

    perf_unavailable = (
        subprocess.call(
            "perf --help",
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        != 0
    )

    sensors_unavailable = (
        subprocess.call(
            "command -v sensors",
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        != 0
    )

    numastat_disabled = (
        subprocess.call(
            "command -v numastat",
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        != 0
    )

    enabled_collectors = list(collectors)

    if "all" in enabled_collectors:
        enabled_collectors = list(CollectorManager.REGISTRY)

    if sensors_unavailable:
        enabled_collectors = [c for c in enabled_collectors if c != "cpu_power"]

    if numastat_disabled:
        enabled_collectors = [c for c in enabled_collectors if c != "numastat"]

    if perf_unavailable and not perf_disabled:
        click.echo("perf not found or not working. Skipping perf data.")

    if perf_unavailable or perf_disabled:
        enabled_collectors = [c for c in enabled_collectors if c != "perf"]

    if not enabled_collectors:
        click.echo(
            f"No requested collectors are available after prerequisite checks: {', '.join(collectors)}",
            err=True,
        )
        sys.exit(1)

    config = CollectorConfig(
        interval=interval,
        sample_count=samples,
        output_dir=Path(result_data_dir),
        network_interface=network_interface,
        perf_frequency=perf_frequency,
        perf_disabled=bool(perf_disabled),
        perf_unavailable=perf_unavailable,
        numastat_disabled=numastat_disabled,
    )

    click.echo(f"Enabled collectors: {', '.join(enabled_collectors)}")
    current_manager = CollectorManager(config, enabled_collectors)
    current_manager.start()

    click.echo(f"Collector PIDs: {current_manager.pids}")
    total_time = interval * samples
    print_progress_bar(total_time, current_manager)

    try:
        current_manager.wait()
    except RuntimeError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)

    clean_up(plot_disabled, result_data_dir)


def print_progress_bar(total_seconds, manager: CollectorManager):
    """
    Print progress while collectors are still running.
    Stop early if they complete or fail before the scheduled duration.
    """

    steps = 10
    start = time.monotonic()

    while True:
        elapsed = time.monotonic() - start
        progress = 1.0 if total_seconds <= 0 else min(elapsed / total_seconds, 1.0)
        filled = int(progress * steps)
        hashes = "#" * filled
        spaces = " " * (steps - filled)
        percent = int(progress * 100)

        print(
            f"\rWaiting for data collectors to complete... [ {hashes}{spaces} ] {percent} %",
            end="",
            flush=True,
        )

        if not manager.is_running or progress >= 1.0:
            break

        time.sleep(0.5)

    print()


def clean_up(plot_disabled, result_data_dir):
    """
    Perform cleanup operations after test termination and optionally generate report.

    This function:
      - Displays a cleanup message.
      - If plotting is enabled, runs the `plot.py` script to generate a report (e.g., report.html).
      - If a network interface was configured, restores the default value in the
        default ASP properties file.

    Args:
        plot_disabled (int): If 0, enables plotting and runs the report generation script.
        network_interface (str or None): Network interface used during collection. If not None,
                                         its value is reset in the properties file.

    Returns:
        None. The function exits the program using sys.exit(0).
    """
    click.echo("\nTest Terminated. Cleaning up...")
    time.sleep(2)
    if plot_disabled == 0:
        try:
            # package_file = files("cli")
            arguments = ["-o", f"{result_data_dir}"]
            plot_file_path = package_file / "plot.py"
            result = subprocess.run(
                ["python", f"{plot_file_path}"] + arguments,
                check=True,
                capture_output=True,
                text=True,
            )
            print("Success:", result.stdout)
        except subprocess.CalledProcessError as e:
            print("Error occurred:")
            print("stdout:", e.stdout)
            print("stderr:", e.stderr)
    sys.exit(0)


@click.command()
@click.option(
    "-n",
    "--number_of_samples",
    type=int,
    default=None,
    help="Number of samples to take",
)
@click.option(
    "-i", "--sample_interval", type=int, default=None, help="Sample interval in seconds"
)
@click.option("-o", "--data_dir", type=str, default=None, help="Data directory")
@click.option(
    "-c",
    "--collector",
    type=str,
    default=None,
    help="Comma-separated list of collectors",
)
@click.option(
    "-f", "--perf_disabled_flag", is_flag=True, default=False, help="Disable PERF"
)
@click.option(
    "-p", "--plot_disabled_flag", is_flag=True, default=False, help="Disable plot"
)
@click.option("-F", "--perf_frequency", type=int, default=None, help="Perf Frequency")
@click.option(
    "-N", "--network_interface", type=str, default=None, help="Network Interface"
)
def main(
    number_of_samples=None,
    sample_interval=None,
    collector=None,
    perf_disabled_flag=False,
    perf_frequency=None,
    plot_disabled_flag=False,
    network_interface=None,
    data_dir=None,
):
    """
    Main entry point to initiate system metrics collection.

    This function checks for prerequisites, optionally prompts the user for missing
    arguments, configures environment variables, and starts the requested data collectors.

    Args:
        number_of_samples (int, optional): Number of samples to collect. If None,
        user is prompted.
        sample_interval (float, optional): Interval (in seconds) between samples.
        If None, user is prompted.
        data_dir (str, optional): Directory path to store collected data. If None,
         defaults are used.
        collector (str, optional): Comma-separated list of collectors to run
        (e.g., "cpu,mem").
        perf_disabled_flag (bool): If True, disables performance-related data collection.
        plot_disabled_flag (bool): If True, disables plotting or visualization steps.
        help_flag (bool): If True, prints usage instructions and exits.
        perf_frequency (int, optional): Frequency setting for perf collector.
        Defaults to 4000 if None.
        network_interface (str, optional): Network interface to monitor (e.g., "eth0").

    Returns:
        None
    """
    collector_arr = ["all"]
    check_prerequisites(network_interface)
    if number_of_samples is None:
        number_of_samples = click.prompt(
            "Please specify the number of samples to take", type=int
        )
    if sample_interval is None:
        sample_interval = click.prompt(
            "Please specify the sample interval (take sample every X seconds)",
            type=int,
        )
    if collector is not None:
        collector_arr = [c.strip() for c in collector.split(",") if c.strip()]

    # Handle PERF_DISABLED environment variable
    perf_disabled = 1 if perf_disabled_flag else 0

    # Plot disabled flag
    plot_disabled = 1 if plot_disabled_flag else 0
    # define frequency
    perf_freq = 0
    if perf_frequency is None:
        perf_freq = 4000
    else:
        perf_freq = perf_frequency

    # check for data_dir
    if data_dir is None:
        result_data_dir = os.path.abspath(os.path.join(cur_dir, "data"))
    else:
        result_data_dir = data_dir

    signal.signal(signal.SIGTERM, make_cleanup_handler(plot_disabled, result_data_dir))
    signal.signal(signal.SIGINT, make_cleanup_handler(plot_disabled, result_data_dir))

    # Start Collector
    start_collectors(
        collector_arr,
        sample_interval,
        number_of_samples,
        result_data_dir,
        perf_freq,
        plot_disabled,
        network_interface,
        perf_disabled,
    )


if __name__ == "__main__":
    main()
