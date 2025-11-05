#!/bin/bash
#install python environment based on OS

# Detect OS
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
else
    echo "Cannot detect OS"
    exit 1
fi

echo "Detected OS: $OS"

case "$OS" in
    ubuntu)
        sudo apt update
        sudo apt install -y python3 python3-venv python3-pip
	sudo apt install -y lm-sensors perf sysstat numactl net-tools linux-tools-common linux-tools-$(uname -r)
        ;;
    debian)
        sudo apt update
        sudo apt install -y python3 python3-venv python3-pip
	sudo apt install -y lm-sensors linux-perf sysstat numactl net-tools
        ;;
    rhel|cento|ol)
        sudo yum install -y python3 python3-virtualenv
	sudo yum install -y lm_sensors perf sysstat numactl net-tools
        ;;
    fedora)
        sudo dnf install -y python3 python3-virtualenv
	sudo dnf install -y lm_sensors perf sysstat numactl net-tools
        ;;
    *)
        echo "Unsupported OS: $OS"
        exit 1
        ;;
esac

rm -rf venv
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip && pip install poetry
poetry install
echo
echo "Python virtual environment successfully created, all dependencies resolved."
echo "To stop virtual environment run 'deactivate'"
