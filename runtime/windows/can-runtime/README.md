# CAN Runtime Dependencies

The CAN Adapter uses architecture-specific Python dependencies. Install them
with the same Python interpreter that will run the vendor DLL:

```powershell
py -3 runtime\windows\can-runtime\install.py --upgrade
```

For an offline install, pass `--wheelhouse C:\path\to\wheels`. Configure vendor
locations through `EMBEDDED_CONTROLCAN_DLL`, `EMBEDDED_ZCANPRO_DLL`, and
optionally `EMBEDDED_CAN_PYTHON`. Vendor DLLs and applications are not bundled
or downloaded by this installer.
