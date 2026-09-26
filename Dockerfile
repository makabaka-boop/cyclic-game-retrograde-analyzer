FROM python:3.12-slim

WORKDIR /workspace

# The analyzer is pure standard library; no runtime dependencies are needed.
# pytest is only installed inside the image's test stage usage (skipped here to
# keep the image minimal) — run tests on the host with `python3 -m pytest`.
COPY gamegraph ./gamegraph

# Pass-through: args forwarded to the analyzer CLI.
#   echo '{"states":...}' | docker compose run --rm -T gamegraph --pretty
ENTRYPOINT ["python", "-m", "gamegraph"]
