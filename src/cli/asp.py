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
import platform
from importlib.resources import files, as_file
import click

cur_dir = os.getcwd()
package_file = files("cli")


def check_prerequisites(network_interface):
    """
    check prerequisites
    input param: network interface
    """
    if network_interface is None:
        click.echo(
            "Warning: 'network_interface' is not set. IRQ data may be incomplete."
        )
    required_cmds = {
        "sar": [None, "sar does not exist or is not in the PATH. Aborting..."],
        "sensors": [
            "The lm_sensors package does not exist or is not in the PATH. "
            "CPU Power data will not be available.",
        ],
        "numastat": [
            "numastat does not exist or is not in the PATH. "
            "NUMA imbalance data will not be collected.",
        ],
    }

    for cmd, env_data in required_cmds.items():
        if (
            subprocess.call(
                f"command -v {cmd}",
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            != 0
        ):
            click.echo(f"{env_data[0]}")

    if (
        subprocess.call(
            "perf --help",
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        != 0
    ):
        click.echo("perf not found or not working. Skipping perf data.")


def start_collectors(
    collectors,
    interval,
    samples,
    data_dir,
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
    click.echo(f"Data collection for {samples} samples, {interval} second interval")
    system_architecture = platform.machine()
    os.makedirs(data_dir, exist_ok=True)
    for filename in os.listdir(data_dir):
        file_path = os.path.join(data_dir, filename)
        os.remove(file_path)
    current_subprocesses = []
    collectors_path = files("cli.collectors")
    if "all" in collectors:
        collectors = [f.name for f in collectors_path.iterdir() if f.is_file()]
    for index, collector in enumerate(collectors):
        resource = files("cli.collectors") / f"{collector}"
        with as_file(resource) as file_path:
            if "perf" == collector:
                cmd = [
                    "bash",
                    file_path,
                    f"{interval}",
                    f"{samples}",
                    f"{data_dir}",
                    f"{perf_frequency}",
                    f"{perf_disabled}",
                ]
            elif collector in ("irq_affinity", "network"):
                cmd = [
                    "bash",
                    file_path,
                    f"{interval}",
                    f"{samples}",
                    f"{data_dir}",
                    f"{network_interface}",
                ]
            elif "cpu_freq" == collector:
                cmd = [
                    "bash",
                    file_path,
                    f"{interval}",
                    f"{samples}",
                    f"{data_dir}",
                    f"{system_architecture}",
                ]
            else:
                cmd = ["bash", file_path, f"{interval}", f"{samples}", f"{data_dir}"]
            current_subprocesses.append(subprocess.Popen(cmd, preexec_fn=os.setsid))
    print_progress_bar(interval * samples)

    # Wait for collectors to finish
    try:
        for process in current_subprocesses:
            time.sleep(3)
            # Send SIGINT to the entire process group
            os.killpg(os.getpgid(process.pid), signal.SIGINT)
            process.wait()
    except subprocess.CalledProcessError as e:
        print("Error occurred:")
        print("stdout:", e.stdout)
        print("stderr:", e.stderr)
    click.echo("Done!")
    clean_up(plot_disabled, data_dir)


def print_progress_bar(total_seconds):
    """
    print progress bar
    input param: total seconds
    """

    steps = 10
    iter_time = total_seconds // steps
    for i in range(steps + 1):
        hashes = "#" * i
        spaces = " " * (steps - i)
        percent = i * 10
        print(
            f"\rWaiting for data collectors to complete... [ {hashes}{spaces} ] {percent} %",
            end="",
        )
        time.sleep(iter_time)


def clean_up(plot_disabled, data_dir):
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
            arguments = ["-o", f"{data_dir}"]
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
    plot_disabled_flag=False,
    perf_frequency=None,
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
        data_dir = os.path.abspath(os.path.join(cur_dir, "data"))
    # Start Collector
    start_collectors(
        collector_arr,
        sample_interval,
        number_of_samples,
        data_dir,
        perf_freq,
        plot_disabled,
        network_interface,
        perf_disabled,
    )


if __name__ == "__main__":
    main()
