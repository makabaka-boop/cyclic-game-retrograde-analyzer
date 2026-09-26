FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY tests ./tests

# Install the package (console script `gamegraph`) plus pytest so the same
# image can run the test suite:  docker compose run --rm --entrypoint pytest gamegraph
RUN pip install --no-cache-dir . pytest

ENTRYPOINT ["gamegraph"]
