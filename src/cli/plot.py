###########################################################################
# Copyright (c) 2025, Ampere Computing LLC
#
# SPDX-License-Identifier: BSD-3-Clause
# License terms can be found in the LICENSE.TXT file at the root of this project.
###########################################################################

"""
plot.py to plot the asp output
"""
import os
import logging
import shlex
import subprocess
import platform
from argparse import ArgumentParser
import plotly.graph_objects as go
import pandas as pd
from plotly.subplots import make_subplots
import plotly.express as px

all_graphs = []
all_df = []
system_architecture = platform.machine()
logger = logging.getLogger()


def is_debian():
    """
    Checks if the operating system is Debian
    """
    # First, check if the system is Linux
    if platform.system() == "Linux":
        try:
            # Read the contents of the /etc/os-release file
            with open("/etc/os-release", "r", encoding="utf-8") as f:
                content = f.read()
                if "ID_LIKE=debian" in content or "ID=debian" in content:
                    return True
        except FileNotFoundError:
            # The file doesn't exist, so it's not a modern Linux system
            pass
    return False


def setup_logger(output_directory, level="info"):
    """
    Configure and return a logger instance for the application.

    Sets up logging with both console (StreamHandler) and file output (FileHandler).
    Log messages include timestamps, severity levels, and messages.
    The default log file is named 'asp.log'.

    Args:
        level (str): Logging level. Accepts "info" (default) or "debug".

    Returns:
        logging.Logger: Configured logger instance.
    """
    dir_name = ""
    if output_directory is None:
        dir_name = "./data"
    else:
        dir_name = output_directory
    logging.basicConfig(
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(f"{dir_name}/asp.log")],
    )
    logger_local = logging.getLogger()
    if level == "debug":
        logger_local.setLevel(logging.DEBUG)
    else:
        logger_local.setLevel(logging.INFO)
    return logger_local


def create_df_from_data(data):
    """
    Convert raw CPU utilization lines into a structured pandas DataFrame.

    Parses timestamped CPU utilization data from a list of strings,
    filters out header lines (e.g., lines containing "CPU"), cleans up
    time annotations (e.g., "AM", "PM"), and converts relevant columns
    to floats. Calculates actual utilization as `100 - idle`.

    Args:
        data (list of str): List of raw text lines containing CPU metrics.

    Returns:
        pd.DataFrame: A DataFrame with columns:
            ["timestamp", "cpu#", "usr", "nice", "sys", "iowait", "steal", "total_util"],
            where `total_util` is adjusted to represent actual CPU usage.
    """
    header = [
        "timestamp",
        "cpu#",
        "usr",
        "nice",
        "sys",
        "iowait",
        "steal",
        "total_util",
    ]
    df = pd.DataFrame(columns=header)
    cnt = 0
    for line in data:
        if "CPU" not in line:
            line = line.replace("AM", "")
            line = line.replace("PM", "")
            col = line.split()
            df.loc[cnt] = col
            cnt += 1

    df["total_util"] = df["total_util"].astype(float)
    df["usr"] = df["usr"].astype(float)
    df["sys"] = df["sys"].astype(float)
    df["total_util"] = 100 - df["total_util"]  # 100 - idle
    logger.debug("created dataframe from data successfully")
    logger.debug(df)
    return df


def create_graphs_from_df_all_cpu(df, title):
    """
    Generate line graphs for per-CPU utilization from the provided DataFrame.

    Filters out the aggregated "all" CPU row and creates individual line plots
    for each physical/logical CPU present in the data. Each graph shows total,
    user, and system CPU utilization over time.

    Args:
        df (pd.DataFrame): Input DataFrame containing CPU usage metrics with columns:
                           ["cpu#", "timestamp", "total_util", "usr", "sys"]
        title (str): Title prefix to use for each CPU graph.

    Returns:
        None. Generated Plotly figures are appended to the global `all_graphs` list.
    """
    df = df.loc[df["cpu#"] != "all"]
    for cpu in range(int(cpus)):
        all_df.append(df.loc[df["cpu#"] == str(cpu)])

    for df_local in all_df:
        fig = px.line(
            df,
            y=[df_local["total_util"], df_local["usr"], df_local["sys"]],
            x=df_local["timestamp"],
            title=f'{title+" cpu# "+df["cpu#"].iloc[0]}',
            render_mode="lines",
        )
        all_graphs.append(fig)
    logger.debug("created graphs with all core util data")


