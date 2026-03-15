# Support Plane Decomposition Contract v1

This contract decomposes support into two explicit surfaces without changing runtime endpoints.

## Support Tenant Runtime (Operational)

- Plane: `OPERATIONAL`
- Protected prefixes: `/support/tenant/*`
- Public runtime prefixes: `/support/public/*`
- Intent: business-facing tenant runtime support surface

## Support Superadmin Control (Foundation)

- Plane: `FOUNDATION`
- Protected prefixes: `/support/superadmin/*`
- Intent: foundation-controlled operational control surface

## Runtime invariants

- No endpoint moves
- No prefix changes
- No auth semantics changes
- No launcher runtime entrypoint changes
