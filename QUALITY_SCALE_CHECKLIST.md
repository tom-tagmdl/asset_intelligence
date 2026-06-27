# Asset Intelligence Quality Scale Checklist

Use this checklist as the working plan for moving the integration up the Home Assistant quality scale.

## Implementation Order

### Phase 1: Bronze foundation

1. Add `quality_scale.yaml`.
2. Add the Bronze documentation pages.
3. Add the first pytest fixtures for config flow and setup.
4. Add config flow tests.
5. Add startup and unload tests.
6. Add a first service test for document flows.
7. Add a first service test for history classification.

### Phase 2: Bronze completion

8. Add the remaining service-handler tests for the important flows.
9. Ensure config flow validates setup before creating the entry.
10. Ensure only one config entry can be created.
11. Move any remaining setup state to `ConfigEntry.runtime_data`.
12. Add documentation pages for high-level description, installation, removal, and supported actions.

### Phase 3: Silver readiness

13. Add robust error handling for unavailable storage or services.
14. Add tests for failure and recovery paths.
15. Ensure log output is quiet for expected unavailable states.
16. Add an integration owner entry in Home Assistant metadata.
17. Add reauthentication or equivalent recovery behavior where applicable.
18. Add unloading and reload coverage for config entries.

### Phase 4: Gold preparation

19. Add diagnostics support.
20. Add reconfigure flow support.
21. Expand end-user documentation with supported functions, known limitations, examples, and use cases.
22. Improve entity metadata and translations where applicable.
23. Add tests covering the full integration behavior, not just setup.

### Phase 5: Platinum runway

24. Make the codebase fully typed.
25. Remove remaining legacy or redundant code paths.
26. Keep all code fully asynchronous where possible.
27. Improve data handling efficiency and reduce CPU and network overhead.
28. Ensure tests cover the entire integration at a high level of confidence.
29. Review and align with all Home Assistant integration standards and best practices.

## Current Baseline

- [x] UI config flow exists
- [x] Services are registered in `async_setup`
- [x] Runtime data is centralized in the integration runtime
- [x] Core document, custody, environment, and history flows are functional
- [x] Quality scale metadata file exists
- [x] Automated test suite exists
- [x] User-facing integration documentation exists

## Bronze

- [x] Add `quality_scale.yaml`
- [x] Add a high-level integration description
- [x] Add installation instructions
- [x] Add removal instructions
- [x] Add a basic description of supported actions and entities
- [x] Add config flow tests
- [x] Add startup / unload tests
- [x] Add service-handler tests for the most important flows
- [x] Ensure config flow validates setup before creating the entry
- [x] Ensure only one config entry can be created for the integration
- [x] Move any remaining setup state to `ConfigEntry.runtime_data`

## Bronze Validation Goal

- [ ] Integration can be set up entirely through the UI
- [ ] Core setup behavior is covered by tests
- [ ] Documentation is enough for a user to install and start using the integration
- [ ] The integration has a `quality_scale.yaml` file with Bronze rules tracked

## Silver

- [x] Add robust error handling for unavailable storage or services
- [x] Add tests for failure and recovery paths
- [x] Ensure log output is quiet for expected unavailable states
- [x] Add an integration owner entry in Home Assistant metadata
- [x] Add unloading and reload coverage for config entries
- [ ] Add reauthentication or equivalent recovery behavior where applicable

Note: this integration does not use external authentication, so reauthentication is likely not applicable.

## Gold

- [x] Add diagnostics support
- [x] Add reconfigure flow support
- [x] Add fuller end-user documentation
- [x] Document supported functions, actions, and known limitations
- [x] Add examples or use cases in documentation
- [x] Improve entity metadata and translations where applicable
- [x] Add tests covering the full integration behavior, not just setup

## Platinum

- [x] Make the codebase fully typed
- [x] Remove remaining legacy or redundant code paths
- [x] Keep all code fully asynchronous where possible
- [x] Improve data handling efficiency and reduce CPU / network overhead
- [ ] Ensure tests cover the entire integration at a high level of confidence
- [ ] Review and align with all Home Assistant integration standards and best practices

Platinum verification evidence:

- Coverage gate + artifacts: `tests/run_quality_gate.ps1`
- Standards and checklist audit: `docs/quality_scale_audit.md`
- Current gate status: in progress (latest artifacts show failing tests and coverage below threshold)

## Near-Term Work

- [x] Create Bronze documentation pages
- [x] Add the `quality_scale.yaml` file
- [x] Build the first pytest fixtures for config flow and setup
- [x] Add one service test for documents
- [x] Add one service test for history classification
- [x] Add one unload test
- [x] Identify remaining legacy code paths to remove or replace

## Notes

- Start with Bronze and only move up once the lower tier is complete.
- Treat the checklist as the source of truth for the next few days.
- Update items as they are completed or if Home Assistant requirements change.