def generate_graph(output_directory):
    """
    Generate a multi-panel Plotly figure for the ASP performance report.

    Creates a grid of subplots organized into 5 rows and 2 columns to visualize various system
    performance metrics such as:
        - CPU Utilization
        - Per-Core Utilization
        - CPU+IO Power
        - CPU Frequencies
        - Disk I/O
        - NUMA Statistics
        - Network Utilization
        - Top CPU Hotspots (as a table)
        - Interrupt Queue Mapping

    The layout includes appropriate subplot titles, shared X-axes for aligned time series,
    and different plot types (line and table). The figure is intended to be populated
    with traces elsewhere in the application.

    """
    power = "CPU+IO Power"
    if system_architecture == "x86_64" or system_architecture == "AMD64":
        power = "CPU Power"
    logger.info("Generating graphs for ASP report")

    fig = make_subplots(
        rows=5,
        cols=2,
        shared_xaxes="columns",
        subplot_titles=(
            "<b>CPU Utilization</b>",
            "<b>Per-Core Utilization</b>",
            f"<b>{power}</b>",
            "<b>CPU Frequencies</b>",
            "<b>Disk I/O</b>",
            "<b>NUMA Stats</b>",
            "<b>Network Utilization</b>",
            "<b>Top CPU Hotspots</b>",
        ),
        vertical_spacing=0.07,
        specs=[
            [{"type": "xy"}, {"type": "xy"}],
            [{"type": "xy"}, {"type": "xy"}],
            [{"type": "xy"}, {"type": "xy"}],
            [{"type": "xy"}, {"type": "table"}],
            [{"type": "xy"}, None],
        ],
    )

    try:
        # cpu
        dir_name = ""
        if output_directory is None:
            dir_name = "./data"
        else:
            dir_name = output_directory

        cpu_util_df = pd.read_csv(
            f"{dir_name}/cpu.dat", header=1, sep=r"\s+"
        )  # usecols=[0,2,4])

        cpu_util_df = cpu_util_df.rename(columns={cpu_util_df.columns[0]: "Timestamp"})
        cpu_util_df["Timestamp"] = pd.to_datetime(
            cpu_util_df["Timestamp"], format="%H:%M:%S", errors="coerce"
        )
        start_time = cpu_util_df["Timestamp"].min()
        cpu_util_df["Elapsed_Seconds"] = (
            cpu_util_df["Timestamp"] - start_time
        ).dt.total_seconds()
        x_axis_data = cpu_util_df["Elapsed_Seconds"]

        user_time = go.Scatter(x=x_axis_data, y=cpu_util_df["%user"], name="%User")
        sys_time = go.Scatter(x=x_axis_data, y=cpu_util_df["%system"], name="%System")
        iowait_time = go.Scatter(
            x=x_axis_data, y=cpu_util_df["%iowait"], name="%IOWait"
        )
        fig.add_trace(user_time, row=1, col=1)
        fig.add_trace(sys_time, row=1, col=1)
        fig.add_trace(iowait_time, row=1, col=1)
        logger.info("CPU charts added to trace")
    except IOError as e:
        logger.error("could not find cpu.dat. Skipping CPU charts")
        logger.exception(e)

    try:
        # per-CPU utilization
        cpu_consolidated_df = pd.read_csv(
            f"{dir_name}/cpu_consolidated.dat", header=0, sep=r"\s+"
        )
        cpu_ind_usr_util = go.Bar(
            x=cpu_consolidated_df["CPU"],
            y=cpu_consolidated_df["%user"],
            name="Per-core User Utilization %",
        )
        cpu_ind_sys_util = go.Bar(
            x=cpu_consolidated_df["CPU"],
            y=cpu_consolidated_df["%system"],
            name="Per-core System Utilization %",
        )
        fig.add_trace(cpu_ind_usr_util, row=1, col=2)
        fig.add_trace(cpu_ind_sys_util, row=1, col=2)
        logger.info("CPU per core utilization added to trace")

        cpu_freq_consolidated_df = pd.read_csv(
            f"{dir_name}/cpu_freq_consolidated.dat", header=0, sep=r"\s+"
        )
        cpu_freq = go.Bar(
            x=cpu_freq_consolidated_df["CPU"],
            y=cpu_freq_consolidated_df["Frequency"] / 1000,
            name="Per-core Frequency",
        )
        fig.add_trace(cpu_freq, row=2, col=2)
        logger.info("CPU freq added to trace")

    except IOError as e:
        logger.error(
            "could not find cpu_consolidated.dat."
            " Skipping individual CPU utilization charts"
        )
        logger.exception(e)

    try:
        # Disk
        disk_df = pd.read_csv(f"{dir_name}/iotransfer.dat", header=1, sep=r"\s+")

        # Conversion: (KB/s * 0.5) / 1024 = MB/s
        conversion_factor = 0.5 / 1024.0

        cpu_util_df = cpu_util_df.rename(columns={cpu_util_df.columns[0]: "Timestamp"})

        # Convert the 'Timestamp' column to datetime objects
        cpu_util_df["Timestamp"] = pd.to_datetime(
            cpu_util_df["Timestamp"], format="%H:%M:%S", errors="coerce"
        )

        # Calculate Elapsed Seconds (Relative Time)
        start_time = cpu_util_df["Timestamp"].min()
        cpu_util_df["Elapsed_Seconds"] = (
            cpu_util_df["Timestamp"] - start_time
        ).dt.total_seconds()

        # Define the x-axis data variable
        x_axis_data = cpu_util_df["Elapsed_Seconds"]

        disk_read = go.Scatter(
            x=x_axis_data,
            y=disk_df["bread/s"]
            * conversion_factor,  # Division by 1024 converts KB to MB
            name="MBytes read/sec",
        )

        disk_write = go.Scatter(
            x=x_axis_data,
            y=disk_df["bwrtn/s"]
            * conversion_factor,  # Division by 1024 converts KB to MB
            name="MBytes written/sec",
        )

        fig.add_trace(disk_read, row=3, col=1)
        fig.add_trace(disk_write, row=3, col=1)
        logger.info("Disk read/write added to trace")

    except IOError as e:
        logger.error("could not find iotransfer.dat. Skipping I/O charts")
        logger.error(e)

    try:
        # network
        network_df = pd.read_csv(f"{dir_name}/netinterface.dat", header=0, sep=r"\s+")

        cpu_util_df = cpu_util_df.rename(columns={cpu_util_df.columns[0]: "Timestamp"})

        # Convert the 'Timestamp' column to datetime objects
        cpu_util_df["Timestamp"] = pd.to_datetime(
            cpu_util_df["Timestamp"], format="%H:%M:%S", errors="coerce"
        )

        # Calculate Elapsed Seconds (Relative Time)
        start_time = cpu_util_df["Timestamp"].min()
        cpu_util_df["Elapsed_Seconds"] = (
            cpu_util_df["Timestamp"] - start_time
        ).dt.total_seconds()

        # Define the x-axis data variable
        x_axis_data = cpu_util_df["Elapsed_Seconds"]

        rx = go.Scatter(
            x=x_axis_data,
            y=network_df["rxkB/s"]
            * conversion_factor,  # conversion factor to change KB/s to GiB/s
            name="Receive GiB/sec",
        )

        tx = go.Scatter(
            x=x_axis_data,
            y=network_df["txkB/s"]
            * conversion_factor,  # conversion factor to change KB/s to GiB/s
            name="Transmit GiB/sec",
        )
        fig.add_trace(rx, row=4, col=1)
        fig.add_trace(tx, row=4, col=1)
        logger.info("network bandwidth added to trace")
    except IOError as e:
        logger.error("could not find netinterface.dat. Skipping network charts")
        logger.exception(e)

    try:
        # perf
        if os.path.exists(f"{dir_name}/perf.dat"):
            perf_dat = f"{shlex.quote(dir_name)}/perf.dat"
            perf_out = f"{shlex.quote(dir_name)}/perf.out"

            awk_script = r"""
            (!/^#/ && !/^$/){
                sub(/%/, "", $1);
                if($1 >= 2) {
                    x=x+$1;
                    printf("%s\t%s\t%s\t%s\n", $1, $2, $3, $5);
                }
            }
            END {
                printf("%s\t%s\n", 100 - x, "Other")
            }
            """

            perf_cmd = f"""
            perf report -i {perf_dat} | awk '{awk_script}' > {perf_out}
            """

            subprocess.run(perf_cmd, check=True, shell=True)
        perf_out = pd.read_csv(f"{dir_name}/perf.out", header=None, sep=r"\s+")
        # Overhead  Command "Shared Object" Symbol
        perf = go.Table(
            header={
                "values": ["%cycles", "Command", "Shared Object", "Symbol"],
                "align": "left",
            },
            cells={
                "values": [
                    perf_out.iloc[:, 0],
                    perf_out.iloc[:, 1],
                    perf_out.iloc[:, 2],
                    perf_out.iloc[:, 3],
                ],
                "align": "left",
            },
        )
        fig.add_trace(perf, row=4, col=2)
        logger.info("perf hotspot data added to trace")
    except IOError as e:
        logger.error("could not find perf data. Skipping hotspot table")
        logger.exception(e)
    except IndexError as e:
        logger.error("parse perf data failed. Skipping hotspot table")
        logger.exception(e)

    # CPU power
    try:
        # Read the CPU Power data

        max_power_value = 100.0  # Default max power value if file reading fails

        cpu_power_df = pd.read_csv(f"{dir_name}/cpu_power.dat", header=None, sep=r"\s+")
        num_sockets = len(cpu_power_df.columns)

        # Rename the first column for clarity
        cpu_util_df = cpu_util_df.rename(columns={cpu_util_df.columns[0]: "Timestamp"})

        # Convert the 'Timestamp' column to datetime objects
        cpu_util_df["Timestamp"] = pd.to_datetime(
            cpu_util_df["Timestamp"], format="%H:%M:%S", errors="coerce"
        )

        # Calculate Elapsed Seconds (Relative Time)
        start_time = cpu_util_df["Timestamp"].min()
        cpu_util_df["Elapsed_Seconds"] = (
            cpu_util_df["Timestamp"] - start_time
        ).dt.total_seconds()

        # Define the x-axis data variable
        x_axis_data = cpu_util_df["Elapsed_Seconds"]

        # --- Traces ---
        if is_debian():
            cpu_power = go.Scatter(
                x=x_axis_data,
                y=cpu_power_df.iloc[:, 1],
                name="CPU Power",
            )
            fig.add_trace(cpu_power, row=2, col=1)
        else:
            if system_architecture == "x86_64" or system_architecture == "AMD64":
                cpu_power = go.Scatter(
                    x=x_axis_data,
                    y=cpu_power_df.iloc[:, 1],
                    name="CPU Power",
                )
                fig.add_trace(cpu_power, row=2, col=1)
            else:
                cpu_power = go.Scatter(
                    x=x_axis_data,
                    y=cpu_power_df.iloc[:, 1],
                    name="CPU Power",
                )
                fig.add_trace(cpu_power, row=2, col=1)
                io_power = go.Scatter(
                    x=x_axis_data,
                    y=cpu_power_df.iloc[:, 2],
                    name="IO Power",
                )
                fig.add_trace(io_power, row=2, col=1)
                total_power = go.Scatter(
                    x=x_axis_data,
                    y=cpu_power_df.iloc[:, 3],
                    name="Total Power",
                )
                fig.add_trace(total_power, row=2, col=1)

        # Define which columns contain power data (starting from index 1)
        power_cols_to_check = cpu_power_df.columns[1:num_sockets]

        # Safely calculate the max value across all relevant power columns
        # We use .max().max() to get a single scalar from the DataFrame slice.
        current_max = cpu_power_df[power_cols_to_check].max(numeric_only=True).max()

        # Update the global max_power_value if the reading was successful
        # This value will be used by the update_yaxes call AFTER the try block
        if pd.notna(current_max) and current_max > max_power_value:
            # Use a small buffer (5%)
            max_power_value = current_max * 1.05

        fig.update_yaxes(
            title_text="Power(W)",
            range=[0, max_power_value],  # y-axis start at 0
            row=2,
            col=1,
        )

    except IOError as e:
        logger.error("Could not find cpu_power.dat. Skipping CPU Power chart")
        logger.exception(e)

    # numastat
    try:
        numa_df1 = pd.read_csv(f"{dir_name}/numastat_start.dat", header=0, sep=r"\s+")
        numa_df2 = pd.read_csv(f"{dir_name}/numastat_end.dat", header=0, sep=r"\s+")
        num_numa_nodes = len(numa_df1.columns) - 1
        for x in range(num_numa_nodes):
            diff = numa_df2["node" + str(x)] - numa_df1["node" + str(x)]
            # Filter out zero values
            non_zero_mask = diff != 0
            filtered_x = numa_df1.iloc[:, 0][non_zero_mask]
            filtered_y = diff[non_zero_mask]
            # Only plot if there's at least one non-zero value
            if not filtered_y.empty:
                numa_node = go.Bar(
                    x=filtered_x,
                    y=filtered_y,
                    name=f"Node{x} NUMA stats",
                )
                fig.add_trace(numa_node, row=3, col=2)
    except IOError as e:
        logger.error("Could not find numastat.dat. Skipping NUMA imbalance chart")
        logger.exception(e)

    fig.update_xaxes(
        title_text="Timestamp",
        row=1,
        col=1,
        showticklabels=True,
        tickangle=-45,
        nticks=20,
    )
    fig.update_yaxes(title_text="%Utilization", range=[0, 100], row=1, col=1)

    fig.update_xaxes(
        title_text="CPU_num", row=1, col=2, showticklabels=True, tickangle=0, nticks=20
    )
    fig.update_yaxes(title_text="Per-core %Utilization", range=[0, 100], row=1, col=2)

    fig.update_xaxes(
        title_text="Timestamp",
        row=2,
        col=1,
        showticklabels=True,
        tickangle=-45,
        nticks=20,
    )

    fig.update_xaxes(
        title_text="CPU_num", row=2, col=2, showticklabels=True, tickangle=0, nticks=20
    )
    fig.update_yaxes(
        title_text="Average CPU Frequency (MHz)", row=2, col=2, tickformat=".1f"
    )

    fig.update_xaxes(
        title_text="Timestamp",
        row=3,
        col=1,
        showticklabels=True,
        tickangle=-45,
        nticks=20,
    )
    fig.update_yaxes(title_text="I/O (MB/sec)", row=3, col=1)

    fig.update_xaxes(
        title_text="Timestamp",
        row=4,
        col=1,
        showticklabels=True,
        tickangle=-45,
        nticks=20,
    )
    fig.update_yaxes(title_text="Network I/O (Gib/sec)", row=4, col=1)

    fig.update_layout(
        title={
            "text": "<b>Ampere System Profiler</b>",
            "font": {"color": "#f63823", "size": 24},
        },
        height=2000,
        autosize=True,
    )
    try:
        fig.write_html(f"{dir_name}/report.html", auto_open=False)
        logger.info("Collection complete. Output => report.html")
    except Exception as e:
        logger.exception(e)


