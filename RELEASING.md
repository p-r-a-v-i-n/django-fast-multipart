# Releasing

Do not create a release tag until the trusted-publishing workflow is merged
and configured for this repository.

1. Update the version in:
   - `pyproject.toml`
   - `uv.lock`
   - `rust/Cargo.toml`
   - `rust/Cargo.lock`
2. Run the validation commands documented in `README.md`.
3. Commit the version bump.
4. Tag the release and push:

```bash
git tag vX.Y.Z
git push origin vX.Y.Z
```

The GitHub Actions `Release` workflow verifies all four version declarations,
builds and tests the five supported wheels, builds the source distribution,
publishes the artifacts to TestPyPI and PyPI using trusted publishing, and then
creates the GitHub release.
