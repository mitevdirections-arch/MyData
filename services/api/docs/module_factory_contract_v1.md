# Module Factory Contract v1

Module Factory Contract v1 defines the minimum mandatory shape for future business modules.

## Mandatory module markers

Each business module must provide `module_contract.py` with `MODULE_CONTRACT_V1` including:
- `module_name`
- `module_code`
- `plane_ownership`
- `authz_mode`
- `marketplace_facing`
- `typed_schemas`
- `readme`
- `router_service_boundaries`
- `sensitivity`
- `route_prefixes`
- `minimum_tests`
- `minimum_gate_expectations`

## Canonical minimum expectations

- Module identity/code: explicit and stable (`module_name`, `module_code`)
- Plane ownership: explicit (`FOUNDATION` or `OPERATIONAL`)
- AuthZ mode: explicit and aligned with protected route policy (`DB_TRUTH`, `TOKEN_CLAIMS`, or `FAST_PATH`)
- Marketplace-facing: explicit boolean declaration
- Typed schemas: mandatory (`schemas.py` + marker `typed_schemas=true`)
- Documentation: mandatory `README.md`
- Router/service boundaries: mandatory (`router.py` + `service.py`, marker `router_service_boundaries=true`)
- Sensitivity declaration: mandatory (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`)
- Minimum tests: explicit test files for module contract/route surface
- Minimum gate expectations: explicit gate dependencies

## Current v1 scope

Contract validation is strict for current reference-ready business module targets:
- Orders (`MODULE_ORDERS`) as reference module

Orders is the first reference module for contract shape and boundaries, without claiming full workflow completion.

## Coverage Step 2

Coverage is explicitly tracked for mixed/foundation surfaces without forcing premature v1 markers.
See `docs/module_factory_coverage_v1.md` for current ready/not-ready classification and reasons.
