# Dockerfile

# inherit from this "empty base image", see https://hub.docker.com/_/python/
FROM python:3.13-alpine

# take some responsibility for this container
LABEL org.opencontainers.image.authors="Aarno Aukia <aarno.aukia@vshn.ch>"

# directory to install the app inside the container
WORKDIR /usr/src/app

# https://github.com/HubSpot/hubspot-api-python/issues/303
# https://stackoverflow.com/a/10538412
RUN pip install --upgrade setuptools

# install python dependencies, this will be cached if the requirements.txt file does not change
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# copy application source code into container
COPY app.py .

# drop root privileges when running the application
USER 1001

# run this command at run-time
CMD [ "python", "app.py" ]

# expose this TCP-port
EXPOSE 8080
