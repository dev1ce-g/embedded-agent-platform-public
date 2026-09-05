# -*- coding: utf-8 -*-
"""Driver-neutral PC CAN bench scenarios for the Windows CAN Runtime."""

from __future__ import annotations

import argparse
import binascii
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any, Iterable, List, Optional, Sequence, Tuple

import can_middleware


DEFAULT_BITRATE = 500000
DEFAULT_RX_ID = 0x660
DEFAULT_TX_ID = 0x668

PROFILE_GOLDEN = "golden"
PROFILE_SILENCE = "silence"
PROFILE_LATE = "late-response-after-timeout"
PROFILE_SAME_SID_LATE = "same-sid-late-response"
PROFILE_NRC78_OK = "nrc78-then-ok"
PROFILE_NRC78_TIMEOUT = "nrc78-then-timeout"
PROFILE_NRC_FINAL = "nrc-final"
PROFILE_TRANSFER_DROP = "transfer-drop-block"
PROFILE_TRANSFER_NRC = "transfer-nrc-block"
PROFILE_TRANSFER_WRONG_BSC = "transfer-wrong-bsc"
PROFILE_TRANSFER_DELAY = "transfer-delay-block"
PROFILE_DUPLICATE = "duplicate-response"
PROFILE_MALFORMED = "malformed-response"

PROFILES = (
    PROFILE_GOLDEN,
    PROFILE_SILENCE,
    PROFILE_LATE,
    PROFILE_SAME_SID_LATE,
    PROFILE_NRC78_OK,
    PROFILE_NRC78_TIMEOUT,
    PROFILE_NRC_FINAL,
    PROFILE_TRANSFER_DROP,
    PROFILE_TRANSFER_NRC,
    PROFILE_TRANSFER_WRONG_BSC,
    PROFILE_TRANSFER_DELAY,
    PROFILE_DUPLICATE,
    PROFILE_MALFORMED,
)

OTA_STATE_IDLE = "idle"
OTA_STATE_PROGRAMMING = "programming"
OTA_STATE_SECURITY_UNLOCKED = "security_unlocked"
OTA_STATE_DOWNLOAD_READY = "download_ready"
OTA_STATE_TRANSFER_DONE = "transfer_done"
OTA_STATE_VERIFIED = "verified"


def parse_int(value: Any) -> int:
    if isinstance(value, int):
        return value
    return int(str(value), 0)


