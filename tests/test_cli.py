###########################################################################
# Copyright (c) 2025, Ampere Computing LLC
#
# SPDX-License-Identifier: BSD-3-Clause
# License terms can be found in the LICENSE.TXT file at the root of this project.
###########################################################################

import subprocess
import shutil
import platform
import pytest
import time


def run_command(cmd):
    res = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )
    return res


def ensure_stress_ng_installed():
    if shutil.which("stress-ng"):
        return
    distro = (
        platform.linux_distribution()[0].lower()
        if hasattr(platform, "linux_distribution")
        else platform.system().lower()
    )
    try:
        if "ubuntu" in distro or "debian" in distro:
            subprocess.run(["sudo", "apt-get", "update"], check=True)
            subprocess.run(
                ["sudo", "apt-get", "install", "-y", "stress-ng"], check=True
            )
        elif "fedora" in distro or "redhat" in distro or "centos" in distro:
            subprocess.run(["sudo", "dnf", "install", "-y", "stress-ng"], check=True)
        elif "arch" in distro:
            subprocess.run(
                ["sudo", "pacman", "-S", "--noconfirm", "stress-ng"], check=True
            )
        else:
            raise RuntimeError(f"unsupported OS for stress-ng installation: {distro}")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to install stress-ng: {e}")


@pytest.fixture(scope="session", autouse=True)
def setup_stress_ng():
    ensure_stress_ng_installed()


def test_cli_help():
    # assumes `poetry install` is run
    result = run_command(["asp", "--help"])
    assert "Usage:" in result.stdout
    assert "-n" in result.stdout
    assert "-i" in result.stdout


def test_cli_sample10_interval(capsys):
    bg_process = subprocess.Popen(
        ["stress-ng", "-C", "10", "-t", "10"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    time.sleep(1)
    result = subprocess.run(
        ["asp", "-n", "10", "-i", "1"], capture_output=True, text=True
    )
    print(result.stdout)
    captured = capsys.readouterr()
    # terminate stress-ng
    bg_process.terminate()
    bg_process.wait()
    assert "Test Terminated. Cleaning up...\nSuccess" in captured.out
    assert result.returncode == 0


def test_cli_sample10_interval_output(capsys):
    bg_process = subprocess.Popen(
        ["stress-ng", "-C", "10", "-t", "10"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    time.sleep(1)
    result = subprocess.run(
        ["asp", "-n", "10", "-i", "1", "-o", "~/test"], capture_output=True, text=True
    )
    print(result.stdout)
    captured = capsys.readouterr()
    # terminate stress-ng
    bg_process.terminate()
    bg_process.wait()
    assert "Test Terminated. Cleaning up...\nSuccess" in captured.out
    assert result.returncode == 0


def test_cli_sample10_interval_network_interface(capsys):
    bg_process = subprocess.Popen(
        ["stress-ng", "-C", "10", "-t", "10"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    time.sleep(1)
    result = subprocess.run(
        ["asp", "-n", "10", "-i", "1", "-N", "eth0"], capture_output=True, text=True
    )
    print(result.stdout)
    captured = capsys.readouterr()
    # terminate stress-ng
    bg_process.terminate()
    bg_process.wait()
    assert "Test Terminated. Cleaning up...\nSuccess" in captured.out
    assert result.returncode == 0


def test_cli_sample10_interval_disable_perf(capsys):
    bg_process = subprocess.Popen(
        ["stress-ng", "-C", "10", "-t", "10"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    time.sleep(1)
    result = subprocess.run(
        ["asp", "-n", "10", "-i", "1", "-f"], capture_output=True, text=True
    )
    print(result.stdout)
    captured = capsys.readouterr()
    # terminate stress-ng
    bg_process.terminate()
    bg_process.wait()
    assert "Test Terminated. Cleaning up...\nSuccess" in captured.out
    assert result.returncode == 0


def test_cli_sample10_interval_disable_plot(capsys):
    bg_process = subprocess.Popen(
        ["stress-ng", "-C", "10", "-t", "10"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    time.sleep(1)
    result = subprocess.run(
        ["asp", "-n", "10", "-i", "1", "-p"], capture_output=True, text=True
    )
    print(result.stdout)
    captured = capsys.readouterr()
    # terminate stress-ng
    bg_process.terminate()
    bg_process.wait()
    assert "Test Terminated. Cleaning up" in captured.out
    assert result.returncode == 0
