#!/usr/bin/env python3
"""Run a Python module with socket connections and DNS disabled."""
import runpy
import socket
import sys


def no_network(*args, **kwargs):
    raise RuntimeError("Network access is disabled for this offline publication or validation step")


def main():
    if len(sys.argv) < 3 or sys.argv[1] != "-m":
        raise SystemExit("Usage: offline-python.py -m module [arguments ...]")
    socket.create_connection = no_network
    socket.socket.connect = no_network
    socket.socket.connect_ex = no_network
    socket.getaddrinfo = no_network
    module = sys.argv[2]
    sys.argv = [module, *sys.argv[3:]]
    runpy.run_module(module, run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
