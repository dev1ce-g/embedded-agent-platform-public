#!/usr/bin/env python3
"""Minimal UDS ECU simulator for ZLG ControlCAN adapters.

This script is intended for K41 UDS client pipeline validation on a Windows PC.
It talks to ZLG's classic ControlCAN.dll directly through ctypes and implements
enough ISO-TP to answer 10/22/34/36/37 requests from the K41 tester.
"""

from __future__ import annotations

import argparse
import ctypes
import os
import signal
import sys
import time
from ctypes import POINTER, Structure, byref, c_ubyte, c_uint

from can_middleware import require_trusted_driver_path


STATUS_OK = 1
MAX_CAN_OBJ = 2500


DEVICE_TYPES = {
    "USBCAN1": 3,
    "USBCAN2": 4,
    "CANET-TCP": 17,
    "USBCAN-E-U": 20,
    "USBCAN-2E-U": 21,
    "USBCAN-4E-U": 31,
    "CANDTU-200UR": 32,
    "USBCAN-8E-U": 34,
    "CANDTU-NET": 36,
    "CANDTU-100UR": 37,
    "CANDTU-NET-400": 47,
}


TIMING_500K = (0x00, 0x1C)
TIMING_250K = (0x01, 0x1C)
TIMING_125K = (0x03, 0x1C)
BITRATES = {
    125000: TIMING_125K,
    250000: TIMING_250K,
    500000: TIMING_500K,
}


class VciCanObj(Structure):
    _fields_ = [
        ("ID", c_uint),
        ("TimeStamp", c_uint),
        ("TimeFlag", c_ubyte),
        ("SendType", c_ubyte),
        ("RemoteFlag", c_ubyte),
        ("ExternFlag", c_ubyte),
        ("DataLen", c_ubyte),
        ("Data", c_ubyte * 8),
        ("Reserved", c_ubyte * 3),
    ]


class VciInitConfig(Structure):
    _fields_ = [
        ("AccCode", c_uint),
        ("AccMask", c_uint),
        ("Reserved", c_uint),
        ("Filter", c_ubyte),
        ("Timing0", c_ubyte),
        ("Timing1", c_ubyte),
        ("Mode", c_ubyte),
    ]


def parse_int(text: str) -> int:
    return int(text, 0)


def parse_dev_type(text: str) -> int:
    upper = text.upper()
    if upper in DEVICE_TYPES:
        return DEVICE_TYPES[upper]
    return parse_int(text)


def parse_hex_bytes(text: str) -> bytes:
    cleaned = text.replace(",", " ").replace(":", " ").replace("-", " ")
    if not cleaned.strip():
        return b""
    return bytes(int(item, 16) for item in cleaned.split())


def format_hex(data: bytes) -> str:
    return " ".join(f"{item:02X}" for item in data)


