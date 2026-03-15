# Module Factory Coverage v1 (Step 2)

## Reference-ready modules

- `orders`
  - status: `REFERENCE_READY`
  - business runtime: `true`
  - marketplace-facing: `true`
  - plane ownership: `OPERATIONAL`
  - reason: `reference_module_with_typed_contract_and_operational_plane`

## Not-ready modules / surfaces

- `marketplace`
  - status: `NOT_READY`
  - business runtime: `false`
  - marketplace-facing: `true`
  - plane ownership: `FOUNDATION`
  - reason: `foundation_controlled_facade_not_business_runtime_module`

- `support_tenant_runtime`
  - status: `NOT_READY`
  - business runtime: `true`
  - marketplace-facing: `false`
  - plane ownership: `OPERATIONAL`
  - reason: `decomposed_operational_support_surface_not_reference_ready_yet`

- `support_superadmin_control`
  - status: `NOT_READY`
  - business runtime: `false`
  - marketplace-facing: `false`
  - plane ownership: `FOUNDATION`
  - reason: `decomposed_foundation_control_surface_not_reference_ready_yet`

- `ai_tenant_runtime`
  - status: `NOT_READY`
  - business runtime: `true`
  - marketplace-facing: `false`
  - plane ownership: `OPERATIONAL`
  - reason: `decomposed_operational_ai_surface_not_reference_ready_yet`

- `ai_superadmin_control`
  - status: `NOT_READY`
  - business runtime: `false`
  - marketplace-facing: `false`
  - plane ownership: `FOUNDATION`
  - reason: `decomposed_foundation_ai_control_surface_not_reference_ready_yet`
