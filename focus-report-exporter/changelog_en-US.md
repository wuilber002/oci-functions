# Changelog

[Leia este changelog em português](./changelog.md) <span>&#x1f1e7;&#x1f1f7;</span>

This document records the relevant changes introduced after the project's
initial published version.

## Current version — 2026-07-28

### Changed

- Synchronization now compares source and destination objects by their relative
  path (`Year/Month/Day/file`), preserving the hierarchy in the destination
  bucket.
- Object Storage listing now uses the API's correct pagination
  (`next_start_with`/`start`) and processes results as streams, without keeping
  the complete bucket inventory in memory.
- Destination listing starts at the first path present in the source. This
  avoids scanning history that cannot match current reports and prevents the
  lock object from using a useful position in a result page.
- File equality is now determined by `size` and `md5`. ETag remains a safety
  precondition during copy operations, rather than an equivalence criterion
  between source and destination.
- The destination bucket region accepts `OCI_BUCKET_DESTINATION_REGION` as an
  override; when it is absent, `OCI_RESOURCE_PRINCIPAL_REGION` is used.
- The SDK retry strategy was limited to respect the Function's maximum runtime.

### Added

- A distributed lock in the destination bucket, with expiration and ETag, to
  prevent concurrent executions.
- Asynchronous copies are submitted before *work request* polling, reducing
  repeated queries and giving Object Storage more time to complete the work.
- Execution metrics in the response and log: source and destination objects,
  copies, updates, identical objects, errors, pending requests, conflicts, and
  pages queried.
- Structured JSON logs for operational events and detailed diagnostics for
  failed copies, including *work request* errors and logs.
- Suppression of `urllib3` HTTP logs at the `DEBUG` level while retaining
  relevant warning and error messages.
- Unit tests for pagination, merge, object comparison, destination region,
  lock, copies, and *work request* failures.
- Function update procedures in Portuguese and English.
- Diagrams, an execution flow, pre-deployment test instructions, and expanded
  documentation in Portuguese and English.

### Fixed

- Incomplete `list_objects` pagination, which caused objects outside the first
  page to be treated as missing.
- Incorrect merge advancement after finding an identical object, which could
  submit an unnecessary copy with the `if-none-match` precondition.
- Copy failures now expose the cause returned by Object Storage instead of
  logging only the `FAILED` status.

### Compatibility and operation

- The Function keeps the same Application, OCID, Dynamic Group, policies, and
  schedule when updated through the documented procedure.
- Run `python -m unittest -v` and `python -m py_compile func.py test_func.py`
  before publishing a new image.

