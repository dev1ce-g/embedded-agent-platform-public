# Third-Party And SDK Boundary

Default read-only areas:

- `mcu/sdk/`
- `mcu/third_party/`
- `mcu/third_party/inc/autosar/`
- `mpu/sdk/`
- `mpu/sdk/lib/`

Rules:

- Do not modify vendor SDK headers or libraries to implement product behavior.
- Do not modify AUTOSAR stack headers or libraries unless the task explicitly
  requires AUTOSAR integration work.
- Prefer adapter code in `rte_component/`, `framework/` or `project/config/`.
- When SDK or prebuilt-library behavior must notify product code, prefer an SDK
  registration API such as `Set...Callback(...)` and let the product RTE
  register its handler. Do not make reusable SDK libraries directly call
  product-specific RTE symbols.
- If a vendor-layer change is unavoidable, document why the adapter layer cannot
  solve it and what validation was run.

## Callback Dependency Direction

SDK and prebuilt libraries must not hard-link to product-specific RTE symbols.
If SDK behavior needs to notify product code, the SDK owns a registration API and
the product RTE registers its handler during `Create()` / unregisters during
`Destroy()`.

Wrong:

```c
/* Inside SDK/prebuilt-library code */
RteXcuCanTxOnCanSent(channel, data);
```

Correct:

```c
/* SDK API */
void TBsCanServerSetSentDataCallback(void *user_param, TBsCanServerSentDataCallback callback);

/* Product RTE */
TBsCanServerSetSentDataCallback(NULL, RteXcuCanTxOnCanSent);
```

This keeps SDK libraries reusable and prevents link failures when a product RTE
symbol is absent from another target.
