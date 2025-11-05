# Ampere System Profiler

The Ampere System Profiler (ASP) is a system-level analysis profiler that can be used to look for common platform-level problems while running workloads. It also includes a visualizer in the form of Plotly graphs and tables in an HTML report.
ASP can be used for workload characterization at a system level, a first step towards a balanced platform. 

## System pre-Requisites
Required Commands
 - sar
 - sensors
 - route
 - numastat
 - perf
 - python3
  
YUM Packages for RHEL based systems:
```shell
sudo yum install lm_sensors perf sysstat numactl net-tools python3
```
 
APT Packages for Ubuntu or Debian:
```shell
sudo apt install lm-sensors sysstat numactl net-tools linux-tools-common linux-tools-$(uname -r) python3
```

Python Modules:
```shell
sudo python3 -m pip install plotly pandas argparse
```

## Output
ASP will generate a html format report under the root directory of ASP.   
The report includes:  
- CPU Utilization
- Per-Core Utilization
- CPU Power
- CPU Frequencies
- Disk I/O
- Network Utilization
- NUMA Stats
- Top CPU Hotspots

## Getting Started

### 1. Clone the Repository

## 2. Run Setup
```bash
source setup.sh
```

## Building the Wheel
This project uses Poetry for packaging and dependency management.

### Step 1: Build the Wheel
```bash
poetry build
```
This will generate a .whl file and .tar.gz source distribution in the dist/ directory.

## Installing the Package Locally
After building the wheel:

```bash
pip install dist/system_metrics_collector-<version>-py3-none-any.whl
```
Replace <version> with the actual version number shown in the wheel filename.

## Usage
```bash
asp [OPTIONS]
```

### Examples

#### Output Help Message
```bash
asp --help
```

#### Sample Commands

```bash
#Supported Collectors:
#cpu,cpu_freq,cpu_power,io,irq_affinity,network,numastat,perf

# generate 20 samples at 2 seconds interval, all collectors
asp -n 20 -i 2 -N $NETWORK_INTERFACE

# generate 20 samples at 1 seconds interval, only collect cpu utilization,cpu_freq and cpu_power
asp -n 20 -i 1 -c cpu,cpu_freq,cpu_power


# generate 20 samples at 2 seconds interval, all collectors execept perf 
asp -n 20 -i 2 -f


# generate 20 samples at 1 seconds interval, only collect cpu utilization, cpu_freq, io, network, and perf with lower frequency rate of 99
asp -n 20 -i 1 -c cpu,cpu_freq,io,network,perf -F 99
```

## CLI Options
| Option       | Description                                                |
| ------------ | ---------------------------------------------------------- |
| `-n INTEGER` | Number of samples to take                                  |
| `-i INTEGER` | Interval in seconds between samples                        |
| `-o TEXT`    | Output directory for collected data                        |
| `-c TEXT`    | Comma-separated list of collectors to use                  |
| `-f`         | Disable `perf` collection                                  |
| `-p`         | Disable plotting of results                                |
| `-F INTEGER` | Sampling frequency for `perf` collector (default: 4000 Hz) |
| `-N TEXT`    | Network interface to monitor (e.g., eth0)                  |
| `-h, --help` | Show help message and exit                                 |

## Output
 - Data is stored as .dat files in the specified output directory.
 - If plotting is enabled, an report.html file is generated after collection.

## Tested on
 - Ubuntu 20.04
 - Ubuntu 22.04
 - Ubuntu 24.04
 - Ubuntu 25.04
 - Fedora 40
 - Fedora 41
 - Fedora 42
 - Debian 12
 - Debian 13
 - Oracle Linux 9

## FAQ
 - For non standard kernels, ensure perf is installed to see hotspots.
 - For runs on the cloud, readings from Frequency and Perf Hotspots might not show up.
 - Cloud runs will not show power.
