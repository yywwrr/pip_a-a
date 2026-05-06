#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

usage() {
  cat <<'EOF'
Usage:
  ./scripts/publish_pypi.sh [--test] [--dry-run] [--skip-version-check] [--no-clean]

Options:
  --test                Upload to TestPyPI (repository: testpypi).
  --dry-run             Build + twine check only (no upload).
  --skip-version-check  Skip checking pyproject.toml vs src/a_a/__init__.py.
  --no-clean            Do not remove dist/ and build/ before building.

Prereqs:
  - ~/.pypirc configured with an API token (as you already have)
  - build + twine available (script will install/upgrade into current env)

Notes:
  - This script does NOT bump version. Update both:
      - pyproject.toml [project].version
      - src/a_a/__init__.py __version__
EOF
}

REPOSITORY="pypi"
SKIP_VERSION_CHECK="0"
NO_CLEAN="0"
DRY_RUN="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --test)
      REPOSITORY="testpypi"
      shift
      ;;
    --dry-run)
      DRY_RUN="1"
      shift
      ;;
    --skip-version-check)
      SKIP_VERSION_CHECK="1"
      shift
      ;;
    --no-clean)
      NO_CLEAN="1"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "$SKIP_VERSION_CHECK" != "1" ]]; then
  PYPROJECT_VERSION="$(python -c 'import tomllib; print(tomllib.load(open("pyproject.toml","rb"))["project"]["version"])')"
  INIT_VERSION="$(python -c 'import re, pathlib; s=pathlib.Path("src/a_a/__init__.py").read_text(encoding="utf-8"); m=re.search(r"__version__\s*=\s*[\"\\x27]([^\"\\x27]+)[\"\\x27]", s); print(m.group(1) if m else "")')"

  if [[ -z "$PYPROJECT_VERSION" || -z "$INIT_VERSION" ]]; then
    echo "Version check failed: could not read version from files." >&2
    echo "pyproject.toml: '$PYPROJECT_VERSION'" >&2
    echo "src/a_a/__init__.py: '$INIT_VERSION'" >&2
    exit 1
  fi

  if [[ "$PYPROJECT_VERSION" != "$INIT_VERSION" ]]; then
    echo "Version mismatch:" >&2
    echo "  pyproject.toml:        $PYPROJECT_VERSION" >&2
    echo "  src/a_a/__init__.py:   $INIT_VERSION" >&2
    echo "Bump both before publishing (or pass --skip-version-check)." >&2
    exit 1
  fi

  echo "Version OK: $PYPROJECT_VERSION"
fi

python -m pip install -U build twine >/dev/null

if [[ "$NO_CLEAN" != "1" ]]; then
  rm -rf dist build
fi

python -m build
python -m twine check dist/*

if [[ "$DRY_RUN" == "1" ]]; then
  echo "Dry run: skipping upload."
  exit 0
fi

echo "Uploading to: $REPOSITORY"
python -m twine upload --repository "$REPOSITORY" dist/*

