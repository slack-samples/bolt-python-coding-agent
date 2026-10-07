# Maintainers Guide

## Dependencies

Dependabot opens weekly updates for each implementation directory and for GitHub Actions. Patch and minor updates are approved and merged automatically by `.github/workflows/dependencies.yml` once checks pass. Major updates wait for a maintainer.

Each implementation pins its dependencies in both `requirements.txt` and `pyproject.toml`, so keep the two in sync when updating by hand.

## Adding an implementation

Each framework is a standalone sample in its own directory. When adding one, also add its directory to:

- the `matrix.directory` lists in `.github/workflows/ruff.yml` and `.github/workflows/tests.yml`
- the pip `directories` list in `.github/dependabot.yml`
- the framework table in the root `README.md`
