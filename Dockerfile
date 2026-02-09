# Dockerfile

# inherit from this "empty base image", see https://hub.docker.com/_/python/
FROM python:3.14-alpine

# take some responsibility for this container
LABEL org.opencontainers.image.authors="Aarno Aukia <aarno.aukia@vshn.ch>"

# directory to install the app inside the container
WORKDIR /usr/src/app

COPY --from=ghcr.io/astral-sh/uv:0.10 /uv /bin/uv

# use the venv python for all subsequent commands
ENV PATH="/usr/src/app/.venv/bin:$PATH"

# install python dependencies, this will be cached if pyproject.toml does not change
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --no-editable

# copy application source code into container
COPY app.py .

# drop root privileges when running the application
USER 1001

# run this command at run-time
CMD [ "python", "app.py" ]

# expose this TCP-port
EXPOSE 8080