def plot_all_core_util():
    """
    Generate and save an HTML report of CPU core utilization over time.

    This function:
      - Reads CPU summary data from 'data/cpu_all.dat'
      - Extracts metadata like kernel version, hostname, and number of CPUs
      - Parses the data and creates line plots for each CPU core
      - Arranges all plots in a grid using Plotly subplots
      - Saves the result as 'all_core_util.html'

    The function logs progress and errors using the global `logger`.

    Global Variables Used:
        cpus (str): Number of CPU cores (extracted from input file)
        all_graphs (list): Populated with individual Plotly figure objects
        all_df (list): DataFrames for each core's data

    Raises:
        Logs and handles any exceptions encountered during file reading,
        data processing, or plotting.
    """
    try:
        with open("data/cpu_all.dat", "r", encoding="utf-8") as inp:
            global cpus
            server = inp.readline().split()
            kernel, host, date_run, cpus = server[1], server[2], server[3], server[5]
            cpus = cpus[1:]  # get only digits
            page_title = kernel + ":" + host + ":" + date_run
            logger.debug("CPU: %s", cpus)
            logger.debug(page_title)
            targets = [
                line
                for line in inp
                if "Average" not in line and len(line) > 2 and line[-2].isdigit()
            ]
        df = create_df_from_data(targets)
        create_graphs_from_df_all_cpu(df, "cpu-util")
        cols = 3
        rows = (len(all_graphs) + cols - 1) // cols
        fig = make_subplots(
            rows=rows,
            cols=cols,
            subplot_titles=[f"cpu {i}" for i in range(len(all_df))],
            horizontal_spacing=0.05,
        )
        for i, fig_data in enumerate(all_graphs, start=1):
            row = (i - 1) // cols + 1
            col = (i - 1) % cols + 1
            for trace in fig_data.data:
                if i > 1:
                    # Don't show duplicate legends
                    trace.showlegend = False
                fig.add_trace(trace, row=row, col=col)
        fig.update_layout(
            width=2500,
            height=8000,
        )
        fig.update_traces(legendgroup=True)
        fig.update_layout(font={"size": 16})
        fig.update_layout(margin={"l": 50, "r": 50, "t": 100, "b": 50})
        fig.update_yaxes(range=[0, 100])
        fig.update_xaxes(showticklabels=False)
        fig.update_layout(
            title={
                "text": "<b> Ampere System Profiler:" " all core utilization </b>",
                "font": {"color": "#f63823", "size": 24},
            },
            autosize=True,
            title_x=0.05,
            title_y=0.995,
        )
        fig.write_html("all_core_util.html", auto_open=False)
        logger.info(
            "Plotting per cpu utilization completed, plot saved in file all_core_util.html"
        )
    except Exception as e:
        logger.error("Error creating all core utilization")
        logger.exception(e)


# ======================
# MAIN
# ======================

if __name__ == "__main__":
    parser = ArgumentParser(
        description="Ampere System Profiler:"
        " plot CPU-utilization, "
        " power,"
        " CPU-freq,"
        " Network,"
        " IRQs and I/O"
    )
    parser.add_argument(
        "-o", "--output_directory", default=None, help="save plot ustilization charts"
    )
    parser.add_argument(
        "-ACU",
        "--allcoreutil",
        default=None,
        action="store_true",
        help="plot utilization charts for all cores on the system",
    )
    parser.add_argument(
        "-d",
        "--debug",
        default=None,
        action="store_true",
        help="plot utilization charts for all cores on the system",
    )
    args = parser.parse_args()
    LOG_LEVEL = "info"
    if args.debug:
        LOG_LEVEL = "debug"
    logger = setup_logger(args.output_directory, LOG_LEVEL)
    generate_graph(args.output_directory)

    if args.allcoreutil:
        plot_all_core_util()