def parse_hex_bytes(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    text = str(value).replace("0x", "").replace("0X", "")
    text = "".join(ch for ch in text if ch not in " \t\r\n:_-,")
    if len(text) % 2 != 0:
        raise argparse.ArgumentTypeError("hex byte string must have even number of digits")
    try:
        return bytes.fromhex(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def hexstr(data: bytes) -> str:
    return data.hex(" ")


def now_ms() -> int:
    return int(time.time() * 1000)


def parse_id_list(values: Optional[Sequence[Any]]) -> Optional[set[int]]:
    if not values:
        return None
    return {parse_int(value) for value in values}


def create_bus(args: argparse.Namespace) -> Tuple[Any, Any]:
    return can_middleware.open_bus(
        args.driver,
        channel=args.channel,
        bitrate=args.bitrate,
        dll_path=args.dll or None,
        device_model=args.device_model,
        device_index=args.device_index,
    )


def shutdown_bus(bus: Any) -> None:
    try:
        bus.shutdown()
    except AttributeError:
        return
    try:
        import can  # type: ignore

        can.BusABC.shutdown(bus)
    except Exception:
        pass


def format_can_message(msg: Any) -> str:
    frame_id = int(msg.arbitration_id)
    ext = "x" if bool(getattr(msg, "is_extended_id", False)) else "s"
    data = bytes(msg.data)
    ts = getattr(msg, "timestamp", None)
    prefix = f"{time.strftime('%H:%M:%S')} " if ts is None else f"{ts:.6f} "
    return f"{prefix}{ext} id=0x{frame_id:X} dlc={len(data)} data={hexstr(data)}"


def can_message_to_dict(msg: Any) -> dict:
    return {
        "time_ms": now_ms(),
        "id": int(msg.arbitration_id),
        "extended": bool(getattr(msg, "is_extended_id", False)),
        "data": bytes(msg.data).hex(),
    }


def should_accept_message(
    msg: Any, include_ids: Optional[set[int]], exclude_ids: Optional[set[int]], extended: Optional[bool]
) -> bool:
    frame_id = int(msg.arbitration_id)
    if include_ids is not None and frame_id not in include_ids:
        return False
    if exclude_ids is not None and frame_id in exclude_ids:
        return False
    if extended is not None and bool(getattr(msg, "is_extended_id", False)) != extended:
        return False
    return True


def run_monitor(args: argparse.Namespace) -> int:
    _can, bus = create_bus(args)
    include_ids = parse_id_list(args.can_id)
    exclude_ids = parse_id_list(args.exclude_id)
    extended = True if args.extended else False if args.standard else None
    count = 0
    start = time.monotonic()
    log_file = open(args.jsonl, "a", encoding="utf-8") if args.jsonl else None
    try:
        print(
            f"monitor channel={args.channel} bitrate={args.bitrate} "
            f"include={include_ids} exclude={exclude_ids}",
            flush=True,
        )
        while True:
            msg = bus.recv(timeout=args.recv_timeout)
            now = time.monotonic()
            if msg is None:
                if args.duration is not None and now - start >= args.duration:
                    return 0
                continue
            if not should_accept_message(msg, include_ids, exclude_ids, extended):
                continue
            print(format_can_message(msg), flush=True)
            if log_file is not None:
                log_file.write(json.dumps(can_message_to_dict(msg), separators=(",", ":")) + "\n")
                log_file.flush()
            count += 1
            if args.count is not None and count >= args.count:
                return 0
            if args.duration is not None and now - start >= args.duration:
                return 0
    finally:
        if log_file is not None:
            log_file.close()
        shutdown_bus(bus)


@dataclass
class RawFrame:
    arbitration_id: int
    data: bytes
    extended: bool = False
    delay_ms: int = 0


def parse_frame_spec(value: str, default_extended: bool) -> RawFrame:
    if "#" in value:
        id_text, data_text = value.split("#", 1)
    elif ":" in value:
        id_text, data_text = value.split(":", 1)
    else:
        raise argparse.ArgumentTypeError("frame must be ID#DATA or ID:DATA")
    return RawFrame(parse_int(id_text), parse_hex_bytes(data_text), default_extended)


def build_send_frames(args: argparse.Namespace) -> List[RawFrame]:
    frames: List[RawFrame] = []
    if args.frame:
        for item in args.frame:
            frames.append(parse_frame_spec(item, args.extended))
    elif args.can_id is not None and args.data is not None:
        frames.append(RawFrame(parse_int(args.can_id), parse_hex_bytes(args.data), args.extended))
    else:
        raise SystemExit("send requires --frame ID#DATA or --id ID --data DATA")
    return frames


def send_one(can: Any, bus: Any, frame: RawFrame, timeout: float, fd: bool, brs: bool) -> None:
    kwargs = {
        "arbitration_id": frame.arbitration_id,
        "data": frame.data,
        "is_extended_id": frame.extended,
    }
    if fd:
        kwargs["is_fd"] = True
        kwargs["bitrate_switch"] = brs
    msg = can.Message(**kwargs)
    bus.send(msg, timeout=timeout)
    print(
        f"< raw id=0x{frame.arbitration_id:X} extended={int(frame.extended)} "
        f"data={hexstr(frame.data)}",
        flush=True,
    )


def run_send(args: argparse.Namespace) -> int:
    can, bus = create_bus(args)
    frames = build_send_frames(args)
    try:
        loops = max(args.count, 1)
        for _idx in range(loops):
            for frame in frames:
                send_one(can, bus, frame, args.send_timeout, args.fd, args.brs)
                if args.period_ms > 0:
                    time.sleep(args.period_ms / 1000.0)
        return 0
    finally:
        shutdown_bus(bus)


def raw_frame_from_json(item: dict, default_extended: bool) -> RawFrame:
    frame_id = item.get("id", item.get("can_id"))
    data = item.get("data")
    if frame_id is None or data is None:
        raise ValueError("replay item requires id and data")
    return RawFrame(
        arbitration_id=parse_int(frame_id),
        data=parse_hex_bytes(data),
        extended=bool(item.get("extended", default_extended)),
        delay_ms=int(item.get("delay_ms", 0)),
    )


def run_replay(args: argparse.Namespace) -> int:
    can, bus = create_bus(args)
    try:
        with open(args.file, "r", encoding="utf-8") as fp:
            frames = [raw_frame_from_json(json.loads(line), args.extended) for line in fp if line.strip()]
        loops = max(args.count, 1)
        for _idx in range(loops):
            for frame in frames:
                if frame.delay_ms > 0:
                    time.sleep(frame.delay_ms / 1000.0)
                send_one(can, bus, frame, args.send_timeout, args.fd, args.brs)
        return 0
    finally:
        shutdown_bus(bus)


@dataclass
class TxEvent:
    payload: bytes
    delay_ms: int = 0
    label: str = "rsp"


@dataclass
class OtaDownload:
    address: int
    size: int
    data_format: int
    address_length_format: int
    received: int = 0
    blocks: int = 0
    expected_seq: int = 1
    crc32: int = 0


class UdsDispatcher:
    def __init__(
        self,
        profile: str = PROFILE_GOLDEN,
        ota_strict: bool = False,
        ota_max_block_len: int = 0x80,
        seed: bytes = b"\x12\x34\x56\x78",
        key: bytes = b"\x87\x65\x43\x21",
        late_ms: int = 1500,
        nrc_code: int = 0x22,
        nrc78_delay_ms: int = 200,
        transfer_fault_block: int = 1,
        transfer_delay_ms: int = 1500,
        malformed_payload: bytes = b"\x00",
    ) -> None:
        self.profile = profile
        self.ota_strict = ota_strict
        self.ota_max_block_len = max(ota_max_block_len, 8)
        self.seed = seed
        self.key = key
        self.late_ms = max(late_ms, 0)
        self.nrc_code = nrc_code & 0xFF
        self.nrc78_delay_ms = max(nrc78_delay_ms, 0)
        self.transfer_fault_block = max(transfer_fault_block, 1)
        self.transfer_delay_ms = max(transfer_delay_ms, 0)
        self.malformed_payload = malformed_payload
        self.ota_state = OTA_STATE_IDLE
        self.download: Optional[OtaDownload] = None
        self.request_count = 0
        self.transfer_blocks = 0
        self.transfer_bytes = 0

    def handle(self, req: bytes) -> List[TxEvent]:
        self.request_count += 1
        if not req:
            return []

        sid = req[0]
        if self.profile == PROFILE_SILENCE:
            return []
        if self.profile == PROFILE_NRC78_TIMEOUT:
            return [TxEvent(self.negative(sid, 0x78), label="nrc78")]
        if self.profile == PROFILE_NRC_FINAL:
            return [TxEvent(self.negative(sid, self.nrc_code), label="nrc-final")]
        if self.profile == PROFILE_MALFORMED:
            return [TxEvent(self.malformed_payload, label="malformed")]

        positive = self.build_positive(req)
        if not positive:
            return []

        if self.profile in (PROFILE_LATE, PROFILE_SAME_SID_LATE):
            return [TxEvent(positive, delay_ms=self.late_ms, label="late")]
        if self.profile == PROFILE_NRC78_OK:
            return [
                TxEvent(self.negative(sid, 0x78), label="nrc78"),
                TxEvent(positive, delay_ms=self.nrc78_delay_ms, label="final"),
            ]
        if self.profile == PROFILE_DUPLICATE:
            return [
                TxEvent(positive, label="dup-1"),
                TxEvent(positive, delay_ms=5, label="dup-2"),
            ]
        return [TxEvent(positive)]

    @staticmethod
    def negative(sid: int, nrc: int) -> bytes:
        return bytes([0x7F, sid & 0xFF, nrc & 0xFF])

    def build_positive(self, req: bytes) -> bytes:
        sid = req[0]
        if sid == 0x10:
            sub = req[1] if len(req) > 1 else 0x01
            if sub == 0x02:
                self.reset_download()
                self.ota_state = OTA_STATE_PROGRAMMING
            return bytes([0x50, sub, 0x00, 0x32, 0x00, 0xC8])

        if sid == 0x11:
            sub = req[1] if len(req) > 1 else 0x01
            self.reset_download()
            self.ota_state = OTA_STATE_IDLE
            return bytes([0x51, sub])

        if sid == 0x22 and len(req) >= 3:
            did = (req[1] << 8) | req[2]
            if did == 0xF190:
                return b"\x62\xF1\x90PCCANTOOLTEST0001"[:20]
            return bytes([0x62, req[1], req[2], 0x12, 0x34])

        if sid == 0x2E and len(req) >= 3:
            return bytes([0x6E, req[1], req[2]])

        if sid == 0x27:
            sub = req[1] if len(req) > 1 else 0x01
            if sub & 0x01:
                return bytes([0x67, sub]) + self.seed
            if self.ota_strict and req[2:] != self.key:
                return self.negative(sid, 0x35)
            self.ota_state = OTA_STATE_SECURITY_UNLOCKED
            return bytes([0x67, sub])

        if sid == 0x34:
            return self.handle_request_download(req)
        if sid == 0x36:
            return self.handle_transfer_data(req)
        if sid == 0x37:
            return self.handle_transfer_exit(req)
        if sid == 0x31:
            return self.handle_routine_control(req)
        if sid == 0x3E:
            sub = req[1] if len(req) > 1 else 0x00
            return bytes([0x7E, sub])

        return self.negative(sid, 0x11)

    def reset_download(self) -> None:
        self.download = None
        self.transfer_blocks = 0
        self.transfer_bytes = 0

    def handle_request_download(self, req: bytes) -> bytes:
        sid = req[0]
        if self.ota_strict and self.ota_state not in (
            OTA_STATE_PROGRAMMING,
            OTA_STATE_SECURITY_UNLOCKED,
        ):
            return self.negative(sid, 0x22)
        if len(req) < 4:
            return self.negative(sid, 0x13)

        data_format = req[1]
        alfid = req[2]
        address_len = (alfid >> 4) & 0x0F
        size_len = alfid & 0x0F
        expected_len = 3 + address_len + size_len
        if address_len == 0 or size_len == 0 or len(req) < expected_len:
            return self.negative(sid, 0x31)

        pos = 3
        address = int.from_bytes(req[pos : pos + address_len], "big")
        pos += address_len
        size = int.from_bytes(req[pos : pos + size_len], "big")
        if size <= 0:
            return self.negative(sid, 0x31)

        self.download = OtaDownload(address, size, data_format, alfid)
        self.transfer_blocks = 0
        self.transfer_bytes = 0
        self.ota_state = OTA_STATE_DOWNLOAD_READY
        print(
            f"request-download addr=0x{address:X} size={size} "
            f"data_format=0x{data_format:02X} alfid=0x{alfid:02X}",
            flush=True,
        )
        return bytes([0x74, 0x20]) + self.ota_max_block_len.to_bytes(2, "big")

    def handle_transfer_data(self, req: bytes) -> bytes:
        sid = req[0]
        if len(req) < 2:
            return self.negative(sid, 0x13)
        block = req[1]
        data = req[2:]
        next_block_index = self.transfer_blocks + 1

        if self.profile == PROFILE_TRANSFER_DROP and next_block_index == self.transfer_fault_block:
            print(f"drop transfer block={next_block_index} seq=0x{block:02X}", flush=True)
            return b""
        if self.profile == PROFILE_TRANSFER_NRC and next_block_index == self.transfer_fault_block:
            return self.negative(sid, self.nrc_code)

        if self.download is not None:
            expected = self.download.expected_seq
            if block != expected:
                print(f"wrong request bsc expected=0x{expected:02X} got=0x{block:02X}", flush=True)
                return self.negative(sid, 0x73)
            if self.download.received + len(data) > self.download.size:
                return self.negative(sid, 0x31)
            self.download.received += len(data)
            self.download.blocks += 1
            self.download.expected_seq = (self.download.expected_seq + 1) & 0xFF
            self.download.crc32 = binascii.crc32(data, self.download.crc32) & 0xFFFFFFFF
        elif self.ota_strict:
            return self.negative(sid, 0x24)

        self.transfer_blocks += 1
        self.transfer_bytes += len(data)
        if self.transfer_blocks == 1 or self.transfer_blocks % 20 == 0:
            print(
                f"transfer block={self.transfer_blocks} seq=0x{block:02X} "
                f"bytes={self.transfer_bytes}",
                flush=True,
            )

        rsp_seq = block
        if self.profile == PROFILE_TRANSFER_WRONG_BSC and next_block_index == self.transfer_fault_block:
            rsp_seq = (block + 1) & 0xFF
        if self.profile == PROFILE_TRANSFER_DELAY and next_block_index == self.transfer_fault_block:
            time.sleep(self.transfer_delay_ms / 1000.0)
        return bytes([0x76, rsp_seq])

    def handle_transfer_exit(self, req: bytes) -> bytes:
        sid = req[0]
        if self.download is not None:
            if self.download.received != self.download.size:
                print(f"transfer-exit too early bytes={self.download.received}/{self.download.size}", flush=True)
                return self.negative(sid, 0x24)
            self.ota_state = OTA_STATE_TRANSFER_DONE
            print(
                f"transfer-exit blocks={self.transfer_blocks} bytes={self.transfer_bytes} "
                f"crc32=0x{self.download.crc32:08X}",
                flush=True,
            )
        elif self.ota_strict:
            return self.negative(sid, 0x24)
        return bytes([0x77]) + req[1:]

    def handle_routine_control(self, req: bytes) -> bytes:
        sid = req[0]
        sub = req[1] if len(req) > 1 else 0x01
        routine = req[2:4] if len(req) >= 4 else b"\x00\x00"
        if self.ota_strict and self.ota_state != OTA_STATE_TRANSFER_DONE:
            return self.negative(sid, 0x24)
        self.ota_state = OTA_STATE_VERIFIED
        rsp = bytes([0x71, sub]) + routine
        if self.download is not None:
            rsp += self.download.crc32.to_bytes(4, "big")
        return rsp


def build_isotp_address(isotp: Any, args: argparse.Namespace) -> Any:
    if args.addressing == "normal-11bits":
        return isotp.Address(isotp.AddressingMode.Normal_11bits, txid=args.txid, rxid=args.rxid)
    if args.addressing == "normal-29bits":
        return isotp.Address(isotp.AddressingMode.Normal_29bits, txid=args.txid, rxid=args.rxid)
    if args.addressing == "normal-fixed-29bits":
        return isotp.Address(
            addressing_mode=isotp.AddressingMode.NormalFixed_29bits,
            target_address=args.target_address,
            source_address=args.source_address,
        )
    raise ValueError(f"unsupported addressing mode: {args.addressing}")


def build_isotp_params(args: argparse.Namespace) -> dict:
    return {
        "stmin": args.stmin,
        "blocksize": args.blocksize,
        "tx_padding": args.padding,
        "rx_flowcontrol_timeout": args.rx_flowcontrol_timeout_ms,
        "rx_consecutive_frame_timeout": args.rx_consecutive_frame_timeout_ms,
        "tx_data_length": args.tx_data_length,
        "max_frame_size": args.max_frame_size,
        "blocking_send": True,
    }


def create_isotp_stack(args: argparse.Namespace) -> Tuple[Any, Any, Any]:
    can, bus = create_bus(args)
    try:
        import isotp  # type: ignore
    except ImportError as exc:
        shutdown_bus(bus)
        raise RuntimeError("can-isotp is not installed in the CAN Runtime") from exc
    notifier = can.Notifier(bus, [], timeout=0.01)
    stack = isotp.NotifierBasedCanStack(
        bus=bus,
        notifier=notifier,
        address=build_isotp_address(isotp, args),
        params=build_isotp_params(args),
    )
    return bus, notifier, stack


def stop_isotp_stack(bus: Any, notifier: Any, stack: Any) -> None:
    try:
        stack.stop()
    finally:
        try:
            notifier.stop()
        finally:
            shutdown_bus(bus)


def run_uds_ecu(args: argparse.Namespace) -> int:
    bus, notifier, stack = create_isotp_stack(args)
    dispatcher = UdsDispatcher(
        profile=args.profile,
        ota_strict=args.ota_strict,
        ota_max_block_len=args.ota_max_block_len,
        seed=args.seed,
        key=args.key,
        late_ms=args.late_ms,
        nrc_code=args.nrc_code,
        nrc78_delay_ms=args.nrc78_delay_ms,
        transfer_fault_block=args.transfer_fault_block,
        transfer_delay_ms=args.transfer_delay_ms,
        malformed_payload=args.malformed_payload,
    )
    print(
        "uds-ecu listening "
        f"profile={args.profile} addressing={args.addressing} "
        f"rxid=0x{args.rxid:X} txid=0x{args.txid:X} "
        f"channel={args.channel} bitrate={args.bitrate}",
        flush=True,
    )
    try:
        stack.start()
        last_activity = time.monotonic()
        while True:
            req = stack.recv(block=True, timeout=0.1)
            now = time.monotonic()
            if req is None:
                if args.idle_timeout is not None and now - last_activity >= args.idle_timeout:
                    print("idle timeout reached, exit", flush=True)
                    return 0
                continue

            last_activity = now
            payload = bytes(req)
            print(f"> {hexstr(payload)}", flush=True)
            for event in dispatcher.handle(payload):
                if event.delay_ms > 0:
                    time.sleep(event.delay_ms / 1000.0)
                if not event.payload:
                    continue
                stack.send(event.payload, send_timeout=args.send_timeout)
                print(f"< {event.label} {hexstr(event.payload)}", flush=True)

            if args.max_requests is not None and dispatcher.request_count >= args.max_requests:
                print(
                    f"max request count reached requests={dispatcher.request_count} "
                    f"blocks={dispatcher.transfer_blocks} bytes={dispatcher.transfer_bytes}",
                    flush=True,
                )
                return 0
    finally:
        stop_isotp_stack(bus, notifier, stack)


def _load_zuds_file(filepath: str) -> List[Tuple[bytes, Optional[bytes], str, int]]:
    """Load a .zuds JSON test sequence file.

    Returns list of (request_bytes, expected_prefix_or_None, remark, delay_ms).
    """
    with open(filepath, "r", encoding="utf-8") as f:
        entries = json.load(f)
    result = []
    for entry in entries:
        if not entry.get("checked", True):
            continue
        code = entry.get("code", 0)
        req_payload = parse_hex_bytes(entry.get("request data", ""))
        req = bytes([code]) + req_payload
        resp_str = entry.get("response data", "")
        expected = parse_hex_bytes(resp_str) if resp_str else None
        if not entry.get("check response", False):
            expected = None
        remark = entry.get("remark", "")
        delay_ms = entry.get("delay time", 0) if entry.get("is time delay", False) else 0
        result.append((req, expected, remark, delay_ms))
    return result


def run_uds_tester(args: argparse.Namespace) -> int:
    bus, notifier, stack = create_isotp_stack(args)

    # Build request list from --zuds-file or --request/--expect
    if getattr(args, "zuds_file", None):
        zuds_entries = _load_zuds_file(args.zuds_file)
        requests_list = []
        expects_list = []
        remarks = []
        delays = []
        for req, expected, remark, delay_ms in zuds_entries:
            requests_list.append(req)
            expects_list.append(expected)
            remarks.append(remark)
            delays.append(delay_ms)
        if not requests_list:
            raise SystemExit(f"no enabled entries in zuds file: {args.zuds_file}")
    else:
        requests_list = [parse_hex_bytes(r) for r in (args.request or [])]
        expects_list = []
        for i, _ in enumerate(requests_list):
            expects_list.append(parse_hex_bytes(args.expect[i]) if i < len(args.expect or []) else None)
        remarks = [""] * len(requests_list)
        delays = [0] * len(requests_list)
        if not requests_list:
            raise SystemExit("uds-tester requires at least one --request or --zuds-file")

    try:
        stack.start()
        pass_count = 0
        fail_count = 0
        for index, req in enumerate(requests_list):
            expected = expects_list[index]
            remark = remarks[index]
            delay_ms = delays[index]

            if delay_ms > 0:
                time.sleep(delay_ms / 1000.0)

            if getattr(args, "verbose", False) and remark:
                print(f"# [{index+1}/{len(requests_list)}] {remark}", flush=True)

            print(f"> {hexstr(req)}", flush=True)
            stack.send(req, send_timeout=args.send_timeout)

            # Handle NRC 0x78 (responsePending): keep waiting for final response
            nrc78_retries = 0
            max_nrc78 = 30  # up to 30 x response_timeout
            while True:
                rsp = stack.recv(block=True, timeout=args.response_timeout)
                if rsp is None:
                    print("  TIMEOUT", flush=True)
                    fail_count += 1
                    if args.zuds_file:
                        break  # continue to next request
                    else:
                        return 10
                payload = bytes(rsp)
                print(f"< {hexstr(payload)}", flush=True)
                # Check for NRC 0x78: 7F <SID> 78
                if len(payload) >= 3 and payload[0] == 0x7F and payload[2] == 0x78:
                    nrc78_retries += 1
                    if nrc78_retries <= max_nrc78:
                        print(f"  NRC 0x78 pending, retry {nrc78_retries}/{max_nrc78}...", flush=True)
                        continue  # wait for final response
                    else:
                        print(f"  NRC 0x78 max retries ({max_nrc78}) exceeded", flush=True)
                        fail_count += 1
                        break
                # Not NRC 0x78, this is the final response
                break

            if rsp is None:
                if args.zuds_file:
                    continue
                else:
                    return 10

            if expected is not None:
                if payload.startswith(expected):
                    print("  OK", flush=True)
                    pass_count += 1
                else:
                    print(f"  MISMATCH expected={hexstr(expected)} actual={hexstr(payload)}", flush=True)
                    fail_count += 1
            else:
                # No expected prefix; check if it is a NRC (0x7F)
                if payload[0] == 0x7F:
                    nrc = payload[2] if len(payload) >= 3 else 0
                    print(f"  NRC 0x{nrc:02X}", flush=True)
                    fail_count += 1
                else:
                    pass_count += 1

            if args.gap_ms > 0:
                time.sleep(args.gap_ms / 1000.0)

        if args.zuds_file:
            total = len(requests_list)
            print(f"\nSummary: {pass_count}/{total} passed, {fail_count} failed", flush=True)
            return 0 if fail_count == 0 else 12
        return 0
    finally:
        stop_isotp_stack(bus, notifier, stack)


def run_check_env(args: argparse.Namespace) -> int:
    try:
        import can  # type: ignore
        import isotp  # type: ignore
    except ImportError as exc:
        raise RuntimeError(str(exc)) from exc
    inventory = can_middleware.driver_inventory(args.driver)[0]
    print(f"driver={args.driver}", flush=True)
    print(f"driver_ready={inventory['ready']}", flush=True)
    print(f"driver_blockers={inventory['blockers']}", flush=True)
    print(f"python={sys.version}", flush=True)
    print(f"python-can={getattr(can, '__version__', 'unknown')}", flush=True)
    print(f"can-isotp={getattr(isotp, '__version__', 'unknown')}", flush=True)
    return 0


def run_self_test(_args: argparse.Namespace) -> int:
    assert parse_hex_bytes("10 03") == b"\x10\x03"
    assert parse_hex_bytes("10-03") == b"\x10\x03"
    dispatcher = UdsDispatcher(profile=PROFILE_GOLDEN, ota_strict=True)
    cases: Iterable[Tuple[bytes, bytes]] = (
        (b"\x10\x03", b"\x50\x03\x00\x32\x00\xC8"),
        (b"\x22\xF1\x90", b"\x62\xF1\x90"),
        (b"\x10\x02", b"\x50\x02\x00\x32\x00\xC8"),
        (b"\x34\x00\x44\x00\x00\x10\x00\x00\x00\x00\x02", b"\x74\x20\x00\x80"),
        (b"\x36\x01\xAA\xBB", b"\x76\x01"),
        (b"\x37", b"\x77"),
        (b"\x31\x01\xFF\x00", b"\x71\x01\xFF\x00"),
    )
    for req, prefix in cases:
        events = dispatcher.handle(req)
        assert events, f"no response for {hexstr(req)}"
        actual = events[-1].payload
        assert actual.startswith(prefix), f"{hexstr(req)} -> {hexstr(actual)}"

    dispatcher = UdsDispatcher(profile=PROFILE_NRC78_OK)
    events = dispatcher.handle(b"\x10\x03")
    assert [event.payload for event in events] == [b"\x7F\x10\x78", b"\x50\x03\x00\x32\x00\xC8"]

    dispatcher = UdsDispatcher(profile=PROFILE_DUPLICATE)
    events = dispatcher.handle(b"\x22\xF1\x90")
    assert len(events) == 2

    print("self-test ok", flush=True)
    return 0


def add_runtime_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--driver", choices=tuple(can_middleware.DRIVERS), default=os.environ.get("PC_CAN_DRIVER", "controlcan"))
    parser.add_argument("--channel", type=int, default=0)
    parser.add_argument("--bitrate", type=int, default=DEFAULT_BITRATE)
    parser.add_argument("--dll", help="deprecated; must exactly match the Runtime machine configuration")
    parser.add_argument("--device-model")
    parser.add_argument("--device-index", type=int, default=0)


def add_raw_filter_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--id", dest="can_id", action="append", help="CAN ID to include, can be repeated")
    parser.add_argument("--exclude-id", action="append", help="CAN ID to exclude, can be repeated")
    parser.add_argument("--standard", action="store_true", help="accept only standard frames")
    parser.add_argument("--extended", action="store_true", help="use or accept extended frames")


def add_raw_send_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--frame", action="append", help="raw frame in ID#DATA or ID:DATA format")
    parser.add_argument("--id", dest="can_id", help="CAN ID when --frame is not used")
    parser.add_argument("--data", help="hex payload when --frame is not used")
    parser.add_argument("--extended", action="store_true")
    parser.add_argument("--fd", action="store_true", help="create python-can CAN FD message if backend supports it")
    parser.add_argument("--brs", action="store_true", help="CAN FD bitrate switch flag")
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--period-ms", type=int, default=0)
    parser.add_argument("--send-timeout", type=float, default=1.0)


def add_isotp_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--addressing", choices=("normal-11bits", "normal-29bits", "normal-fixed-29bits"), default="normal-11bits")
    parser.add_argument("--rxid", type=parse_int, default=DEFAULT_RX_ID, help="CAN ID received by this PC tool")
    parser.add_argument("--txid", type=parse_int, default=DEFAULT_TX_ID, help="CAN ID transmitted by this PC tool")
    parser.add_argument("--source-address", type=parse_int, default=0xF1)
    parser.add_argument("--target-address", type=parse_int, default=0x81)
    parser.add_argument("--padding", type=parse_int, default=0x00)
    parser.add_argument("--stmin", type=parse_int, default=0)
    parser.add_argument("--blocksize", type=parse_int, default=0)
    parser.add_argument("--tx-data-length", type=int, default=8)
    parser.add_argument("--max-frame-size", type=int, default=4095)
    parser.add_argument("--rx-flowcontrol-timeout-ms", type=int, default=1000)
    parser.add_argument("--rx-consecutive-frame-timeout-ms", type=int, default=1000)
    parser.add_argument("--send-timeout", type=float, default=2.0)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Driver-neutral Windows PC CAN test tool")
    sub = parser.add_subparsers(dest="command", required=True)

    self_test = sub.add_parser("self-test", help="run pure Python dispatcher self-test")
    self_test.set_defaults(func=run_self_test)

    check_env = sub.add_parser("check-env", help="check python-can / can-isotp runtime")
    add_runtime_args(check_env)
    check_env.set_defaults(func=run_check_env)

    monitor = sub.add_parser("monitor", help="monitor raw CAN frames")
    add_runtime_args(monitor)
    add_raw_filter_args(monitor)
    monitor.add_argument("--duration", type=float, default=None)
    monitor.add_argument("--count", type=int, default=None)
    monitor.add_argument("--recv-timeout", type=float, default=0.1)
    monitor.add_argument("--jsonl", default=None, help="optional raw frame log file")
    monitor.set_defaults(func=run_monitor)

    send = sub.add_parser("send", help="send raw CAN frame(s)")
    add_runtime_args(send)
    add_raw_send_args(send)
    send.set_defaults(func=run_send)

    replay = sub.add_parser("replay", help="replay raw CAN frames from JSONL")
    add_runtime_args(replay)
    replay.add_argument("--file", required=True)
    replay.add_argument("--extended", action="store_true")
    replay.add_argument("--fd", action="store_true")
    replay.add_argument("--brs", action="store_true")
    replay.add_argument("--count", type=int, default=1)
    replay.add_argument("--send-timeout", type=float, default=1.0)
    replay.set_defaults(func=run_replay)

    uds_ecu = sub.add_parser("uds-ecu", help="run ISO-TP UDS ECU responder")
    add_runtime_args(uds_ecu)
    add_isotp_args(uds_ecu)
    uds_ecu.add_argument("--profile", choices=PROFILES, default=PROFILE_GOLDEN)
    uds_ecu.add_argument("--ota-strict", action="store_true")
    uds_ecu.add_argument("--ota-max-block-len", type=parse_int, default=0x80)
    uds_ecu.add_argument("--seed", type=parse_hex_bytes, default=b"\x12\x34\x56\x78")
    uds_ecu.add_argument("--key", type=parse_hex_bytes, default=b"\x87\x65\x43\x21")
    uds_ecu.add_argument("--late-ms", type=int, default=1500)
    uds_ecu.add_argument("--nrc78-delay-ms", type=int, default=200)
    uds_ecu.add_argument("--nrc-code", type=parse_int, default=0x22)
    uds_ecu.add_argument("--transfer-fault-block", type=int, default=1)
    uds_ecu.add_argument("--transfer-delay-ms", type=int, default=1500)
    uds_ecu.add_argument("--malformed-payload", type=parse_hex_bytes, default=b"\x00")
    uds_ecu.add_argument("--idle-timeout", type=float, default=None)
    uds_ecu.add_argument("--max-requests", type=int, default=None)
    uds_ecu.set_defaults(func=run_uds_ecu)

    uds_tester = sub.add_parser("uds-tester", help="send ISO-TP UDS request(s) as tester")
    add_runtime_args(uds_tester)
    add_isotp_args(uds_tester)
    uds_tester.add_argument("--request", action="append", help="UDS request payload, can be repeated")
    uds_tester.add_argument("--expect", action="append", help="expected positive/negative response prefix")
    uds_tester.add_argument("--response-timeout", type=float, default=5.0)
    uds_tester.add_argument("--gap-ms", type=int, default=0)
    uds_tester.add_argument("--zuds-file", default=None, help="load a .zuds JSON test sequence file")
    uds_tester.add_argument("--verbose", action="store_true", help="print remark for each request")
    uds_tester.set_defaults(func=run_uds_tester)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if hasattr(args, "padding") and not 0 <= args.padding <= 0xFF:
        parser.error("--padding must be 0..255")
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
