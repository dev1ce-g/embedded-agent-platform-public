# Config And Generated File Rules

Prefer product configuration sources for target-specific constants, channels,
storage tables, protocol parameters and feature wiring.

Generated outputs are not the long-term source of truth. Before editing a file
that looks generated:

* locate the source table, schema, template or generator script.
* update the source and regenerate when practical.
* record any temporary hand edit in the task notes.
* verify generated outputs match the source after regeneration.

Before adding or moving source files, update the owning build list:

* MCU: IDE project, linker/scatter file, include paths and linked libraries.
* MPU/application: CMake, SDK component list, package manifest or build script.

Source presence is not build membership. Confirm the active target compiles the
file you are editing.
