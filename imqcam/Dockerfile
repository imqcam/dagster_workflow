FROM python:3.10-slim

ARG DAGSTER_VERSION=1.6.4

# All packages are hard-pinned to `dagster`, so setting the version on just `DAGSTER`
# will ensure compatible versions.
RUN pip install \
    dagster==${DAGSTER_VERSION} \
    dagster-postgres \
    dagster-aws \
    dagster-k8s \
    dagster-celery[flower,redis,kubernetes] \
    dagster-celery-k8s

# pip install other dependencies
RUN pip install \
    pandas==2.2.2 \
    scipy==1.13.0 \
    matplotlib==3.8.4 \
    girder-client==3.2.3 \
    globus-compute-sdk==2.27.1

# Bake in Python code
COPY . /imqcam

#env var for the timezone
ENV TZ=America/New_York

# Remove this dockerfile from the image
RUN rm /imqcam/Dockerfile
