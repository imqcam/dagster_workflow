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

# Bake in Python code
COPY . /imqcam

# Remove this dockerfile from the image
RUN rm /imqcam/Dockerfile
