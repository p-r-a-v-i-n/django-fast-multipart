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

The planned GitHub Actions `Release` workflow will build the wheels and source
distribution and publish them to PyPI using trusted publishing.