class ControlCan:
    def __init__(self, dll_path: str | None, dev_type: int, dev_index: int, can_index: int):
        trusted = require_trusted_driver_path("controlcan", dll_path)
        assert trusted is not None
        self.dll_path = str(trusted)
        self.dev_type = dev_type
        self.dev_index = dev_index
        self.can_index = can_index
        self.dll_dirs = []
        try:
            self._add_dll_search_dirs(self.dll_path)
            self.dll = ctypes.WinDLL(self.dll_path)
        except OSError as exc:
            raise RuntimeError(
                f"failed to load {self.dll_path}: {exc}. "
                "Check 32/64-bit Python and ControlCAN.dll architecture."
            ) from exc
        self._bind()

    def _add_dll_search_dirs(self, dll_path: str) -> None:
        dll_dir = os.path.dirname(os.path.abspath(dll_path))
        candidates = [
            dll_dir,
            os.path.join(dll_dir, "kerneldlls"),
            os.path.join(dll_dir, "plugin"),
            os.path.dirname(dll_dir),
            os.path.join(os.path.dirname(dll_dir), "kerneldlls"),
            os.path.join(os.path.dirname(dll_dir), "plugin"),
        ]
        for item in candidates:
            if not item or not os.path.isdir(item):
                continue
            if hasattr(os, "add_dll_directory"):
                self.dll_dirs.append(os.add_dll_directory(item))
            os.environ["PATH"] = item + os.pathsep + os.environ.get("PATH", "")

    def _bind(self) -> None:
        self.dll.VCI_OpenDevice.argtypes = [c_uint, c_uint, c_uint]
        self.dll.VCI_OpenDevice.restype = c_uint
        self.dll.VCI_CloseDevice.argtypes = [c_uint, c_uint]
        self.dll.VCI_CloseDevice.restype = c_uint
        self.dll.VCI_InitCAN.argtypes = [c_uint, c_uint, c_uint, POINTER(VciInitConfig)]
        self.dll.VCI_InitCAN.restype = c_uint
        self.dll.VCI_StartCAN.argtypes = [c_uint, c_uint, c_uint]
        self.dll.VCI_StartCAN.restype = c_uint
        self.dll.VCI_ResetCAN.argtypes = [c_uint, c_uint, c_uint]
        self.dll.VCI_ResetCAN.restype = c_uint
        self.dll.VCI_Transmit.argtypes = [c_uint, c_uint, c_uint, POINTER(VciCanObj), c_uint]
        self.dll.VCI_Transmit.restype = c_uint
        self.dll.VCI_Receive.argtypes = [
            c_uint,
            c_uint,
            c_uint,
            POINTER(VciCanObj),
            c_uint,
            c_uint,
        ]
        self.dll.VCI_Receive.restype = c_uint

    def open(self, bitrate: int) -> None:
        if bitrate not in BITRATES:
            raise RuntimeError(f"unsupported bitrate {bitrate}; supported: {sorted(BITRATES)}")
        timing0, timing1 = BITRATES[bitrate]
        if self.dll.VCI_OpenDevice(self.dev_type, self.dev_index, 0) != STATUS_OK:
            raise RuntimeError(
                f"VCI_OpenDevice failed: type={self.dev_type} index={self.dev_index}"
            )
        cfg = VciInitConfig(
            AccCode=0x00000000,
            AccMask=0xFFFFFFFF,
            Reserved=0,
            Filter=1,
            Timing0=timing0,
            Timing1=timing1,
            Mode=0,
        )
        if self.dll.VCI_InitCAN(self.dev_type, self.dev_index, self.can_index, byref(cfg)) != STATUS_OK:
            self.close()
            raise RuntimeError(
                f"VCI_InitCAN failed: channel={self.can_index} bitrate={bitrate}"
            )
        if self.dll.VCI_StartCAN(self.dev_type, self.dev_index, self.can_index) != STATUS_OK:
            self.close()
            raise RuntimeError(f"VCI_StartCAN failed: channel={self.can_index}")

    def close(self) -> None:
        try:
            self.dll.VCI_ResetCAN(self.dev_type, self.dev_index, self.can_index)
            self.dll.VCI_CloseDevice(self.dev_type, self.dev_index)
        except Exception:
            pass

    def send(self, can_id: int, data: bytes, extended: bool = False) -> None:
        if len(data) > 8:
            raise ValueError("classic CAN frame payload must be <= 8 bytes")
        obj = VciCanObj()
        obj.ID = can_id & 0x1FFFFFFF
        obj.SendType = 0
        obj.RemoteFlag = 0
        obj.ExternFlag = 1 if extended else 0
        obj.DataLen = len(data)
        for i, item in enumerate(data):
            obj.Data[i] = item
        sent = self.dll.VCI_Transmit(self.dev_type, self.dev_index, self.can_index, byref(obj), 1)
        if sent != 1:
            raise RuntimeError(f"VCI_Transmit failed for id=0x{can_id:X} data={format_hex(data)}")

    def recv_many(self, timeout_ms: int) -> list[VciCanObj]:
        arr_type = VciCanObj * MAX_CAN_OBJ
        arr = arr_type()
        count = self.dll.VCI_Receive(
            self.dev_type,
            self.dev_index,
            self.can_index,
            arr,
            MAX_CAN_OBJ,
            timeout_ms,
        )
        if count == 0xFFFFFFFF:
            raise RuntimeError("VCI_Receive failed")
        return [arr[i] for i in range(count)]


