#!/usr/bin/env python3
"""Run a Python module with external socket connections and DNS disabled.

Local loopback connections (127.0.0.1, ::1, localhost) remain permitted for
in-process/child-process IPC such as a local ``docspec serve`` worker.
"""
import runpy
import socket
import sys

_ORIG_CREATE_CONNECTION = socket.create_connection
_ORIG_CONNECT = socket.socket.connect
_ORIG_CONNECT_EX = socket.socket.connect_ex
_ORIG_GETADDRINFO = socket.getaddrinfo
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def _is_loopback_host(host) -> bool:
    if isinstance(host, bytes):
        try:
            host = host.decode("ascii")
        except UnicodeDecodeError:
            return False
    if not isinstance(host, str):
        return False
    return host.strip().lower() in _LOOPBACK_HOSTS


def _is_loopback_address(address) -> bool:
    return isinstance(address, tuple) and len(address) >= 1 and _is_loopback_host(address[0])


def no_network(*args, **kwargs):
    raise RuntimeError("Network access is disabled for this offline publication or validation step")


def _offline_create_connection(address, *args, **kwargs):
    if _is_loopback_address(address):
        return _ORIG_CREATE_CONNECTION(address, *args, **kwargs)
    no_network()


def _offline_connect(self, address):
    if _is_loopback_address(address):
        return _ORIG_CONNECT(self, address)
    no_network()


def _offline_connect_ex(self, address):
    if _is_loopback_address(address):
        return _ORIG_CONNECT_EX(self, address)
    no_network()


def _offline_getaddrinfo(host, port, *args, **kwargs):
    if _is_loopback_host(host):
        return _ORIG_GETADDRINFO(host, port, *args, **kwargs)
    no_network()


def main():
    if len(sys.argv) < 3 or sys.argv[1] != "-m":
        raise SystemExit("Usage: offline-python.py -m module [arguments ...]")
    socket.create_connection = _offline_create_connection
    socket.socket.connect = _offline_connect
    socket.socket.connect_ex = _offline_connect_ex
    socket.getaddrinfo = _offline_getaddrinfo
    module = sys.argv[2]
    sys.argv = [module, *sys.argv[3:]]
    runpy.run_module(module, run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
