#!/usr/bin/env python3
"""Minimal direct ctypes adapter for the ZCANPro zlgcan.dll classic CAN API."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
from typing import Any


STATUS_OK = 1
INVALID_HANDLE_VALUES = {0, ctypes.c_void_p(-1).value}
CAN_TYPE_CLASSIC = 0
CAN_EFF_FLAG = 0x80000000
CAN_RTR_FLAG = 0x40000000
CAN_EFF_MASK = 0x1FFFFFFF
CAN_SFF_MASK = 0x7FF
MAX_RECEIVE_FRAMES = 2500

DEVICE_TYPES = {
    "ZCAN_USBCAN1": 3,
    "ZCAN_USBCAN2": 4,
    "ZCAN_USBCAN_E_U": 20,
    "ZCAN_USBCAN_2E_U": 21,
    "ZCAN_USBCAN_4E_U": 31,
    "ZCAN_USBCAN_8E_U": 34,
    "USBCAN1": 3,
    "USBCAN2": 4,
}

# SJA1000 timing values used by classic USB-CAN devices.
BITRATES = {
    125000: (0x03, 0x1C),
    250000: (0x01, 0x1C),
    500000: (0x00, 0x1C),
    1000000: (0x00, 0x14),
}


class ZCanClassicConfig(ctypes.Structure):
    _fields_ = [
        ("acc_code", ctypes.c_uint32),
        ("acc_mask", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32),
        ("filter", ctypes.c_uint8),
        ("timing0", ctypes.c_uint8),
        ("timing1", ctypes.c_uint8),
        ("mode", ctypes.c_uint8),
    ]


class ZCanFdConfig(ctypes.Structure):
    _fields_ = [
        ("acc_code", ctypes.c_uint32),
        ("acc_mask", ctypes.c_uint32),
        ("abit_timing", ctypes.c_uint32),
        ("dbit_timing", ctypes.c_uint32),
        ("brp", ctypes.c_uint32),
        ("filter", ctypes.c_uint8),
        ("mode", ctypes.c_uint8),
        ("pad", ctypes.c_uint16),
        ("reserved", ctypes.c_uint32),
    ]


class ZCanChannelConfigUnion(ctypes.Union):
    _fields_ = [("can", ZCanClassicConfig), ("canfd", ZCanFdConfig)]


class ZCanChannelInitConfig(ctypes.Structure):
    _fields_ = [("can_type", ctypes.c_uint32), ("config", ZCanChannelConfigUnion)]


class ZCanFrame(ctypes.Structure):
    _fields_ = [
        ("can_id", ctypes.c_uint32),
        ("can_dlc", ctypes.c_uint8),
        ("pad", ctypes.c_uint8),
        ("reserved0", ctypes.c_uint8),
        ("reserved1", ctypes.c_uint8),
        ("data", ctypes.c_uint8 * 8),
    ]


class ZCanTransmitData(ctypes.Structure):
    _fields_ = [("frame", ZCanFrame), ("transmit_type", ctypes.c_uint32)]


class ZCanReceiveData(ctypes.Structure):
    _fields_ = [("frame", ZCanFrame), ("timestamp", ctypes.c_uint64)]


class ZCanDeviceInfo(ctypes.Structure):
    _fields_ = [
        ("hardware_version", ctypes.c_uint16),
        ("firmware_version", ctypes.c_uint16),
        ("driver_version", ctypes.c_uint16),
        ("interface_version", ctypes.c_uint16),
        ("irq", ctypes.c_uint16),
        ("can_channels", ctypes.c_uint8),
        ("serial_number", ctypes.c_char * 20),
        ("hardware_type", ctypes.c_char * 40),
        ("reserved", ctypes.c_uint16 * 4),
    ]


def parse_device_type(value: str | int) -> int:
    if isinstance(value, int):
        return value
    name = value.upper()
    if name in DEVICE_TYPES:
        return DEVICE_TYPES[name]
    return int(value, 0)


def _valid_handle(value: Any) -> bool:
    return value not in INVALID_HANDLE_VALUES and value is not None


def load_library(path: str) -> tuple[Any, list[Any]]:
    dll_path = Path(path).resolve()
    directories = (dll_path.parent, dll_path.parent / "kerneldlls", dll_path.parent / "plugin")
    handles = []
    for directory in directories:
        if not directory.is_dir():
            continue
        os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")
        if hasattr(os, "add_dll_directory"):
            handles.append(os.add_dll_directory(str(directory)))
    loader = getattr(ctypes, "WinDLL", ctypes.CDLL)
    return loader(str(dll_path)), handles


def bind_library(dll: Any) -> None:
    dll.ZCAN_OpenDevice.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32]
    dll.ZCAN_OpenDevice.restype = ctypes.c_void_p
    dll.ZCAN_CloseDevice.argtypes = [ctypes.c_void_p]
    dll.ZCAN_CloseDevice.restype = ctypes.c_uint32
    if hasattr(dll, "ZCAN_GetDeviceInf"):
        dll.ZCAN_GetDeviceInf.argtypes = [ctypes.c_void_p, ctypes.POINTER(ZCanDeviceInfo)]
        dll.ZCAN_GetDeviceInf.restype = ctypes.c_uint32
    dll.ZCAN_InitCAN.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ZCanChannelInitConfig)]
    dll.ZCAN_InitCAN.restype = ctypes.c_void_p
    dll.ZCAN_StartCAN.argtypes = [ctypes.c_void_p]
    dll.ZCAN_StartCAN.restype = ctypes.c_uint32
    dll.ZCAN_ResetCAN.argtypes = [ctypes.c_void_p]
    dll.ZCAN_ResetCAN.restype = ctypes.c_uint32
    dll.ZCAN_Transmit.argtypes = [ctypes.c_void_p, ctypes.POINTER(ZCanTransmitData), ctypes.c_uint32]
    dll.ZCAN_Transmit.restype = ctypes.c_uint32
    dll.ZCAN_Receive.argtypes = [ctypes.c_void_p, ctypes.POINTER(ZCanReceiveData), ctypes.c_uint32, ctypes.c_int]
    dll.ZCAN_Receive.restype = ctypes.c_uint32


class ZCanProDevice:
    def __init__(self, dll_path: str, device_type: str | int, device_index: int, channel: int):
        self.dll_path = dll_path
        self.device_type = parse_device_type(device_type)
        self.device_index = device_index
        self.channel = channel
        self.dll, self.dll_directory_handles = load_library(dll_path)
        bind_library(self.dll)
        self.device_handle: Any = None
        self.channel_handle: Any = None

    def open(self, bitrate: int) -> None:
        if bitrate not in BITRATES:
            raise RuntimeError(f"unsupported bitrate {bitrate}; supported: {sorted(BITRATES)}")
        timing0, timing1 = BITRATES[bitrate]
        self.device_handle = self.dll.ZCAN_OpenDevice(self.device_type, self.device_index, 0)
        if not _valid_handle(self.device_handle):
            raise RuntimeError(f"ZCAN_OpenDevice failed: type={self.device_type} index={self.device_index}")
        config = ZCanChannelInitConfig()
        config.can_type = CAN_TYPE_CLASSIC
        config.config.can = ZCanClassicConfig(0, 0xFFFFFFFF, 0, 1, timing0, timing1, 0)
        self.channel_handle = self.dll.ZCAN_InitCAN(self.device_handle, self.channel, ctypes.byref(config))
        if not _valid_handle(self.channel_handle):
            self.close()
            raise RuntimeError(f"ZCAN_InitCAN failed: channel={self.channel} bitrate={bitrate}")
        if self.dll.ZCAN_StartCAN(self.channel_handle) != STATUS_OK:
            self.close()
            raise RuntimeError(f"ZCAN_StartCAN failed: channel={self.channel}")

    def send(self, can_id: int, data: bytes, extended: bool = False) -> None:
        if len(data) > 8:
            raise ValueError("classic CAN frame payload must be <= 8 bytes")
        value = ZCanTransmitData()
        mask = CAN_EFF_MASK if extended else CAN_SFF_MASK
        value.frame.can_id = (can_id & mask) | (CAN_EFF_FLAG if extended else 0)
        value.frame.can_dlc = len(data)
        for index, byte in enumerate(data):
            value.frame.data[index] = byte
        value.transmit_type = 0
        if self.dll.ZCAN_Transmit(self.channel_handle, ctypes.byref(value), 1) != 1:
            raise RuntimeError(f"ZCAN_Transmit failed for id=0x{can_id:X} data={data.hex(' ')}")

    def recv_many(self, timeout_ms: int) -> list[ZCanReceiveData]:
        frames_type = ZCanReceiveData * MAX_RECEIVE_FRAMES
        frames = frames_type()
        count = self.dll.ZCAN_Receive(self.channel_handle, frames, MAX_RECEIVE_FRAMES, timeout_ms)
        if count == 0xFFFFFFFF:
            raise RuntimeError("ZCAN_Receive failed")
        return [frames[index] for index in range(count)]

    def close(self) -> None:
        if _valid_handle(self.channel_handle):
            try:
                self.dll.ZCAN_ResetCAN(self.channel_handle)
            except Exception:
                pass
            self.channel_handle = None
        if _valid_handle(self.device_handle):
            try:
                self.dll.ZCAN_CloseDevice(self.device_handle)
            except Exception:
                pass
            self.device_handle = None