class IsoTpEcu:
    def __init__(
        self,
        can: ControlCan,
        rxid: int,
        txid: int,
        extended: bool,
        padding: int,
        stmin_s: float,
        verbose: bool,
    ):
        self.can = can
        self.rxid = rxid
        self.txid = txid
        self.extended = extended
        self.padding = padding
        self.stmin_s = stmin_s
        self.verbose = verbose
        self.rx_buf = bytearray()
        self.rx_expected_len: int | None = None
        self.rx_next_sn = 1

    def _pad(self, payload: bytes) -> bytes:
        if len(payload) >= 8:
            return payload
        return payload + bytes([self.padding] * (8 - len(payload)))

    def _send_frame(self, data: bytes) -> None:
        self.can.send(self.txid, self._pad(data), self.extended)
        if self.verbose:
            print(f"CAN TX 0x{self.txid:X}: {format_hex(self._pad(data))}")

    def send_pdu(self, payload: bytes) -> None:
        if len(payload) <= 7:
            self._send_frame(bytes([len(payload)]) + payload)
            return
        length = len(payload)
        self._send_frame(bytes([0x10 | ((length >> 8) & 0x0F), length & 0xFF]) + payload[:6])
        offset = 6
        sn = 1
        while offset < length:
            chunk = payload[offset : offset + 7]
            self._send_frame(bytes([0x20 | (sn & 0x0F)]) + chunk)
            offset += len(chunk)
            sn = (sn + 1) & 0x0F
            if self.stmin_s > 0:
                time.sleep(self.stmin_s)

    def on_frame(self, can_id: int, data: bytes) -> bytes | None:
        if can_id != self.rxid or not data:
            return None
        pci = data[0]
        frame_type = pci & 0xF0

        if self.verbose:
            print(f"CAN RX 0x{can_id:X}: {format_hex(data)}")

        if frame_type == 0x00:
            length = pci & 0x0F
            return data[1 : 1 + length]

        if frame_type == 0x10:
            length = ((pci & 0x0F) << 8) | data[1]
            self.rx_expected_len = length
            self.rx_buf = bytearray(data[2:8])
            self.rx_next_sn = 1
            self._send_frame(bytes([0x30, 0x00, 0x00]))
            if len(self.rx_buf) >= length:
                pdu = bytes(self.rx_buf[:length])
                self.rx_expected_len = None
                return pdu
            return None

        if frame_type == 0x20 and self.rx_expected_len is not None:
            sn = pci & 0x0F
            if sn != self.rx_next_sn:
                print(f"sequence mismatch: expect {self.rx_next_sn:X}, got {sn:X}", file=sys.stderr)
                self.rx_expected_len = None
                self.rx_buf.clear()
                return None
            self.rx_next_sn = (self.rx_next_sn + 1) & 0x0F
            self.rx_buf.extend(data[1:8])
            if len(self.rx_buf) >= self.rx_expected_len:
                pdu = bytes(self.rx_buf[: self.rx_expected_len])
                self.rx_expected_len = None
                self.rx_buf.clear()
                return pdu
            return None

        return None


