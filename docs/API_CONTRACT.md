# API contract workflow

FastAPI's OpenAPI is the source for public JSON request/response fields, enums,
query parameters, nullability and validation errors. Output models describe
serialized defaults as present. `frontend/src/types/index.ts` provides familiar
UI aliases to generated server types; mutation bodies and photo queries use the
generated operation contracts. Missing-photo filtering, match acknowledgement,
candidate pagination and previously undocumented action responses are exposed.

From the repository root, using the project's Python environment:

```powershell
python scripts/api_contract.py
python scripts/api_contract.py --check
```

The first command regenerates `api/openapi.json` and
`frontend/src/api/generated.ts`. Commit both together with API/client changes.
The second compares in memory and exits nonzero when either artifact is stale;
it never rewrites source. Backend CI runs this check and frontend CI compiles
the aliases/client against the generated types. The backend regression suite
also demonstrates that adding a server-only field is detected without rewriting.

Generation imports the app with a temporary data directory, does not initialize
a real catalog, start its lifespan, contact providers or read credentials. Only
API routes enter the snapshot, making it independent of frontend build presence.
Future WebUse routes must declare success response models and participate in the
same snapshot/type generation; untyped success responses fail generation.

The generator supports references, objects, arrays, enums, nullable unions and
the scalar types currently emitted by this app. Unsupported composed schemas
fail explicitly and require a reviewed generator extension. Arbitrary validation
error input is `unknown`, requiring narrowing. There are no `any` escape hatches.

`openapi-typescript` 7.13.0 was evaluated on 2026-10-04, but its declared
TypeScript `^5.x` peer conflicts with the repository's TypeScript 7.0.2. The
bounded Python generator avoids changing the canonical frontend compiler or
accepting an unsupported peer dependency tree. It does not perform runtime JSON
validation; the backend's response models enforce serialization contracts.
