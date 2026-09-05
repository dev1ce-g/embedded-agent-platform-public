# Repository Layout Rules

Record the ownership model for each embedded package before changing code.
Common embedded layers:

* `business/`: product task code and project glue logic.
* `framework/`: reusable domain components, protocol frameworks and services.
* `rte_component/`: deployment/adaptation layer between project code and
  framework or SDK APIs.
* `project/config/`: product-specific configuration for this target.
* `project/`: build project files, tools and target-specific integration.
* `sdk/`: vendor or platform SDK headers and libraries; default read-only.
* `third_party/`: third-party stack code; default read-only.

Prefer the narrowest layer that owns the behavior. Do not modify SDK or
third-party code for a product configuration problem unless the task explicitly
requires that boundary crossing and documents the risk.