class UdsResponder:
    def __init__(self, vin: bytes, delay_s: float, download: bool):
        self.vin = vin
        self.delay_s = delay_s
        self.download = download
        self.transfer_blocks = 0

    def respond(self, req: bytes) -> bytes:
        if self.delay_s > 0:
            time.sleep(self.delay_s)
        if not req:
            return b""
        sid = req[0]

        if sid == 0x10 and len(req) >= 2:
            sub = req[1]
            return bytes([0x50, sub, 0x00, 0x32, 0x00, 0xC8])

        if sid == 0x3E:
            sub = req[1] if len(req) > 1 else 0x00
            return bytes([0x7E, sub])

        if sid == 0x22 and len(req) >= 3:
            did = req[1:3]
            if did == b"\xF1\x90":
                return b"\x62" + did + self.vin
            return b"\x62" + did + b"\x12\x34"

        if sid == 0x2E and len(req) >= 3:
            return b"\x6E" + req[1:3]

        if sid == 0x27 and len(req) >= 2:
            sub = req[1]
            if sub % 2 == 1:
                return bytes([0x67, sub, 0x12, 0x34, 0x56, 0x78])
            return bytes([0x67, sub])

        if sid == 0x34:
            if not self.download:
                return bytes([0x7F, sid, 0x11])
            self.transfer_blocks = 0
            return bytes([0x74, 0x20, 0x00, 0x80])

        if sid == 0x36:
            if len(req) < 2:
                return bytes([0x7F, sid, 0x13])
            self.transfer_blocks += 1
            return bytes([0x76, req[1]])

        if sid == 0x37:
            return bytes([0x77, 0x00])

        return bytes([0x7F, sid, 0x11])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ZLG ControlCAN UDS ECU simulator")
    parser.add_argument("--dll", help="deprecated; must exactly match the machine-configured DLL")
    parser.add_argument("--dev-type", default="17", type=parse_dev_type, help="device type name/id, default 17 CANET-TCP")
    parser.add_argument("--dev-index", default=0, type=parse_int, help="device index, default 0")
    parser.add_argument("--can-index", default=0, type=parse_int, help="CAN channel index in adapter, default 0")
    parser.add_argument("--bitrate", default=500000, type=parse_int, help="classic CAN bitrate, default 500000")
    parser.add_argument("--rxid", default=0x660, type=parse_int, help="tester request CAN ID, default 0x660")
    parser.add_argument("--txid", default=0x668, type=parse_int, help="ECU response CAN ID, default 0x668")
    parser.add_argument("--extended", action="store_true", help="use 29-bit CAN IDs")
    parser.add_argument("--padding", default=0xFF, type=parse_int, help="CAN frame padding byte, default 0xFF")
    parser.add_argument("--vin", default="TESTVIN0000000000", help="VIN payload for DID F190")
    parser.add_argument("--delay-ms", default=0, type=parse_int, help="response delay in ms")
    parser.add_argument("--stmin-ms", default=0, type=parse_int, help="TX consecutive frame gap in ms")
    parser.add_argument("--no-download", action="store_true", help="reject 0x34 RequestDownload")
    parser.add_argument("--verbose", action="store_true", help="print CAN frames")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    running = True

    def stop(_sig: int, _frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    if args.padding < 0 or args.padding > 0xFF:
        print("--padding must be 0..255", file=sys.stderr)
        return 2

    try:
        can = ControlCan(args.dll, args.dev_type, args.dev_index, args.can_index)
    except RuntimeError as exc:
        print(f"pc_uds_ecu_sim: error: {exc}", file=sys.stderr)
        return 2
    ecu = IsoTpEcu(
        can=can,
        rxid=args.rxid,
        txid=args.txid,
        extended=args.extended,
        padding=args.padding,
        stmin_s=args.stmin_ms / 1000.0,
        verbose=args.verbose,
    )
    responder = UdsResponder(
        vin=args.vin.encode("ascii", "replace")[:17],
        delay_s=args.delay_ms / 1000.0,
        download=not args.no_download,
    )

    print(
        "pc_uds_ecu_sim: "
        f"dll={args.dll} dev_type={args.dev_type} dev_index={args.dev_index} "
        f"can_index={args.can_index} bitrate={args.bitrate} "
        f"rxid=0x{args.rxid:X} txid=0x{args.txid:X} "
        f"extended={args.extended}"
    )

    try:
        can.open(args.bitrate)
        print("pc_uds_ecu_sim: running, press Ctrl+C to stop")
        while running:
            for frame in can.recv_many(100):
                can_id = frame.ID & 0x1FFFFFFF
                data = bytes(frame.Data[: frame.DataLen])
                req = ecu.on_frame(can_id, data)
                if req is None:
                    continue
                print(f"UDS RX: {format_hex(req)}")
                rsp = responder.respond(req)
                if not rsp:
                    continue
                print(f"UDS TX: {format_hex(rsp)}")
                ecu.send_pdu(rsp)
    except RuntimeError as exc:
        print(f"pc_uds_ecu_sim: error: {exc}", file=sys.stderr)
        return 1
    finally:
        can.close()
    print("pc_uds_ecu_sim: stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
