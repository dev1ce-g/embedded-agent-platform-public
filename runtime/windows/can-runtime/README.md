# CAN Runtime Dependencies

The CAN Adapter uses architecture-specific Python dependencies. Install them
with the same Python interpreter that will run the vendor DLL:

```powershell
py -3 runtime\windows\can-runtime\install.py --upgrade
```

For an offline install, pass `--wheelhouse C:\path\to\wheels`. Configure vendor
drivers in the machine-owned `can-drivers.json` next to `embedded-agent.cmd`:

```powershell
Copy-Item .\can-runtime\can-drivers.example.json .\can-drivers.json
```

The Runtime reads only that fixed file; command-line and environment values
cannot select another registry. Each `dll` (and optional `python`) must be an
absolute, canonical regular-file path with no symlink or reparse point in its
path. Add `sha256` and `python_sha256` to pin file content when required:

```json
{
  "schema_version": "embedded-can-driver-config/v1",
  "drivers": {
    "controlcan": {
      "dll": "C:\\Program Files\\ZLG\\ControlCAN.dll",
      "sha256": "<64-character lowercase SHA-256>",
      "python": "C:\\Python38-32\\python.exe",
      "python_sha256": "<64-character lowercase SHA-256>"
    }
  }
}
```

Generate a digest with `(Get-FileHash -Algorithm SHA256 <path>).Hash.ToLower()`.
Without a valid machine entry, a physical Driver Adapter is unavailable. The
pure Python `can self-test` remains available. The legacy `--dll` parser option
is accepted only when its path exactly matches the trusted entry; it cannot
select a workspace DLL. Vendor DLLs and applications are not bundled or
downloaded by this installer.
